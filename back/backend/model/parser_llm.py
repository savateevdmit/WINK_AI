#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import json, re, os
from typing import Any, Dict, List, Optional, Tuple

try:
    import demjson3 as demjson
    _HAS_DEMJSON = True
except Exception:
    _HAS_DEMJSON = False


def _maybe_dump(ddir: Optional[str], fname: str, content: Any):
    if not ddir: return
    try:
        os.makedirs(ddir, exist_ok=True)
        with open(os.path.join(ddir, fname), "w", encoding="utf-8") as f:
            if isinstance(content,(dict,list)):
                json.dump(content,f,ensure_ascii=False,indent=2)
            else:
                f.write(str(content))
    except Exception:
        pass

_WRAPPER_RE = re.compile(r"<\|[^|]{0,200}\|>", re.I)
_TYPE_RE = re.compile(r':\s*(int|integer|string|str|float|number|boolean|bool)\b', re.I)

def _strip_wrappers(s: str)->str:
    return _WRAPPER_RE.sub("", s or "")

def _base_clean(s: str)->str:
    s=_strip_wrappers(s)
    s=re.sub(r"//.*?$","",s,flags=re.M)
    s=re.sub(r"/\*.*?\*/","",s,flags=re.S)
    s=s.replace("\x00","").replace("\x0b","")
    return s

def _replace_type_placeholders(s: str)->str:
    return _TYPE_RE.sub(": null", s)

def _fix_comma_issues(s: str)->str:
    s=re.sub(r'}\s*{', '},{', s)
    s=re.sub(r']\s*{', '],{', s)
    s=re.sub(r'(?<=\bnull)\s*{', ',{', s)
    s=re.sub(r'}\s*(?=null\b)', '},', s)
    s=re.sub(r',\s*,', ',', s)
    return s

def _remove_strays(s: str)->str:
    s=re.sub(r'\{"\}', '}', s)
    s=re.sub(r'"explanation"\s*:\s*string\b', '"explanation": ""', s, flags=re.I)
    s=re.sub(r'(":)\s*string\b', r'\1 ""', s)
    return s

def _sanitize_field_quotes(src: str, field: str)->str:
    # Stream-sanitize inner quotes in "field":"..."
    pat=re.compile(rf'"{field}"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"')
    out=[]; i=0; n=len(src)
    while i<n:
        m=pat.search(src,i)
        if not m:
            out.append(src[i:]); break
        out.append(src[i:m.start()])
        value=m.group(1)
        repaired=[]; prev=''
        for ch in value:
            if ch=='"' and prev!='\\':
                repaired.append('\\\"')
            else:
                repaired.append(ch)
            prev=ch
        out.append(f'"{field}":"{"".join(repaired)}"')
        i=m.end()
    return ''.join(out)

def _sanitize_text_fields(s: str)->str:
    for f in ("rsn","adv","explanation","new_text"):
        s=_sanitize_field_quotes(s,f)
    return s

def _autoclose(s: str)->str:
    stack=[]; out=[]; in_str=False; esc=False
    for ch in s:
        out.append(ch)
        if in_str:
            if esc: esc=False
            elif ch=='\\': esc=True
            elif ch=='"': in_str=False
            continue
        if ch=='"': in_str=True
        elif ch=='{': stack.append('}')
        elif ch=='[': stack.append(']')
        elif ch in '}]':
            if stack and stack[-1]==ch: stack.pop()
    while stack:
        out.append(stack.pop())
    return ''.join(out)

def _balanced_slice(text: str, start: int)->Optional[str]:
    n=len(text); i=start
    while i<n and text[i] not in '{[': i+=1
    if i>=n: return None
    stack=[]; in_str=False; esc=False
    for j in range(i,n):
        ch=text[j]
        if in_str:
            if esc: esc=False
            elif ch=='\\': esc=True
            elif ch=='"': in_str=False
            continue
        if ch=='"': in_str=True
        elif ch=='{': stack.append('}')
        elif ch=='[': stack.append(']')
        elif ch in '}]':
            if stack and stack[-1]==ch:
                stack.pop()
                if not stack: return text[i:j+1]
            else:
                return text[i:j+1]
    return text[i:] if stack else None

def _find_regions(s: str)->List[str]:
    out=[]; idx=0; n=len(s)
    while idx<n:
        m=re.search(r'[{[]', s[idx:])
        if not m: break
        i=idx+m.start()
        cand=_balanced_slice(s,i)
        if cand:
            out.append(cand); idx=i+len(cand)
        else:
            idx=i+1
    return out

def _coalesce_key_arrays(s: str, key: str)->Optional[str]:
    bodies=[]
    for m in re.finditer(rf'"{re.escape(key)}"\s*:\s*\[', s):
        lb=m.end()-1
        depth=0; in_str=False; esc=False
        for j in range(lb,len(s)):
            ch=s[j]
            if in_str:
                if esc: esc=False
                elif ch=='\\': esc=True
                elif ch=='"': in_str=False
                continue
            if ch=='"': in_str=True
            elif ch=='[': depth+=1
            elif ch==']':
                depth-=1
                if depth==0:
                    bodies.append(s[lb+1:j])
                    break
    if len(bodies)<=1: return None
    merged=",".join(bodies)
    return f'{{"{key}":[{merged}]}}'

def _try_parsers(s: str)->Optional[Dict]:
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

def _score(obj: Any, prefer: Optional[str])->int:
    if not isinstance(obj, dict): return -1
    score=0
    if "final_rating" in obj: score+=300
    if "ans" in obj: score+=120
    if "scene_results" in obj: score+=110
    if "non_neutral" in obj or "scene_indices" in obj or "nn" in obj: score+=105
    text=json.dumps(obj,ensure_ascii=False)
    if '"vlc"' in text or '"det"' in text: score+=10
    if prefer and prefer in obj: score+=1000
    return score

def _normalize(obj: Any)->Dict:
    if isinstance(obj, list):
        if all(isinstance(x,int) for x in obj):
            return {"non_neutral": list(dict.fromkeys(obj))}
        if obj and all(isinstance(x,dict) and "scID" in x for x in obj):
            return {"scene_results": obj}
        return {"ans": obj}
    if isinstance(obj, dict):
        if "nn" in obj and "non_neutral" not in obj:
            obj["non_neutral"]=obj.get("nn")
        if "scene_indices" in obj and "non_neutral" not in obj:
            obj["non_neutral"]=obj.get("scene_indices")
        if "explanation" in obj and obj["explanation"] in ("string","STRING","0+|6+|12+|16+|18+"):
            obj["explanation"]=""
        if obj.get("final_rating")=="0+|6+|12+|16+|18+":
            obj.pop("final_rating",None)
        if "scene_results" in obj and isinstance(obj["scene_results"], list):
            for sr in obj["scene_results"]:
                if isinstance(sr, dict) and isinstance(sr.get("snt"), list):
                    sr["snt"]=[x for x in sr["snt"] if isinstance(x, dict)]
        if "non_neutral" in obj and isinstance(obj["non_neutral"], list):
            ints=[]
            for x in obj["non_neutral"]:
                if isinstance(x,int): ints.append(x)
                elif isinstance(x,float) and x.is_integer(): ints.append(int(x))
                elif isinstance(x,str) and x.strip().isdigit(): ints.append(int(x.strip()))
            obj["non_neutral"]=list(dict.fromkeys(ints))
    return obj

def _normalize_stage2_stray_segments(s: str)->str:
    s=re.sub(r',\s*"scID"\s*:', ',{"scID":', s)
    s=re.sub(r'^\s*"scID"\s*:', '{"scID":', s)
    return s

# SAFE key quoting: only when OUTSIDE strings and at object key positions
def _quote_unquoted_object_keys_safe(s: str) -> str:
    out: List[str] = []
    n = len(s)
    i = 0
    in_str = False
    esc = False
    last_non_ws = ''  # track last non-whitespace char to detect positions after '{' or ','
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_@-")
    while i < n:
        ch = s[i]

        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
            continue

        # outside string
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue

        # If we're at a potential key boundary (after '{' or ',' or start), try to detect bare key
        if (last_non_ws in ('{', ',', '') or (last_non_ws == '' and not out)):

            # preserve any whitespaces
            if ch.isspace():
                out.append(ch)
                i += 1
                continue

            # Snapshot from current i to see if we have keyToken ':' pattern
            j = i
            # read key token
            while j < n and s[j] in allowed:
                j += 1
            # skip spaces between token and colon
            k = j
            while k < n and s[k].isspace():
                k += 1
            # If we have a non-empty token and immediate colon, and token is not already quoted
            if j > i and k < n and s[k] == ':':
                # Quote the key token
                out.append('"')
                out.append(s[i:j])
                out.append('"')
                # keep original spaces before colon
                out.append(s[j:k])
                out.append(':')
                i = k + 1
                last_non_ws = ':'
                continue
            # else fall through to normal append

        # Normal append
        out.append(ch)
        if not ch.isspace():
            last_non_ws = ch
        i += 1

    return ''.join(out)

_STAGE2_ENTRY_RE = re.compile(r'"scID"\s*:\s*(\d+)\s*,\s*"id"\s*:\s*(\d+)\s*,\s*"det"\s*:\s*\[(.*?)\]', re.S)

def _fallback_extract_stage2_ans(s: str)->Optional[Dict]:
    t=_replace_type_placeholders(_fix_comma_issues(_remove_strays(_sanitize_text_fields(_base_clean(s)))))
    items=[]
    for m in _STAGE2_ENTRY_RE.finditer(t):
        scid=m.group(1); sid=m.group(2); det_body=m.group(3)
        det_body=_sanitize_text_fields(det_body)
        open_count=det_body.count('['); close_count=det_body.count(']')
        det_fixed=det_body + (']' * max(0, open_count-close_count))
        items.append(f'{{"scID":{scid},"id":{sid},"det":[{det_fixed}]}}')
    if not items: return None
    ans_text='{"ans":[' + ",".join(items) + "]}"
    ans_text=_autoclose(_fix_comma_issues(_remove_strays(_sanitize_text_fields(ans_text))))
    parsed=_try_parsers(ans_text)
    if isinstance(parsed, dict) and "ans" in parsed: return parsed
    return None

_INT_ARRAY_RE = re.compile(r'\[\s*(?:\d+\s*(?:,\s*\d+\s*)*)\]')

def _fallback_extract_stage0_non_neutral(s: str)->Optional[Dict]:
    m=_INT_ARRAY_RE.search(s)
    if not m: return None
    try:
        arr=json.loads(m.group(0))
        if isinstance(arr,list) and all(isinstance(x,int) for x in arr):
            return {"non_neutral": list(dict.fromkeys(arr))}
    except Exception:
        pass
    return None

def parse_llm_response(raw: str, encoding=None, effort: str="low", debug_dir: Optional[str]=None, prefer: Optional[str]=None) -> Dict:
    _maybe_dump(debug_dir,"raw.txt", raw)
    stripped=_base_clean(raw)
    candidates=[]
    m_final=re.search(r"<\|channel\|\>\s*final\s*<\|message\|\>", raw or "", re.I)
    if m_final:
        frag=_balanced_slice(raw,m_final.end())
        if frag: candidates.append(frag)
    candidates.extend(_find_regions(stripped))
    if not candidates and "{" in stripped:
        candidates.append(stripped[stripped.find("{"):])

    parsed_list: List[Tuple[int, Dict, str]]=[]
    for idx,cand in enumerate(candidates):
        fragment=_base_clean(cand)
        repaired=fragment
        obj=None
        for _round in range(6):
            repaired=_replace_type_placeholders(repaired)
            repaired=_normalize_stage2_stray_segments(repaired)
            repaired=_fix_comma_issues(repaired)
            repaired=_remove_strays(repaired)
            repaired=_quote_unquoted_object_keys_safe(repaired)  # SAFE key quoting outside strings
            repaired=_sanitize_text_fields(repaired)
            repaired=_autoclose(repaired)
            for k in ("scene_results","ans"):
                if repaired.count(f'"{k}"')>1:
                    coal=_coalesce_key_arrays(repaired,k)
                    if coal: repaired=coal
            obj=_try_parsers(repaired)
            if obj is not None:
                obj=_normalize(obj)
                parsed_list.append((_score(obj, prefer), obj, repaired))
                _maybe_dump(debug_dir,f"candidate_ok_{idx}.json", obj)
                break
        if obj is None:
            _maybe_dump(debug_dir,f"candidate_fail_{idx}.txt", repaired)

    if not parsed_list:
        fb2=_fallback_extract_stage2_ans(stripped)
        if fb2:
            fb2=_normalize(fb2)
            _maybe_dump(debug_dir, "fallback_stage2_ans.json", fb2)
            return fb2
        fb0=_fallback_extract_stage0_non_neutral(stripped)
        if fb0:
            _maybe_dump(debug_dir, "fallback_stage0_non_neutral.json", fb0)
            return fb0
        raise ValueError("Could not parse any JSON from LLM output.")

    parsed_list.sort(key=lambda x: x[0], reverse=True)
    if prefer:
        for _,obj,_txt in parsed_list:
            if prefer in obj:
                _maybe_dump(debug_dir,"chosen.json", obj)
                return obj
    best=parsed_list[0][1]
    _maybe_dump(debug_dir,"chosen.json", best)
    return best