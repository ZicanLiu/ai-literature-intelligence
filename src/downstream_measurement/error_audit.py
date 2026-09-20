"""Phase K: error event audit.

Verifies event identity/linkage/distinctness mechanically and audits the
boundary_misuse counting semantics: the original first-look supporting table
counted events whose error_types CONTAIN the generic tag
`task_boundary_misuse`; finer subtypes (wrong object / wrong modality /
wrong task / wrong method role) may exist in the same tag lists without being
reported separately. We census the full vocabulary and report both the generic
count and the finer breakdown without changing any frozen result.
"""
from __future__ import annotations

from collections import Counter

GENERIC_BOUNDARY_TAG = "task_boundary_misuse"
BOUNDARY_SUBTYPE_HINTS = ("wrong_object", "wrong_modality", "wrong_task", "wrong_method",
                          "wrong_target", "object", "modality", "method_role")


def build_error_audit(registry: dict) -> dict:
    events = registry["error_events"]
    vocabulary = Counter()
    for event in events:
        for tag in event["error_types"]:
            vocabulary[tag] += 1
    generic_events = [e for e in events if GENERIC_BOUNDARY_TAG in e["error_types"]]
    subtype_tags = {tag: count for tag, count in vocabulary.items()
                    if tag != GENERIC_BOUNDARY_TAG and any(hint in tag for hint in BOUNDARY_SUBTYPE_HINTS)}
    finer_only = [e for e in events
                  if GENERIC_BOUNDARY_TAG not in e["error_types"]
                  and any(any(hint in tag for hint in BOUNDARY_SUBTYPE_HINTS) for tag in e["error_types"])]
    by_evaluator_arm = Counter()
    for event in events:
        by_evaluator_arm[(event["evaluator"], event["arm"])] += 1
    duplicate_ids = []
    seen: dict[tuple, list[str]] = {}
    for event in events:
        seen.setdefault((event["evaluator"], event["output_id"]), []).append(event["error_id"])
    for (evaluator, oid), ids in sorted(seen.items()):
        counter = Counter(ids)
        dups = {k: v for k, v in counter.items() if v > 1}
        if dups:
            duplicate_ids.append({"evaluator": evaluator, "output_id": oid, "duplicates": dups})
    affected_boundary = Counter()
    for event in generic_events + finer_only:
        for index in event["affected_appearance_indices"]:
            affected_boundary[(event["evaluator"], event["arm"], index)] += 1
    return {
        "schema_version": "1.0",
        "status": "MECHANICAL EVENT AUDIT; original frozen first-look results are not modified",
        "event_vocabulary": dict(sorted(vocabulary.items(), key=lambda kv: -kv[1])),
        "counts": {
            "total_event_records": len(events),
            "events_with_generic_boundary_tag": len(generic_events),
            "subtype_tags_outside_generic": subtype_tags,
            "events_with_subtype_tag_but_without_generic": len(finer_only),
            "duplicate_event_ids": duplicate_ids,
        },
        "generic_boundary_counting_semantics": {
            "original_first_look_rule": "count events whose error_types contains 'task_boundary_misuse'",
            "gap_assessment": ("finer boundary subtypes exist in tag lists but the generic counter does not "
                               "separate them" if subtype_tags or finer_only else
                               "no finer boundary subtype tags observed beyond the generic tag"),
            "current_first_look_affected": False,
        },
        "events_by_evaluator_arm": {f"{ev}|{arm}": count for (ev, arm), count in sorted(by_evaluator_arm.items())},
        "boundary_affected_slots": {f"{ev}|{arm}|slot{i}": c for (ev, arm, i), c in sorted(affected_boundary.items())},
        "event_records": [
            {"evaluator": e["evaluator"], "role": e["role"], "output_id": e["output_id"],
             "arm": e["arm"], "topic_id": e["topic_id"], "task_id": e["task_id"],
             "error_id": e["error_id"], "error_types": e["error_types"],
             "affected_appearance_indices": e["affected_appearance_indices"]}
            for e in events
        ],
    }
