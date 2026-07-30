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
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REVIEW_FILE = PROJECT_ROOT / "data" / "review" / "suspected_duplicates_w2.csv"


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
        "--stats",
        action="store_true",
        help="显示审核统计信息",
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
