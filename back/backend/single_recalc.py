#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utilities to perform single-scene recalculation and full-scenario recalculation
by invoking the existing pipeline (backend/model/pipeline.py) on a reduced input.

Behavior:
- recalc_single_scene(ws, scene_index, payload):
    * Loads parsed_scenes.json from workspace `ws`.
    * Extracts the single scene at `scene_index` and writes it to inputs/<scenario_name>.json
      (scenario_name is taken from payload.scenario_name if present, otherwise "recalc_<scene_index>").
    * Runs the pipeline subprocess (defaults to backend/model/pipeline.py) with batch-size=1
      and effort params taken from payload if provided (effort_s1/2/3).
    * Waits for the process to complete and returns the resulting output dict (parsed JSON).
    * On error raises RuntimeError with stderr/stdout included.

- recalc_full_scenario(ws, scenes):
    * Writes `scenes` (list) to a temporary inputs file and runs the pipeline over the whole list,
      returning the final pipeline output JSON.

Notes:
- These functions are synchronous (blocking). They are intended to be invoked from FastAPI
  endpoint functions that are synchronous (as in backend/main.py).
- The pipeline path and law.json default to backend/model/pipeline.py and backend/model/law.json.
- The functions keep compatibility with workspace layout created by create_doc_workspace:
    <ws>/inputs/, <ws>/model/, <ws>/stages/
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Optional typing for payload from FastAPI route
try:
    from .models import SceneRecalcRequest  # type: ignore
except Exception:
    SceneRecalcRequest = None  # type: ignore


def _find_pipeline_and_law():
    """
    Resolve default pipeline and law.json paths relative to this file (backend/).
    Returns (pipeline_path: Path, law_path: Path)
    """
    module_dir = Path(__file__).resolve().parent  # backend/
    # if this file sits in backend/ then module_dir is backend; if in subpackage adjust accordingly
    backend_dir = module_dir
    # pipeline default
    pipeline = backend_dir / "model" / "pipeline.py"
    law = backend_dir / "model" / "law.json"
    return pipeline.resolve(), law.resolve()


def _write_scenes_input(ws: str, scenario_name: str, scenes: List[Dict[str, Any]]) -> str:
    """
    Write a scenes list to ws/inputs/<scenario_name>.json, returns the absolute path.
    Overwrites any existing file with same name.
    """
    ws_path = Path(ws)
    inputs_dir = ws_path / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{scenario_name}.json"
    dest = inputs_dir / filename
    # Ensure scene indices are consistent (0..n-1)
    for i, sc in enumerate(scenes):
        sc["scene_index"] = i
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(scenes, f, ensure_ascii=False, indent=2)
    return str(dest)


def _run_pipeline_cmd(
    input_path: str,
    output_path: str,
    debug_dir: str,
    pipeline_path: str,
    law_path: str,
    effort_s1: str = "low",
    effort_s2: str = "medium",
    effort_s3: str = "high",
    python_bin: Optional[str] = None,
    model_path: Optional[str] = None,
    repo_id: Optional[str] = None,
    filename: Optional[str] = None,
    n_gpu_layers: int = -1,
    timeout: int = 600,
) -> None:
    """
    Run the pipeline subprocess synchronously. Raises RuntimeError on non-zero exit.
    stdout/stderr captured and included in exception message.
    """
    py = python_bin or sys.executable
    cmd = [
        py,
        str(pipeline_path),
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--law-file",
        str(law_path),
        "--batch-size",
        "1",
        "--llm-effort-s1",
        effort_s1,
        "--llm-effort-s2",
        effort_s2,
        "--llm-effort-s3",
        effort_s3,
        "--debug-dir",
        str(debug_dir),
        "--n-gpu-layers",
        str(n_gpu_layers),
    ]
    if model_path:
        cmd += ["--model-path", model_path]
    else:
        if repo_id:
            cmd += ["--repo-id", repo_id]
        if filename:
            cmd += ["--filename", filename]

    env = os.environ.copy()
    # Keep locale/encoding predictable
    env.setdefault("PYTHONUNBUFFERED", "1")

    try:
        completed = subprocess.run(
            cmd,
            cwd=str(Path(pipeline_path).resolve().parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as te:
        raise RuntimeError(f"Pipeline timed out after {timeout}s; cmd={' '.join(cmd)}; stdout={te.stdout}; stderr={te.stderr}") from te

    if completed.returncode != 0:
        raise RuntimeError(
            f"Pipeline exited with code {completed.returncode}\n"
            f"cmd: {' '.join(cmd)}\n\n"
            f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}"
        )


def recalc_single_scene(
    ws: str,
    scene_index: int,
    payload: Any,
    *,
    pipeline_path_override: Optional[str] = None,
    law_file_override: Optional[str] = None,
    python_bin: Optional[str] = None,
    model_path: Optional[str] = None,
    repo_id: Optional[str] = None,
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Recalculate a single scene by invoking the pipeline on that single scene.
    - ws: workspace path (string)
    - scene_index: index of scene to recalc
    - payload: typically SceneRecalcRequest (may contain scenario_name, efforts, timeout)
    Returns the pipeline output JSON as dict.

    Raises HTTPException or RuntimeError on errors (caller should map to HTTP).
    """
    # Load parsed scenes
    ws_path = Path(ws)
    parsed_path = ws_path / "parsed_scenes.json"
    if not parsed_path.exists():
        raise RuntimeError(f"parsed_scenes.json not found in workspace: {parsed_path}")

    with open(parsed_path, "r", encoding="utf-8") as f:
        scenes = json.load(f)
    if not isinstance(scenes, list):
        raise RuntimeError("parsed_scenes.json must contain a list of scenes")
    if scene_index < 0 or scene_index >= len(scenes):
        raise RuntimeError(f"scene_index out of range: {scene_index}")

    scene = scenes[scene_index]

    # Determine scenario_name (where to write input copy). Prefer payload.scenario_name or payload.name
    scenario_name = None
    try:
        # payload may be Pydantic model or dict
        if hasattr(payload, "scenario_name") and payload.scenario_name:
            scenario_name = str(payload.scenario_name)
        elif isinstance(payload, dict) and payload.get("scenario_name"):
            scenario_name = str(payload.get("scenario_name"))
    except Exception:
        scenario_name = None
    if not scenario_name:
        scenario_name = f"recalc_{scene_index}"

    # Build minimal scenes list containing only this scene (reset indices)
    single_scene_list = [scene.copy()]
    # Reset scene_index in the single-file to 0 for pipeline expectations
    single_scene_list[0]["scene_index"] = 0

    # Write input file
    input_file = _write_scenes_input(ws, scenario_name, single_scene_list)

    # Prepare output path
    stages_dir = ws_path / "stages"
    stages_dir.mkdir(parents=True, exist_ok=True)
    output_file = stages_dir / f"output_recalc_{scene_index}.json"

    # Determine pipeline and law paths
    default_pipeline, default_law = _find_pipeline_and_law()
    pipeline_path = Path(pipeline_path_override) if pipeline_path_override else default_pipeline
    law_path = Path(law_file_override) if law_file_override else default_law

    if not pipeline_path.is_file():
        raise RuntimeError(f"Pipeline script not found at: {pipeline_path}")
    if not law_path.is_file():
        raise RuntimeError(f"Law file not found at: {law_path}")

    # Determine effort params from payload if present, otherwise defaults
    effort_s1 = "low"
    effort_s2 = "medium"
    effort_s3 = "high"
    timeout = 600
    try:
        if hasattr(payload, "effort_s1") and payload.effort_s1:
            effort_s1 = str(payload.effort_s1)
        if hasattr(payload, "effort_s2") and payload.effort_s2:
            effort_s2 = str(payload.effort_s2)
        if hasattr(payload, "effort_s3") and payload.effort_s3:
            effort_s3 = str(payload.effort_s3)
        if hasattr(payload, "timeout") and getattr(payload, "timeout") is not None:
            timeout = int(getattr(payload, "timeout"))
    except Exception:
        # ignore and use defaults
        pass

    debug_dir = ws_path / "model" / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    # Run pipeline
    _run_pipeline_cmd(
        input_path=input_file,
        output_path=str(output_file),
        debug_dir=str(debug_dir),
        pipeline_path=str(pipeline_path),
        law_path=str(law_path),
        effort_s1=effort_s1,
        effort_s2=effort_s2,
        effort_s3=effort_s3,
        python_bin=python_bin,
        model_path=model_path,
        repo_id=repo_id,
        filename=filename,
        timeout=timeout,
    )

    # Read and persist output: copy to model/output.json and stages/output_recalc_{i}.json
    try:
        with open(output_file, "r", encoding="utf-8") as f:
            out = json.load(f)
    except Exception as e:
        raise RuntimeError(f"Failed to read pipeline output: {e}")

    # Persist canonical model output as well
    model_dir = ws_path / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    with open(model_dir / "output.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # Also write a final stages file copy
    final_stage_path = stages_dir / "output_final.json"
    with open(final_stage_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    return out


def recalc_full_scenario(ws: str, scenes: List[Dict[str, Any]], *, pipeline_path_override: Optional[str] = None, law_file_override: Optional[str] = None, python_bin: Optional[str] = None, model_path: Optional[str] = None, repo_id: Optional[str] = None, filename: Optional[str] = None, timeout: int = 1800) -> Dict[str, Any]:
    """
    Recalculate the full scenario using the provided scenes list (overwrites parsed_scenes.json input for this run).
    Writes inputs/<recalc_full.json> and calls pipeline over the provided list.
    Returns the pipeline final output JSON as dict.
    """
    ws_path = Path(ws)
    # Write scenes into inputs/recalc_full.json
    input_file = _write_scenes_input(ws, "recalc_full", scenes)

    stages_dir = ws_path / "stages"
    stages_dir.mkdir(parents=True, exist_ok=True)
    output_file = stages_dir / "output_recalc_full.json"

    default_pipeline, default_law = _find_pipeline_and_law()
    pipeline_path = Path(pipeline_path_override) if pipeline_path_override else default_pipeline
    law_path = Path(law_file_override) if law_file_override else default_law

    if not pipeline_path.is_file():
        raise RuntimeError(f"Pipeline script not found at: {pipeline_path}")
    if not law_path.is_file():
        raise RuntimeError(f"Law file not found at: {law_path}")

    # Use defaults for efforts (could be extended to accept params)
    effort_s1 = "low"
    effort_s2 = "medium"
    effort_s3 = "high"

    debug_dir = ws_path / "model" / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    _run_pipeline_cmd(
        input_path=input_file,
        output_path=str(output_file),
        debug_dir=str(debug_dir),
        pipeline_path=str(pipeline_path),
        law_path=str(law_path),
        effort_s1=effort_s1,
        effort_s2=effort_s2,
        effort_s3=effort_s3,
        python_bin=python_bin,
        model_path=model_path,
        repo_id=repo_id,
        filename=filename,
        timeout=timeout,
    )

    try:
        with open(output_file, "r", encoding="utf-8") as f:
            out = json.load(f)
    except Exception as e:
        raise RuntimeError(f"Failed to read pipeline output: {e}")

    # Persist canonical output
    model_dir = ws_path / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    with open(model_dir / "output.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    with open(stages_dir / "output_final.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    return out