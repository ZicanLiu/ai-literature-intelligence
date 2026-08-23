import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
ERROR_CASES_PATH = ROOT / "data" / "w5_error_cases.csv"
RANKING_PATHS = {
    "sparse": ROOT / "data" / "w5_ranking_sparse.csv",
    "dense": ROOT / "data" / "w5_ranking_dense.csv",
    "hybrid": ROOT / "data" / "w5_ranking_hybrid.csv"
}
MATRIX_OUTPUT_PATH = ROOT / "data" / "w5_error_method_matrix.csv"
ERROR_TYPES = ["hard_negative", "topic_drift", "term_ambiguity", "unclassified"]
TOP_K = [5, 10]


def load_error_cases() -> dict:
    error_map = {}
    with open(ERROR_CASES_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            oa_id = row["openalex_id"]
            error_type = row["error_type"].strip()
            if not error_type or error_type not in ERROR_TYPES:
                error_type = "unclassified"
            error_map[oa_id] = {
                "pair_id": row["pair_id"],
                "research_query_id": row["research_query_id"],
                "error_type": error_type
            }
    return error_map


def load_ranking(ranking_path: Path) -> dict:
    ranking_map = {}
    if not ranking_path.exists():
        return ranking_map
    with open(ranking_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for rank, row in enumerate(reader, 1):
            oa_id = row["openalex_id"]
            ranking_map[oa_id] = rank
    return ranking_map


def build_error_method_matrix(error_map: dict, ranking_dict: dict):
    matrix = []
    header = ["error_type", "total_count"]
    for method_name in ranking_dict.keys():
        header.append(f"{method_name}_total")
        for k in TOP_K:
            header.append(f"{method_name}_top{k}")
            header.append(f"{method_name}_irrelevant_in_top{k}")

    for error_type in ERROR_TYPES:
        row = {"error_type": error_type}
        type_total = sum(1 for v in error_map.values() if v["error_type"] == error_type)
        row["total_count"] = type_total
        for method_name, ranking_map in ranking_dict.items():
            method_total = 0
            top_k_stats = {k: {"hit":0,"irrelevant":0} for k in TOP_K}
            for oa_id, info in error_map.items():
                if info["error_type"] != error_type:
                    continue
                if oa_id in ranking_map:
                    method_total +=1
                    r = ranking_map[oa_id]
                    for k in TOP_K:
                        if r <= k:
                            top_k_stats[k]["hit"] +=1
                            top_k_stats[k]["irrelevant"] +=1
            row[f"{method_name}_total"] = method_total
            for k in TOP_K:
                row[f"{method_name}_top{k}"] = top_k_stats[k]["hit"]
                row[f"{method_name}_irrelevant_in_top{k}"] = top_k_stats[k]["irrelevant"]
        matrix.append(row)
    return matrix, header


def build_query_error_matrix(error_map: dict):
    queries = sorted({v["research_query_id"] for v in error_map.values()})
    header = ["research_query_id"] + ERROR_TYPES + ["total"]
    matrix = []
    for q in queries:
        row = {"research_query_id": q}
        total = 0
        for et in ERROR_TYPES:
            cnt = sum(1 for v in error_map.values() if v["research_query_id"]==q and v["error_type"]==et)
            row[et] = cnt
            total += cnt
        row["total"] = total
        matrix.append(row)
    return matrix, header


def print_md_table(matrix, header):
    print("|"+"|".join(header)+"|")
    print("|"+"|".join(["---"]*len(header))+"|")
    for r in matrix:
        print("|"+"|".join(str(r[h]) for h in header)+"|")


def save_csv(matrix, header, outpath):
    with open(outpath,"w",newline="",encoding="utf-8-sig") as fw:
        w = csv.DictWriter(fw, fieldnames=header)
        w.writeheader()
        w.writerows(matrix)


def main():
    err_map = load_error_cases()
    print(f"导出错误案例数量：{len(err_map)}")
    rank_dict = {m:load_ranking(p) for m,p in RANKING_PATHS.items()}

    q_mat,q_head = build_query_error_matrix(err_map)
    print("\n=== 查询 × 错误类型 ===")
    print_md_table(q_mat,q_head)

    m_mat,m_head = build_error_method_matrix(err_map, rank_dict)
    print("\n=== 错误类型 × 方法 ===")
    print_md_table(m_mat,m_head)
    save_csv(m_mat,m_head, MATRIX_OUTPUT_PATH)
    print(f"\n文件输出到 {MATRIX_OUTPUT_PATH.resolve()}")


if __name__ == "__main__":
    main()
