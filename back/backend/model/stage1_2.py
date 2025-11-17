from __future__ import annotations
import time, json, os, re, sys
from typing import Any, Dict, List, Optional

from llama_cpp import Llama

# Импорт констант и парсера
from constants import (
    LABELS, THEMATIC_GROUPS, SEVERITY_WEIGHT, SEV_MAP_INT2STR, SEV_MAP_STR2INT,
    FW_RULES, S1_EXCLUSIVE_PAIRS,
    _PROFANITY_ROOT_PATTERNS, _ALIAS_MAP
)
from parser_llm import parse_llm_response

# -------- Harmony (опционально) --------
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


# -------- Effort helpers (заготовки) --------
def _effort_to_reasoning(effort: str):
    e=(effort or "low").lower()
    if not HARMONY_AVAILABLE: return None
    return ReasoningEffort.HIGH if e=="high" else (ReasoningEffort.MEDIUM if e=="medium" else ReasoningEffort.LOW)

def _effort_temperature(effort: str)->float:
    e=(effort or "low").lower()
    return 0.15 if e=="high" else (0.08 if e=="medium" else 0.01)


# -------- Stage 1 prompt (заготовка) --------
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

# -------- Stage 2 prompt (заготовка) --------
def build_stage2_conversation(q_batch: List[Dict], encoding, llm_effort: str="low")->tuple[str,List[str]]:
    instruction=(
        "You rate Russian screenplay sentences. Return ONLY JSON:\n"
        "{\"ans\":[{\"scID\":int,\"id\":int,\"det\":[{\"label\":string,\"sev\":\"Mild|Moderate|Severe\",\"scr\":int,\"rsn\":string,\"adv\":string,\"ok\":boolean,\"suggest\":string|null}]}]}\n"
        "FOR EACH input label produce a det object. Use allowed labels exactly. Profanity only if obscene roots.\n"
        "Drugs depiction only explicit illegal human use; else ok=false suggest DRUGS_MENTION_NON_DETAILED/REMOVE.\n"
        "sev from th; scr from bs (+/- brief rationale). Пиши reason и advice на русском языке. final-only."
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


# -------- Helpers (скопировано и упрощено из пайплайна) --------
def _maybe_dump(debug_dir: Optional[str], filename: str, content: Any)->None:
    if not debug_dir: return
    try:
        os.makedirs(debug_dir, exist_ok=True)
        path=os.path.join(debug_dir, filename)
        with open(path,"w",encoding="utf-8") as f:
            if isinstance(content,(dict,list)):
                json.dump(content,f,ensure_ascii=False,indent=2)
            else:
                f.write(str(content))
    except Exception:
        pass

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
        if lab=="PROFANITY_OBSCENE":
            t=sentence_text.lower().replace("ё","е")
            if not any(p.search(t) for p in _PROFANITY_ROOT_PATTERNS):
                continue
        c=int(conf) if isinstance(conf,(int,float)) else 0
        if lab not in best or c>best[lab]:
            best[lab]=c
    # Взаимоисключения
    for a,b in S1_EXCLUSIVE_PAIRS:
        if a in best and b in best:
            if best[a]>=best[b]: del best[b]
            else: del best[a]
    return [{"label":lab,"conf":best[lab]} for lab in best]

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

def ensure_stage2_backfill(q_batch: List[Dict], parsed2: Optional[Dict])->List[Dict]:
    def _norm_label(x: Any)->Optional[str]:
        if isinstance(x,str):
            return normalize_label(x)
        if isinstance(x,dict):
            v=x.get("label")
            return normalize_label(v) if isinstance(v,str) else None
        return None

    model_map={}
    if isinstance(parsed2,dict) and isinstance(parsed2.get("ans"),list):
        for ans in parsed2["ans"]:
            if not isinstance(ans,dict): continue
            scid=ans.get("scID"); sid=ans.get("id"); det=ans.get("det",[])
            if not (isinstance(scid,int) and isinstance(sid,int)): continue
            if not isinstance(det,list): det=[]
            labmap={}
            for d in det:
                if not isinstance(d,dict): continue
                lab=_norm_label(d.get("label"))
                if not lab: continue
                labmap[lab]={
                    "label": lab,
                    "sev": d.get("sev"),
                    "scr": d.get("scr"),
                    "rsn": d.get("rsn"),
                    "adv": d.get("adv"),
                    "ok": d.get("ok",True),
                    "suggest": d.get("suggest")
                }
            model_map[(scid,sid)]=labmap

    full=[]
    for q in q_batch:
        scid=q.get("scID"); sid=q.get("id"); vlc=q.get("vlc",[])
        if not (isinstance(scid,int) and isinstance(sid,int)): continue
        in_labels=[]
        for v in vlc:
            lab=_norm_label(v)
            if lab: in_labels.append(lab)
        # preserve order unique
        seen=set(); in_labels=[x for x in in_labels if not (x in seen or seen.add(x))]
        det_out=[]
        mlabs=model_map.get((scid,sid),{})
        for lab in in_labels:
            base=int(FW_RULES["bs"].get(lab,40))
            default={
                "label": lab,
                "sev": _severity_from_base_score(base),
                "scr": base,
                "rsn": "Авто: базовая оценка.",
                "adv": "Редактура: смягчить при необходимости.",
                "ok": True,
                "suggest": None
            }
            if lab in mlabs:
                md=mlabs[lab]
                for k in ("sev","scr","rsn","adv","ok","suggest"):
                    if md.get(k) is not None: default[k]=md[k]
            det_out.append(default)
        # model-added labels
        for lab, md in mlabs.items():
            if lab not in in_labels:
                base=int(FW_RULES["bs"].get(lab,40))
                det_out.append({
                    "label": lab,
                    "sev": md.get("sev", _severity_from_base_score(base)),
                    "scr": md.get("scr", base),
                    "rsn": md.get("rsn","Авто: добавлено моделью."),
                    "adv": md.get("adv","Редактура: смягчить при необходимости."),
                    "ok": md.get("ok",True),
                    "suggest": md.get("suggest")
                })
        full.append({"scID":scid,"id":sid,"det":det_out})
    return full

def apply_stage2(full_ans: List[Dict], problem_fragments: List[Dict])->List[Dict]:
    det_map={(a.get("scID"), a.get("id")): a.get("det",[]) for a in full_ans}
    out=[]
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
                continue
            if lab not in labels:
                labels.append(lab)
                ev[lab]={"severity":"", "score":None, "reason":"", "advice":None, "trigger":None}
            if lab in ev:
                if d.get("sev"): ev[lab]["severity"]=d["sev"]
                if isinstance(d.get("scr"),(int,float)): ev[lab]["score"]=int(d["scr"])
                if isinstance(d.get("rsn"),str) and d["rsn"].strip(): ev[lab]["reason"]=d["rsn"].strip()
                if isinstance(d.get("adv"),str) and d["adv"].strip():
                    ev[lab]["advice"]=d["adv"].strip(); adv_acc.append(d["adv"].strip())
        if labels and ev:
            pf["labels"]=labels
            pf["evidence_spans"]=ev
            pf["severity_local"]=_compute_severity_local_from_evidence(ev)
            if adv_acc: pf["recommendations"]=list(dict.fromkeys(adv_acc))
            out.append(pf)
    return out

def aggregate_parents_guide(problem_fragments: List[Dict]) -> Dict[str,Any]:
    total_scenes=1
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
            "scenes_with_issues_percent":round(len(scenes_set)/1*100,1),
            "examples":examples
        }
    return guide

def _infer_final_rating(parents_guide: Dict[str,Any])->str:
    # Аналог assemble_report без модели
    max_sev=0
    for g in parents_guide.values():
        sev=SEV_MAP_STR2INT.get(str(g.get("severity","")).lower(),0)
        max_sev=max(max_sev, sev)
    if max_sev>=3: return "18+"
    if max_sev==2: return "16+"
    if max_sev==1: return "12+"
    # Если есть любые эпизоды mild (episodes >0) — 6+, иначе 0+
    if any(g.get("episodes",0)>0 for g in parents_guide.values()):
        return "6+"
    return "0+"


# -------- Основная функция --------
def analyze_single_scene(
    scene_input: Dict[str, Any],
    *,
    document_name: str = "single_scene",
    repo_id: str = "unsloth/gpt-oss-20b-GGUF",
    filename: str = "gpt-oss-20b-F16.gguf",
    model_path: Optional[str] = None,
    n_ctx: int = 6000,
    n_gpu_layers: int = -1,
    llm_effort_s1: str = "low",
    llm_effort_s2: str = "low",
    retries: int = 3,
    batch_size: int = 1,
    debug_dir: Optional[str] = None,
    seed_stage1: int = 101,
    seed_stage2: int = 202
) -> Dict[str, Any]:
    """
    Выполняет Stage 1 и Stage 2 для одной сцены и возвращает итоговый отчёт.
    """
    start=time.time()

    # Подготовка структуры сцены в формате пайплайна
    sentences = scene_input.get("sentences", [])
    if not isinstance(sentences, list) or not all(isinstance(x,str) for x in sentences):
        raise ValueError("scene_input['sentences'] must be a list of strings.")
    scene = {
        "scene_index": 0,
        "heading": scene_input.get("heading",""),
        "page": scene_input.get("page"),
        "sentences": [{"text": s} for s in sentences]
    }
    scenes = [scene]

    # Init Harmony encoding (optional)
    encoding = load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS) if HARMONY_AVAILABLE else None

    # Init LLM
    try:
        if model_path:
            llm = Llama(model_path=model_path, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers, verbose=False)
        else:
            if hasattr(Llama,"from_pretrained"):
                llm = Llama.from_pretrained(repo_id=repo_id, filename=filename,
                                            n_ctx=n_ctx, n_gpu_layers=n_gpu_layers, verbose=False)
            else:
                llm = Llama(model_path=filename, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers, verbose=False)
    except Exception as e:
        raise RuntimeError(f"Model init failed: {e}")

    problem_fragments: List[Dict] = []

    # ---------- Stage 1 ----------
    prompt_s1,_ = build_stage1_conversation(scenes, encoding, llm_effort_s1)
    raw_s1=""; parsed_s1=None
    gen1 = {
        "prompt": prompt_s1,
        "temperature": _effort_temperature(llm_effort_s1),
        "max_tokens": 2048,
        "top_p": 0.3,
        "repeat_penalty": 1.05,
        "seed": seed_stage1
    }
    for attempt in range(retries):
        try:
            resp = llm.create_completion(**gen1)
            raw_s1 = resp["choices"][0].get("text","")
            parsed_s1 = parse_llm_response(raw_s1, encoding, effort=llm_effort_s1,
                                           debug_dir=debug_dir, prefer="scene_results")
            break
        except Exception as e:
            if attempt+1 == retries:
                raise
            time.sleep(0.2)

    if debug_dir:
        _maybe_dump(debug_dir,"stage1.raw.txt",raw_s1)
        if parsed_s1:
            _maybe_dump(debug_dir,"stage1.parsed.json",parsed_s1)

    # Конвертация scene_results -> problem_fragments
    converted=[]
    scene_results=[]
    if isinstance(parsed_s1,dict) and isinstance(parsed_s1.get("scene_results"),list):
        scene_results = parsed_s1["scene_results"]
    elif isinstance(parsed_s1,list):
        scene_results = parsed_s1

    for sr in scene_results:
        if not isinstance(sr,dict): continue
        sc_id=sr.get("scID")
        if sc_id != 0: continue
        snts=sr.get("snt",[])
        packed=[]
        for item in snts:
            if not isinstance(item,dict): continue
            sid=item.get("id")
            if sid is None: continue
            vlc=item.get("vlc",[])
            text_val=sentences[sid] if sid < len(sentences) else ""
            norm=_collect_stage1_labels(vlc, text_val)
            if norm or vlc==[]:
                packed.append({"id":sid,"text":text_val,"violations":norm})
        # Fallback: если нет меток ни в одной реплике — назначить MILD_CONFLICT первой
        if packed and not any(p["violations"] for p in packed):
            packed[0]["violations"]=[{"label":"MILD_CONFLICT","conf":60}]
        if packed:
            converted.append({"scene_index":0,"sentences":packed})

    pf_add = build_problem_fragments_from_compact(converted, scenes)
    problem_fragments.extend(pf_add)

    # Инициализация defaults в evidence
    finalize_evidence_fields(problem_fragments)

    # ---------- Stage 2 ----------
    # Формируем queries
    queries=[]
    for pf in problem_fragments:
        scID=pf["scene_index"]; sid=pf["sentence_index"]
        pt=""; nt=""
        if sid-1>=0: pt=scene["sentences"][sid-1].get("text","")
        if sid+1<len(scene["sentences"]): nt=scene["sentences"][sid+1].get("text","")
        queries.append({"scID": scID, "id": sid, "pt": pt, "t": pf["text"], "nt": nt, "vlc": pf["labels"]})

    prompt_s2,_ = build_stage2_conversation(queries, encoding, llm_effort_s2)
    raw_s2=""; parsed_s2=None
    gen2={
        "prompt": prompt_s2,
        "temperature": _effort_temperature(llm_effort_s2),
        "max_tokens": 4096,
        "top_p": 0.3,
        "repeat_penalty": 1.05,
        "seed": seed_stage2
    }
    for attempt in range(retries):
        try:
            resp2=llm.create_completion(**gen2)
            raw_s2=resp2["choices"][0].get("text","")
            parsed_s2=parse_llm_response(raw_s2, encoding, effort=llm_effort_s2,
                                         debug_dir=debug_dir, prefer="ans")
            break
        except Exception as e:
            if attempt+1==retries:
                raise
            time.sleep(0.2)

    if debug_dir:
        _maybe_dump(debug_dir,"stage2.raw.txt", raw_s2)
        if parsed_s2:
            _maybe_dump(debug_dir,"stage2.parsed.json", parsed_s2)

    ans_full=ensure_stage2_backfill(queries, parsed_s2)
    problem_fragments=apply_stage2(ans_full, problem_fragments)
    finalize_evidence_fields(problem_fragments)

    # ---------- Parents Guide & Final rating ----------
    parents_guide=aggregate_parents_guide(problem_fragments)
    final_rating=_infer_final_rating(parents_guide)

    processing_time=time.time()-start
    report={
        "document": document_name,
        "final_rating": final_rating,
        "scenes_total": 1,
        "parents_guide": parents_guide,
        "problem_fragments": problem_fragments,
        "processing_seconds": round(processing_time,2)
    }

    # Debug dump
    if debug_dir:
        _maybe_dump(debug_dir,"final_report.json", report)

    return report


# -------- Пример вызова (можно удалить) --------
if __name__ == "__main__":
    test_scene = {
  "sentences":
 []
}

    result = analyze_single_scene(
        test_scene,
        document_name="6_out.json",
        llm_effort_s1="medium",
        llm_effort_s2="medium",
        n_ctx=4000,
        retries=2,
        debug_dir="debug_single_scene"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))