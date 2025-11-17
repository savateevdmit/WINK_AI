#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Storage utilities for the Scenario Analysis backend.

Responsibilities:
- Initialize storage directories
- Create per-document workspace layout
- Save uploaded files
- Parse uploaded screenplay files (PDF/DOCX/JSON) using parser.segmentation.parse_file_to_scenes
- Load/save parsed_scenes.json and stage/model outputs
- Track simple metadata/status/dirty flags
- Helpers for export and basic edits (replace fragment / cancel violation)

This module is intentionally self-contained and filesystem-based (no DB).
"""

from __future__ import annotations

import os
import json
import shutil
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from datetime import datetime
import asyncio

# import parser
try:
    from .parser.segmentation import parse_file_to_scenes
except Exception:
    # If parser not available at import time, raise helpful message on use
    parse_file_to_scenes = None  # type: ignore

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


# ---------------------------------------------------------------------
# Initialization / workspace
# ---------------------------------------------------------------------

def init_storage(base_dir: str) -> None:
    """
    Ensure base storage directories exist.
    """
    p = Path(base_dir)
    p.mkdir(parents=True, exist_ok=True)
    (p / "static").mkdir(parents=True, exist_ok=True)
    (p / "static" / "exports").mkdir(parents=True, exist_ok=True)


def create_doc_workspace(base_dir: str, doc_id: str) -> str:
    """
    Create workspace directories for a document and return workspace path.
    Layout:
      <base_dir>/<doc_id>/
        uploads/
        inputs/
        stages/
        model/
          debug/
    """
    base = Path(base_dir)
    ws = base / doc_id
    (ws / "uploads").mkdir(parents=True, exist_ok=True)
    (ws / "inputs").mkdir(parents=True, exist_ok=True)
    (ws / "stages").mkdir(parents=True, exist_ok=True)
    (ws / "model" / "debug").mkdir(parents=True, exist_ok=True)
    return str(ws)


# ---------------------------------------------------------------------
# Upload handling
# ---------------------------------------------------------------------

async def save_uploaded_file(ws: str, upload_file) -> str:
    """
    Save ASGI UploadFile to ws/uploads/ and return the absolute path to saved file.
    This function is async and reads the upload in chunks.
    """
    upload_dir = Path(ws) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = getattr(upload_file, "filename", None) or f"upload_{int(datetime.utcnow().timestamp())}"
    dst = upload_dir / filename
    # Support either Starlette/FastAPI UploadFile (async read) or a file-like object
    try:
        # FastAPI UploadFile
        async with await upload_file.readable():
            pass
    except Exception:
        # Not all UploadFile implementations expose readable(); fallback to normal async reading below
        pass

    # Try the upload_file.read async API (FastAPI)
    try:
        with open(dst, "wb") as f:
            while True:
                chunk = await upload_file.read(1024 * 1024)
                if not chunk:
                    break
                if isinstance(chunk, str):
                    chunk = chunk.encode()
                f.write(chunk)
        return str(dst)
    except Exception:
        # Fallback: maybe upload_file is a SpooledTemporaryFile or file-like
        try:
            upload_file.file.seek(0)
            with open(dst, "wb") as f:
                shutil.copyfileobj(upload_file.file, f)
            return str(dst)
        except Exception as e:
            raise RuntimeError(f"Failed to save uploaded file: {e}") from e


# ---------------------------------------------------------------------
# Parsing and parsed scenes management
# ---------------------------------------------------------------------

def _ensure_scene_index(scenes: List[Dict[str, Any]]) -> None:
    for i, sc in enumerate(scenes):
        sc["scene_index"] = i
        if "sentences" not in sc or not isinstance(sc["sentences"], list):
            sent = []
            for b in sc.get("blocks", []):
                t = b.get("text", "")
                if not t:
                    continue
                sent.append({
                    "text": t,
                    "kind": b.get("type", "action"),
                    "speaker": b.get("speaker", None),
                    "line_no": b.get("line_no", None)
                })
            sc["sentences"] = sent


def parse_and_store_scenario(ws: str, uploaded_path: str, *, verbose: bool = False) -> List[Dict[str, Any]]:
    """
    Parse the uploaded screenplay file (pdf/docx/json) and store parsed_scenes.json in the workspace.
    Returns the parsed scenes list.
    """
    if parse_file_to_scenes is None:
        raise RuntimeError("Parser module not available (parse_file_to_scenes)")

    scenes = parse_file_to_scenes(uploaded_path, verbose=verbose)
    if not isinstance(scenes, list):
        raise ValueError("Parser must return a list of scenes")

    _ensure_scene_index(scenes)

    ws_path = Path(ws)
    out_path = ws_path / "parsed_scenes.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(scenes, f, ensure_ascii=False, indent=2)

    meta = {
        "uploaded_file": os.path.basename(uploaded_path),
        "scenes_count": len(scenes),
        "status": "parsed",
        "dirty_global": False,
        "dirty_scenes": [],
        "updated_at": _now_iso(),
    }
    with open(ws_path / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return scenes


def load_parsed_scenes(ws: str) -> Optional[List[Dict[str, Any]]]:
    p = Path(ws) / "parsed_scenes.json"
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ---------------------------------------------------------------------
# Metadata / status management
# ---------------------------------------------------------------------

def _read_meta(ws: str) -> Dict[str, Any]:
    p = Path(ws) / "meta.json"
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_meta(ws: str, meta: Dict[str, Any]) -> None:
    p = Path(ws) / "meta.json"
    meta["updated_at"] = _now_iso()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def set_doc_status(ws: str, status: str, error: Optional[str] = None) -> None:
    meta = _read_meta(ws)
    meta["status"] = status
    if error:
        meta["error"] = error
    _write_meta(ws, meta)


def get_doc_status(ws: str) -> Dict[str, Any]:
    meta = _read_meta(ws)
    return meta


# ---------------------------------------------------------------------
# Stage / result storage
# ---------------------------------------------------------------------

def stage_path(ws: str, filename: str) -> str:
    """
    Return path to a file inside <ws>/stages/.
    """
    p = Path(ws) / "stages"
    p.mkdir(parents=True, exist_ok=True)
    return str(p / filename)


def ensure_static_mount_dir(path_like) -> str:
    p = Path(path_like)
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def save_result_json(ws: str, filename: str, data: Any) -> str:
    """
    Save `data` as JSON into stages/<filename>.
    Additionally, if filename looks like the main pipeline output (output.json),
    also write it to <ws>/model/output.json for compatibility with the runner.
    Returns the path written.
    """
    ws_path = Path(ws)
    stages_dir = ws_path / "stages"
    stages_dir.mkdir(parents=True, exist_ok=True)
    dest = stages_dir / filename
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Also write canonical model/output.json if relevant
    if filename in ("output.json", "output_final.json", "output_1.json", "output_2.json"):
        model_dir = ws_path / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        with open(model_dir / "output.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return str(dest)


def load_json_if_exists(path: str) -> Optional[dict]:
    p = Path(path)
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ---------------------------------------------------------------------
# Dirty flags / edits
# ---------------------------------------------------------------------

def mark_scene_dirty(ws: str, scene_index: int) -> None:
    meta = _read_meta(ws)
    dirty = set(meta.get("dirty_scenes", []))
    dirty.add(int(scene_index))
    meta["dirty_scenes"] = sorted(list(dirty))
    meta["dirty_global"] = True
    _write_meta(ws, meta)


def clear_dirty_flags_all(ws: str) -> None:
    meta = _read_meta(ws)
    meta["dirty_scenes"] = []
    meta["dirty_global"] = False
    _write_meta(ws, meta)


def register_violation_cancel(ws: str, scene_index: int, fragment_text: str) -> bool:
    """
    Mark a problem fragment as 'cancelled' in model/output.json and stages files.
    Returns True if at least one fragment matched and was flagged.
    """
    ws_path = Path(ws)
    model_out = ws_path / "model" / "output.json"
    changed = False
    if not model_out.exists():
        return False
    try:
        with open(model_out, "r", encoding="utf-8") as f:
            j = json.load(f)
    except Exception:
        return False

    for pf in j.get("problem_fragments", []):
        if pf.get("text") == fragment_text and pf.get("scene_index") == int(scene_index):
            pf["cancelled"] = True
            changed = True

    if changed:
        # persist to stages and model
        save_result_json(ws, "output_final.json", j)
    return changed


def apply_replace_ai_fragment(ws: str, scene_index: int, fragment_original: str, fragment_new: str) -> bool:
    """
    Replace text of an AI-detected fragment. Returns True if replacement done.
    """
    ws_path = Path(ws)
    model_out = ws_path / "model" / "output.json"
    changed = False
    if not model_out.exists():
        return False
    try:
        with open(model_out, "r", encoding="utf-8") as f:
            j = json.load(f)
    except Exception:
        return False

    for pf in j.get("problem_fragments", []):
        if pf.get("text") == fragment_original and pf.get("scene_index") == int(scene_index):
            pf["text"] = fragment_new
            changed = True

    if changed:
        save_result_json(ws, "output_final.json", j)
    return changed


# ---------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------

def check_dirty_before_export(ws: str) -> Dict[str, Any]:
    """
    Return a small dict indicating whether export is allowed or recalc required.
    """
    meta = _read_meta(ws)
    needs = {"needs_recalc": bool(meta.get("dirty_global", False)), "dirty_scenes": meta.get("dirty_scenes", [])}
    return needs


def perform_export(ws: str, fmt: str = "json") -> str:
    """
    Export the final output. Supported formats: json, zip (json inside).
    Writes to <BASE_DATA_DIR>/static/exports/<filename> and returns the public path
    relative to server: /static/exports/<filename>
    """
    ws_path = Path(ws)
    # Read final output from model/output.json or stages/output_final.json
    candidates = [
        ws_path / "model" / "output.json",
        ws_path / "stages" / "output_final.json",
        ws_path / "stages" / "output.json",
    ]
    data = None
    for c in candidates:
        if c.exists():
            try:
                with open(c, "r", encoding="utf-8") as f:
                    data = json.load(f)
                break
            except Exception:
                continue
    if data is None:
        raise FileNotFoundError("No final output found to export")

    base_dir = ws_path.parent  # this is BASE_DATA_DIR
    export_dir = base_dir / "static" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    doc_id = ws_path.name
    if fmt == "json":
        fname = f"{doc_id}.export.{ts}.json"
        outp = export_dir / fname
        with open(outp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return f"/static/exports/{fname}"
    elif fmt == "zip":
        import zipfile
        fname = f"{doc_id}.export.{ts}.zip"
        outp = export_dir / fname
        with zipfile.ZipFile(outp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{doc_id}.json", json.dumps(data, ensure_ascii=False, indent=2))
        return f"/static/exports/{fname}"
    else:
        raise ValueError("Unsupported export format: " + str(fmt))


# ---------------------------------------------------------------------
# Utility: load/save stage JSON using canonical stage_path
# ---------------------------------------------------------------------

def save_stage_json(ws: str, filename: str, data: Any) -> str:
    path = stage_path(ws, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


# ---------------------------------------------------------------------
# End of storage.py
# ---------------------------------------------------------------------