import json
import csv
from pathlib import Path
from typing import Dict, List, Any

FIXTURE_ROOT = Path("tests/fixtures/w6_bootstrap/valid")
SOURCE_RECORDS_PATH = FIXTURE_ROOT / "source_records.json"
RETRIEVAL_RUNS_PATH = FIXTURE_ROOT / "retrieval_runs.json"
OUTPUT_DIR = Path("output/w6_diagnostics")

META_FIELDS = ["abstract", "doi", "openalex_id", "year", "venue", "authors", "landing_page", "provider"]


def load_source_records() -> List[Dict[str, Any]]:
    with open(SOURCE_RECORDS_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        data = raw
    elif isinstance(raw, dict):
        data = list(raw.values())
    else:
        data = []
    return [x for x in data if isinstance(x, dict)]


def load_retrieval_runs() -> List[Dict[str, Any]]:
    with open(RETRIEVAL_RUNS_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        data = raw
    elif isinstance(raw, dict):
        data = list(raw.values())
    else:
        data = []
    return [x for x in data if isinstance(x, dict)]


def metadata_completeness_analysis(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(records)
    field_stats = {}
    missing_distribution = {}
    for field in META_FIELDS:
        present = 0
        for rec in records:
            val = rec.get(field)
            if val is not None and val != "":
                present += 1
        absent = total - present
        field_stats[field] = {"total": total, "present": present, "missing": absent}
        missing_distribution[field] = absent
    return {
        "record_count": total,
        "field_statistics": field_stats,
        "missing_field_distribution": missing_distribution
    }


def retrieval_query_diagnostics(retrieval_runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    variant_stats = []
    all_hit_ids = set()
    per_variant_hit_sets = {}

    for run in retrieval_runs:
        variant_id = run.get("query_variant_id", "unknown")
        hit_records = run.get("hit_records", [])
        hit_ids = set()
        for h in hit_records:
            if isinstance(h, dict) and "source_record_id" in h:
                hit_ids.add(h["source_record_id"])
        success = run.get("success", False)
        variant_stats.append({
            "query_variant_id": variant_id,
            "hit_count": len(hit_ids),
            "retrieval_success": success
        })
        per_variant_hit_sets[variant_id] = hit_ids
        all_hit_ids.update(hit_ids)

    record_to_variants = {}
    for vid, hid_set in per_variant_hit_sets.items():
        for rid in hid_set:
            record_to_variants.setdefault(rid, []).append(vid)
    multi_query_hit = set()
    single_query_only = set()
    for rid, v_list in record_to_variants.items():
        if len(v_list) > 1:
            multi_query_hit.add(rid)
        else:
            single_query_only.add(rid)

    return {
        "variant_statistics": variant_stats,
        "unique_hit_record_count": len(all_hit_ids),
        "multi_query_intersection_count": len(multi_query_hit),
        "only_single_query_hit_count": len(single_query_only)
    }


def write_meta_report_csv(analysis_result: Dict[str, Any], out_path: Path):
    rows = []
    for field, stat in analysis_result["field_statistics"].items():
        rows.append({"field": field, "total": stat["total"], "present": stat["present"], "missing": stat["missing"]})
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["field", "total", "present", "missing"])
        writer.writeheader()
        writer.writerows(rows)


def main():
    records = load_source_records()
    runs = load_retrieval_runs()
    meta_report = metadata_completeness_analysis(records)
    diag_report = retrieval_query_diagnostics(runs)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_meta_report_csv(meta_report, OUTPUT_DIR / "metadata_completeness.csv")

    with open(OUTPUT_DIR / "retrieval_diagnostics.json", "w", encoding="utf-8") as f:
        json.dump(diag_report, f, indent=2, ensure_ascii=False)

    print(json.dumps(meta_report, indent=2, ensure_ascii=False))
    print(json.dumps(diag_report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
