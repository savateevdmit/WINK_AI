#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Export utilities for Scenario Analysis backend.

Provides:
- check_dirty_before_export(ws) -> dict  (wrapper over storage.check_dirty_before_export)
- perform_export(ws, fmt="json") -> str (public URL to exported file)

Supported formats:
- "json" : final JSON (default)
- "csv"  : CSV of problem_fragments (one row per fragment)
- "zip"  : ZIP containing JSON + CSV
- "xlsx" : Excel workbook (requires openpyxl), fallback to zip if not available

Files are written to: <BASE_DATA_DIR>/static/exports/<docid>.export.<TIMESTAMP>.<ext>
Returned path is "/static/exports/<filename>"

The exporter reads final model output from:
 - <ws>/model/output.json
 - <ws>/stages/output_final.json
 - <ws>/stages/output.json
in that order.
"""
from __future__ import annotations

import csv
import io
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .storage import (
    check_dirty_before_export as storage_check_dirty_before_export,
    load_json_if_exists,
    stage_path,
)

# try optional deps
try:
    import openpyxl  # type: ignore
    from openpyxl import Workbook  # type: ignore
    _HAVE_OPENPYXL = True
except Exception:
    _HAVE_OPENPYXL = False


def _now_ts() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def check_dirty_before_export(ws: str) -> Dict[str, Any]:
    """
    Wrapper that returns same dict as storage.check_dirty_before_export.
    """
    return storage_check_dirty_before_export(ws)


def _find_final_output(ws: str) -> Optional[Dict[str, Any]]:
    """
    Return parsed final output dict or None if not found.
    """
    ws_path = Path(ws)
    candidates = [
        ws_path / "model" / "output.json",
        ws_path / "stages" / "output_final.json",
        ws_path / "stages" / "output.json",
    ]
    for c in candidates:
        if c.exists():
            try:
                with open(c, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                continue
    return None


def _ensure_exports_dir(ws: str) -> Path:
    ws_path = Path(ws)
    base_dir = ws_path.parent  # BASE_DATA_DIR
    export_dir = base_dir / "static" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir


def _write_json_export(export_dir: Path, doc_id: str, data: Dict[str, Any]) -> Path:
    ts = _now_ts()
    fname = f"{doc_id}.export.{ts}.json"
    outp = export_dir / fname
    with open(outp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return outp


def _problem_fragments_to_rows(data: Dict[str, Any]) -> List[List[str]]:
    """
    Convert data["problem_fragments"] to CSV rows.
    Header columns:
      scene_index, sentence_index, text, labels (pipe-separated), severity_local, recommendations (pipe), evidence_json
    """
    rows: List[List[str]] = []
    frags = data.get("problem_fragments", []) or []
    for pf in frags:
        scene_index = str(pf.get("scene_index", ""))
        sentence_index = str(pf.get("sentence_index", ""))
        text = pf.get("text", "") or ""
        labels = pf.get("labels", []) or []
        labels_s = "|".join(labels)
        severity_local = pf.get("severity_local", "") or ""
        recs = pf.get("recommendations", []) or []
        recs_s = "|".join(recs)
        evidence = pf.get("evidence_spans", {}) or {}
        # store evidence as compact JSON string
        try:
            evidence_s = json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            evidence_s = str(evidence)
        rows.append([scene_index, sentence_index, text, labels_s, severity_local, recs_s, evidence_s])
    return rows


def _write_csv_export(export_dir: Path, doc_id: str, data: Dict[str, Any]) -> Path:
    ts = _now_ts()
    fname = f"{doc_id}.export.{ts}.csv"
    outp = export_dir / fname
    rows = _problem_fragments_to_rows(data)
    header = ["scene_index", "sentence_index", "text", "labels", "severity_local", "recommendations", "evidence"]
    with open(outp, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for r in rows:
            # ensure text fields are strings
            safe_row = [str(x) if x is not None else "" for x in r]
            writer.writerow(safe_row)
    return outp


def _write_xlsx_export(export_dir: Path, doc_id: str, data: Dict[str, Any]) -> Optional[Path]:
    """
    Try to write XLSX using openpyxl. If openpyxl is not available, return None.
    """
    if not _HAVE_OPENPYXL:
        return None
    ts = _now_ts()
    fname = f"{doc_id}.export.{ts}.xlsx"
    outp = export_dir / fname
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "ProblemFragments"
    header = ["scene_index", "sentence_index", "text", "labels", "severity_local", "recommendations", "evidence"]
    ws1.append(header)
    rows = _problem_fragments_to_rows(data)
    for r in rows:
        # Openpyxl handles unicode fine
        ws1.append(r)
    # Optionally add a sheet with summary metadata
    meta = data.get("document", "")
    ws_meta = wb.create_sheet("Summary")
    ws_meta.append(["document", meta])
    try:
        wb.save(str(outp))
        return outp
    except Exception:
        return None


def perform_export(ws: str, fmt: str = "json") -> str:
    """
    Export final output in requested format.
    Returns public URL path like "/static/exports/<filename>".

    Raises FileNotFoundError if final output is missing, ValueError for unsupported format.
    """
    ws_path = Path(ws)
    if not ws_path.exists():
        raise FileNotFoundError(f"Workspace not found: {ws}")

    # Prevent exporting when dirty (conservative)
    dirty_info = storage_check_dirty_before_export(ws)
    if dirty_info.get("needs_recalc"):
        raise RuntimeError("There are unsynchronized changes. Recalculate before exporting.")

    data = _find_final_output(ws)
    if data is None:
        raise FileNotFoundError("Final output JSON not found in workspace (model/output.json or stages/output_final.json)")

    export_dir = _ensure_exports_dir(ws)
    doc_id = ws_path.name

    fmt_l = (fmt or "json").lower().strip()
    if fmt_l == "json":
        p = _write_json_export(export_dir, doc_id, data)
        return f"/static/exports/{p.name}"
    elif fmt_l == "csv":
        p = _write_csv_export(export_dir, doc_id, data)
        return f"/static/exports/{p.name}"
    elif fmt_l == "xlsx":
        p = _write_xlsx_export(export_dir, doc_id, data)
        if p:
            return f"/static/exports/{p.name}"
        # fallback to zip if xlsx not available
        # continue to zip branch below
    if fmt_l == "zip" or fmt_l == "xlsx":
        # create zip containing JSON + CSV (and XLSX if requested AND available)
        ts = _now_ts()
        fname = f"{doc_id}.export.{ts}.zip"
        outp = export_dir / fname
        csv_p = _write_csv_export(export_dir, doc_id, data)
        json_p = _write_json_export(export_dir, doc_id, data)
        xlsx_p = None
        if fmt_l == "xlsx":
            xlsx_p = _write_xlsx_export(export_dir, doc_id, data)
        # Build zip (use in-memory names)
        with zipfile.ZipFile(outp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(str(json_p), arcname=json_p.name)
            zf.write(str(csv_p), arcname=csv_p.name)
            if xlsx_p and xlsx_p.exists():
                zf.write(str(xlsx_p), arcname=xlsx_p.name)
        return f"/static/exports/{outp.name}"
    else:
        raise ValueError(f"Unsupported export format: {fmt}")


# Module can be used programmatically; example:
#   from backend.exporter import perform_export
#   url = perform_export("/path/to/data/<doc_id>", fmt="zip")