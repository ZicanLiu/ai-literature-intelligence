import csv
from pathlib import Path
from collections import Counter

BASE = Path(__file__).parent.parent

# W4原始冻结输入文件
W4_INPUT = BASE / "data/analysis/w4_query_boundary_examples.csv"
# W5输出目录
W5_OUT = BASE / "data/analysis/w5_error_taxonomy"
W5_OUT.mkdir(exist_ok=True)

MAPPING_CSV = W5_OUT / "w5_taxonomy_mapping.csv"
COVERAGE_CSV = W5_OUT / "w5_class_coverage.csv"
MATRIX_TEMPLATE = W5_OUT / "w5_error_type_matrix_template.csv"

# 1. 生成机器可读mapping
records = []
with open(W4_INPUT, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        item = {
            "pair_id": row.get("pair_id", ""),
            "research_query_id": row.get("research_query_id", ""),
            "error_boundary_category": row.get("error_boundary_category", "unclassified"),
            "source": "w4_query_boundary_analysis",
            "short_definition": row.get("short_definition", "")
        }
        records.append(item)

fields = ["pair_id","research_query_id","error_boundary_category","source","short_definition"]
with open(MAPPING_CSV, "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(records)
print(f"✅机器可读映射表：{MAPPING_CSV}，共{len(records)}条")

# 2. 统计分类覆盖率
cat_counter = Counter(r["error_boundary_category"] for r in records)
total = len(records)
coverage_rows = []
for cat, cnt in cat_counter.items():
    coverage_rows.append({
        "error_category": cat,
        "count": cnt,
        "total_pairs": total,
        "ratio": round(cnt / total, 4)
    })

with open(COVERAGE_CSV, "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["error_category","count","total_pairs","ratio"])
    w.writeheader()
    w.writerows(coverage_rows)
print(f"✅分类覆盖率：{COVERAGE_CSV}")

# 3. 生成矩阵空模板（等待ranking输入）
matrix_fields = ["method","error_type","n_pairs","top5_count","top10_count","irrelevant_top5","irrelevant_top10"]
with open(MATRIX_TEMPLATE, "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=matrix_fields)
    w.writeheader()
print(f"✅矩阵模板（待填入ranking结果）：{MATRIX_TEMPLATE}")

print("\n=== W5工具基础部分完成 ===")
print("后续：拿到W5 ranking artifact后，再填充矩阵、做Top‑K错误案例识别")
