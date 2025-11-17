#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main FastAPI application.

Изменения:
- /api/report/{doc_id} теперь GET (как вы просили).
- На основе output.json генерируется подробный PDF‑отчёт с:
  * итоговым рейтингом,
  * полной статистикой по нарушениям,
  * списком эпизодов с причинами и советами,
  * часто встречающимися нарушениями,
  * Parents guide и хронологической визуализацией.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Body, Query
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from .runners.stream_stage_runner import router as analyze_router
from .runners.stage3_recalc import perform_stage3_recalc

from .models import SceneUploadResponse
from .edit_scene.service import recalc_and_merge_single_scene

from .storage import (
    init_storage,
    create_doc_workspace,
    save_uploaded_file,
    parse_and_store_scenario,
    load_parsed_scenes,
    stage_path,
    load_json_if_exists,
)
from .ai.replacer import process_ai_replace
from .edit.service import (
    add_violation_extended,
    update_violation_extended,
    cancel_violation,
    update_violation_sentence,
)

from .save.exporter import build_script_html


from .report.builder import build_report_context
from .report.generator import async_generate_report, render_report_html
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi import Query

import sys

if sys.platform == "win32":
    import asyncio
    try:
        # Установим ProactorEventLoopPolicy для корректной работы asyncio.create_subprocess_exec на Windows
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        # если по какой-то причине не получилось — логируем, но продолжаем
        try:
            import logging
            logging.getLogger("startup").warning("Could not set WindowsProactorEventLoopPolicy()")
        except Exception:
            pass

app = FastAPI(
    title="Scenario Analysis API",
    version="1.7.1",
    description="Многостадийный анализ сценариев, редактирование нарушений, AI‑переписывание, пересчёт рейтинга и PDF/HTML‑отчёты.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

BASE_DATA_DIR = Path(os.environ.get("DATA_DIR", "data")).resolve()
try:
    init_storage(str(BASE_DATA_DIR))
except Exception:
    BASE_DATA_DIR.mkdir(parents=True, exist_ok=True)


def _ensure_dir(p: Path) -> str:
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


app.mount("/static", StaticFiles(directory=_ensure_dir(BASE_DATA_DIR / "static")), name="static")



# --------- Upload ----------
@app.post("/api/scenario/upload", response_model=SceneUploadResponse)
async def upload_scenario(file: UploadFile = File(...)):
    base_name = os.path.basename(file.filename) if file.filename else "scenario"
    doc_id = os.path.splitext(base_name)[0] + "_" + os.urandom(4).hex()
    ws = create_doc_workspace(str(BASE_DATA_DIR), doc_id)
    stored = await save_uploaded_file(ws, file)
    try:
        scenes = parse_and_store_scenario(ws, stored)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Parse error: {e}")
    return SceneUploadResponse(doc_id=doc_id, scenes=scenes)


# --------- Get parsed scenario ----------
@app.get("/api/scenario/{doc_id}")
def get_scenario(doc_id: str):
    ws = os.path.join(str(BASE_DATA_DIR), doc_id)
    scenes = load_parsed_scenes(ws)
    if scenes is None:
        raise HTTPException(status_code=404, detail="Parsed scenes not found")
    return JSONResponse({"doc_id": doc_id, "scenes": scenes})


# --------- Stage outputs ----------
@app.get("/api/stage/{doc_id}/1")
def get_stage1(doc_id: str):
    ws = os.path.join(str(BASE_DATA_DIR), doc_id)
    data = load_json_if_exists(stage_path(ws, "output_1.json"))
    if not data:
        raise HTTPException(status_code=404, detail="Stage1 not ready")
    return data


@app.get("/api/stage/{doc_id}/2")
def get_stage2(doc_id: str):
    ws = os.path.join(str(BASE_DATA_DIR), doc_id)
    data = load_json_if_exists(stage_path(ws, "output_2.json"))
    if not data:
        raise HTTPException(status_code=404, detail="Stage2 not ready")
    return data


@app.get("/api/stage/{doc_id}/final")
def get_stage_final(doc_id: str):
    ws = os.path.join(str(BASE_DATA_DIR), doc_id)
    data = load_json_if_exists(stage_path(ws, "output_final.json"))
    if not data:
        raise HTTPException(status_code=404, detail="Final not ready")
    return data


# --------- AI Replace ----------
@app.post("/api/ai/replace/{doc_id}")
def ai_replace(
    doc_id: str,
    payload: Dict[str, Any] = Body(...),
    law_path: Optional[str] = Query(None),
    model_path: Optional[str] = Query(None),
    repo_id: str = Query("unsloth/gpt-oss-20b-GGUF"),
    filename: str = Query("gpt-oss-20b-F16.gguf"),
    effort: str = Query("medium", regex="^(low|medium|high)$"),
    batch_size: int = Query(2, ge=1, le=16),
    n_ctx: int = Query(8192, ge=1024),
    n_gpu_layers: int = Query(-1),
    temperature: Optional[float] = Query(None),
    top_p: float = Query(0.2),
    repeat_penalty: float = Query(1.05),
    seed: int = Query(2025),
    max_tokens: int = Query(4096, ge=128),
    retries: int = Query(3, ge=1),
    debug: bool = Query(False),
):
    ws = os.path.join(str(BASE_DATA_DIR), doc_id)
    if not os.path.isdir(ws):
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        result = process_ai_replace(
            ws=ws,
            payload=payload,
            law_path=law_path,
            model_path=model_path,
            repo_id=repo_id,
            filename=filename,
            effort=effort,
            batch_size=batch_size,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            temperature=temperature,
            top_p=top_p,
            repeat_penalty=repeat_penalty,
            seed=seed,
            max_tokens=max_tokens,
            retries=retries,
            debug=debug,
        )
        Path(ws, "temp.txt").touch()
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI replace failed: {e}")
    return JSONResponse(result)


# --------- Violations CRUD (использует edit.service, который уже ставит temp.txt) ----------
@app.post("/api/edit/violation/add/{doc_id}")
def violation_add(doc_id: str, payload: Dict[str, Any] = Body(...)):
    required = ["scene_index", "sentence_index", "text", "fragment_severity", "labels"]
    for k in required:
        if k not in payload:
            raise HTTPException(status_code=400, detail=f"Missing field '{k}'")
    ws = os.path.join(str(BASE_DATA_DIR), doc_id)
    if not os.path.isdir(ws):
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        data = add_violation_extended(
            ws=ws,
            scene_index=int(payload["scene_index"]),
            sentence_index=int(payload["sentence_index"]),
            text=str(payload["text"]),
            fragment_severity=str(payload["fragment_severity"]),
            labels_spec=list(payload.get("labels", [])),
        )
        return JSONResponse(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/edit/violation/update/{doc_id}")
def violation_update(doc_id: str, payload: Dict[str, Any] = Body(...)):
    required = ["scene_index", "sentence_index", "text", "fragment_severity", "labels"]
    for k in required:
        if k not in payload:
            raise HTTPException(status_code=400, detail=f"Missing field '{k}'")
    ws = os.path.join(str(BASE_DATA_DIR), doc_id)
    if not os.path.isdir(ws):
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        data = update_violation_extended(
            ws=ws,
            scene_index=int(payload["scene_index"]),
            sentence_index=int(payload["sentence_index"]),
            text=str(payload["text"]),
            fragment_severity=str(payload["fragment_severity"]),
            labels_spec=list(payload.get("labels", [])),
        )
        return JSONResponse(data)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.patch("/api/edit/violation/sentence/{doc_id}")
def violation_sentence_update(doc_id: str, payload: Dict[str, Any] = Body(...)):
    required = ["scene_index", "sentence_index", "text"]
    for k in required:
        if k not in payload:
            raise HTTPException(status_code=400, detail=f"Missing field '{k}'")
    ws = os.path.join(str(BASE_DATA_DIR), doc_id)
    if not os.path.isdir(ws):
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        data = update_violation_sentence(
            ws=ws,
            scene_index=int(payload["scene_index"]),
            sentence_index=int(payload["sentence_index"]),
            new_text=str(payload["text"]),
        )
        return JSONResponse(data)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/edit/violation/cancel/{doc_id}")
def violation_cancel(doc_id: str, payload: Dict[str, Any] = Body(...)):
    required = ["scene_index", "sentence_index"]
    for k in required:
        if k not in payload:
            raise HTTPException(status_code=400, detail=f"Missing field '{k}'")
    ws = os.path.join(str(BASE_DATA_DIR), doc_id)
    if not os.path.isdir(ws):
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        data = cancel_violation(
            ws=ws,
            scene_index=int(payload["scene_index"]),
            sentence_index=int(payload["sentence_index"]),
        )
        return JSONResponse(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/scene/recalc_one/{doc_id}")
def recalc_one_scene(
    doc_id: str,
    payload: Dict[str, Any] = Body(...),
    model_path: Optional[str] = Query(None),
    repo_id: str = Query("unsloth/gpt-oss-20b-GGUF"),
    filename: str = Query("gpt-oss-20b-F16.gguf"),
    n_ctx: int = Query(6000, ge=2048),
    n_gpu_layers: int = Query(-1),
    llm_effort_s1: str = Query("low", regex="^(low|medium|high)$"),
    llm_effort_s2: str = Query("low", regex="^(low|medium|high)$"),
    retries: int = Query(3, ge=1),
    debug: bool = Query(False)
):
    """
    Recalculate Stage 1+2 for a single edited scene and merge results into the full output.json.

    Expected body:
    {
      "scene_index": 12,
      "heading": "8-1. ...",
      "page": 10,                  # optional
      "sentences": ["...", "..."]  # required
    }
    """
    required = ["scene_index", "sentences"]
    for k in required:
        if k not in payload:
            raise HTTPException(status_code=400, detail=f"Missing field '{k}'")
    if not isinstance(payload.get("sentences"), list) or not all(isinstance(x, str) for x in payload["sentences"]):
        raise HTTPException(status_code=400, detail="Field 'sentences' must be a list of strings")

    ws = os.path.join(str(BASE_DATA_DIR), doc_id)
    if not os.path.isdir(ws):
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        updated = recalc_and_merge_single_scene(
            ws=ws,
            scene_index=int(payload["scene_index"]),
            scene_payload={
                "heading": payload.get("heading",""),
                "page": payload.get("page"),
                "sentences": payload["sentences"]
            },
            repo_id=repo_id,
            filename=filename,
            model_path=model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            llm_effort_s1=llm_effort_s1,
            llm_effort_s2=llm_effort_s2,
            retries=retries,
            debug=debug
        )
        return JSONResponse(updated)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Single-scene recalc failed: {e}")

# ---------- Report (GET, async Playwright) ----------
@app.get("/api/report/{doc_id}")
async def report_endpoint(
    doc_id: str,
    inline: bool = Query(True, description="true — открыть в браузере; false — скачать"),
    engine: str = Query("auto", regex="^(auto|weasyprint|pisa|html)$", description="engine to use: 'auto'|'weasyprint'|'pisa'|'html'"),
    diagnostic: bool = Query(False, description="unused here, kept for compatibility"),
    return_json: bool = Query(False, description="Возвращать JSON метаданные вместо файла"),
):
    ws = BASE_DATA_DIR / doc_id
    if not ws.is_dir():
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        context = build_report_context(str(ws))
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build report context: {e}")

    # If user explicitly asks for HTML -> return HTML (or JSON with html length)
    if engine == "html":
        html = render_report_html(context)
        if return_json:
            return JSONResponse({"ok": True, "html_length": len(html)})
        return HTMLResponse(content=html, status_code=200)

    # Try to generate PDF (weasyprint -> pisa)
    try:
        res = await async_generate_report(str(ws), context, mode="pdf", engine=engine)
    except RuntimeError as e:
        # If user requested specific engine, return error 500; if auto, fallback to returning HTML
        msg = str(e)
        if engine != "auto":
            raise HTTPException(status_code=500, detail=f"PDF generation failed ({engine}): {msg}")
        # auto fallback -> return HTML for browser
        html = render_report_html(context)
        if return_json:
            return JSONResponse({"ok": False, "fallback": "html", "error": msg})
        return HTMLResponse(content=html, status_code=200)

    # В начале файла добавьте:
    import urllib.parse

    # Внутри report_endpoint — замените часть возврата файла на это:
    # Success -> return file
    path = res.get("path")
    size_bytes = res.get("size_bytes", 0)
    if not path:
        raise HTTPException(status_code=500, detail="PDF generator did not return a path")

    # Подготовим безопасный заголовок Content-Disposition,
    # чтобы избежать ошибки кодирования latin-1 при использовании non-ASCII имени файла.
    filename = f"{doc_id}_report.pdf"

    def _ascii_fallback(name: str) -> str:
        # Оставляем только ASCII-символы как fallback; если получится пусто — используем 'report.pdf'
        fb = "".join(ch for ch in name if ord(ch) < 128)
        fb = fb.strip() or "report.pdf"
        # Уберём кавычки на всякий случай
        return fb.replace('"', "").replace("'", "")

    fallback_name = _ascii_fallback(filename)
    filename_star = urllib.parse.quote(filename, safe="")  # percent-encode UTF-8
    disposition = "inline" if inline else "attachment"
    content_disp = f'{disposition}; filename="{fallback_name}"; filename*=UTF-8\'\'{filename_star}'

    headers = {"Content-Disposition": content_disp}

    if return_json:
        return JSONResponse({"ok": True, "path": path, "size_bytes": size_bytes})

    # Передаём headers — теперь header value содержит только ASCII символы и %-escapes
    return FileResponse(path, media_type="application/pdf", filename=filename, headers=headers)


# --------- Stage3 rating recalc ----------
@app.get("/api/rating/recalc/{doc_id}")
def rating_recalc(
    doc_id: str,
    no_llm: bool = Query(False),
    llm_effort: str = Query("medium", regex="^(low|medium|high)$"),
    model_path: Optional[str] = Query(None),
    repo_id: str = Query("unsloth/gpt-oss-20b-GGUF"),
    filename: str = Query("gpt-oss-20b-F16.gguf"),
    n_ctx: int = Query(12000),
    n_gpu_layers: int = Query(-1),
    debug: bool = Query(False),
):
    ws = os.path.join(str(BASE_DATA_DIR), doc_id)
    if not os.path.isdir(ws):
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        result = perform_stage3_recalc(
            ws=ws,
            use_llm=not no_llm,
            repo_id=repo_id,
            filename=filename,
            model_path=model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            llm_effort=llm_effort,
            retries=3,
            debug=debug,
        )
        return JSONResponse(result)
    except FileNotFoundError as fe:
        raise HTTPException(status_code=404, detail=str(fe))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stage3 recalc failed: {e}")

# ---------- New: HTML view for script ----------
@app.post("/api/scenario/view/{doc_id}")
def scenario_view(
    doc_id: str,
    payload: Any = Body(...),
    inline: bool = Query(True, description="true — вернуть HTML (страница откроется в браузере); false — вернуть путь к файлу"),
    save: bool = Query(True, description="Сохранить HTML в <ws>/exports"),
    show_lines: bool = Query(False),
    use_blocks: bool = Query(False),
    uppercase_headings: bool = Query(False),
    title: Optional[str] = Query(None),
):
    """
    HTML‑визуализация сценария:
      POST /api/scenario/view/{doc_id}?inline=true&save=true&show_lines=false&use_blocks=false&uppercase_headings=false
      Body: {"scriptScenes":[...]} или [ ... ]
    """
    ws = os.path.join(str(BASE_DATA_DIR), doc_id)
    if not os.path.isdir(ws):
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        res = build_script_html(
            ws=ws,
            payload=payload,
            uppercase_headings=uppercase_headings,
            show_lines=show_lines,
            use_blocks=use_blocks,
            save_file=save,
            title=title or f"Сценарий — {doc_id}",
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render script HTML: {e}")

    if inline:
        # Вернём HTML сразу (удобно открывать в новой вкладке)
        return HTMLResponse(content=res["html"], status_code=200)

    # Иначе вернём информацию о пути к файлу
    rel = ""
    if res.get("path"):
        try:
            rel = os.path.relpath(res["path"], ws)
        except Exception:
            rel = res["path"]
    return JSONResponse({"saved": bool(res.get("path")), "path": res.get("path"), "relative_path": rel})


# --------- Подключаем SSE пайплайн ----------
app.include_router(analyze_router)


# --------- Root ----------
@app.get("/")
def root():
    return {
        "ok": True,
        "version": "1.7.0",
        "endpoints": [
            "POST /api/scenario/upload",
            "GET  /api/scenario/{doc_id}",
            "GET  /api/stage/{doc_id}/1|2|final",
            "POST /api/ai/replace/{doc_id}",
            "POST /api/scene/recalc_one/{doc_id}",
            "POST /api/edit/violation/add/{doc_id}",
            "PUT  /api/edit/violation/update/{doc_id}",
            "PATCH /api/edit/violation/sentence/{doc_id}",
            "POST /api/edit/violation/cancel/{doc_id}",
            "GET  /api/rating/recalc/{doc_id}",
            "GET  /api/report/{doc_id}",
            "POST /api/scenario/view/{doc_id}",
            "GET  /api/analyze/run (SSE multi-stage pipeline)",
        ],
    }