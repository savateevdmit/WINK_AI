from __future__ import annotations
import argparse, json, os, re, sys, time
from typing import Any, Dict, List, Optional

from tqdm import tqdm
from llama_cpp import Llama

from constants import (
    LABELS, THEMATIC_GROUPS, SEVERITY_WEIGHT, SEV_MAP_INT2STR, SEV_MAP_STR2INT,
    HARD_18_LABELS, ORDERED_RATINGS, TYPICAL_16_LABELS, TYPICAL_12_LABELS,
    FW_RULES, S1_EXCLUSIVE_PAIRS,
    CONDEMNATION_TOKENS, FAMILY_TOKENS, COMEDY_TOKENS, GRAPHIC_TOKENS, AROUSAL_TOKENS,
    _PROFANITY_ROOT_PATTERNS, _ALIAS_MAP
)
from parser_llm import parse_llm_response

# Harmony (optional)
try:
    from openai_harmony import (
        load_harmony_encoding, HarmonyEncodingName, Role,
        Message, Conversation, SystemContent, ReasoningEffort
    )
    HARMONY_AVAILABLE=True
except Exception:
    HARMONY_AVAILABLE=False
    class Dummy: ...
    load_harmony_encoding=lambda *a,**k: None
    HarmonyEncodingName=Dummy
    Role=Dummy
    Message=Dummy
    Conversation=Dummy
    SystemContent=Dummy
    ReasoningEffort=Dummy


# ---------------- Utility ----------------
def _maybe_dump(ddir: Optional[str], fname: str, content: Any):
    if not ddir: return
    try:
        os.makedirs(ddir, exist_ok=True)
        with open(os.path.join(ddir,fname),"w",encoding="utf-8") as f:
            if isinstance(content,(dict,list)):
                json.dump(content,f,ensure_ascii=False,indent=2)
            else:
                f.write(str(content))
    except Exception:
        pass

def is_obscene_by_roots(text: str)->bool:
    if not text: return False
    t=text.lower().replace("ё","е")
    return any(p.search(t) for p in _PROFANITY_ROOT_PATTERNS)

def normalize_label(raw: Any)->Optional[str]:
    if not isinstance(raw,str): return None
    s=raw.strip().lower()
    s=re.sub(r"[\s\-/]+","_",s)
    s=re.sub(r"[^a-z0-9_]+","",s)
    if s in _ALIAS_MAP: return _ALIAS_MAP[s]
    up=s.upper()
    if up in LABELS: return up
    if s.startswith("weapon") and "usage" in s: return "WEAPONS_USAGE"
    if s.startswith("weapon") and any(k in s for k in ("mention","shown","present")): return "WEAPONS_MENTION"
    return None

def _effort_to_reasoning(effort: str):
    e=(effort or "low").lower()
    if not HARMONY_AVAILABLE: return None
    return ReasoningEffort.HIGH if e=="high" else (ReasoningEffort.MEDIUM if e=="medium" else ReasoningEffort.LOW)

def _effort_temperature(effort: str)->float:
    e=(effort or "low").lower()
    return 0.15 if e=="high" else (0.08 if e=="medium" else 0.01)

# ---------------- Stage 0 (prefilter) ----------------
def _scene_preview(scene: Dict[str,Any], max_sentences: int)->Dict[str,Any]:
    sents=scene.get("sentences",[]) or []
    texts=[s.get("text","") for s in sents if isinstance(s,dict)]
    if max_sentences>0 and len(texts)>max_sentences:
        head=max_sentences//2
        tail=max_sentences - head
        texts = texts[:head] + texts[-tail:]
    return {"scene_index": scene["scene_index"], "sentences": texts, "heading": scene.get("heading","")}

def build_stage0_conversation(scenes_batch: List[Dict], encoding, llm_effort: str, max_sentences: int)->tuple[str,List[str]]:
    previews=[_scene_preview(sc, max_sentences) for sc in scenes_batch]
    instruction=(
        "You are a fast triage assistant for Russian screenplay scenes.\n"
        "Return ONLY JSON: {\"non_neutral\":[int,...]} with indices of scenes that likely contain ANY listed categories.\n"
        "Be INCLUSIVE: if uncertain, include the index. Do NOT output texts."
    )
    user_content=instruction+"\nCategories:"+", ".join(LABELS)+"\nInput:"+json.dumps(previews,ensure_ascii=False)
    if HARMONY_AVAILABLE and encoding:
        sysc=SystemContent.new().with_reasoning_effort(_effort_to_reasoning(llm_effort)).with_required_channels(["final"])
        convo=Conversation.from_messages([
            Message.from_role_and_content(Role.SYSTEM, sysc),
            Message.from_role_and_content(Role.USER, user_content)
        ])
        tokens=encoding.render_conversation_for_completion(convo, Role.ASSISTANT)
        return encoding.decode(tokens), []
    return user_content, []

# ---------------- Stage 1 prompt ----------------
def build_stage1_conversation(batch: List[Dict], encoding, llm_effort: str="low")->tuple[str,List[str]]:
    payload=[]
    for s in batch:
        sc_id=s["scene_index"]
        sents=[{"id":i,"t":sent.get("text","")} for i,sent in enumerate(s.get("sentences",[]))]
        payload.append({"scID":sc_id,"snt":sents})
    instruction=(
        "You analyze Russian screenplay sentences. Return ONLY JSON:\n"
        "{\"scene_results\":[{\"scID\":int,\"snt\":[{\"id\":int,\"vlc\":[{\"label\":string,\"conf\":int}]}]}]}\n"
        "MANDATORY: Each scene MUST have at least ONE sentence with at least ONE label. If all are neutral, assign MILD_CONFLICT to the most contextually active sentence.\n"
        "Gates:\n"
        "- VIOLENCE_GRAPHIC: explicit gore/blood/wounds/torture only.\n"
        "- MURDER_HOMICIDE: clear attempt or commission.\n"
        "- DRUGS_USE_DEPICTION: explicit HUMAN illegal/controlled drug consumption or explicit name of such drug.\n"
        "- PROFANITY_OBSCENE: only if sentence contains obscene root (-бзд-;-бля-;-(ё/е)б-;-елд-;-говн-;-жоп-;-манд-;-муд-;-перд-;-пизд-;-сра-;-(с)са-;-хуе-/-хуй-/-хуя-;-шлюх-).\n"
        "Confidence 0..100. Do NOT include original texts back. final-only."
    )
    user_content=instruction+"\nAllowed labels:"+json.dumps(LABELS,ensure_ascii=False)+"\nInput:"+json.dumps(payload,ensure_ascii=False)
    if HARMONY_AVAILABLE and encoding:
        sysc=SystemContent.new().with_reasoning_effort(_effort_to_reasoning(llm_effort)).with_required_channels(["final"])
        convo=Conversation.from_messages([
            Message.from_role_and_content(Role.SYSTEM, sysc),
            Message.from_role_and_content(Role.USER, user_content)
        ])
        tokens=encoding.render_conversation_for_completion(convo, Role.ASSISTANT)
        return encoding.decode(tokens), []
    return user_content, []

# ---------------- Stage 2 prompt ----------------
def build_stage2_conversation(q_batch: List[Dict], encoding, llm_effort: str="low")->tuple[str,List[str]]:
    instruction=(
        "You rate Russian screenplay sentences. Return ONLY JSON:\n"
        "{\"ans\":[{\"scID\":int,\"id\":int,\"det\":[{\"label\":string,\"sev\":\"Mild|Moderate|Severe\",\"scr\":int,\"rsn\":string,\"adv\":string,\"ok\":boolean,\"suggest\":string|null}]}]}\n"
        "FOR EACH input label produce a det object. Use allowed labels exactly. Profanity only if obscene roots.\n"
        "Drugs depiction only explicit illegal human use; else ok=false suggest DRUGS_MENTION_NON_DETAILED/REMOVE.\n"
        "sev from th; scr from bs (+/- brief rationale).Пиши reason и advice на русском языке\nfinal-only."
    )
    user_payload={"fw":FW_RULES,"Queries":q_batch}
    user_content=instruction+"\n"+json.dumps(user_payload,ensure_ascii=False)
    if HARMONY_AVAILABLE and encoding:
        sysc=SystemContent.new().with_reasoning_effort(_effort_to_reasoning(llm_effort)).with_required_channels(["final"])
        convo=Conversation.from_messages([
            Message.from_role_and_content(Role.SYSTEM, sysc),
            Message.from_role_and_content(Role.USER, user_content)
        ])
        tokens=encoding.render_conversation_for_completion(convo, Role.ASSISTANT)
        return encoding.decode(tokens), []
    return user_content, []

# ---------------- Stage 3 prompt (soft) ----------------
def build_stage3_conversation(law_rules_obj: Dict[str, Any],
                              violated_sentences: List[Dict[str, Any]],
                              encoding,
                              llm_effort: str="medium")->tuple[str,List[str]]:
    instruction = (
        "You are an expert on the Federal Law of the Russian Federation No. 436-FZ. Your task is to assign "
" THE LEAST acceptable age rating (0+, 6+, 12+, 16+, 18+). "
"Return ONLY JSON: {\"final_rating\":\"0+|6+|12+|16+|18+\",\"explanation\":string}.\n\n"

    "Key decision-making rules (strictly):\n"
"1) Start from 0+. Raise the rating ONLY if there is an explicit, "
"unavoidable content that complies with the prohibitions/restrictions of the law.\n"
"2) **18+** — only if there is at least ONE of: \n"
    " - explicit detailed sexual content (anatomical/medical/erotic/arousing, with details),\n"
" - sexual violence with details/coercion,\n"
" - detailed instructions on committing a serious crime or suicide/self-harm,\n"
" - extremist/terrorist propaganda or materials, definitely inciting to a crime.\n"
" If THERE are NO such criteria, do not raise it to 18+ even when mentioning the words \"kill\", \"murder\", etc.\n\n"
"3) Interpretation of important labels:\n"
    " - MURDER_HOMICIDE (mention of murder) — **not** automatically 18+. If this is a retelling/rumor without a detailed stage demonstration or without praise, consider it Moderate/12-16+. Only an explicit image, encouragement, or instruction is above.\n"
" - DANGEROUS_IMITABLE_ACTS — consider it serious ONLY if the text contains specific step-by-step actions/tools/precise parameters that are easy to repeat. General descriptions of risk/danger — do not raise to 18+; more often 12+ or 16+ according to the context.\n"
    " - WEAPONS_USAGE / VIOLENCE_NON_GRAPHIC — usually 12+; raise to 16+ if there are many episodes, there is a demonstration of damage /consequences, or there is glorification/instruction.\n"
" - DRUGS_USE_DEPICTION — only in case of explicit demonstration of use/overdose/preparation details — 16+-18+ . A simple mention or description of past events is not 18+.\n"
" - PROFANITY_OBSCENE — limit to 16+ only if there is widespread rude language and it is key to the scene; a single obscene insertion usually does not raise above 12+.\n\n"
    "4) Mitigating factors (if present, they lower the rating):\n"
" - explicit condemnation/showing of negative consequences/consequences for characters (condemnation),\n"
" - family/protective context, medical or legal context (family_context),\n"
" - comic/parodic tone without realistic instructions (comedy),\n"
" - low detail (low_detail) — lack of anatomical/technical details.\n"
" If there are mitigating factors, lower the rating by one notch if possible.\n\n"
    "5) Practical logic: Consider the difference between a 'phrase' and an 'action.'" 
"Explicit mention of past crimes/threats is not the same as step—by-step execution or instruction.\n\n"
    "6) Provide a CLEAR list of labels/ fragments in the explanation, "
" which, in your opinion, force the outcome, and what mitigating factors were applied. "
"If you upgraded to 18+, specify the specific reason for item 2.\n\n"
"Input: JSON with categories of the law and a list of infringing sentences with context. "
    "Rely on the law, but the goal is TO ASSIGN THE LOWEST ACCEPTABLE rating. Пиши explanation на русском языке\n"
    )
    payload={"law_categories":law_rules_obj,"violated_sentences":violated_sentences}
    user_content=instruction+"\nInput:"+json.dumps(payload,ensure_ascii=False)
    if HARMONY_AVAILABLE and encoding:
        sysc=SystemContent.new().with_reasoning_effort(_effort_to_reasoning(llm_effort)).with_required_channels(["final"])
        convo=Conversation.from_messages([
            Message.from_role_and_content(Role.SYSTEM, sysc),
            Message.from_role_and_content(Role.USER, user_content)
        ])
        tokens=encoding.render_conversation_for_completion(convo, Role.ASSISTANT)
        return encoding.decode(tokens), []
    return user_content, []

# ---------------- Stage 1 helpers ----------------
def _collect_stage1_labels(vlc_list: List[Any], sentence_text: str)->List[Dict[str,Any]]:
    best={}
    for v in (vlc_list or []):
        if isinstance(v,str):
            lab_raw=v; conf=None
        elif isinstance(v,dict):
            lab_raw=v.get("label") or v.get("lbl") or v.get("type")
            conf=v.get("conf", v.get("confidence", v.get("score")))
        else:
            continue
        lab=normalize_label(lab_raw)
        if not lab: continue
        if lab=="PROFANITY_OBSCENE" and not is_obscene_by_roots(sentence_text):
            continue
        c=int(conf) if isinstance(conf,(int,float)) else 0
        if lab not in best or c>best[lab]:
            best[lab]=c
    for a,b in S1_EXCLUSIVE_PAIRS:
        if a in best and b in best:
            if best[a]>=best[b]: del best[b]
            else: del best[a]
    return [{"label":lab,"conf":best[lab]} for lab in best]

def build_problem_fragments_from_compact(compact_items: List[Dict], all_scenes: List[Dict])->List[Dict]:
    frags=[]
    for scene in compact_items:
        sc_id=scene["scene_index"]
        heading=next((s.get("heading","") for s in all_scenes if s["scene_index"]==sc_id),"")
        for s_item in scene.get("sentences",[]):
            viols=s_item.get("violations",[])
            labels=[v.get("label") for v in viols if v.get("label")]
            if not labels: continue
            evidence={}
            for v in viols:
                lab=v.get("label"); conf=v.get("conf")
                if not lab: continue
                score_val=int(conf) if isinstance(conf,(int,float)) else None
                evidence[lab]={"severity":"", "score":score_val, "reason":"", "advice":None, "trigger":None}
            max_w=max((SEVERITY_WEIGHT.get(l,1) for l in labels), default=0)
            frags.append({
                "scene_index":sc_id,
                "scene_heading":heading,
                "page":None,
                "sentence_index":s_item["id"],
                "text":s_item.get("text",""),
                "labels":labels,
                "evidence_spans":evidence,
                "severity_local":SEV_MAP_INT2STR.get(max_w,"None"),
                "recommendations":[]
            })
    return frags

def _severity_from_base_score(base: int)->str:
    for name,(lo,hi) in FW_RULES["th"].items():
        if lo<=base<=hi: return name
    return "Severe" if base>=80 else ("Moderate" if base>=50 else ("Mild" if base>=25 else "None"))

def finalize_evidence_fields(problem_fragments: List[Dict])->None:
    for pf in problem_fragments:
        ev=pf.get("evidence_spans",{})
        for lab, span in ev.items():
            if not span.get("severity"):
                base=FW_RULES["bs"].get(lab,40)
                span["severity"]=_severity_from_base_score(int(base))
            if not span.get("reason"):
                span["reason"]="Авто: требуется сверка с текстом."
            if not span.get("advice"):
                span["advice"]="Смягчить при необходимости."
        pf["severity_local"]=_compute_severity_local_from_evidence(ev)

def _compute_severity_local_from_evidence(ev: Dict[str,Dict[str,Any]])->str:
    max_v=0
    for data in ev.values():
        sev=str(data.get("severity","")).lower()
        max_v=max(max_v, SEV_MAP_STR2INT.get(sev,0))
    return SEV_MAP_INT2STR.get(max_v,"None")

# ---------------- Stage 2 backfill ----------------
def ensure_stage2_backfill(q_batch: List[Dict], parsed2: Optional[Dict]) -> List[Dict]:
    """
    Returns a complete ans list covering EVERY input (scID,id) and EACH of its labels.
    - Tolerates malformed parsed2["ans"] items (skips non-dict).
    - Tolerates non-list det (treats as empty).
    """
    def _norm_label(x: Any) -> Optional[str]:
        if isinstance(x, str): return x.strip().upper().replace(" ", "_")
        if isinstance(x, dict):
            v = x.get("label")
            return v.strip().upper().replace(" ", "_") if isinstance(v, str) else None
        return None

    model_map: Dict[tuple, Dict[str, Dict[str, Any]]] = {}
    if isinstance(parsed2, dict) and isinstance(parsed2.get("ans"), list):
        for ans in parsed2["ans"]:
            if not isinstance(ans, dict):
                # Skip stray strings like "SEX_EXPLICIT" that caused AttributeError
                continue
            scid = ans.get("scID"); sid = ans.get("id"); det = ans.get("det", [])
            if not (isinstance(scid, int) and isinstance(sid, int)): continue
            if not isinstance(det, list): det = []
            labmap: Dict[str, Dict[str, Any]] = {}
            for d in det:
                if not isinstance(d, dict): continue
                lab = _norm_label(d.get("label"))
                if not lab: continue
                labmap[lab] = {
                    "label": lab,
                    "sev": d.get("sev"),
                    "scr": d.get("scr"),
                    "rsn": d.get("rsn"),
                    "adv": d.get("adv"),
                    "ok":  d.get("ok", True),
                    "suggest": d.get("suggest")
                }
            model_map[(scid, sid)] = labmap

    full_ans: List[Dict] = []
    for q in q_batch:
        scid = q.get("scID"); sid = q.get("id"); vlc = q.get("vlc", [])
        if not (isinstance(scid, int) and isinstance(sid, int)): continue
        in_labels: List[str] = []
        for v in vlc:
            lab = _norm_label(v)
            if lab: in_labels.append(lab)
        # de-dup while preserving order
        seen=set(); in_labels=[x for x in in_labels if not (x in seen or seen.add(x))]
        det_out: List[Dict[str, Any]] = []
        mlabs = model_map.get((scid, sid), {})

        for lab in in_labels:
            base = 40
            try:
                from constants import FW_RULES
                base = int(FW_RULES["bs"].get(lab, 40))
            except Exception:
                pass
            default = {
                "label": lab,
                "sev": "Severe" if base>=80 else ("Moderate" if base>=50 else ("Mild" if base>=25 else "None")),
                "scr": base,
                "rsn": "Авто: базовая оценка.",
                "adv": "Редактура: смягчить при необходимости.",
                "ok": True,
                "suggest": None
            }
            if lab in mlabs:
                md = mlabs[lab]
                for k in ("sev","scr","rsn","adv","ok","suggest"):
                    if md.get(k) is not None: default[k]=md[k]
            det_out.append(default)

        # Include model-added labels too
        for lab, md in mlabs.items():
            if lab not in in_labels:
                base = 40
                try:
                    from constants import FW_RULES
                    base = int(FW_RULES["bs"].get(lab, 40))
                except Exception:
                    pass
                det_out.append({
                    "label": lab,
                    "sev": md.get("sev", "Severe" if base>=80 else ("Moderate" if base>=50 else ("Mild" if base>=25 else "None"))),
                    "scr": md.get("scr", base),
                    "rsn": md.get("rsn", "Авто: добавлено моделью."),
                    "adv": md.get("adv", "Редактура: смягчить при необходимости."),
                    "ok": md.get("ok", True),
                    "suggest": md.get("suggest")
                })

        full_ans.append({"scID": scid, "id": sid, "det": det_out})
    return full_ans

def apply_stage2(full_ans: List[Dict], problem_fragments: List[Dict], debug_dir: Optional[str])->List[Dict]:
    det_map={(a.get("scID"), a.get("id")): a.get("det",[]) for a in full_ans}
    out=[]
    removal=[]
    for pf in problem_fragments:
        key=(pf["scene_index"], pf["sentence_index"])
        if key not in det_map:
            out.append(pf); continue
        ev=pf.get("evidence_spans",{})
        labels=list(pf.get("labels") or [])
        adv_acc=[]
        for d in det_map[key]:
            lab=normalize_label(d.get("label"))
            if not lab: continue
            if d.get("ok") is False and (d.get("suggest") in ("REMOVE","remove")):
                if lab in labels: labels=[x for x in labels if x!=lab]
                if lab in ev: ev.pop(lab,None)
                removal.append({"scene_index":pf["scene_index"],"sentence_index":pf["sentence_index"],"removed_label":lab})
                continue
            if lab not in labels:
                labels.append(lab)
                ev[lab]={"severity":"", "score":None, "reason":"", "advice":None, "trigger":None}
            if lab in ev:
                if d.get("sev"): ev[lab]["severity"]=d["sev"]
                if isinstance(d.get("scr"), (int,float)): ev[lab]["score"]=int(d["scr"])
                if isinstance(d.get("rsn"), str) and d["rsn"].strip(): ev[lab]["reason"]=d["rsn"].strip()
                if isinstance(d.get("adv"), str) and d["adv"].strip():
                    ev[lab]["advice"]=d["adv"].strip(); adv_acc.append(d["adv"].strip())
        if labels and ev:
            pf["labels"]=labels
            pf["evidence_spans"]=ev
            pf["severity_local"]=_compute_severity_local_from_evidence(ev)
            if adv_acc: pf["recommendations"]=list(dict.fromkeys(adv_acc))
            out.append(pf)
    if removal: _maybe_dump(debug_dir,"stage2_removed.json", removal)
    return out

# ---------------- Context & softeners extraction ----------------
def extract_context(sentences: List[Dict], idx: int, window: int = 2)->tuple[List[str],str,List[str]]:
    prev=[]; next_=[]
    for i in range(max(0, idx-window), idx):
        if i < len(sentences) and isinstance(sentences[i],dict):
            prev.append(sentences[i].get("text",""))
    cur = sentences[idx].get("text","") if idx < len(sentences) and isinstance(sentences[idx],dict) else ""
    for i in range(idx+1, min(len(sentences), idx+1+window)):
        if isinstance(sentences[i],dict):
            next_.append(sentences[i].get("text",""))
    return prev, cur, next_

def detect_softeners(text_block: str)->dict:
    t=text_block.lower()
    return {
        "condemnation": any(tok in t for tok in CONDEMNATION_TOKENS),
        "family_context": any(tok in t for tok in FAMILY_TOKENS),
        "comedy": any(tok in t for tok in COMEDY_TOKENS),
        "low_detail": not any(tok in t for tok in (GRAPHIC_TOKENS | AROUSAL_TOKENS))
    }

def pack_violated_sentences_with_context(problem_fragments: List[Dict], scenes: List[Dict]) -> List[Dict]:
    scene_map={sc["scene_index"]: sc for sc in scenes}
    out=[]
    for pf in problem_fragments:
        sc=scene_map.get(pf["scene_index"])
        sentences=sc.get("sentences",[]) if sc else []
        idx=pf["sentence_index"]
        prev_list, cur_text, next_list = extract_context(sentences, idx, window=2)
        full_context_text=" ".join(prev_list+[cur_text]+next_list)
        soft=detect_softeners(full_context_text)
        out.append({
            "scene_index": pf["scene_index"],
            "sentence_index": pf["sentence_index"],
            "text": pf["text"],
            "labels": pf["labels"],
            "groups": _groups_for_labels(pf["labels"]),
            "severity_local": pf.get("severity_local","None"),
            "ev": {lab:{
                "sev": pf["evidence_spans"][lab].get("severity",""),
                "scr": pf["evidence_spans"][lab].get("score")
            } for lab in pf["labels"]},
            "context_prev": prev_list,
            "context_next": next_list,
            "scene_heading": pf.get("scene_heading"),
            "softeners": soft
        })
    return out

def _groups_for_labels(labels: List[str])->List[str]:
    groups=[]
    for g,labs in THEMATIC_GROUPS.items():
        if any(l in labs for l in labels):
            groups.append(g)
    return sorted(set(groups))

# ---------------- Rating guard logic ----------------
def _minimal_needed_rating(packed_items: List[Dict]) -> str:
    all_labels=[]
    soft_any={"condemnation":False,"family_context":False,"comedy":False,"low_detail":True}
    counts={}
    for it in packed_items:
        for k,v in it.get("softeners",{}).items():
            if k in soft_any:
                soft_any[k] = soft_any[k] or v
        for l in it.get("labels",[]):
            all_labels.append(l)
            counts[l]=counts.get(l,0)+1
    label_set=set(all_labels)

    # Hard 18+
    if any(l in HARD_18_LABELS for l in label_set):
        return "18+"

    # SEX_SUGGESTIVE логика
    if "SEX_SUGGESTIVE" in label_set:
        if soft_any["family_context"] or soft_any["comedy"] or soft_any["low_detail"]:
            if counts.get("SEX_SUGGESTIVE",0) <= 1:
                return "12+"
            return "16+"

    # VIOLENCE_NON_GRAPHIC
    if "VIOLENCE_NON_GRAPHIC" in label_set:
        v_count=counts.get("VIOLENCE_NON_GRAPHIC",0)
        if v_count <= 2 and soft_any["condemnation"]:
            return "12+"
        if v_count <= 1:
            return "12+"
        if v_count >= 5 and not soft_any["condemnation"]:
            return "16+"
        return "12+"

    # WEAPONS_USAGE / CRIMINAL_ACTIVITY
    if "WEAPONS_USAGE" in label_set or "CRIMINAL_ACTIVITY" in label_set:
        if not soft_any["condemnation"]:
            wu=counts.get("WEAPONS_USAGE",0)
            ca=counts.get("CRIMINAL_ACTIVITY",0)
            if wu+ca >=3:
                return "16+"
            return "12+"
        else:
            return "12+"

    # Typical 12+
    if any(l in TYPICAL_12_LABELS for l in label_set):
        return "12+"

    if label_set:
        return "6+"
    return "0+"

def adjust_stage3_rating(model_rating: Optional[str], packed_items: List[Dict]) -> str:
    auto_min=_minimal_needed_rating(packed_items)
    if model_rating not in ORDERED_RATINGS:
        return auto_min
    mr_i=ORDERED_RATINGS.index(model_rating)
    min_i=ORDERED_RATINGS.index(auto_min)
    if mr_i > min_i: return auto_min
    if mr_i < min_i: return auto_min
    return model_rating

# ---------------- Parents Guide aggregation ----------------
def aggregate_parents_guide(problem_fragments: List[Dict], total_scenes:int)->Dict:
    guide={}
    for group,labs in THEMATIC_GROUPS.items():
        eps=[pf for pf in problem_fragments if any(l in labs for l in pf["labels"])]
        if not eps:
            guide[group]={"severity":"None","episodes":0,"scenes_with_issues_percent":0.0,"examples":[]}
            continue
        scenes_set={pf["scene_index"] for pf in eps}
        max_sev=0
        examples=[]
        for pf in eps[:5]:
            sev_loc=pf.get("severity_local","None").lower()
            sev_val=SEV_MAP_STR2INT.get(sev_loc,0)
            max_sev=max(max_sev, sev_val)
            examples.append({
                "scene_index":pf["scene_index"],
                "page":pf.get("page"),
                "text":pf["text"],
                "labels":[l for l in pf["labels"] if l in labs],
                "severity_local":SEV_MAP_INT2STR.get(sev_val,"None")
            })
        guide[group]={
            "severity":SEV_MAP_INT2STR.get(max_sev,"None"),
            "episodes":len(eps),
            "scenes_with_issues_percent":round(len(scenes_set)/max(total_scenes,1)*100,1),
            "examples":examples
        }
    return guide

def assemble_report(document_name: str, total_scenes:int, problem_fragments: List[Dict],
                    processing_time: float, final_rating_override: Optional[str]=None,
                    model_explanation: Optional[str]=None, model_final_rating: Optional[str]=None)->Dict:
    parents_guide=aggregate_parents_guide(problem_fragments,total_scenes)
    if final_rating_override in ORDERED_RATINGS:
        final_rating=final_rating_override
    else:
        max_sev=0
        for g in parents_guide.values():
            sev=SEV_MAP_STR2INT.get(str(g.get("severity","")).lower(),0)
            max_sev=max(max_sev, sev)
        final_rating="18+" if max_sev>=3 else ("16+" if max_sev==2 else ("12+" if max_sev==1 else ("6+" if any(g.get("episodes",0)>0 for g in parents_guide.values()) else "0+")))
    out={
        "document":document_name,
        "final_rating":final_rating,
        "scenes_total":total_scenes,
        "parents_guide":parents_guide,
        "problem_fragments":problem_fragments,
        "processing_seconds":round(processing_time,2)
    }
    if model_final_rating: out["model_final_rating"]=model_final_rating
    if isinstance(model_explanation,str) and model_explanation.strip():
        out["model_explanation"]=model_explanation
    return out

# ---------------- Main ----------------
def main():
    ap=argparse.ArgumentParser(description="Multi-stage content rater with Stage 0 prefilter and soft Stage 3.")
    ap.add_argument("--input", default="sc.json")
    ap.add_argument("--output", default="test.json")
    ap.add_argument("--law-file", default="law.json")
    ap.add_argument("--repo-id", default="unsloth/gpt-oss-20b-GGUF")
    ap.add_argument("--filename", default="gpt-oss-20b-F16.gguf")
    ap.add_argument("--model-path", default=None)
    ap.add_argument("--n-ctx", type=int, default=12000)
    ap.add_argument("--n-gpu-layers", type=int, default=-1)
    ap.add_argument("--batch-size", type=int, default=1)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--llm-effort-s0", choices=["low","medium","high"], default="medium")
    ap.add_argument("--llm-effort-s1", choices=["low","medium","high"], default="medium")
    ap.add_argument("--llm-effort-s2", choices=["low","medium","high"], default="medium")
    ap.add_argument("--llm-effort-s3", choices=["low","medium","high"], default="high")
    ap.add_argument("--stage0-enable", action="store_true", default=True)
    ap.add_argument("--no-stage0-enable", dest="stage0_enable", action="store_false")
    ap.add_argument("--stage0-batch-size", type=int, default=6)
    ap.add_argument("--stage0-max-sentences", type=int, default=70)
    ap.add_argument("--debug-dir", default="debug_full")
    args=ap.parse_args()

    encoding=load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS) if HARMONY_AVAILABLE else None

    with open(args.input,"r",encoding="utf-8") as f:
        scenes=json.load(f)
    if not isinstance(scenes,list):
        raise TypeError("Input must be list of scenes.")
    for i,sc in enumerate(scenes):
        sc["scene_index"]=i

    with open(args.law_file,"r",encoding="utf-8") as f:
        law=json.load(f)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    if args.debug_dir: os.makedirs(args.debug_dir, exist_ok=True)
    # init model
    try:
        if args.model_path:
            llm=Llama(model_path=args.model_path, n_ctx=args.n_ctx, n_gpu_layers=args.n_gpu_layers, verbose=False)
        else:
            if hasattr(Llama,"from_pretrained"):
                llm=Llama.from_pretrained(repo_id=args.repo_id, filename=args.filename,
                                          n_ctx=args.n_ctx, n_gpu_layers=args.n_gpu_layers, verbose=False)
            else:
                llm=Llama(model_path=args.filename, n_ctx=args.n_ctx, n_gpu_layers=args.n_gpu_layers, verbose=False)
    except Exception as e:
        print("Model init failed:", e, file=sys.stderr); raise
    start=time.time()
    problem_fragments: List[Dict]=[]

    # Stage 0
    selected_scene_indices=None
    if args.stage0_enable:
        nn_set=set()
        with tqdm(total=len(scenes), desc="Stage 0") as pbar0:
            for b in range(0,len(scenes), args.stage0_batch_size):
                batch=scenes[b:b+args.stage0_batch_size]
                prompt0,_=build_stage0_conversation(batch, encoding, args.llm_effort_s0, args.stage0_max_sentences)
                raw0=""; parsed0=None
                temp0=_effort_temperature(args.llm_effort_s0)
                gen0={"prompt":prompt0,"temperature":temp0,"max_tokens":4048,"top_p":0.35,"repeat_penalty":1.05,"seed":101+b*42}
                for att in range(args.retries):
                    try:
                        resp0=llm.create_completion(**gen0)
                        raw0=resp0["choices"][0].get("text","")
                        parsed0=parse_llm_response(raw0, encoding, effort=args.llm_effort_s0, debug_dir=args.debug_dir, prefer="non_neutral")
                        break
                    except Exception as ee:
                        print(f"[Stage0 batch {b}] attempt {att+1} failed: {ee}", file=sys.stderr)
                        time.sleep(0.3)
                _maybe_dump(args.debug_dir,f"stage0_batch_{b}.raw.txt",raw0)
                if parsed0: _maybe_dump(args.debug_dir,f"stage0_batch_{b}.parsed.json",parsed0)

                nn_list=[]
                if isinstance(parsed0, dict) and isinstance(parsed0.get("non_neutral"), list):
                    nn_list=[int(x) for x in parsed0["non_neutral"] if isinstance(x,int)]
                if nn_list:
                    nn_set.update(nn_list)
                else:
                    # fail-safe: включаем весь батч
                    nn_set.update(sc["scene_index"] for sc in batch)
                pbar0.update(len(batch))
        selected_scene_indices=nn_set

    def _scenes_for_stage1(all_scenes: List[Dict])->List[Dict]:
        if selected_scene_indices is None:
            return all_scenes
        return [sc for sc in all_scenes if sc["scene_index"] in selected_scene_indices]

    scenes_s1=_scenes_for_stage1(scenes)

    # Stage 1
    with tqdm(total=len(scenes_s1), desc="Stage 1") as pbar1:
        for b in range(0,len(scenes_s1), args.batch_size):
            batch=scenes_s1[b:b+args.batch_size]
            prompt,_=build_stage1_conversation(batch, encoding, args.llm_effort_s1)
            raw=""; parsed=None
            temp=_effort_temperature(args.llm_effort_s1)
            gen={"prompt":prompt,"temperature":temp,"max_tokens":4096,"top_p":0.3,"repeat_penalty":1.05,"seed":1111+b*42}
            for att in range(args.retries):
                try:
                    resp=llm.create_completion(**gen)
                    raw=resp["choices"][0].get("text","")
                    parsed=parse_llm_response(raw, encoding, effort=args.llm_effort_s1, debug_dir=args.debug_dir, prefer="scene_results")
                    break
                except Exception as ee:
                    print(f"[Stage1 batch {b}] attempt {att+1} failed: {ee}", file=sys.stderr)
                    time.sleep(0.3)
            _maybe_dump(args.debug_dir,f"stage1_batch_{b}.raw.txt",raw)
            if parsed: _maybe_dump(args.debug_dir,f"stage1_batch_{b}.parsed.json",parsed)

            scene_results=[]
            if isinstance(parsed,dict) and isinstance(parsed.get("scene_results"),list):
                scene_results=parsed["scene_results"]
            elif isinstance(parsed,list):
                scene_results=parsed
            else:
                pbar1.update(len(batch)); continue

            converted=[]
            for sr in scene_results:
                if not isinstance(sr,dict): continue
                sc_id=sr.get("scID")
                if sc_id is None: continue
                orig=next((s for s in batch if s["scene_index"]==sc_id), None)
                if not orig: continue
                snts=sr.get("snt",[])
                packed=[]
                for item in snts:
                    if not isinstance(item,dict): continue
                    sid=item.get("id")
                    if sid is None: continue
                    vlc=item.get("vlc",[])
                    try:
                        sentence_text=orig.get("sentences",[])[sid].get("text","")
                    except Exception:
                        sentence_text=""
                    norm_labels=_collect_stage1_labels(vlc, sentence_text)
                    if norm_labels or vlc==[]:
                        packed.append({"id":sid,"text":sentence_text,"violations":norm_labels})
                # Fallback: если сцена вообще без меток — назначить MILD_CONFLICT на первое предложение
                if not any(x["violations"] for x in packed) and packed:
                    packed[0]["violations"]=[{"label":"MILD_CONFLICT","conf":60}]
                if packed:
                    converted.append({"scene_index":sc_id,"sentences":packed})
            new_frags=build_problem_fragments_from_compact(converted, scenes)
            problem_fragments.extend(new_frags)

            finalize_evidence_fields(problem_fragments)
            report=assemble_report(os.path.basename(args.input), len(scenes), problem_fragments, time.time()-start)
            with open(args.output,"w",encoding="utf-8") as f:
                json.dump(report,f,ensure_ascii=False,indent=2)
            pbar1.update(len(batch))

    # Stage 2
    queries=[]; seen=set()
    for pf in problem_fragments:
        key=(pf["scene_index"], pf["sentence_index"])
        if key in seen: continue
        seen.add(key)
        pt=""; nt=""
        try:
            sents=scenes[pf["scene_index"]].get("sentences",[])
            if pf["sentence_index"]-1>=0: pt=sents[pf["sentence_index"]-1].get("text","")
            if pf["sentence_index"]+1<len(sents): nt=sents[pf["sentence_index"]+1].get("text","")
        except Exception:
            pass
        queries.append({"scID":pf["scene_index"],"id":pf["sentence_index"],"pt":pt,"t":pf["text"],"nt":nt,"vlc":pf["labels"]})

    with tqdm(total=len(queries), desc="Stage 2") as pbar2:
        for q in range(0,len(queries), 3):
            q_batch=queries[q:q+3]
            prompt2,_=build_stage2_conversation(q_batch, encoding, args.llm_effort_s2)
            raw2=""; parsed2=None
            temp2=_effort_temperature(args.llm_effort_s2)
            gen2={"prompt":prompt2,"temperature":temp2,"max_tokens":40096,"top_p":0.3,"repeat_penalty":1.05,"seed":2222+q*42}
            for att in range(args.retries):
                try:
                    resp2=llm.create_completion(**gen2)
                    raw2=resp2["choices"][0].get("text","")
                    parsed2=parse_llm_response(raw2, encoding, effort=args.llm_effort_s2, debug_dir=args.debug_dir, prefer="ans")
                    break
                except Exception as ee:
                    print(f"[Stage2 batch {q}] attempt {att+1} failed: {ee}", file=sys.stderr)
                    time.sleep(0.3)
            _maybe_dump(args.debug_dir,f"stage2_batch_{q}.raw.txt",raw2)
            if parsed2: _maybe_dump(args.debug_dir,f"stage2_batch_{q}.parsed.json",parsed2)

            ans_full=ensure_stage2_backfill(q_batch, parsed2)
            problem_fragments=apply_stage2(ans_full, problem_fragments, args.debug_dir)
            finalize_evidence_fields(problem_fragments)
            report=assemble_report(os.path.basename(args.input), len(scenes), problem_fragments, time.time()-start)
            with open(args.output,"w",encoding="utf-8") as f:
                json.dump(report,f,ensure_ascii=False,indent=2)
            pbar2.update(len(q_batch))

    # Stage 3

    packed_violated=pack_violated_sentences_with_context(problem_fragments, scenes)
    prompt3,_=build_stage3_conversation(law, packed_violated, encoding, args.llm_effort_s3)
    raw3=""; parsed3=None
    temp3=_effort_temperature(args.llm_effort_s3)
    for att in range(args.retries):
        gen3 = {"prompt": prompt3, "temperature": 0, "max_tokens": 30000, "top_p": 1, "repeat_penalty": 1.05,
                "seed": 420 + 42 * b}
        llm.close()
        try:
            if args.model_path:
                llm = Llama(model_path=args.model_path, n_ctx=30000 + att * 7000, n_gpu_layers=args.n_gpu_layers, verbose=False)
            else:
                if hasattr(Llama, "from_pretrained"):
                    llm = Llama.from_pretrained(repo_id=args.repo_id, filename=args.filename,
                                                n_ctx=30000 + att * 7000, n_gpu_layers=args.n_gpu_layers, verbose=False)
                else:
                    llm = Llama(model_path=args.filename, n_ctx=30000 + att * 7000, n_gpu_layers=args.n_gpu_layers, verbose=False)
        except Exception as e:
            print("Model init failed:", e, file=sys.stderr)
            raise
        try:
            resp3=llm.create_completion(**gen3)
            raw3=resp3["choices"][0].get("text","")
            parsed3=parse_llm_response(raw3, encoding, effort=args.llm_effort_s3, debug_dir=args.debug_dir, prefer="final_rating")
            break
        except Exception as ee:
            print(f"[Stage3] attempt {att+1} failed: {ee}", file=sys.stderr)
            time.sleep(0.3)
    _maybe_dump(args.debug_dir,"stage3.raw.txt",raw3)
    if parsed3: _maybe_dump(args.debug_dir,"stage3.parsed.json",parsed3)

    model_final_rating=None
    model_explanation=None
    if isinstance(parsed3,dict):
        fr=parsed3.get("final_rating")
        if isinstance(fr,str) and fr.strip():
            model_final_rating=fr.strip()
        exp=parsed3.get("explanation")
        if isinstance(exp,str) and exp.strip():
            model_explanation=exp.strip()

    report=assemble_report(os.path.basename(args.input), len(scenes), problem_fragments,
                           time.time()-start,
                           final_rating_override=None,
                           model_explanation=model_explanation,
                           model_final_rating=model_final_rating)

    if parsed3 and isinstance(model_final_rating, str) and model_final_rating.strip():
        report["final_rating"] = model_final_rating.strip()

    with open(args.output,"w",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
    print(f"Done. Final rating: {report['final_rating']} (model raw: {report.get('model_final_rating','n/a')}) Saved: {args.output}")

if __name__=="__main__":
    main()