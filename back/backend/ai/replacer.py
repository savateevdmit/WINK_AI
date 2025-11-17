#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Scene Sentence Replacer (Point 6 revised)

New requirements:
- Do NOT persist incoming JSON to workspace.
- Directly invoke model rewrite logic (rewrite_scenes.py).
- Input may contain nested arrays: "all_scenes": [ [ {...} ], {...} ] — must flatten.
- Return format:

{
  "results": [
    {
      "heading": "<scene heading or ''>",
      "replacements": [
        { "sentence_id": <int>, "new_sentence": "<string>" },
        ...
      ]
    }
  ],
  "mode": "llm" | "noop",
  "elapsed_seconds": <float>
}

Behavior:
1. Accept payload with "all_scenes".
2. Prepare data for model (only fields it cares about).
3. Call rewrite_scenes_for_age (LLM) if available; else fallback "noop".
4. Diff original vs rewritten for ids in replace_sentences_id.
5. Produce the required results list.

Errors:
- If input malformed: raise ValueError (caller maps to HTTP).
- If model initialization fails: fallback to noop (mode='noop') unless you want hard failure.

You can later extend with caching or streaming rewriting.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from pathlib import Path

# Import model rewrite logic
from ..model.rewrite_scenes import rewrite_scenes_for_age, _HAS_LLAMA

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _flatten_all_scenes(raw: Any) -> List[Dict[str, Any]]:
    """
    Accepts raw "all_scenes" which may be:
      - list of dicts
      - list of lists of dicts
      - mixture
    Returns a flat list of dict scenes.
    """
    out: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, list):
            for sub in item:
                if isinstance(sub, dict):
                    out.append(sub)
    return out

def _ensure_scene_fields(scene: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize minimal keys for a single scene:
    - heading (optional)
    - replace_sentences_id: list[int]
    - age_rating
    - sentences: list[{id:int,text:str}]
    """
    sc = dict(scene)
    sc.setdefault("heading", "")
    ids = sc.get("replace_sentences_id") or sc.get("replace_ids") or []
    if not isinstance(ids, list):
        ids = []
    # filter only ints
    ids_norm = []
    for v in ids:
        try:
            ids_norm.append(int(v))
        except Exception:
            continue
    sc["replace_sentences_id"] = ids_norm

    age = sc.get("age_rating") or ""
    sc["age_rating"] = str(age)

    sents = sc.get("sentences") or []
    if not isinstance(sents, list):
        sents = []
    norm_sents = []
    for s in sents:
        if isinstance(s, dict) and "id" in s and "text" in s:
            try:
                sid = int(s["id"])
                txt = str(s["text"])
                norm_sents.append({"id": sid, "text": txt})
            except Exception:
                continue
    sc["sentences"] = norm_sents
    return sc

def _build_model_input(flat_scenes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Model expects {"all_scenes":[{...}, ...]} with keys:
        replace_sentences_id, age_rating, sentences
    Heading is preserved so we can return it in results.
    """
    return {
        "all_scenes": [
            {
                "replace_sentences_id": sc["replace_sentences_id"],
                "age_rating": sc["age_rating"],
                "sentences": sc["sentences"]
            }
            for sc in flat_scenes
        ]
    }

def _diff_replacements(original_flat: List[Dict[str, Any]], rewritten_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Produce results list with headings and replacements:
    [
      {
        "heading": <heading>,
        "replacements": [
          {"sentence_id": id, "new_sentence": new_text}, ...
        ]
      }
    ]
    Only include sentences whose id is in replace_sentences_id.
    If a sentence text unchanged -> still returned (spec expects list for each requested id).
    """
    results: List[Dict[str, Any]] = []
    rewritten_scenes = rewritten_data.get("all_scenes") or []
    for idx, orig_scene in enumerate(original_flat):
        heading = orig_scene.get("heading", "") or ""
        replace_ids = set(orig_scene.get("replace_sentences_id") or [])
        orig_sent_map = {s["id"]: s["text"] for s in orig_scene.get("sentences") or []}
        new_sent_map = {}
        if idx < len(rewritten_scenes):
            rw_scene = rewritten_scenes[idx]
            for s in (rw_scene.get("sentences") or []):
                if isinstance(s, dict) and "id" in s and "text" in s:
                    new_sent_map[int(s["id"])] = s["text"]

        replacements = []
        for sid in sorted(replace_ids):
            new_text = new_sent_map.get(sid, orig_sent_map.get(sid, ""))
            replacements.append({"sentence_id": sid, "new_sentence": new_text})

        results.append({"heading": heading, "replacements": replacements})
    return results

# ---------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------

def process_ai_replace(
    ws: str,
    payload: Dict[str, Any],
    *,
    law_path: Optional[str] = None,
    model_path: Optional[str] = None,
    repo_id: str = "unsloth/gpt-oss-20b-GGUF",
    filename: str = "gpt-oss-20b-F16.gguf",
    effort: str = "medium",
    batch_size: int = 2,
    n_ctx: int = 8192,
    n_gpu_layers: int = -1,
    temperature: Optional[float] = None,
    top_p: float = 0.2,
    repeat_penalty: float = 1.05,
    seed: int = 2025,
    max_tokens: int = 4096,
    retries: int = 3,
    debug: bool = False
) -> Dict[str, Any]:
    """
    Adapted for new point 6.
    ws is used only to locate law.json if not provided; not for persistence.
    Returns dict matching required output format.
    """
    t0 = time.time()
    raw_scenes = payload.get("all_scenes")
    flat = _flatten_all_scenes(raw_scenes)
    if not flat:
        raise ValueError("Payload must contain non-empty 'all_scenes' list.")

    normalized = [_ensure_scene_fields(sc) for sc in flat]
    model_input = _build_model_input(normalized)

    # Law path resolution
    if not law_path:
        backend_root = Path(__file__).resolve().parents[1]  # backend/
        law_path = str(backend_root / "model" / "law.json")
    if not Path(law_path).is_file():
        raise FileNotFoundError(f"law.json not found at: {law_path}")

    debug_dir = None
    if debug:
        debug_dir = str(Path(ws) / "model" / "debug" / "rewrite_ai")
        Path(debug_dir).mkdir(parents=True, exist_ok=True)

    # Attempt LLM rewrite
    mode = "llm"
    rewritten = None
    try:
        if not _HAS_LLAMA:
            raise RuntimeError("LLM backend not available (llama_cpp missing).")
        rewritten = rewrite_scenes_for_age(
            data=model_input,
            law=law_path,
            llm_repo_id=repo_id,
            llm_filename=filename,
            model_path=model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            effort=effort,
            batch_size=batch_size,
            temperature=temperature,
            top_p=top_p,
            repeat_penalty=repeat_penalty,
            seed=seed,
            max_tokens=max_tokens,
            retries=retries,
            debug_dir=debug_dir
        )
    except Exception:
        # Fallback: no changes — just echo original texts
        mode = "noop"
        rewritten = model_input

    results = _diff_replacements(normalized, rewritten)
    return {
        "results": results,
        "mode": mode,
        "elapsed_seconds": round(time.time() - t0, 3)
    }