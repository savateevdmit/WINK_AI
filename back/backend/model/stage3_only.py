#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# llama_cpp (опционально)
try:
    from llama_cpp import Llama
    _HAS_LLAMA = True
except Exception:
    _HAS_LLAMA = False

# Harmony (опционально, если используется у вас в окружении)
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

# Парсер и константы — используем те же файлы, что и в пайплайне
from parser_llm import parse_llm_response
from constants import (
    ORDERED_RATINGS,
    THEMATIC_GROUPS,
    CONDEMNATION_TOKENS, FAMILY_TOKENS, COMEDY_TOKENS, GRAPHIC_TOKENS, AROUSAL_TOKENS
)

# ---------------- Effort helpers (как в пайплайне) ----------------
def _effort_to_reasoning(effort: str):
    e=(effort or "low").lower()
    if not HARMONY_AVAILABLE: return None
    return ReasoningEffort.HIGH if e=="high" else (ReasoningEffort.MEDIUM if e=="medium" else ReasoningEffort.LOW)

def _effort_temperature(effort: str)->float:
    e=(effort or "low").lower()
    return 0.15 if e=="high" else (0.08 if e=="medium" else 0.01)

# ---------------- Вспомогательные утилиты ----------------
def _maybe_dump(debug_dir: Optional[str], filename: str, content: Any) -> None:
    if not debug_dir: return
    try:
        os.makedirs(debug_dir, exist_ok=True)
        with open(os.path.join(debug_dir, filename), "w", encoding="utf-8") as f:
            if isinstance(content, (dict, list)):
                json.dump(content, f, ensure_ascii=False, indent=2)
            else:
                f.write(str(content))
    except Exception:
        pass

def _groups_for_labels(labels: List[str])->List[str]:
    groups=[]
    for g,labs in THEMATIC_GROUPS.items():
        if any(l in labs for l in labels):
            groups.append(g)
    return sorted(set(groups))

# ---------------- Контекст и смягчающие факторы ----------------
def detect_softeners(text_block: str)->dict:
    t=text_block.lower()
    return {
        "condemnation": any(tok in t for tok in CONDEMNATION_TOKENS),
        "family_context": any(tok in t for tok in FAMILY_TOKENS),
        "comedy": any(tok in t for tok in COMEDY_TOKENS),
        "low_detail": not any(tok in t for tok in (GRAPHIC_TOKENS | AROUSAL_TOKENS))
    }

def _pack_with_optional_context(problem_fragments: List[Dict[str,Any]],
                                scenes_index: Optional[Dict[int, Dict[str,Any]]]) -> List[Dict[str,Any]]:
    """
    Формирует violated_sentences как в пайплайне. Если есть сцены — добавляем prev/next.
    Если сцен нет — отправляем без prev/next (LLM промпт допускает отсутствие контекста).
    """
    out=[]
    for pf in problem_fragments:
        sc_idx = pf.get("scene_index")
        sent_idx = pf.get("sentence_index")
        text = pf.get("text","")
        labels = pf.get("labels",[]) or []
        ev_src = pf.get("evidence_spans",{}) or {}
        prev_list: List[str] = []
        next_list: List[str] = []
        if scenes_index is not None and isinstance(sc_idx,int) and isinstance(sent_idx,int):
            sc = scenes_index.get(sc_idx)
            if sc and isinstance(sc.get("sentences"), list):
                sents = sc["sentences"]
                if sent_idx-1 >= 0 and sent_idx-1 < len(sents):
                    prev_list.append(sents[sent_idx-1].get("text",""))
                if sent_idx+1 < len(sents):
                    next_list.append(sents[sent_idx+1].get("text",""))
        full_text_for_soft = " ".join(prev_list + [text] + next_list)
        soft = detect_softeners(full_text_for_soft)
        out.append({
            "scene_index": sc_idx,
            "sentence_index": sent_idx,
            "text": text,
            "labels": labels,
            "groups": _groups_for_labels(labels),
            "severity_local": pf.get("severity_local","None"),
            "ev": {lab:{
                "sev": ev_src.get(lab,{}).get("severity",""),
                "scr": ev_src.get(lab,{}).get("score")
            } for lab in labels},
            "context_prev": prev_list,
            "context_next": next_list,
            "scene_heading": pf.get("scene_heading"),
            "softeners": soft
        })
    return out

# ---------------- Построение промпта Stage 3 (как в пайплайне) ----------------
def build_stage3_conversation(law_rules_obj: Dict[str,Any],
                              violated_sentences: List[Dict[str,Any]],
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
        "Rely on the law, but the goal is TO ASSIGN THE LOWEST ACCEPTABLE rating.\n"
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

# ---------------- Фолбэк (если модель не распарсилась) ----------------
def fallback_minimal(problem_fragments: List[Dict[str,Any]]) -> str:
    """
    Простой резерв: если модель не дала валидный рейтинг — присвоим минимум по наличию проблем:
    - Если есть хоть один фрагмент — 6+, иначе 0+.
    (Ровно как в assemble_report без входа модели, самый базовый нижний порог.)
    """
    return "6+" if problem_fragments else "0+"

# ---------------- Основной поток Stage 3 ----------------
def main():
    ap = argparse.ArgumentParser(description="Stage 3 only — run exactly like pipeline Stage 3 (model rating preferred).")
    ap.add_argument("--input", default="test.json", help="JSON from stages 1+2 (must include problem_fragments)")
    ap.add_argument("--law-file", default="law.json", help="Path to law.json")
    ap.add_argument("--output", default="stage3_output.json", help="Path to final JSON")
    # LLM options
    ap.add_argument("--no-llm", default=False, action="store_true", help="Disable LLM call (fallback only)")
    ap.add_argument("--repo-id", default="unsloth/gpt-oss-20b-GGUF")
    ap.add_argument("--filename", default="gpt-oss-20b-F16.gguf")
    ap.add_argument("--model-path", default=None)
    ap.add_argument("--n-ctx", type=int, default=30000)
    ap.add_argument("--n-gpu-layers", type=int, default=-1)
    ap.add_argument("--llm-effort", choices=["low","medium","high"], default="high")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--debug-dir", default='debug')
    args = ap.parse_args()

    start = time.time()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise TypeError("Input must be JSON object containing 'problem_fragments'")

    problem_fragments: List[Dict[str,Any]] = data.get("problem_fragments") or []
    if not isinstance(problem_fragments, list):
        raise TypeError("'problem_fragments' must be a list")

    scenes_total = int(data.get("scenes_total") or 0)
    document_name = data.get("document") or os.path.basename(args.input)

    # Опционально: если есть полные сцены — используем для контекста
    scenes_by_index: Optional[Dict[int, Dict[str,Any]]] = None
    if isinstance(data.get("scenes"), list):
        scenes_by_index = {sc.get("scene_index"): sc for sc in data["scenes"] if isinstance(sc, dict) and "scene_index" in sc}

    # Загружаем закон
    with open(args.law_file, "r", encoding="utf-8") as f:
        law_obj = json.load(f)

    # Формируем violated_sentences как в пайплайне (с контекстом, если можем)
    violated_sentences = _pack_with_optional_context(problem_fragments, scenes_by_index)

    # Вызов модели (как в пайплайне): собираем промпт, просим только финальный JSON, парсим prefer="final_rating"
    model_final_rating: Optional[str] = None
    model_explanation: Optional[str] = None

    raw3 = ""
    parsed3: Optional[Dict[str,Any]] = None

    if not args.no_llm if False else not args.no_llm:  # safe guard in case of typo in flags
        pass
    # Корректная проверка:
    if (not args.no_llm) and _HAS_LLAMA:
        # Инициализируем модель
        llm = None
        try:
            if args.model_path:
                llm = Llama(model_path=args.model_path, n_ctx=args.n_ctx, n_gpu_layers=args.n_gpu_layers, verbose=False)
            else:
                if hasattr(Llama, "from_pretrained"):
                    llm = Llama.from_pretrained(repo_id=args.repo_id, filename=args.filename,
                                                n_ctx=args.n_ctx, n_gpu_layers=args.n_gpu_layers, verbose=False)
                else:
                    llm = Llama(model_path=args.filename, n_ctx=args.n_ctx, n_gpu_layers=args.n_gpu_layers, verbose=False)
        except Exception as e:
            print(f"[Stage3] LLM init failed: {e}", file=sys.stderr)

        if llm is not None:
            # Harmony (опционально)
            encoding = load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS) if HARMONY_AVAILABLE else None
            prompt3, _ = build_stage3_conversation(law_obj, violated_sentences, encoding, args.llm_effort)
            gen3 = {
                "prompt": prompt3,
                "temperature": 0,
                "max_tokens": 50000,
                "top_p": 1,
                "repeat_penalty": 1.05,
                "seed": 420,
            }
            for att in range(args.retries):
                try:
                    resp3 = llm.create_completion(**gen3)
                    raw3 = resp3["choices"][0].get("text","")
                    break
                except Exception as ee:
                    if att+1 == args.retries:
                        print(f"[Stage3] LLM call failed: {ee}", file=sys.stderr)
                    time.sleep(0.25)
            _maybe_dump(args.debug_dir,"stage3.raw.txt",raw3)

            if raw3:
                try:
                    parsed3 = parse_llm_response(raw3, encoding, effort=args.llm_effort, debug_dir=args.debug_dir, prefer="final_rating")
                    _maybe_dump(args.debug_dir,"stage3.parsed.json", parsed3)
                except Exception as pe:
                    print(f"[Stage3] parse failed: {pe}", file=sys.stderr)

    # Как в пайплайне: записываем рейтинг МОДЕЛИ, если он распарсился; иначе — фолбэк.
    if isinstance(parsed3, dict):
        fr = parsed3.get("final_rating")
        if isinstance(fr, str) and fr.strip() in ORDERED_RATINGS:
            model_final_rating = fr.strip()
        exp = parsed3.get("explanation")
        if isinstance(exp, str) and exp.strip():
            model_explanation = exp.strip()

    # Итоговый рейтинг:
    if model_final_rating:
        final_rating = model_final_rating
    else:
        # Только если парсинг не удался — подставляем фолбэк (строго по вашему требованию).
        final_rating = fallback_minimal(problem_fragments)

    # Пишем отчёт (как в пайплайне — модельный рейтинг всегда дублируем в model_final_rating)
    out: Dict[str,Any] = {
        "document": document_name,
        "final_rating": final_rating,
        "scenes_total": scenes_total,
        "problem_fragments": problem_fragments,
        "model_final_rating": model_final_rating,
        "model_explanation": model_explanation,
        "processing_seconds": round(time.time()-start, 2)
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Stage 3 done. Final rating: {out['final_rating']} (model: {out.get('model_final_rating') or 'n/a'}) Saved: {args.output}")


if __name__ == "__main__":
    main()