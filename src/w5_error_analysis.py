import csv
from pathlib import Path

ROOT = Path(__file__).parent.parent
INPUT_CSV = ROOT / "data" / "annotation_tasks" / "w4" / "annotations" / "chenxingyu.csv"
OUTPUT_CSV = ROOT / "data" / "w5_error_cases.csv"

error_records = []

with open(INPUT_CSV, "r", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for row in reader:
        label = row.get("label", "")
        note = row.get("note", "")

        if label in ["0", "1"]:
            rec = {
                "pair_id": row["pair_id"],
                "research_query_id": row["research_query_id"],
                "research_question_zh": row["research_question_zh"],
                "title": row["title"],
                "openalex_id": row["openalex_id"],
                "label": label,
                "note": note,
                "error_type": ""
            }
            error_records.append(rec)

fieldnames = ["pair_id","research_query_id","research_question_zh","title","openalex_id","label","note","error_type"]
with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as fw:
    writer = csv.DictWriter(fw, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(error_records)

print(f"导出错误案例数量：{len(error_records)}")
print(f"文件输出到 {OUTPUT_CSV.resolve()}")
