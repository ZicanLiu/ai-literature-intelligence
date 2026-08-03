"""
W2 疑似重复人工审核 CLI 工具。

读取 data/review/suspected_duplicates_w2.csv，允许用户逐条审核：
  - 标记为 confirmed（确认重复）/ distinct（不是重复）/ unreadable（无法判断）
  - 添加 reviewer_note

不修改原始 CSV 以外的任何文件。
"""

import argparse
import csv
import os
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from src.deduplication import find_exact_duplicates, find_suspected_duplicates

DEFAULT_REVIEW_FILE = PROJECT_ROOT / "data" / "review" / "suspected_duplicates_w2.csv"
DEFAULT_COMBINED_CSV = PROJECT_ROOT / "data" / "samples" / "w2" / "dedup" / "combined_w2_raw.csv"
ANALYSIS_DIR = PROJECT_ROOT / "data" / "analysis" / "w2_dedup"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="W2 疑似重复人工审核 CLI")
    parser.add_argument(
        "--review-file",
        default=str(DEFAULT_REVIEW_FILE),
        help="疑似重复 CSV 文件路径",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="仅列出所有 pending 的疑似重复对，不进入交互模式",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="从 combined_w2_raw.csv 重新生成全部去重结果",
    )
    parser.add_argument(
        "--combined-csv",
        default=str(DEFAULT_COMBINED_CSV),
        help="合并原始数据 CSV 路径（与 --generate 配合使用）",
    )
    return parser.parse_args()


def load_review_file(path: str) -> list[dict]:
    if not os.path.exists(path):
        print(f"错误：找不到审核文件 {path}")
        sys.exit(1)
    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def save_review_file(rows: list[dict], path: str) -> None:
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def show_pair(record: dict, index: int) -> None:
    print(f"\n{'=' * 70}")
    print(f"  Pair #{index + 1}  |  {record.get('pair_id', 'N/A')}")
    print(f"{'=' * 70}")
    print(f"  Left  [{record.get('left_id', 'N/A')}]:")
    print(f"    {record.get('left_title', '')}")
    print(f"  Right [{record.get('right_id', 'N/A')}]:")
    print(f"    {record.get('right_title', '')}")
    print(f"  ---")
    print(f"  相似度: {record.get('title_similarity', '')}")
    print(f"  作者重合: {record.get('author_overlap', '')}")
    print(f"  年份差: {record.get('year_difference', '')}")
    print(f"  DOI关系: {record.get('doi_relation', '')}")
    print(f"  原因: {record.get('suspected_reason', '')}")
    if record.get("reviewer_note", ""):
        print(f"  已有备注: {record['reviewer_note']}")


def show_stats(rows: list[dict]) -> None:
    total = len(rows)
    status_counts = {}
    for row in rows:
        s = row.get("review_status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1
    print(f"\n审核统计（共 {total} 对）")
    print("-" * 40)
    for status, count in sorted(status_counts.items()):
        bar = "#" * min(count, 40)
        print(f"  {status:<12} {count:>3}  {bar}")
    confirmed = status_counts.get("confirmed", 0)
    distinct = status_counts.get("distinct", 0)
    if confirmed > 0:
        print(f"\n  可直接合并: {confirmed} 对")
    if distinct > 0:
        print(f"  确认为不同: {distinct} 对")


def generate_results(combined_path: str) -> int:
    """从 combined CSV 重新生成全部去重结果。"""
    if not os.path.exists(combined_path):
        print(f"错误：找不到合并数据文件 {combined_path}")
        return 1

    with open(combined_path, "r", encoding="utf-8-sig") as f:
        papers = list(csv.DictReader(f))

    raw_count = len(papers)
    print(f"加载论文: {raw_count} 条")

    exact_result = find_exact_duplicates(papers)
    kept = exact_result["kept_papers"]
    exact_dups = exact_result["exact_duplicates"]
    print(f"确定重复: {len(exact_dups)} 条")
    print(f"  same_openalex_id: {exact_result['stats']['same_openalex_id']}")
    print(f"  same_doi: {exact_result['stats']['same_doi']}")
    print(f"  same_title_no_id: {exact_result['stats']['same_title_no_id']}")

    suspected_result = find_suspected_duplicates(kept)
    suspected = suspected_result["suspected_duplicates"]
    print(f"疑似重复: {len(suspected)} 对")

    if raw_count != len(kept) + len(exact_dups):
        print(f"警告：数量不匹配！原始{raw_count} ≠ 保留{len(kept)} + 确定重复{len(exact_dups)}")
    else:
        print(f"数量验证通过: {raw_count} = {len(kept)} + {len(exact_dups)}")

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    Path(DEFAULT_REVIEW_FILE).parent.mkdir(parents=True, exist_ok=True)

    if exact_dups:
        exact_path = ANALYSIS_DIR / "exact_duplicates_w2.csv"
        with open(exact_path, "w", encoding="utf-8", newline="") as fout:
            w = csv.DictWriter(fout, fieldnames=list(exact_dups[0].keys()))
            w.writeheader()
            w.writerows(exact_dups)
        print(f"  精确重复: {exact_path}")

    if suspected:
        suspected_fields = [
            "pair_id", "left_id", "right_id", "left_title", "right_title",
            "title_similarity", "author_overlap", "year_difference", "doi_relation",
            "suspected_reason", "recommended_action", "review_status", "reviewer_note",
            "left_keyword", "right_keyword", "left_run_id", "right_run_id", "created_at",
        ]
        suspected_path = Path(DEFAULT_REVIEW_FILE)
        with open(suspected_path, "w", encoding="utf-8", newline="") as fout:
            w = csv.DictWriter(fout, fieldnames=suspected_fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(suspected)
        print(f"  疑似重复: {suspected_path} ({len(suspected)} 对)")

    kept_path = ANALYSIS_DIR / "deduplicated_papers_w2.csv"
    if kept:
        kept_fields = [k for k in kept[0].keys() if not k.startswith("_")]
        with open(kept_path, "w", encoding="utf-8", newline="") as fout:
            w = csv.DictWriter(fout, fieldnames=kept_fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(kept)
        print(f"  去重保留: {kept_path} ({len(kept)} 条)")

    reason_counter = Counter()
    for s in suspected:
        reason_counter[s["suspected_reason"]] += 1

    summary_rows = [
        {"metric": "total_raw_papers", "value": raw_count},
        {"metric": "total_kept_papers", "value": len(kept)},
        {"metric": "exact_duplicate_count", "value": len(exact_dups)},
        {"metric": "exact_same_openalex_id", "value": exact_result["stats"]["same_openalex_id"]},
        {"metric": "exact_same_doi", "value": exact_result["stats"]["same_doi"]},
        {"metric": "exact_same_title_no_id", "value": exact_result["stats"]["same_title_no_id"]},
        {"metric": "suspected_pair_count", "value": len(suspected)},
    ]
    for reason, count in reason_counter.most_common():
        summary_rows.append({"metric": f"reason_{reason}", "value": count})

    summary_path = ANALYSIS_DIR / "dedup_summary_w2.csv"
    with open(summary_path, "w", encoding="utf-8", newline="") as fout:
        w = csv.DictWriter(fout, fieldnames=["metric", "value"])
        w.writeheader()
        w.writerows(summary_rows)
    print(f"  汇总: {summary_path}")

    run_id_counts = Counter(p.get("run_id", "") for p in papers)
    print(f"\n来源分布:")
    for rid, cnt in run_id_counts.items():
        print(f"  {rid}: {cnt}")

    return 0


def interactive_review(rows: list[dict], path: str) -> None:
    pending_indices = [i for i, r in enumerate(rows) if r.get("review_status") == "pending"]
    if not pending_indices:
        print("没有待审核的疑似重复对。")
        return

    total = len(pending_indices)
    print(f"共 {total} 对待审核。")
    reviewed = 0

    for i in pending_indices:
        show_pair(rows[i], i)
        print()
        while True:
            choice = input("操作 [y=确认重复 / n=不是重复 / s=跳过 / q=退出]: ").strip().lower()
            if choice == "y":
                rows[i]["review_status"] = "confirmed"
                rows[i]["recommended_action"] = "merge"
                note = input("  备注（可选）: ").strip()
                if note:
                    rows[i]["reviewer_note"] = note
                reviewed += 1
                save_review_file(rows, path)
                print("  -> 已标记为 confirmed")
                break
            elif choice == "n":
                rows[i]["review_status"] = "distinct"
                rows[i]["recommended_action"] = "keep_separate"
                note = input("  备注（可选）: ").strip()
                if note:
                    rows[i]["reviewer_note"] = note
                reviewed += 1
                save_review_file(rows, path)
                print("  -> 已标记为 distinct")
                break
            elif choice == "s":
                print("  -> 跳过")
                break
            elif choice == "q":
                print(f"\n已审核 {reviewed} 对，剩余 {total - reviewed} 对。")
                return
            else:
                print("  无效输入，请输入 y/n/s/q")

    print(f"\n审核完成！共审核 {reviewed}/{total} 对。")


def main() -> int:
    args = parse_args()

    if args.generate:
        return generate_results(args.combined_csv)

    rows = load_review_file(args.review_file)

    if args.stats:
        show_stats(rows)
        return 0

    if args.list:
        pending = [r for r in rows if r.get("review_status") == "pending"]
        if not pending:
            print("没有待审核的疑似重复对。")
            return 0
        for i, record in enumerate(rows):
            if record.get("review_status") == "pending":
                show_pair(record, i)
        print(f"\n共 {len(pending)} 对待审核。")
        return 0

    interactive_review(rows, args.review_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
