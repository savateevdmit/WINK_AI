#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Edit service (extended + change-flag support).

Change:
- Any mutation that persists output.json will now also create/touch <ws>/temp.txt to invalidate analyzer cache.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..storage import save_result_json, load_json_if_exists

# Group mapping and severity maps reused from previous revision
THEMATIC_GROUPS: Dict[str, List[str]] = {
    "Violence_Gore": ["VIOLENCE_GRAPHIC","VIOLENCE_NON_GRAPHIC","MURDER_HOMICIDE","MEDICAL_GORE_DETAILS","SUICIDE_SELF_HARM"],
    "Sex_Nudity": ["SEX_EXPLICIT","SEXUAL_VIOLENCE","NUDITY_EXPLICIT","SEX_SUGGESTIVE","NUDITY_NONSEXUAL"],
    "Alcohol_Drugs_Smoking": ["DRUGS_USE_DEPICTION","DRUGS_MENTION_NON_DETAILED","ALCOHOL_USE","TOBACCO_USE"],
    "Profanity": ["PROFANITY_OBSCENE"],
    "Crime": ["CRIME_INSTRUCTIONS","CRIMINAL_ACTIVITY"],
    "Weapons": ["WEAPONS_USAGE","WEAPONS_MENTION"],
    "Frightening_Intense": ["HORROR_FEAR","DANGEROUS_IMITABLE_ACTS","ABUSE_HATE_EXTREMISM"],
    "Gambling": ["GAMBLING"],
    "Other": ["MILD_CONFLICT"],
    "Extremism_Propaganda": ["EXTREMISM_PROPAGANDA","NAZISM_PROPAGANDA","FASCISM_PROPAGANDA","ABUSE_HATE_EXTREMISM"],
}

VALID_SEVERITIES = {"None","Mild","Moderate","Severe"}
SEV_RANK = {"none":0,"mild":1,"moderate":2,"severe":3}
SEV_REV = {0:"None",1:"Mild",2:"Moderate",3:"Severe"}


def _load_output(ws: str) -> Dict[str, Any]:
    p = Path(ws)
    model_out = p / "model" / "output.json"
    stages_out = p / "stages" / "output_final.json"
    data = load_json_if_exists(str(model_out)) or load_json_if_exists(str(stages_out))
    if not isinstance(data, dict):
        raise FileNotFoundError("output.json not found (model/output.json or stages/output_final.json).")
    data.setdefault("problem_fragments", [])
    data.setdefault("parents_guide", {})
    data.setdefault("scenes_total", 0)
    return data

def _touch_change_flag(ws: str) -> None:
    Path(ws, "temp.txt").touch()

def _save_output(ws: str, data: Dict[str, Any]) -> Dict[str, Any]:
    # Invalidate analyzer cache on any user-driven change
    _touch_change_flag(ws)
    return save_result_json(ws, "output_final.json", data)


def _labels_for_group(labels: List[str], group_list: List[str]) -> List[str]:
    return [l for l in labels if l in group_list]

def _derive_fragment_severity_from_evidence(ev: Dict[str, Dict[str, Any]]) -> str:
    max_rank = 0
    for lab_data in ev.values():
        sev = str(lab_data.get("severity","None"))
        max_rank = max(max_rank, SEV_RANK.get(sev.lower(),0))
    return SEV_REV.get(max_rank,"None")

def _recompute_parents_guide(problem_fragments: List[Dict[str, Any]], scenes_total: int) -> Dict[str, Any]:
    guide: Dict[str, Any] = {}
    for group, glabels in THEMATIC_GROUPS.items():
        matched = [pf for pf in problem_fragments if any(l in glabels for l in pf.get("labels", []))]
        if not matched:
            guide[group] = {
                "severity": "None",
                "episodes": 0,
                "scenes_with_issues_percent": 0.0,
                "examples": []
            }
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
                "labels": _labels_for_group(pf.get("labels", []), glabels),
                "severity_local": SEV_REV.get(r,"None")
            })
        guide[group] = {
            "severity": SEV_REV.get(max_group_rank,"None"),
            "episodes": len(matched),
            "scenes_with_issues_percent": round(len(scenes_set)/max(scenes_total or 1,1)*100.0,1),
            "examples": examples
        }
    return guide


def _find_fragment(problem_fragments: List[Dict[str, Any]], scene_index: int, sentence_index: int) -> Optional[Dict[str, Any]]:
    for pf in problem_fragments:
        if int(pf.get("scene_index",-1)) == scene_index and int(pf.get("sentence_index",-1)) == sentence_index:
            return pf
    return None

def _normalize_labels_spec(labels_spec: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    norm: List[Dict[str, Any]] = []
    if not isinstance(labels_spec, list):
        return norm
    for item in labels_spec:
        if not isinstance(item, dict): continue
        label = item.get("label")
        if not isinstance(label,str) or not label:
            continue
        local_sev = item.get("local_severity") or "None"
        if local_sev not in VALID_SEVERITIES:
            local_sev = "None"
        reason = item.get("reason") or ""
        advice = item.get("advice") or ""
        norm.append({
            "label": label,
            "local_severity": local_sev,
            "reason": reason,
            "advice": advice
        })
    return norm


def add_violation_extended(
    ws: str,
    scene_index: int,
    sentence_index: int,
    text: str,
    fragment_severity: str,
    labels_spec: List[Dict[str, Any]]
) -> Dict[str, Any]:
    if fragment_severity not in VALID_SEVERITIES:
        fragment_severity = "Mild"

    data = _load_output(ws)
    pfr = list(data.get("problem_fragments", []))

    pf = _find_fragment(pfr, scene_index, sentence_index)
    if pf is None:
        pf = {
            "scene_index": scene_index,
            "scene_heading": "",
            "page": None,
            "sentence_index": sentence_index,
            "text": text,
            "labels": [],
            "confidence": {},
            "evidence_spans": {},
            "recommendations": [],
            "fragment_severity": fragment_severity,
            "severity_local": "None"
        }
        pfr.append(pf)
    else:
        pf["text"] = text
        pf["fragment_severity"] = fragment_severity

    norm_labels = _normalize_labels_spec(labels_spec)
    existing_labels = set(pf.get("labels", []))
    for item in norm_labels:
        existing_labels.add(item["label"])
    pf["labels"] = sorted(existing_labels)

    ev_old = pf.get("evidence_spans", {}) or {}
    ev_new: Dict[str, Dict[str, Any]] = {}
    for item in norm_labels:
        lab = item["label"]
        ev_new[lab] = {
            "severity": item["local_severity"],
            "score": ev_old.get(lab, {}).get("score", None),
            "reason": item["reason"],
            "advice": item["advice"],
            "trigger": ev_old.get(lab, {}).get("trigger", None)
        }
    for lab in pf["labels"]:
        if lab not in ev_new:
            prev = ev_old.get(lab, {})
            ev_new[lab] = {
                "severity": prev.get("severity","None"),
                "score": prev.get("score", None),
                "reason": prev.get("reason",""),
                "advice": prev.get("advice",""),
                "trigger": prev.get("trigger", None)
            }
    pf["evidence_spans"] = ev_new
    pf["severity_local"] = _derive_fragment_severity_from_evidence(pf["evidence_spans"])

    data["problem_fragments"] = pfr
    data["parents_guide"] = _recompute_parents_guide(pfr, int(data.get("scenes_total",0)))
    return _save_output(ws, data)


def update_violation_extended(
    ws: str,
    scene_index: int,
    sentence_index: int,
    text: str,
    fragment_severity: str,
    labels_spec: List[Dict[str, Any]]
) -> Dict[str, Any]:
    if fragment_severity not in VALID_SEVERITIES:
        fragment_severity = "Mild"

    data = _load_output(ws)
    pfr = list(data.get("problem_fragments", []))
    pf = _find_fragment(pfr, scene_index, sentence_index)
    if pf is None:
        raise ValueError("Violation not found for given scene_index & sentence_index")

    pf["text"] = text
    pf["fragment_severity"] = fragment_severity

    norm_labels = _normalize_labels_spec(labels_spec)
    if not norm_labels:
        pfr = [x for x in pfr if not (int(x.get("scene_index",-1)) == scene_index and int(x.get("sentence_index",-1)) == sentence_index)]
        data["problem_fragments"] = pfr
        data["parents_guide"] = _recompute_parents_guide(pfr, int(data.get("scenes_total",0)))
        return _save_output(ws, data)

    pf["labels"] = sorted({item["label"] for item in norm_labels})
    ev_new: Dict[str, Dict[str, Any]] = {}
    for item in norm_labels:
        ev_new[item["label"]] = {
            "severity": item["local_severity"],
            "score": None,
            "reason": item["reason"],
            "advice": item["advice"],
            "trigger": None
        }
    pf["evidence_spans"] = ev_new
    pf["severity_local"] = _derive_fragment_severity_from_evidence(ev_new)

    data["problem_fragments"] = pfr
    data["parents_guide"] = _recompute_parents_guide(pfr, int(data.get("scenes_total",0)))
    return _save_output(ws, data)


def cancel_violation(ws: str, scene_index: int, sentence_index: int) -> Dict[str, Any]:
    data = _load_output(ws)
    pfr = list(data.get("problem_fragments", []))
    pfr = [pf for pf in pfr if not (int(pf.get("scene_index",-1)) == scene_index and int(pf.get("sentence_index",-1)) == sentence_index)]
    data["problem_fragments"] = pfr
    data["parents_guide"] = _recompute_parents_guide(pfr, int(data.get("scenes_total",0)))
    return _save_output(ws, data)


def update_violation_sentence(
    ws: str,
    scene_index: int,
    sentence_index: int,
    new_text: str
) -> Dict[str, Any]:
    data = _load_output(ws)
    pfr = list(data.get("problem_fragments", []))
    pf = _find_fragment(pfr, scene_index, sentence_index)
    if pf is None:
        raise ValueError("Violation not found for given scene_index & sentence_index")
    pf["text"] = new_text
    pf["severity_local"] = _derive_fragment_severity_from_evidence(pf.get("evidence_spans", {}) or {})
    data["problem_fragments"] = pfr
    data["parents_guide"] = _recompute_parents_guide(pfr, int(data.get("scenes_total",0)))
    return _save_output(ws, data)