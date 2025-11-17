#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
viewer.py — HTML-визуализация сценария (открывается в браузере).

Назначение:
- Принять JSON с массивом сцен (или {"scriptScenes":[...]}).
- Сформировать красиво отформатированную HTML-страницу:
  * Шрифт базовый — системный моно: ui-monospace, Consolas, "Courier New", monospace
  * Заголовки сцен — жирные (опционально UPPERCASE)
  * Список актёров — подчёркнутый, мелкий
  * Диалог: имя — по центру, UPPERCASE, жирным; реплика — с отступом
  * Action — обычный абзац слева
  * Возможность добавлять [ln:N] маркеры (show_lines)
  * Можно предпочесть blocks вместо originalSentences (use_blocks)

Пути:
- Шаблон: backend/save/templates/script_view.html
- Сохранение HTML (опционально): <ws>/exports/script_view_<timestamp>.html
"""

from __future__ import annotations
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape


def _normalize_space(s: Optional[str]) -> str:
    if s is None:
        return ""
    s2 = unicodedata.normalize("NFKC", str(s))
    s2 = s2.replace("\r\n", "\n").replace("\r", "\n")
    s2 = re.sub(r"[ \t]+", " ", s2)
    return s2.strip()


def parse_input_payload(payload: Any) -> List[Dict[str, Any]]:
    """
    Принимает либо объект {"scriptScenes": [...]}, либо список сцен.
    Возвращает нормализованный список сцен (без глубокой валидации).
    """
    if isinstance(payload, dict) and "scriptScenes" in payload:
        arr = payload.get("scriptScenes")
    elif isinstance(payload, list):
        arr = payload
    else:
        raise ValueError("JSON must be an array of scenes or an object with key 'scriptScenes'.")

    if not isinstance(arr, list):
        raise ValueError("'scriptScenes' must be a list.")

    out: List[Dict[str, Any]] = []
    for i, sc in enumerate(arr):
        if not isinstance(sc, dict):
            continue
        scene = dict(sc)
        scene.setdefault("id", f"scene_{i+1}")
        scene.setdefault("sceneNumber", scene.get("sceneNumber", ""))
        scene.setdefault("page", scene.get("page", ""))  # может быть int/str
        scene.setdefault("heading", scene.get("heading", ""))
        scene.setdefault("content", scene.get("content", ""))
        scene.setdefault("originalSentences", scene.get("originalSentences", None))
        scene.setdefault("blocks", scene.get("blocks", None))
        scene.setdefault("cast_list", scene.get("cast_list", []) or [])
        scene.setdefault("meta", scene.get("meta", None))
        scene.setdefault("number", scene.get("number", ""))
        scene.setdefault("number_suffix", scene.get("number_suffix", ""))
        scene.setdefault("ie", scene.get("ie", ""))
        scene.setdefault("location", scene.get("location", ""))
        scene.setdefault("time_of_day", scene.get("time_of_day", ""))
        scene.setdefault("shoot_day", scene.get("shoot_day", ""))
        scene.setdefault("timecode", scene.get("timecode", ""))
        scene.setdefault("removed", bool(scene.get("removed", False)))
        scene.setdefault("scene_index", scene.get("scene_index", i))
        out.append(scene)
    return out


def _env() -> Environment:
    here = Path(__file__).resolve().parent
    tpl_dir = here / "templates"
    return Environment(
        loader=FileSystemLoader(str(tpl_dir)),
        autoescape=select_autoescape(["html"]),
        enable_async=False,
    )


def _select_sentences(sc: Dict[str, Any], use_blocks: bool) -> Optional[List[Dict[str, Any]]]:
    """
    Возвращает унифицированный список "предложений/блоков" с ключами:
      text, kind (action|dialogue), speaker, line_no
    """
    def _from_blocks(blocks: Any) -> List[Dict[str, Any]]:
        res: List[Dict[str, Any]] = []
        if not isinstance(blocks, list):
            return res
        for b in blocks:
            if not isinstance(b, dict):
                continue
            res.append({
                "text": b.get("text", ""),
                "kind": b.get("type", "action"),
                "speaker": b.get("speaker") if b.get("type") == "dialogue" else None,
                "line_no": b.get("line_no"),
            })
        return res

    if use_blocks and sc.get("blocks") is not None:
        return _from_blocks(sc.get("blocks"))
    if sc.get("originalSentences") is not None:
        arr = sc.get("originalSentences")
        if isinstance(arr, list):
            res: List[Dict[str, Any]] = []
            for s in arr:
                if isinstance(s, dict):
                    res.append({
                        "text": s.get("text", ""),
                        "kind": s.get("kind", "action"),
                        "speaker": s.get("speaker"),
                        "line_no": s.get("line_no"),
                    })
                else:
                    res.append({"text": str(s), "kind": "action", "speaker": None, "line_no": None})
            return res
    # fallback на blocks
    if sc.get("blocks") is not None:
        return _from_blocks(sc.get("blocks"))
    # если нет ни того, ни другого — None (будем использовать content)
    return None


def _compute_heading(sc: Dict[str, Any], uppercase_headings: bool) -> str:
    heading = _normalize_space(sc.get("heading", "") or "")
    if not heading:
        num = sc.get("number", "")
        suf = sc.get("number_suffix", "")
        ie = sc.get("ie", "")
        loc = sc.get("location", "")
        tod = sc.get("time_of_day", "")
        parts = []
        if num:
            parts.append(f"{num}{suf}")
        if ie:
            parts.append(ie)
        if loc:
            parts.append(loc)
        if tod:
            parts.append(tod)
        heading = " . ".join([p for p in parts if p])
    return heading.upper() if uppercase_headings else heading


def build_script_html(
    ws: str,
    payload: Any,
    *,
    uppercase_headings: bool = False,
    show_lines: bool = False,
    use_blocks: bool = False,
    save_file: bool = True,
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Рендер HTML сценария.
    - ws: путь к рабочей папке (data/<doc_id>)
    - payload: JSON из фронта
    - save_file: если True, сохранить HTML в <ws>/exports/script_view_<ts>.html
    Возвращает: {"html": "<...>", "path": "<путь или ''>"}
    """
    scenes = parse_input_payload(payload)

    # Подготовим "view" слои (не мутируя исходный объект)
    view_scenes: List[Dict[str, Any]] = []
    for sc in scenes:
        v: Dict[str, Any] = dict(sc)
        v["heading_view"] = _compute_heading(sc, uppercase_headings)
        v["sentences_view"] = _select_sentences(sc, use_blocks)
        # Нормализуем content для fallback
        v["content_norm"] = _normalize_space(sc.get("content", "") or "")
        view_scenes.append(v)

    env = _env()
    tpl = env.get_template("script_view.html")
    html = tpl.render(
        title=title or "Сценарий",
        scenes=view_scenes,
        show_lines=show_lines,
    )

    out_path = ""
    if save_file:
        export_dir = Path(ws) / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_path = str(export_dir / f"script_view_{ts}.html")
        Path(out_path).write_text(html, encoding="utf-8")

    return {"html": html, "path": out_path}