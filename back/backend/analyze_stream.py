#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_stream.py

Light-weight SSE streaming helper that runs the pipeline on an existing workspace
(or on a single-workspace input) and yields event dictionaries suitable for the
existing StreamingResponse wrapper in main.py.

Purpose:
- Provide run_analysis_stream(ws, scenes, ...) async generator that yields plain
  Python dict events (not SSE-formatted strings). This keeps compatibility with
  the previously-commented endpoint in main.py which wrapped events into
  `data: json\n\n`.
- Also expose a convenience endpoint /api/analyze/stream/{doc_id} for older UI
  which uses the same approach (it uses the generator above).

Behavior:
- Writes scenes to inputs/{scenario_name}.json inside workspace `ws`.
- Launches the configured pipeline script (default backend/model/pipeline.py).
- Uses the shared tailer implementation from stream_stage_runner to parse stderr
  and watch model output; converts those SSE strings into dicts and yields them.
- Updates workspace meta status via storage.set_doc_status.
- Includes robust path handling, threaded subprocess fallback (reuses helper from stream_stage_runner)
  and useful error reporting.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Any, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

# storage helpers
from .storage import (
    load_parsed_scenes,
    set_doc_status,
)

# reuse tailing & fallback implementations from stream_stage_runner
from .runners.stream_stage_runner import (
    _tail_process_and_stream,
    _ThreadedProcessAdapter,
)

router = APIRouter(prefix="/api/analyze", tags=["analyze"])


async def run_analysis_stream(
    ws: str,
    scenes: List[Dict[str, Any]],
    scenario_name: str = "stream",
    python_bin: Optional[str] = None,
    pipeline_path: str = "",
    law_file: Optional[str] = None,
    model_path: Optional[str] = None,
    repo_id: Optional[str] = None,
    filename: Optional[str] = None,
    n_gpu_layers: int = -1,
    effort_s1: str = "low",
    effort_s2: str = "medium",
    effort_s3: str = "high",
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Run pipeline on given `scenes` saved into ws/inputs/{scenario_name}.json and
    yield dict events parsed from the tailer.

    Yields:
      - dict objects with keys like 'event', 'stage', 'progress', 'output', etc.
    """
    ws_path = Path(ws)
    if not ws_path.exists():
        raise RuntimeError(f"Workspace not found: {ws}")

    inputs_dir = ws_path / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    input_copy = inputs_dir / f"{scenario_name}.json"

    # write provided scenes list to inputs/<scenario_name>.json
    try:
        # normalize scene_index
        for i, s in enumerate(scenes):
            s["scene_index"] = i
        with open(input_copy, "w", encoding="utf-8") as f:
            json.dump(scenes, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise RuntimeError(f"Failed to write input copy: {e}")

    # prepare model output path
    model_dir = ws_path / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    output_path = model_dir / "output.json"

    # determine backend dir & defaults
    module_dir = Path(__file__).resolve().parent
    backend_dir = module_dir.parent if module_dir.name == "runners" else module_dir
    default_pipeline = (backend_dir / "model" / "pipeline.py").resolve()
    default_law = (backend_dir / "model" / "law.json").resolve()

    pipeline_path_final = Path(pipeline_path).resolve() if pipeline_path and str(pipeline_path).strip() else default_pipeline
    law_file_final = Path(law_file).resolve() if law_file else default_law

    if not pipeline_path_final.is_file():
        raise RuntimeError(f"Pipeline not found at: {pipeline_path_final}")
    if not law_file_final.is_file():
        raise RuntimeError(f"Law file not found at: {law_file_final}")

    # build command
    py = python_bin or sys.executable
    cmd = [
        py,
        str(pipeline_path_final),
        "--input", str(input_copy.resolve()),
        "--output", str(output_path.resolve()),
        "--law-file", str(law_file_final),
        "--batch-size", "1",
        "--llm-effort-s1", effort_s1,
        "--llm-effort-s2", effort_s2,
        "--llm-effort-s3", effort_s3,
        "--debug-dir", str((ws_path / "model" / "debug").resolve()),
        "--n-gpu-layers", str(n_gpu_layers),
    ]
    if model_path:
        cmd += ["--model-path", model_path]
    else:
        if repo_id:
            cmd += ["--repo-id", repo_id]
        if filename:
            cmd += ["--filename", filename]

    cwd_str = str(backend_dir.resolve())
    cmd_str = " ".join(cmd)

    # start subprocess (async) with threaded fallback
    proc = None
    threaded_adapter = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd_str,
        )
    except NotImplementedError:
        # fallback (uvloop on Windows etc.)
        threaded_adapter = _ThreadedProcessAdapter(cmd, cwd=cwd_str)
        proc = threaded_adapter
    except Exception as e:
        raise RuntimeError(f"Failed to start pipeline: {repr(e)} | cmd={cmd_str} | cwd={cwd_str}")

    # delegate to shared tailer which yields SSE-formatted strings like "data: {...}\n\n"
    try:
        async for s in _tail_process_and_stream(
            proc=proc,
            output_path=str(output_path.resolve()),
            stage1_steps_total=len(scenes),
            send_output_updates_for_stage1=True,
        ):
            # skip pings/comments (": ping\n\n")
            if isinstance(s, str) and s.startswith(":"):
                # ignore comments for generator consumers
                continue
            # s looks like "data: {...}\n\n" (possibly with newlines). Extract JSON after "data: "
            try:
                if s.startswith("data:"):
                    payload_text = s[len("data:"):].strip()
                else:
                    payload_text = s.strip()
                # sometimes multiple "data: " lines could appear; handle first JSON object
                # If payload_text contains leading "{" we parse from there
                # Remove any trailing empty lines
                payload_text = payload_text.splitlines()[0] if "\n" in payload_text else payload_text
                ev = json.loads(payload_text)
            except Exception:
                # if parsing fails, yield a raw-text event for debugging
                ev = {"event": "raw", "text": s}
            yield ev
    finally:
        # Ensure process is terminated if generator is cancelled/finished
        try:
            if getattr(proc, "returncode", None) is None:
                proc.kill()
        except Exception:
            pass


# Backwards-compatible endpoint used previously in main.py (commented)
@router.get("/stream/{doc_id}")
async def analyze_stream_route(
    doc_id: str,
    scenario_name: str = Query("stream", description="Scenario name to write in inputs/"),
    base_dir: str = Query("data", description="Base data directory"),
    python_bin: Optional[str] = Query(None),
    pipeline_path: str = Query("", description="Path to pipeline.py (default: backend/model/pipeline.py)"),
    law_file: Optional[str] = Query(None),
    model_path: Optional[str] = Query(None),
    repo_id: Optional[str] = Query(None),
    filename: Optional[str] = Query(None),
    n_gpu_layers: int = Query(-1),
    effort_s1: str = Query("low", regex="^(low|medium|high)$"),
    effort_s2: str = Query("medium", regex="^(low|medium|high)$"),
    effort_s3: str = Query("high", regex="^(low|medium|high)$"),
):
    """
    Endpoint kept for backward-compatibility: streams events for doc_id by reading
    parsed_scenes.json from the workspace and running the pipeline on it.
    This endpoint wraps run_analysis_stream and returns a StreamingResponse with
    SSE-formatted data: lines.
    """
    base_dir_abs = Path(base_dir).resolve()
    ws = base_dir_abs / doc_id
    if not ws.exists() or not (ws / "parsed_scenes.json").exists():
        raise HTTPException(status_code=404, detail="Document workspace or parsed_scenes.json not found")

    scenes = load_parsed_scenes(str(ws))
    if scenes is None:
        raise HTTPException(status_code=400, detail="No parsed scenes found")

    # Update status
    try:
        set_doc_status(str(ws), "processing")
    except Exception:
        pass

    async def gen():
        try:
            async for ev in run_analysis_stream(
                ws=str(ws),
                scenes=scenes,
                scenario_name=scenario_name,
                python_bin=python_bin,
                pipeline_path=pipeline_path,
                law_file=law_file,
                model_path=model_path,
                repo_id=repo_id,
                filename=filename,
                n_gpu_layers=n_gpu_layers,
                effort_s1=effort_s1,
                effort_s2=effort_s2,
                effort_s3=effort_s3,
            ):
                # wrap dict into SSE "data: <json>\n\n"
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            # success
            try:
                set_doc_status(str(ws), "done")
            except Exception:
                pass
        except Exception as e:
            try:
                set_doc_status(str(ws), "error", str(e))
            except Exception:
                pass
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)