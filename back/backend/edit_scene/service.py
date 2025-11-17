#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Single-scene recalc & merge (adds change-flag support + lazy import of analyzer to avoid import-time failures).

Change:
- Do NOT import analyzer_single (and thus llama_cpp) at module import time.
- Import analyzer_single.analyze_single_scene lazily inside recalc_and_merge_single_scene().
- If llama_cpp (or other deps) are missing, raise a clear RuntimeError to be handled by the endpoint.

Also:
- Before persisting merged output.json, create/touch <ws>/temp.txt to invalidate analyzer cache.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..storage import load_json_if_exists, save_result_json, load_parsed_scenes
from ..edit.service import THEMATIC_GROUPS, SEV_RANK, SEV_REV  # reuse constants


def _load_or_init_output(ws: str) -> Dict[str, Any]:
    p = Path(ws)
    model_out = p / "model" / "output.json"
    stages_out = p / "stages" / "output_final.json"
    data = load_json_if_exists(str(model_out)) or load_json_if_exists(str(stages_out))
    if not isinstance(data, dict):
        data = {
            "document": "output.json",
            "final_rating": "0+",
            "scenes_total": 0,
            "parents_guide": {},
            "problem_fragments": [],
            "processing_seconds": 0.0
        }
    data.setdefault("problem_fragments", [])
    data.setdefault("parents_guide", {})
    data.setdefault("scenes_total", 0)
    return data

def _touch_change_flag(ws: str) -> None:
    Path(ws, "temp.txt").touch()

def _recompute_parents_guide(problem_fragments: List[Dict[str, Any]], scenes_total: int) -> Dict[str, Any]:
    guide: Dict[str, Any] = {}
    for group, glabels in THEMATIC_GROUPS.items():
        matched = [pf for pf in problem_fragments if any(l in glabels for l in (pf.get("labels") or []))]
        if not matched:
            guide[group] = {"severity": "None", "episodes": 0, "scenes_with_issues_percent": 0.0, "examples": []}
            continue
        scenes_set = {pf.get("scene_index") for pf in matched if isinstance(pf.get("scene_index"), int)}
        max_group_rank = 0
        examples = []
        for pf in matched[:5]:
            loc_sev = pf.get("fragment_severity") or pf.get("severity_local") or "None"
            r = SEV_RANK.get(str(loc_sev).lower(), 0)
            max_group_rank = max(max_group_rank, r)
            examples.append({
                "scene_index": pf.get("scene_index"),
                "page": pf.get("page"),
                "text": pf.get("text",""),
                "labels": [l for l in (pf.get("labels") or []) if l in glabels],
                "severity_local": SEV_REV.get(r, "None")
            })
        guide[group] = {
            "severity": SEV_REV.get(max_group_rank, "None"),
            "episodes": len(matched),
            "scenes_with_issues_percent": round(len(scenes_set)/max(scenes_total or 1,1)*100.0, 1),
            "examples": examples
        }
    return guide

def recalc_and_merge_single_scene(
    ws: str,
    scene_index: int,
    scene_payload: Dict[str, Any],
    *,
    repo_id: str = "unsloth/gpt-oss-20b-GGUF",
    filename: str = "gpt-oss-20b-F16.gguf",
    model_path: Optional[str] = None,
    n_ctx: int = 6000,
    n_gpu_layers: int = -1,
    llm_effort_s1: str = "low",
    llm_effort_s2: str = "low",
    retries: int = 3,
    debug: bool = False
) -> Dict[str, Any]:
    # Lazy import to avoid llama_cpp import at app startup
    try:
        from .analyzer_single import analyze_single_scene  # type: ignore
    except Exception as e:
        raise RuntimeError(f"Analyzer import failed. Ensure llama_cpp and its dependencies are installed. Original error: {e}")

    single_report = analyze_single_scene(
        {
            "heading": scene_payload.get("heading", ""),
            "page": scene_payload.get("page"),
            "sentences": scene_payload.get("sentences", []),
        },
        document_name=f"scene_{scene_index}",
        repo_id=repo_id,
        filename=filename,
        model_path=model_path,
        n_ctx=n_ctx,
        n_gpu_layers=n_gpu_layers,
        llm_effort_s1=llm_effort_s1,
        llm_effort_s2=llm_effort_s2,
        retries=retries,
        debug_dir=(str(Path(ws) / "model" / "debug" / "single_scene") if debug else None)
    )

    data = _load_or_init_output(ws)
    pfr: List[Dict[str, Any]] = list(data.get("problem_fragments") or [])
    # Remove old fragments for this scene
    pfr = [pf for pf in pfr if int(pf.get("scene_index", -1)) != int(scene_index)]

    # Remap and append new fragments
    heading = scene_payload.get("heading")
    page = scene_payload.get("page")
    for pf in single_report.get("problem_fragments", []):
        new_pf = dict(pf)
        new_pf["scene_index"] = scene_index
        if heading is not None:
            new_pf["scene_heading"] = heading
        if page is not None:
            new_pf["page"] = page
        if "fragment_severity" not in new_pf:
            new_pf["fragment_severity"] = new_pf.get("severity_local", "None")
        pfr.append(new_pf)

    data["problem_fragments"] = pfr
    parsed = load_parsed_scenes(ws)
    scenes_total = len(parsed) if isinstance(parsed, list) else int(data.get("scenes_total", 0))
    data["scenes_total"] = scenes_total
    data["parents_guide"] = _recompute_parents_guide(pfr, scenes_total)

    # Invalidate analyzer cache due to user-triggered edit
    _touch_change_flag(ws)
    return save_result_json(ws, "output_final.json", data)