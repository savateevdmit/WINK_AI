#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Report data builder: готовит расширенный контекст из output.json и parsed_scenes.json
для рендеринга HTML-отчёта с полной статистикой по нарушениям.

Новые требования:
- Полный список нарушений (problem_fragments) с причинами и советами.
- Подсчёт общего количества нарушений.
- Часто встречающиеся нарушения (по label).
- Статистика по severity (Mild/Moderate/Severe).
- Хронологическая визуализация по сценам.
"""

from __future__ import annotations
import datetime as dt
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..storage import load_json_if_exists, load_parsed_scenes


def _load_output(ws: str) -> Dict[str, Any]:
    p = Path(ws)
    model_out = p / "model" / "output.json"
    stages_out = p / "stages" / "output_final.json"
    data = load_json_if_exists(str(model_out)) or load_json_if_exists(str(stages_out))
    if not isinstance(data, dict):
        raise FileNotFoundError("output.json not found (model/output.json or stages/stages_out.json)")
    data.setdefault("parents_guide", {})
    data.setdefault("problem_fragments", [])
    data.setdefault("scenes_total", 0)
    return data


def _mk_key_scenes(problem_fragments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def sev_rank(s: str) -> int:
        m = (s or "None").lower()
        return 3 if m == "severe" else 2 if m == "moderate" else 1 if m == "mild" else 0

    enriched = []
    for pf in problem_fragments:
        sev = sev_rank(pf.get("fragment_severity") or pf.get("severity_local", "None"))
        max_score = 0
        reason = ""
        advice = ""
        ev = pf.get("evidence_spans") or {}
        for span in ev.values():
            sc = span.get("score")
            if isinstance(sc, (int, float)):
                max_score = max(max_score, int(sc))
            if not reason and isinstance(span.get("reason"), str):
                reason = span["reason"]
            if not advice and isinstance(span.get("advice"), str):
                advice = span["advice"]
        enriched.append(
            (
                sev,
                max_score,
                int(pf.get("scene_index", 0)),
                {
                    "scene_index": pf.get("scene_index"),
                    "page": pf.get("page"),
                    "heading": pf.get("scene_heading", ""),
                    "sentence_index": pf.get("sentence_index"),
                    "text": pf.get("text", ""),
                    "labels": pf.get("labels", []),
                    "severity_local": pf.get("severity_local", "None"),
                    "fragment_severity": pf.get("fragment_severity", pf.get("severity_local", "None")),
                    "reason": reason,
                    "advice": advice,
                },
            )
        )
    enriched.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return [e[3] for e in enriched[:15]]


def _timeline_points(problem_fragments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def sev_val(s: str) -> int:
        m = (s or "None").lower()
        return 3 if m == "severe" else 2 if m == "moderate" else 1 if m == "mild" else 0

    pts = []
    for pf in problem_fragments:
        pts.append(
            {
                "x": int(pf.get("scene_index", 0)),
                "y": sev_val(pf.get("fragment_severity") or pf.get("severity_local", "None")),
                "labels": pf.get("labels", []),
                "sentence_index": pf.get("sentence_index"),
            }
        )
    pts.sort(key=lambda d: (d["x"], d["sentence_index"]))
    return pts


def _parents_guide_table(pg: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for group, info in pg.items():
        if not isinstance(info, dict):
            continue
        rows.append(
            {
                "group": group,
                "severity": info.get("severity", "None"),
                "episodes": info.get("episodes", 0),
                "scenes_percent": info.get("scenes_with_issues_percent", 0.0),
            }
        )
    rows.sort(key=lambda r: (-int(r["episodes"]), r["group"]))
    return rows


def _violation_stats(problem_fragments: List[Dict[str, Any]]) -> Dict[str, Any]:
    label_counter = Counter()
    severity_counter = Counter()
    group_by_label: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for pf in problem_fragments:
        sev = pf.get("fragment_severity") or pf.get("severity_local") or "None"
        severity_counter[sev] += 1
        for lab in pf.get("labels") or []:
            label_counter[lab] += 1
            group_by_label[lab].append(
                {
                    "scene_index": pf.get("scene_index"),
                    "sentence_index": pf.get("sentence_index"),
                    "text": pf.get("text", ""),
                    "severity": sev,
                }
            )

    top_labels = [
        {"label": lab, "count": cnt}
        for lab, cnt in label_counter.most_common(10)
    ]

    severity_counts = [
        {"level": "None", "count": severity_counter.get("None", 0)},
        {"level": "Mild", "count": severity_counter.get("Mild", 0)},
        {"level": "Moderate", "count": severity_counter.get("Moderate", 0)},
        {"level": "Severe", "count": severity_counter.get("Severe", 0)},
    ]

    return {
        "total_fragments": len(problem_fragments),
        "label_counter": label_counter,
        "severity_counter": severity_counter,
        "top_labels": top_labels,
        "severity_counts": severity_counts,
        "group_by_label": group_by_label,
    }


def _flatten_violations(problem_fragments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Разворачиваем evidence_spans в детализированный список нарушений."""
    rows: List[Dict[str, Any]] = []
    for pf in problem_fragments:
        ev = pf.get("evidence_spans") or {}
        for lab, span in ev.items():
            rows.append(
                {
                    "scene_index": pf.get("scene_index"),
                    "page": pf.get("page"),
                    "heading": pf.get("scene_heading", ""),
                    "sentence_index": pf.get("sentence_index"),
                    "text": pf.get("text", ""),
                    "label": lab,
                    "severity": span.get("severity", pf.get("fragment_severity") or pf.get("severity_local", "None")),
                    "score": span.get("score"),
                    "reason": span.get("reason", ""),
                    "advice": span.get("advice", ""),
                }
            )
    rows.sort(key=lambda r: (int(r["scene_index"] or 0), int(r["sentence_index"] or 0), r["label"]))
    return rows


def build_report_context(ws: str) -> Dict[str, Any]:
    out = _load_output(ws)
    parsed = load_parsed_scenes(ws)  # может понадобиться фронту
    now = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    pfr: List[Dict[str, Any]] = out.get("problem_fragments", [])
    parents_table = _parents_guide_table(out.get("parents_guide", {}))
    timeline = _timeline_points(pfr)
    key_scenes = _mk_key_scenes(pfr)
    stats = _violation_stats(pfr)
    flat_violations = _flatten_violations(pfr)

    # Часто встречающиеся нарушения с примерами (максимум по 3 примера на label)
    frequent_labels_detail: List[Dict[str, Any]] = []
    for lab, cnt in stats["label_counter"].most_common(8):
        examples = stats["group_by_label"][lab][:3]
        frequent_labels_detail.append(
            {
                "label": lab,
                "count": cnt,
                "examples": examples,
            }
        )

    context: Dict[str, Any] = {
        "generated_at": now,
        "document": out.get("document") or "output.json",
        "final_rating": out.get("final_rating", "0+"),
        "model_final_rating": out.get("model_final_rating"),
        "scenes_total": int(out.get("scenes_total", 0)),
        "parents_guide": out.get("parents_guide", {}),
        "parents_table": parents_table,
        "timeline": timeline,
        "key_scenes": key_scenes,
        "problem_fragments": pfr,
        "flat_violations": flat_violations,
        "total_fragments": stats["total_fragments"],
        "top_labels": stats["top_labels"],
        "severity_counts": stats["severity_counts"],
        "frequent_labels_detail": frequent_labels_detail,
        "parsed_scenes": parsed or [],
        "front_css_path": None,
    }

    # Возможность использовать CSS фронта (например, один из ваших стилей)
    static_css = Path(ws).parent / "static" / "report.css"
    if static_css.is_file():
        context["front_css_path"] = f"/static/report.css"

    return context
