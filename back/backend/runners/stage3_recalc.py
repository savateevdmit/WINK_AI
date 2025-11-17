#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stage3_recalc.py — adapter for the UPDATED model/stage3_only.py (which now only exposes a CLI main).

Purpose:
- Recalculate Stage 3 (final rating) using the new stage3_only.py script exactly as the pipeline does.
- We no longer import a Python function (run_stage3); instead we invoke stage3_only.py via a subprocess.
- Keeps previous backend contract: perform_stage3_recalc(ws, use_llm=..., ...) returns the final JSON dict
  and writes canonical files:
      <ws>/model/output.json
      <ws>/stages/output_final.json

Logic:
1. Read existing <ws>/model/output.json (the Stage 1+2 result with problem_fragments).
2. Run stage3_only.py with the correct arguments, producing a temp final file.
3. Load the result, copy it into model/output.json and stages/output_final.json.
4. Return the loaded final JSON.

Parameters:
- use_llm (bool): if False => adds --no-llm
- repo_id, filename, model_path, n_ctx, n_gpu_layers, llm_effort, retries, debug.
  (Passed through to stage3_only.py; omitted if not needed.)

Law file resolution:
- Primary: backend/model/law.json
- If not found: tries <project_root>/model/law.json
- If still not found: raises FileNotFoundError

Safety:
- All subprocess errors raise RuntimeError for the calling endpoint to map to HTTP errors.
"""

from __future__ import annotations
import json
import os
import sys
import subprocess
import time
from pathlib import Path
from typing import Optional, Dict, Any


def _resolve_law_file() -> Path:
    """
    Attempt to find law.json in backend/model/law.json first, then fallback to project_root/model/law.json.
    """
    # This file location: backend/runners/stage3_recalc.py -> parent.parent = backend/
    backend_dir = Path(__file__).resolve().parent.parent
    primary = backend_dir / "model" / "law.json"
    if primary.is_file():
        return primary
    # Fallback: project root (one level up from backend?)
    root_alt = backend_dir.parent / "model" / "law.json"
    if root_alt.is_file():
        return root_alt
    raise FileNotFoundError(f"law.json not found (tried: {primary}, {root_alt})")


def _resolve_stage3_script() -> Path:
    """
    Locate the updated stage3_only.py script inside backend/model/.
    """
    backend_dir = Path(__file__).resolve().parent.parent
    candidate = backend_dir / "model" / "stage3_only.py"
    if candidate.is_file():
        return candidate
    # Fallback attempt
    alt = backend_dir.parent / "model" / "stage3_only.py"
    if alt.is_file():
        return alt
    raise FileNotFoundError(f"stage3_only.py not found at {candidate} or {alt}")


def perform_stage3_recalc(
    ws: str,
    *,
    use_llm: bool = True,
    repo_id: str = "unsloth/gpt-oss-20b-GGUF",
    filename: str = "gpt-oss-20b-F16.gguf",
    model_path: Optional[str] = None,
    n_ctx: int = 12000,
    n_gpu_layers: int = -1,
    llm_effort: str = "high",
    retries: int = 3,
    debug: bool = False
) -> Dict[str, Any]:
    """
    Run updated stage3_only.py on workspace `ws`.

    Returns final JSON dict.
    Writes:
      <ws>/model/output.json
      <ws>/stages/output_final.json
    """
    ws_path = Path(ws)
    input_file = ws_path / "model" / "output.json"
    if not input_file.is_file():
        raise FileNotFoundError(f"Stage3 input file not found: {input_file}")

    law_file = _resolve_law_file()
    stage3_script = _resolve_stage3_script()

    model_dir = ws_path / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    stages_dir = ws_path / "stages"
    stages_dir.mkdir(parents=True, exist_ok=True)

    # We will write to a temp output first (to avoid partial file overwriting), then promote.
    temp_output = model_dir / "output_stage3_tmp.json"
    final_output = model_dir / "output.json"
    stages_final = stages_dir / "output_final.json"

    debug_dir = model_dir / "debug" / "stage3" if debug else None
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(stage3_script),
        "--input", str(input_file),
        "--law-file", str(law_file),
        "--output", str(temp_output),
        "--llm-effort", llm_effort,
        "--retries", str(retries),
    ]

    if not use_llm:
        cmd.append("--no-llm")
    else:
        # Provide repo/filename or model_path if using LLM
        if model_path:
            cmd += ["--model-path", model_path]
        else:
            cmd += ["--repo-id", repo_id, "--filename", filename]
        cmd += ["--n-ctx", str(n_ctx), "--n-gpu-layers", str(n_gpu_layers)]

    if debug_dir:
        cmd += ["--debug-dir", str(debug_dir)]

    start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(stage3_script.parent),
            timeout=1800  # 30 min safeguard
        )
    except subprocess.TimeoutExpired as te:
        raise RuntimeError(f"Stage3 subprocess timeout: {te}") from te
    except Exception as e:
        raise RuntimeError(f"Stage3 subprocess failed to start: {e}") from e

    if proc.returncode != 0:
        raise RuntimeError(
            "Stage3 subprocess exited with non-zero code.\n"
            f"CMD: {' '.join(cmd)}\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}"
        )

    if not temp_output.is_file():
        raise RuntimeError(f"Stage3 output file not created: {temp_output}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")

    # Load result
    try:
        with open(temp_output, "r", encoding="utf-8") as f:
            final_data = json.load(f)
    except Exception as e:
        raise RuntimeError(f"Failed to read Stage3 output JSON: {e}")

    # Promote temp output to canonical model/output.json & stages/output_final.json
    try:
        # Overwrite model/output.json
        with open(final_output, "w", encoding="utf-8") as f:
            json.dump(final_data, f, ensure_ascii=False, indent=2)
        # Copy to stages/output_final.json
        with open(stages_final, "w", encoding="utf-8") as f:
            json.dump(final_data, f, ensure_ascii=False, indent=2)
        # Remove temp
        temp_output.unlink(missing_ok=True)
    except Exception as e:
        raise RuntimeError(f"Failed to promote Stage3 output: {e}")

    final_data.setdefault("stage3_runtime_seconds", round(time.time() - start, 2))
    return final_data