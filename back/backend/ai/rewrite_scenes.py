#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rewrite_scenes.py — переписывает отмеченные предложения под требуемый возрастной рейтинг.

(Integrated version for backend usage in /api/ai/replace/{doc_id})

Key notes:
- Robust JSON parsing of LLM output (prefers presence of "rewrites").
- Autoclose incomplete JSON structures.
- Sanitizes inner quotes inside textual fields.
- Accepts input format:
    {
      "all_scenes": [
        {
          "replace_sentences_id": [0, 2],
          "age_rating": "12+",
          "sentences": [
            {"id": 0, "text": "..."},
            {"id": 1, "text": "..."},
            {"id": 2, "text": "..."}
          ]
        },
        ...
      ]
    }
- Only sentences whose id is listed in replace_sentences_id are rewritten.
- Public function rewrite_scenes_for_age(data, law, ...) mutates and returns data.

If llama_cpp is not installed, raise RuntimeError (caller will decide fallback).
"""

from __future__ import annotations
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

# llama_cpp (LLM backend)
try:
    from llama_cpp import Llama
    _HAS_LLAMA = True
except Exception:
    _HAS_LLAMA = False

# demjson3 (permissive fallback)
try:
    import demjson3 as demjson
    _HAS_DEMJSON = True
except Exception:
    _HAS_DEMJSON = False


# ----------------------------- Debug helper -----------------------------
def _maybe_dump(debug_dir: Optional[str], filename: str, content: Any) -> None:
    if not debug_dir:
        return
    try:
        os.makedirs(debug_dir, exist_ok=True)
        path = os.path.join(debug_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            if isinstance(content, (dict, list)):
                json.dump(content, f, ensure_ascii=False, indent=2)
            else:
                f.write(str(content))
    except Exception:
        pass


# ----------------------------- Robust JSON Parser -----------------------------
_WRAPPER_RE = re.compile(r"<\|[^|]{0,120}\|>", re.I)

def _strip_wrappers(s: str) -> str:
    return _WRAPPER_RE.sub("", s or "")

def _clean_json_text(candidate: str) -> str:
    s = candidate or ""
    s = _WRAPPER_RE.sub("", s)
    s = re.sub(r"//.*?$", "", s, flags=re.M)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"\[\s*\.\.\.\s*\]", "[]", s)
    s = re.sub(r"([:\[\{,]\s*)\.\.\.(?=\s*[,}\]\)])", r"\1null", s)
    s = s.replace("...", "null")
    s = re.sub(r"(\d(?:\.\d+)?)\.+(?=\D)", r"\1", s)
    s = re.sub(r"\bNaN\b|\bInfinity\b|\binf\b|\b-?Infinity\b", "null", s, flags=re.I)
    s = re.sub(r"}\s*{", "}, {", s)
    s = re.sub(r"]\s*{", "], {", s)
    s = re.sub(r"}\s*\[", "}, [", s)
    s = re.sub(r",\s*([}\]])", r"\1", s)
    def _single_to_double(m):
        inner = m.group(1).replace('"', '\\"')
        return f'"{inner}"'
    s = re.sub(r"(?<![\"\\])'([^'\\]*(?:\\.[^'\\]*)*)'(?![\"\\])", _single_to_double, s)
    s = re.sub(r'(?<=[\{\s,])([A-Za-z0-9_@\-]+)\s*:(?=\s)', r'"\1":', s)
    s = re.sub(r'"\s*null\s*"', "null", s)
    s = s.replace("\x00","").replace("\x0b","")
    return s.strip()

def _sanitize_inner_quotes_in_field(json_like: str, field_key: str) -> str:
    s = json_like
    key_pat = f'"{field_key}"'
    i = 0
    out: List[str] = []
    n = len(s)
    while i < n:
        idx = s.find(key_pat, i)
        if idx == -1:
            out.append(s[i:])
            break
        out.append(s[i:idx])
        j = idx + len(key_pat)
        out.append(s[idx:j])
        while j < n and s[j].isspace(): out.append(s[j]); j += 1
        if j < n and s[j] == ':': out.append(':'); j += 1
        while j < n and s[j].isspace(): out.append(s[j]); j += 1
        if j >= n or s[j] != '"':
            i = j
            continue
        out.append('"'); j += 1
        esc = False
        while j < n:
            ch = s[j]
            if esc:
                out.append(ch); esc = False; j += 1; continue
            if ch == '\\':
                out.append(ch); esc = True; j += 1; continue
            if ch == '"':
                k = j + 1
                while k < n and s[k].isspace(): k += 1
                if k < n and s[k] in [',','}',']']:
                    out.append('"'); j += 1; break
                else:
                    out.append('\\'); out.append('"'); j += 1; continue
            out.append(ch); j += 1
        i = j
    return "".join(out)

def _sanitize_problem_fields(text: str) -> str:
    for field in ("new_text","rationale","reason","explanation"):
        text = _sanitize_inner_quotes_in_field(text, field)
    return text

def _balanced_json_slice_from(text: str, start_idx: int) -> Optional[str]:
    n = len(text); i = start_idx
    while i < n and text[i] not in "{[}]":
        i += 1
    if i >= n or text[i] not in "{[":
        return None
    stack: List[str] = []
    in_str = False
    esc = False
    for j in range(i, n):
        ch = text[j]
        if in_str:
            if esc: esc = False
            elif ch == '\\': esc = True
            elif ch == '"': in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            stack.append('}')
        elif ch == '[':
            stack.append(']')
        elif ch in '}]':
            if not stack or stack[-1] != ch:
                return text[i:j+1]
            stack.pop()
            if not stack:
                return text[i:j+1]
    return text[i:] if i < n else None

def _find_all_balanced_json_regions(text: str) -> List[str]:
    regions: List[str] = []
    n = len(text); idx = 0
    while idx < n:
        m = re.search(r"[\{\[]", text[idx:])
        if not m: break
        i = idx + m.start()
        cand = _balanced_json_slice_from(text, i)
        if cand:
            regions.append(cand)
            idx = i + len(cand)
        else:
            idx = i + 1
    return regions

def _autoclose_json(candidate: str) -> str:
    s = candidate or ""
    stack: List[str] = []
    out: List[str] = []
    in_str = False
    esc = False
    for ch in s:
        out.append(ch)
        if in_str:
            if esc: esc = False
            elif ch == '\\': esc = True
            elif ch == '"': in_str = False
            continue
        else:
            if ch == '"':
                in_str = True
            elif ch == '{':
                stack.append('}')
            elif ch == '[':
                stack.append(']')
            elif ch in '}]':
                if stack and stack[-1] == ch:
                    stack.pop()
    while stack:
        out.append(stack.pop())
    return "".join(out)

def _coalesce_repeated_key_arrays_to_single_object(text: str, key: str, debug_dir: Optional[str] = None) -> Optional[str]:
    bodies: List[str] = []
    for m in re.finditer(rf'"{re.escape(key)}"\s*:\s*\[', text):
        lb = m.end() - 1
        depth = 0; in_str = False; esc = False
        for j in range(lb, len(text)):
            ch = text[j]
            if in_str:
                if esc: esc = False
                elif ch == '\\': esc = True
                elif ch == '"': in_str = False
                continue
            if ch == '"': in_str = True
            elif ch == '[': depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0:
                    bodies.append(text[lb+1:j])
                    break
    if len(bodies) <= 1:
        return None
    merged = ",".join(bodies)
    coalesced = f'{{"{key}":[{merged}]}}'
    _maybe_dump(debug_dir, f"coalesced_{key}.json", coalesced)
    return coalesced

def _try_parse_json(s: str) -> Optional[Dict]:
    try:
        return json.loads(s)
    except Exception:
        pass
    if _HAS_DEMJSON:
        try:
            return demjson.decode(s)
        except Exception:
            pass
    return None

def _score_candidate(obj: Any) -> int:
    if isinstance(obj, dict) and "rewrites" in obj:
        return 100
    if isinstance(obj, dict):
        txt = json.dumps(obj, ensure_ascii=False)
        score = 0
        if '"changes"' in txt: score += 10
        if '"scene_index"' in txt and '"new_text"' in txt: score += 10
        return score
    if isinstance(obj, list):
        return 50
    return -1

def parse_llm_response_to_rewrites(raw: str, debug_dir: Optional[str] = None) -> Dict:
    _maybe_dump(debug_dir, "raw_response.txt", raw)
    stripped = _strip_wrappers(raw or "")
    _maybe_dump(debug_dir, "stripped.txt", stripped)

    candidates: List[str] = []
    m_final = re.search(r"<\|channel\|\>\s*final\s*<\|message\|\>", raw or "", re.I)
    if m_final:
        cand = _balanced_json_slice_from(raw, m_final.end())
        if cand:
            candidates.append(cand)
    candidates.extend(_find_all_balanced_json_regions(stripped))
    if not candidates:
        first_brace = stripped.find("{")
        if first_brace != -1:
            candidates.append(stripped[first_brace:])

    parsed_best: Tuple[int, Any, str] = (-1, None, "")
    for idx, c in enumerate(candidates):
        if not c or ("{" not in c and "[" not in c):
            continue
        cleaned = _clean_json_text(c)
        cleaned = _sanitize_problem_fields(cleaned)
        closed = _autoclose_json(cleaned)
        obj = _try_parse_json(closed)
        if obj is None:
            co = _coalesce_repeated_key_arrays_to_single_object(closed, "rewrites", debug_dir)
            if co:
                co2 = _sanitize_problem_fields(_clean_json_text(co))
                obj = _try_parse_json(_autoclose_json(co2))
        if obj is None:
            first = closed.find("{"); last = closed.rfind("}")
            if first != -1 and last != -1 and last > first:
                sliced = _autoclose_json(_sanitize_problem_fields(closed[first:last+1]))
                obj = _try_parse_json(sliced)
                if obj is not None:
                    closed = sliced
        if obj is not None:
            score = _score_candidate(obj)
            if score > parsed_best[0]:
                parsed_best = (score, obj, closed)
            _maybe_dump(debug_dir, f"candidate_ok_{idx}.json", closed)
        else:
            _maybe_dump(debug_dir, f"candidate_fail_{idx}.txt", closed)

    if parsed_best[1] is None:
        raise ValueError("Could not parse any JSON with rewrites from LLM output.")
    best_obj = parsed_best[1]

    if isinstance(best_obj, list):
        normalized: Dict[int, List[Dict[str, Any]]] = {}
        for ch in best_obj:
            if not isinstance(ch, dict): continue
            sc = ch.get("scene_index"); sid = ch.get("id"); nt = ch.get("new_text")
            if isinstance(sc, int) and isinstance(sid, int) and isinstance(nt, str):
                normalized.setdefault(sc, []).append({"id": sid, "new_text": nt})
        return {"rewrites": [{"scene_index": sc, "changes": chs} for sc, chs in normalized.items()]}

    if isinstance(best_obj, dict) and "rewrites" in best_obj and isinstance(best_obj["rewrites"], list):
        normalized: Dict[int, List[Dict[str, Any]]] = {}
        for item in best_obj["rewrites"]:
            if not isinstance(item, dict): continue
            sc = item.get("scene_index")
            if "changes" in item and isinstance(item["changes"], list):
                for ch in item["changes"]:
                    if not isinstance(ch, dict): continue
                    sid = ch.get("id"); nt = ch.get("new_text")
                    if isinstance(sc, int) and isinstance(sid, int) and isinstance(nt, str):
                        normalized.setdefault(sc, []).append({"id": sid, "new_text": nt})
            else:
                sid = item.get("id"); nt = item.get("new_text")
                if isinstance(sc, int) and isinstance(sid, int) and isinstance(nt, str):
                    normalized.setdefault(sc, []).append({"id": sid, "new_text": nt})
        return {"rewrites": [{"scene_index": sc, "changes": chs} for sc, chs in normalized.items()]}

    if isinstance(best_obj, dict) and "changes" in best_obj and isinstance(best_obj["changes"], list):
        normalized: Dict[int, List[Dict[str, Any]]] = {}
        for ch in best_obj["changes"]:
            if not isinstance(ch, dict): continue
            sc = ch.get("scene_index"); sid = ch.get("id"); nt = ch.get("new_text")
            if isinstance(sc, int) and isinstance(sid, int) and isinstance(nt, str):
                normalized.setdefault(sc, []).append({"id": sid, "new_text": nt})
        return {"rewrites": [{"scene_index": sc, "changes": chs} for sc, chs in normalized.items()]}

    return {"rewrites": []}


# ----------------------------- Prompt Construction -----------------------------
ALLOWED_AGE_RATINGS = ["0+","6+","12+","16+","18+"]

def _effort_to_sampling(effort: str) -> Tuple[float, float]:
    e = (effort or "medium").lower()
    if e == "low":
        return 0.02, 0.2
    if e == "high":
        return 0.15, 0.9
    return 0.06, 0.5

def _scene_to_compact_payload(scene: Dict[str, Any], scene_index: int) -> Dict[str, Any]:
    replace_ids = list(scene.get("replace_sentences_id") or [])
    sentences = scene.get("sentences") or []
    age = scene.get("age_rating") or "0+"
    return {
        "scene_index": scene_index,
        "age_rating": age if age in ALLOWED_AGE_RATINGS else "0+",
        "replace_ids": replace_ids,
        "sentences": [
            {"id": int(s.get("id")), "text": str(s.get("text",""))}
            for s in sentences if isinstance(s, dict) and "id" in s
        ]
    }

def _build_batch_payload(all_scenes: List[Dict[str, Any]], start: int, batch_size: int) -> List[Dict[str, Any]]:
    payload: List[Dict[str, Any]] = []
    end = min(len(all_scenes), start + batch_size)
    for idx in range(start, end):
        payload.append(_scene_to_compact_payload(all_scenes[idx], idx))
    return payload

def _build_rewrite_prompt(law_obj: Dict[str, Any], batch_payload: List[Dict[str, Any]]) -> str:
    instruction = (
        "You are a professional Russian screenwriter and content editor.\n"
        "Task: Rewrite ONLY the sentences with IDs listed in each scene's replace_ids so that the scene fits the REQUIRED age rating, "
        "while preserving meaning, tone, and continuity. DO NOT change any other sentences.\n"
        "Return ONLY JSON in this exact format:\n"
        "{ \"rewrites\": [ {\"scene_index\": int, \"changes\": [{\"id\": int, \"new_text\": string}] } ] }\n"
        "Rules:\n"
        "- Keep speaker cues (e.g., МАША:) intact if inside the sentence.\n"
        "- Minimal edits: do not add new events or remove essential details.\n"
        "- Use double quotes for JSON strings.\n"
        "- Escape internal quotes.\n"
        "Измененные предложения должны максимально органично сочетаться по отдельности и с всей сценой.\n"
    )
    payload = {
        "law_categories": law_obj,
        "scenes_batch": batch_payload
    }
    return instruction + "\nInput:" + json.dumps(payload, ensure_ascii=False)


# ----------------------------- Apply Logic -----------------------------
def _apply_rewrites_to_data(data: Dict[str, Any], rewrites_obj: Dict[str, Any]) -> None:
    if not isinstance(rewrites_obj, dict):
        return
    rw_list = rewrites_obj.get("rewrites")
    if not isinstance(rw_list, list):
        return

    all_scenes = data.get("all_scenes") or []
    for item in rw_list:
        if not isinstance(item, dict):
            continue
        sc_idx = item.get("scene_index")
        changes = item.get("changes")
        if not isinstance(sc_idx, int) or not isinstance(changes, list):
            continue
        if sc_idx < 0 or sc_idx >= len(all_scenes):
            continue
        scene = all_scenes[sc_idx]
        replace_ids = set(scene.get("replace_sentences_id") or [])
        sentences = scene.get("sentences") or []
        for ch in changes:
            if not isinstance(ch, dict): continue
            s_id = ch.get("id"); new_text = ch.get("new_text")
            if s_id in replace_ids and isinstance(new_text, str):
                for s in sentences:
                    if isinstance(s, dict) and s.get("id") == s_id:
                        s["text"] = new_text
                        break
        scene["sentences"] = sentences
        all_scenes[sc_idx] = scene
    data["all_scenes"] = all_scenes


# ----------------------------- Public API -----------------------------
def rewrite_scenes_for_age(
    data: Dict[str, Any],
    law: Union[str, Dict[str, Any]],
    llm_repo_id: str = "unsloth/gpt-oss-20b-GGUF",
    llm_filename: str = "gpt-oss-20b-F16.gguf",
    model_path: Optional[str] = None,
    n_ctx: int = 8192,
    n_gpu_layers: int = -1,
    effort: str = "medium",
    batch_size: int = 2,
    temperature: Optional[float] = None,
    top_p: float = 0.2,
    repeat_penalty: float = 1.05,
    seed: int = 2025,
    max_tokens: int = 4096,
    retries: int = 3,
    debug_dir: Optional[str] = None,
) -> Dict[str, Any]:
    if "all_scenes" not in data or not isinstance(data["all_scenes"], list):
        raise TypeError("Input 'data' must contain key 'all_scenes' with a list value.")

    if isinstance(law, str):
        with open(law, "r", encoding="utf-8") as f:
            law_obj = json.load(f)
    elif isinstance(law, dict):
        law_obj = law
    else:
        raise TypeError("'law' must be a path to JSON or a dict")

    all_scenes: List[Dict[str, Any]] = data["all_scenes"]

    if not _HAS_LLAMA:
        raise RuntimeError("llama_cpp not installed")

    try:
        if model_path:
            llm = Llama(model_path=model_path, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers, verbose=False)
        else:
            if hasattr(Llama, "from_pretrained"):
                llm = Llama.from_pretrained(repo_id=llm_repo_id, filename=llm_filename, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers, verbose=False)
            else:
                llm = Llama(model_path=llm_filename, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers, verbose=False)
    except Exception as e:
        raise RuntimeError(f"Failed to initialize LLM: {e}")

    if temperature is None:
        temp, default_top_p = _effort_to_sampling(effort)
        temperature = temp
        if top_p is None:
            top_p = default_top_p

    for i in range(0, len(all_scenes), batch_size):
        batch_payload = _build_batch_payload(all_scenes, i, batch_size)
        prompt = _build_rewrite_prompt(law_obj, batch_payload)
        raw = ""
        for attempt in range(max(1, retries)):
            try:
                resp = llm.create_completion(
                    prompt=prompt,
                    temperature=float(temperature),
                    max_tokens=int(max_tokens),
                    top_p=float(top_p),
                    repeat_penalty=float(repeat_penalty),
                    seed=int(seed),
                    stop=None
                )
                raw = resp["choices"][0].get("text", "")
                break
            except Exception as ee:
                if attempt + 1 == retries:
                    raise
                time.sleep(0.5)
        _maybe_dump(debug_dir, f"batch_{i}_raw.txt", raw)
        try:
            parsed = parse_llm_response_to_rewrites(raw, debug_dir=debug_dir)
            _maybe_dump(debug_dir, f"batch_{i}_parsed.json", parsed)
        except Exception as pe:
            _maybe_dump(debug_dir, f"batch_{i}_parse_error.txt", str(pe))
            continue
        _apply_rewrites_to_data(data, parsed)

    _maybe_dump(debug_dir, "final_output.json", data)
    return data


# ----------------------------- CLI -----------------------------
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Rewrite marked sentences to satisfy age rating.")
    ap.add_argument("--input", required=True, help="Path to input JSON with all_scenes")
    ap.add_argument("--law", required=True, help="Path to law.json or inline JSON")
    ap.add_argument("--output", required=True, help="Where to save modified JSON")
    ap.add_argument("--model-path", default=None)
    ap.add_argument("--repo-id", default="unsloth/gpt-oss-20b-GGUF")
    ap.add_argument("--filename", default="gpt-oss-20b-F16.gguf")
    ap.add_argument("--n-ctx", type=int, default=8192)
    ap.add_argument("--n-gpu-layers", type=int, default=-1)
    ap.add_argument("--effort", choices=["low","medium","high"], default="medium")
    ap.add_argument("--batch-size", type=int, default=2)
    ap.add_argument("--temperature", type=float, default=None)
    ap.add_argument("--top-p", type=float, default=0.2)
    ap.add_argument("--repeat-penalty", type=float, default=1.05)
    ap.add_argument("--seed", type=int, default=2025)
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--debug-dir", default=None)
    args = ap.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data_in = json.load(f)
    law_param = args.law
    if os.path.exists(law_param):
        law_input = law_param
    else:
        try:
            law_input = json.loads(law_param)
        except Exception:
            print("ERROR: --law must be path or JSON string", file=sys.stderr)
            sys.exit(1)

    out = rewrite_scenes_for_age(
        data=data_in,
        law=law_input,
        llm_repo_id=args.repo_id,
        llm_filename=args.filename,
        model_path=args.model_path,
        n_ctx=args.n_ctx,
        n_gpu_layers=args.n_gpu_layers,
        effort=args.effort,
        batch_size=args.batch_size,
        temperature=args.temperature,
        top_p=args.top_p,
        repeat_penalty=args.repeat_penalty,
        seed=args.seed,
        max_tokens=args.max_tokens,
        retries=args.retries,
        debug_dir=args.debug_dir
    )

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Saved: {args.output}")