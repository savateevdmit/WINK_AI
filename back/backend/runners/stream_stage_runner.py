#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stream_stage_runner.py — SSE анализатор (реальное время) с оптимизированным переиспользованием результатов.

Новые требования (выполнены):
1) Проверяем соседние папки в back/data с тем же базовым названием (без суффикса _<hex> в конце),
   игнорируя любые папки, где есть temp.txt (флаг изменений).
2) Выбираем только те кандидаты, у которых:
   - есть model/output.json,
   - в папке uploads есть файл(ы), и размер основного файла совпадает с размером файла в uploads текущей папки doc_id/uploads.
3) Если найден валидный кандидат, копируем его model/output.json в текущую папку:
   - <doc_id>/model/output.json
   - <doc_id>/stages/output_final.json
   и немедленно возвращаем результат (события SSE: "reuse_from_workspace" и "final").
4) Если переиспользование не удалось — продолжаем обычный запуск пайплайна.
5) Абсолютные пути (Windows-safe), фолбэк на sync Popen, игнорируем предупреждения llama_context.
6) Предыдущий глобальный кэш analyzer_cache сохранён как резервный fallback (после проверки соседних папок).

Пути:
- Папки сценариев: back/data/<doc_id>
- Код: back/backend/*
"""

from __future__ import annotations
import asyncio
import hashlib
import json
import os
import re
import sys
import time
import traceback
import subprocess
import shutil
from pathlib import Path
from typing import AsyncGenerator, Dict, Any, Optional, List, Tuple

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..storage import load_parsed_scenes

router = APIRouter(prefix="/api/analyze", tags=["analyze"])

# -------------------- Регулярки и константы --------------------
RE_COUNT = re.compile(r"(\d+)\s*/\s*(\d+)")
RE_PCT = re.compile(r"(\d+(?:\.\d+)?)%")

STAGE_MARKERS = {
    "Stage 0": "stage0",
    "Stage 1": "stage1",
    "Stage 2": "stage2",
    "Stage 3": "stage3",
}

IGNORED_WARN_PREFIXES = [
    "llama_context: n_ctx_per_seq",  # безопасное предупреждение — не выводим
]

# Нормализация названия: снимаем расширение и суффикс _<8hex> в конце
RE_TRAILING_CODE = re.compile(r"^(?P<stem>.*?)(?:_[0-9a-fA-F]{8})?$")


# -------------------- Утилиты пути/IO --------------------
def _pipeline_script_path() -> Path:
    here = Path(__file__).resolve().parent.parent
    cand = here / "model" / "pipeline.py"
    if cand.is_file():
        return cand
    raise FileNotFoundError(f"pipeline.py not found at {cand}")


def _law_file_path() -> Path:
    here = Path(__file__).resolve().parent.parent
    law = here / "model" / "law.json"
    if law.is_file():
        return law
    raise FileNotFoundError(f"law.json not found at {law}")


def _sse(obj: Dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _preflight(ws: Path, params: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    # pipeline
    try:
        pipeline = _pipeline_script_path()
        if not os.access(pipeline, os.R_OK):
            errors.append(f"Pipeline script not readable: {pipeline}")
    except Exception as e:
        errors.append(f"Pipeline resolution failed: {e}")

    # law
    try:
        law = _law_file_path()
        if not os.access(law, os.R_OK):
            errors.append(f"law.json not readable: {law}")
    except Exception as e:
        errors.append(f"law.json resolution failed: {e}")

    # model spec
    model_path = params.get("model_path")
    if model_path:
        mp = Path(model_path)
        if not mp.is_file():
            errors.append(f"Provided model_path does not exist: {model_path}")
    else:
        if not params.get("repo_id") or not params.get("filename"):
            warnings.append("Using repo_id/filename; ensure network availability if required.")

    # parsed scenes
    if not (ws / "parsed_scenes.json").is_file():
        errors.append(f"parsed_scenes.json missing in workspace: {ws/'parsed_scenes.json'}")

    return {"errors": errors, "warnings": warnings}


def _normalize_title(name: str) -> str:
    """Убираем расширение и суффикс _<8hex>."""
    if not isinstance(name, str):
        return ""
    base = os.path.basename(name)
    stem, _ext = os.path.splitext(base)
    m = RE_TRAILING_CODE.match(stem)
    stem2 = m.group("stem") if m else stem
    return stem2.strip()


def _has_change_flag(ws: Path) -> bool:
    """Есть ли temp.txt — папка была изменена сервером/пользователем, кэш запрещён."""
    return (ws / "temp.txt").is_file()


def _model_output_exists(ws: Path) -> bool:
    return (ws / "model" / "output.json").is_file()


def _get_uploads_main_file_size(ws: Path) -> Optional[int]:
    """Возвращает размер основного файла в ws/uploads.
       Оптимально: если 1 файл — берём его; если несколько — берём самый крупный."""
    up = ws / "uploads"
    if not up.is_dir():
        return None
    max_sz = None
    try:
        for p in up.iterdir():
            if not p.is_file():
                continue
            if p.name.startswith("."):
                continue
            try:
                sz = p.stat().st_size
            except Exception:
                continue
            if max_sz is None or sz > max_sz:
                max_sz = sz
    except Exception:
        return None
    return max_sz


def _promote_output_to_ws(ws: Path, src_output: Path) -> Dict[str, Any]:
    """Копируем model/output.json из кандидата в текущую папку ws + возвращаем JSON."""
    model_dir = ws / "model"
    stages_dir = ws / "stages"
    model_dir.mkdir(parents=True, exist_ok=True)
    stages_dir.mkdir(parents=True, exist_ok=True)
    dst_model = model_dir / "output.json"
    dst_stages = stages_dir / "output_final.json"
    shutil.copyfile(src_output, dst_model)
    shutil.copyfile(src_output, dst_stages)
    with open(dst_model, "r", encoding="utf-8") as f:
        return json.load(f)


# -------------------- Переиспользование по соседним папкам data --------------------
def _find_reusable_workspace(ws: Path) -> Optional[Tuple[Path, Path]]:
    """
    Ищем среди data/* валидную папку с тем же базовым названием (без _<hex>), без temp.txt,
    с model/output.json и совпадающим размером файла uploads.

    Возвращает (candidate_dir, candidate_output_json) или None.
    Выбираем самый свежий (по mtime output.json), чтобы быть детерминированными.
    """
    data_root = ws.parent
    base_title = _normalize_title(ws.name)
    cur_size = _get_uploads_main_file_size(ws)
    if cur_size is None:
        return None

    matches: List[Tuple[float, Path, Path]] = []  # (mtime, candidate_ws, candidate_output)

    for cand in data_root.iterdir():
        if not cand.is_dir():
            continue
        name = cand.name
        if base_title not in name:
            continue
        # Полное соответствие normalized-title
        if _normalize_title(name) != base_title:
            continue
        # Игнорируем саму текущую папку как источник только если там уже есть результат;
        # но спецификация говорит про "соседние", оставим возможность и свою использовать, если output есть.
        # Проверки:
        if _has_change_flag(cand):
            continue
        out_json = cand / "model" / "output.json"
        if not out_json.is_file():
            continue
        cand_size = _get_uploads_main_file_size(cand)
        if cand_size is None or cand_size != cur_size:
            continue
        try:
            mtime = out_json.stat().st_mtime
        except Exception:
            mtime = 0.0
        matches.append((mtime, cand, out_json))

    if not matches:
        return None
    # Берём самый свежий
    matches.sort(key=lambda t: -t[0])
    _mt, cand_ws, cand_out = matches[0]
    # Если кандидат — это та же папка, но она же валидная — тоже ок (в этом случае просто промоут/перечитать).
    return cand_ws, cand_out


# -------------------- Глобальный кэш (fallback) --------------------
def _cache_root(ws: Path) -> Path:
    return ws.parent / "analyzer_cache"


def _cache_key(filename: str, size_bytes: int) -> str:
    s = f"{filename}|{size_bytes}"
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _load_origin_meta(ws: Path) -> Optional[Tuple[str, int]]:
    """Если есть origin_meta.json — используем его; иначе берём крупнейший файл из uploads."""
    meta = ws / "origin_meta.json"
    if meta.is_file():
        try:
            obj = json.loads(meta.read_text(encoding="utf-8"))
            fn = obj.get("filename")
            sz = obj.get("size_bytes")
            if isinstance(fn, str) and isinstance(sz, int) and sz >= 0:
                return fn, sz
        except Exception:
            pass
    # fallback: uploads
    up = ws / "uploads"
    if not up.is_dir():
        return None
    best = None
    for p in up.iterdir():
        if p.is_file() and not p.name.startswith("."):
            try:
                sz = p.stat().st_size
            except Exception:
                continue
            if best is None or sz > best[1]:
                best = (p.name, sz)
    return best if best else None


def _find_cached_output(ws: Path, filename: str, size_bytes: int) -> Optional[Path]:
    """Сканируем analyzer_cache с meta.json (логика contains -> equals(normalized) + size)."""
    base_title = _normalize_title(filename)
    root = _cache_root(ws)
    if not root.is_dir():
        return None

    matches: List[Tuple[float, Path]] = []
    for sub in root.iterdir():
        if not sub.is_dir():
            continue
        meta = sub / "meta.json"
        out = sub / "output.json"
        if not (meta.is_file() and out.is_file()):
            continue
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
        except Exception:
            continue
        fn = str(m.get("filename") or "")
        norm = str(m.get("normalized_title") or "")
        sz = int(m.get("size_bytes") or -1)
        if base_title and base_title in fn and norm == base_title and sz == int(size_bytes):
            try:
                ts = out.stat().st_mtime
            except Exception:
                ts = 0.0
            matches.append((ts, out))
    if matches:
        matches.sort(key=lambda t: -t[0])
        return matches[0][1]

    # legacy fallback (без meta)
    key = _cache_key(filename, size_bytes)
    legacy = root / key / "output.json"
    return legacy if legacy.is_file() else None


def _save_to_cache(ws: Path, filename: str, size_bytes: int, output_path: Path) -> None:
    root = _cache_root(ws)
    root.mkdir(parents=True, exist_ok=True)
    key = _cache_key(filename, size_bytes)
    cache_dir = root / key
    cache_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(output_path, cache_dir / "output.json")
    meta = {
        "filename": filename,
        "normalized_title": _normalize_title(filename),
        "size_bytes": int(size_bytes),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (cache_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


# -------------------- Процесс чтения stderr (sync) --------------------
async def _read_line_async(stream) -> Optional[str]:
    try:
        line = await asyncio.wait_for(stream.readline(), timeout=0.75)
        if not line:
            return None
        return line.decode("utf-8", errors="replace")
    except asyncio.TimeoutError:
        return None


def _spawn_subprocess(cmd: List[str], cwd: str, env: Dict[str, str]):
    try:
        fut = asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd, env=env
        )
        return "async", fut
    except NotImplementedError:
        pass
    except Exception:
        raise
    pop = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env, text=False)
    return "sync", pop


async def _stream_sync_process(pop: subprocess.Popen) -> AsyncGenerator[str, None]:
    loop = asyncio.get_running_loop()

    async def _read_stderr():
        try:
            return await loop.run_in_executor(None, pop.stderr.readline)
        except Exception:
            return b""

    while True:
        if pop.poll() is not None and pop.stderr.closed:
            break
        chunk = await _read_stderr()
        if chunk:
            yield chunk.decode("utf-8", errors="replace")
        await asyncio.sleep(0.05)
        if pop.poll() is not None and not chunk:
            break


# -------------------- Основной пайплайн со streaming --------------------
async def _stream_pipeline(ws: Path, scenes: list[dict], params: Dict[str, Any]) -> AsyncGenerator[str, None]:
    # 0) Префлайт
    pf = _preflight(ws, params)
    if pf["errors"]:
        yield _sse({"event": "error_start", "message": "Preflight failed", "errors": pf["errors"], "warnings": pf["warnings"]})
        return
    elif pf["warnings"]:
        yield _sse({"event": "preflight", "warnings": pf["warnings"]})

    # 1) Подготовка ввода/выхода
    model_dir = ws / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = model_dir / "debug" / "stream" if params.get("debug") else None
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)

    input_path = (model_dir / "input_stream_scenes.json").resolve()
    output_path = (model_dir / "output.json").resolve()
    with open(input_path, "w", encoding="utf-8") as f:
        json.dump(scenes, f, ensure_ascii=False, indent=2)

    # 2) Переиспользование результата из соседних папок data (оптимальный быстрый путь)
    # Игнорируем, если temp.txt в текущей папке
    if not _has_change_flag(ws):
        reuse = _find_reusable_workspace(ws)
        if reuse:
            cand_ws, cand_out = reuse
            try:
                data = _promote_output_to_ws(ws, cand_out)
                await asyncio.sleep(0)
                yield _sse({"event": "reuse_from_workspace", "from_doc_id": cand_ws.name})
                yield _sse({"event": "final", "output": data})
                return
            except Exception as e:
                yield _sse({"event": "log", "line": f"Workspace reuse failed: {e}. Falling back to cache/pipeline."})

    # 3) Глобальный кэш (fallback)
    if not _has_change_flag(ws):
        sig = _load_origin_meta(ws)
        if sig is not None:
            filename, size_bytes = sig
            cached_output = _find_cached_output(ws, filename, size_bytes)
            if cached_output and cached_output.is_file():
                try:
                    data = _promote_output_to_ws(ws, cached_output)
                    await asyncio.sleep(0)
                    yield _sse({"event": "cache_hit", "filename": filename, "size_bytes": size_bytes})
                    yield _sse({"event": "final", "output": data})
                    return
                except Exception as e:
                    yield _sse({"event": "log", "line": f"Cache promotion failed: {e}. Falling back to pipeline."})

    # 4) Запуск пайплайна
    pipeline = _pipeline_script_path()
    law_file = _law_file_path()

    cmd = [
        sys.executable,
        str(pipeline),
        "--input", str(input_path),
        "--output", str(output_path),
        "--law-file", str(law_file),
        "--batch-size", str(params["batch_size"]),
        "--llm-effort-s0", params["llm_effort_s0"],
        "--llm-effort-s1", params["llm_effort_s1"],  # важно: дефисы, не подчёркивания
        "--llm-effort-s2", params["llm_effort_s2"],
        "--llm-effort-s3", params["llm_effort_s3"],
        "--retries", str(params["retries"]),
        "--stage0-batch-size", str(params["stage0_batch_size"]),
        "--stage0-max-sentences", str(params["stage0_max_sentences"]),
    ]
    if not params["stage0_enable"]:
        cmd.append("--no-stage0-enable")
    if params.get("model_path"):
        cmd += ["--model-path", params["model_path"]]
    else:
        if params.get("repo_id"):
            cmd += ["--repo-id", params["repo_id"]]
        if params.get("filename"):
            cmd += ["--filename", params["filename"]]
    cmd += ["--n-ctx", str(params["n_ctx"]), "--n-gpu-layers", str(params["n_gpu_layers"])]
    if debug_dir:
        cmd += ["--debug-dir", str(debug_dir)]

    env = os.environ.copy()
    pipeline_dir = str(pipeline.parent)
    env["PYTHONPATH"] = pipeline_dir + os.pathsep + env.get("PYTHONPATH", "")

    try:
        mode, proc_or_future = _spawn_subprocess(cmd, cwd=pipeline_dir, env=env)
    except Exception as e:
        yield _sse({
            "event": "error_start",
            "message": "Failed to start pipeline subprocess",
            "reason": f"{e.__class__.__name__}: {e}",
            "traceback": traceback.format_exc(),
            "cmd": cmd
        })
        return

    current_stage: Optional[str] = None
    last_mtime: Optional[float] = None
    last_partial_emit = 0.0
    buffered_stage2_snapshot: Optional[Dict[str, Any]] = None

    async def emit_partial(event_type: str, data: Dict[str, Any], extra: Dict[str, Any] | None = None):
        payload = {"event": event_type, "output": data}
        if extra:
            payload.update(extra)
        yield _sse(payload)

    async def run_sync_flow(pop: subprocess.Popen):
        nonlocal current_stage, last_mtime, last_partial_emit, buffered_stage2_snapshot
        output_file = output_path

        async for line in _stream_sync_process(pop):
            now = time.time()
            stripped = line.strip()
            if stripped and not any(stripped.startswith(pfx) for pfx in IGNORED_WARN_PREFIXES):
                stage_detected = None
                for marker, internal in STAGE_MARKERS.items():
                    if marker in stripped:
                        stage_detected = internal
                        break
                if stage_detected:
                    if stage_detected == "stage3" and current_stage != "stage3" and buffered_stage2_snapshot is not None:
                        async for msg in emit_partial("stage2_done", buffered_stage2_snapshot):
                            yield msg
                        buffered_stage2_snapshot = None
                    current_stage = stage_detected
                    progress_val = None
                    m_count = RE_COUNT.search(stripped)
                    if m_count:
                        try:
                            cur = int(m_count.group(1)); total = int(m_count.group(2))
                            if total > 0:
                                progress_val = cur / total
                        except Exception:
                            pass
                    else:
                        m_pct = RE_PCT.search(stripped)
                        if m_pct:
                            try:
                                pct = float(m_pct.group(1))
                                progress_val = pct / 100.0
                            except Exception:
                                pass
                    yield _sse({"event": "progress", "stage": stage_detected, "progress": progress_val, "raw": stripped})
                else:
                    yield _sse({"event": "log", "line": stripped})

            # Политика вывода по стадиям
            if output_file.is_file():
                mtime = output_file.stat().st_mtime
                if last_mtime is None or mtime > last_mtime:
                    try:
                        with open(output_file, "r", encoding="utf-8") as f:
                            snapshot = json.load(f)
                    except Exception:
                        snapshot = None
                    if snapshot is not None:
                        if current_stage == "stage1":
                            async for msg in emit_partial("partial_stage1", snapshot):
                                yield msg
                        elif current_stage == "stage2":
                            buffered_stage2_snapshot = snapshot
                    last_mtime = mtime
                    last_partial_emit = now
                else:
                    if current_stage == "stage1" and (now - last_partial_emit > 15):
                        try:
                            with open(output_file, "r", encoding="utf-8") as f:
                                snapshot = json.load(f)
                            async for msg in emit_partial("partial_stage1", snapshot, {"stale": True}):
                                yield msg
                        except Exception:
                            pass
                        last_partial_emit = now

        # Завершение
        retcode = pop.poll()
        if retcode is None:
            pop.wait()
            retcode = pop.poll()
        if retcode != 0:
            try:
                stderr_tail = pop.stderr.read().decode("utf-8", errors="replace")
            except Exception:
                stderr_tail = ""
            yield _sse({"event": "error", "message": f"Pipeline exited with code {retcode}", "stderr": stderr_tail, "cmd": cmd})
            return

        if buffered_stage2_snapshot is not None:
            async for msg in emit_partial("stage2_done", buffered_stage2_snapshot, {"late": True}):
                yield msg
            buffered_stage2_snapshot = None

        if output_path.is_file():
            try:
                with open(output_path, "r", encoding="utf-8") as f:
                    final_data = json.load(f)
                yield _sse({"event": "final", "output": final_data})
                # Сохраняем в глобальный кэш, если можно
                if not _has_change_flag(ws):
                    sig = _load_origin_meta(ws)
                    if sig is not None:
                        filename, size_bytes = sig
                        _save_to_cache(ws, filename, size_bytes, output_path)
            except Exception as e:
                yield _sse({"event": "error", "message": f"Failed to read final output: {e}"})
        else:
            yield _sse({"event": "error", "message": "Final output.json not found"})

    if mode == "async":
        try:
            proc = await proc_or_future  # type: ignore
        except NotImplementedError:
            # Фолбэк Windows: sync Popen
            try:
                pop = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=pipeline_dir, env=env, text=False
                )
            except Exception as e:
                yield _sse({
                    "event": "error_start",
                    "message": "Failed to start pipeline (sync fallback) after asyncio NotImplementedError",
                    "reason": f"{e.__class__.__name__}: {e}",
                    "traceback": traceback.format_exc(),
                    "cmd": cmd
                })
                return
            async for s in run_sync_flow(pop):
                yield s
            return
        except Exception as e:
            yield _sse({
                "event": "error_start",
                "message": "Failed to start pipeline (await) due to unexpected error",
                "reason": f"{e.__class__.__name__}: {e}",
                "traceback": traceback.format_exc(),
                "cmd": cmd
            })
            return

        output_file = output_path

        while True:
            line = await _read_line_async(proc.stderr)
            now = time.time()

            if line:
                stripped = line.strip()
                if not any(stripped.startswith(pfx) for pfx in IGNORED_WARN_PREFIXES):
                    stage_detected = None
                    for marker, internal in STAGE_MARKERS.items():
                        if marker in stripped:
                            stage_detected = internal
                            break
                    if stage_detected:
                        if stage_detected == "stage3" and current_stage != "stage3" and buffered_stage2_snapshot is not None:
                            async for msg in emit_partial("stage2_done", buffered_stage2_snapshot):
                                yield msg
                            buffered_stage2_snapshot = None
                        current_stage = stage_detected
                        progress_val = None
                        m_count = RE_COUNT.search(stripped)
                        if m_count:
                            try:
                                cur = int(m_count.group(1)); total = int(m_count.group(2))
                                if total > 0:
                                    progress_val = cur / total
                            except Exception:
                                pass
                        else:
                            m_pct = RE_PCT.search(stripped)
                            if m_pct:
                                try:
                                    pct = float(m_pct.group(1))
                                    progress_val = pct / 100.0
                                except Exception:
                                    pass
                        yield _sse({"event": "progress", "stage": stage_detected, "progress": progress_val, "raw": stripped})
                    else:
                        yield _sse({"event": "log", "line": stripped})

            if output_file.is_file():
                mtime = output_file.stat().st_mtime
                if last_mtime is None or mtime > last_mtime:
                    try:
                        with open(output_file, "r", encoding="utf-8") as f:
                            snapshot = json.load(f)
                    except Exception:
                        snapshot = None
                    if snapshot is not None:
                        if current_stage == "stage1":
                            async for msg in emit_partial("partial_stage1", snapshot):
                                yield msg
                        elif current_stage == "stage2":
                            buffered_stage2_snapshot = snapshot
                    last_mtime = mtime
                    last_partial_emit = now
                else:
                    if current_stage == "stage1" and (now - last_partial_emit > 15):
                        try:
                            with open(output_file, "r", encoding="utf-8") as f:
                                snapshot = json.load(f)
                            async for msg in emit_partial("partial_stage1", snapshot, {"stale": True}):
                                yield msg
                        except Exception:
                            pass
                        last_partial_emit = now

            if proc.returncode is not None:
                break
            if proc.stdout.at_eof() and proc.stderr.at_eof():
                ret = await proc.wait()
                if ret is not None:
                    break

        retcode = await proc.wait()
        if retcode != 0:
            try:
                tail = (await proc.stderr.read()).decode("utf-8", errors="replace")
            except Exception:
                tail = ""
            yield _sse({"event": "error", "message": f"Pipeline exited with code {retcode}", "stderr": tail, "cmd": cmd})
            return

        if buffered_stage2_snapshot is not None:
            async for msg in emit_partial("stage2_done", buffered_stage2_snapshot, {"late": True}):
                yield msg
            buffered_stage2_snapshot = None

        if output_path.is_file():
            try:
                with open(output_path, "r", encoding="utf-8") as f:
                    final_data = json.load(f)
                yield _sse({"event": "final", "output": final_data})
                if not _has_change_flag(ws):
                    sig = _load_origin_meta(ws)
                    if sig is not None:
                        filename, size_bytes = sig
                        _save_to_cache(ws, filename, size_bytes, output_path)
            except Exception as e:
                yield _sse({"event": "error", "message": f"Failed to read final output: {e}"})
        else:
            yield _sse({"event": "error", "message": "Final output.json not found"})

    else:
        pop: subprocess.Popen = proc_or_future  # type: ignore
        async for s in run_sync_flow(pop):
            yield s


# -------------------- Публичный SSE эндпоинт --------------------
@router.get("/run")
async def run_pipeline_stream(
    doc_id: str,
    base_dir: str = Query("data"),
    batch_size: int = Query(1, ge=1),
    stage0_enable: bool = Query(True),
    stage0_batch_size: int = Query(6, ge=1),
    stage0_max_sentences: int = Query(50, ge=5),
    repo_id: Optional[str] = Query("unsloth/gpt-oss-20b-GGUF"),
    filename: Optional[str] = Query("gpt-oss-20b-F16.gguf"),
    model_path: Optional[str] = Query(None),
    n_ctx: int = Query(15000, ge=4096),
    n_gpu_layers: int = Query(-1),
    retries: int = Query(3, ge=1),
    llm_effort_s0: str = Query("medium", regex="^(low|medium|high)$"),
    llm_effort_s1: str = Query("medium", regex="^(low|medium|high)$"),
    llm_effort_s2: str = Query("medium", regex="^(low|medium|high)$"),
    llm_effort_s3: str = Query("high", regex="^(low|medium|high)$"),
    debug: bool = Query(False),
):
    """
    Логика:
    - Сначала ищем готовый output.json в соседних папках data/* с тем же базовым названием (без _<hex>),
      без temp.txt, с совпадающим uploads-размером — и используем его мгновенно.
    - Если нет — пробуем глобальный кэш analyzer_cache.
    - Если нет — запускаем пайплайн и стримим прогресс.
    """
    ws = Path(base_dir) / doc_id
    parsed_path = ws / "parsed_scenes.json"
    if not parsed_path.is_file():
        raise HTTPException(status_code=404, detail="parsed_scenes.json not found for doc_id")

    scenes = load_parsed_scenes(str(ws))
    if scenes is None:
        raise HTTPException(status_code=400, detail="Failed to load parsed scenes")

    params = {
        "batch_size": batch_size,
        "stage0_enable": stage0_enable,
        "stage0_batch_size": stage0_batch_size,
        "stage0_max_sentences": stage0_max_sentences,
        "repo_id": repo_id,
        "filename": filename,
        "model_path": model_path,
        "n_ctx": n_ctx,
        "n_gpu_layers": n_gpu_layers,
        "retries": retries,
        "llm_effort_s0": llm_effort_s0,
        "llm_effort_s1": llm_effort_s1,
        "llm_effort_s2": llm_effort_s2,
        "llm_effort_s3": llm_effort_s3,
        "debug": debug,
    }

    async def gen():
        try:
            async for chunk in _stream_pipeline(ws, scenes, params):
                yield chunk
        except Exception:
            yield _sse({"event": "error", "message": "Unhandled streaming exception", "traceback": traceback.format_exc()})

    headers = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)