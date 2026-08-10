"""Issue #21 批量实验命令行入口。"""

from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

from src.batch_runner import batch_contains_live, load_batch_definition, run_batch
from src.run_context import safe_error_summary


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="读取 batch config，多次调用同一个 W2 unified pipeline API。"
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "experiments",
        help="各 parent run 的输出根目录。",
    )
    parser.add_argument(
        "--batch-output-root",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "batches",
        help="batch 摘要根目录。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        definition = load_batch_definition(args.config)
        if batch_contains_live(definition):
            load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
        result = run_batch(
            args.config,
            project_root=PROJECT_ROOT,
            pipeline_output_root=args.output_root,
            batch_output_root=args.batch_output_root,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(
            "Batch 运行失败："
            + safe_error_summary(error, PROJECT_ROOT, args.batch_output_root)
        )
        return 1

    try:
        display_dir = result.batch_dir.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        display_dir = result.batch_dir.name
    summary = result.summary
    print(f"Batch 完成：{result.batch_id}")
    print(f"摘要目录：{display_dir}")
    print(
        f"items={summary['item_count']}，success={summary['success_count']}，"
        f"failed={summary['failure_count']}，skipped={summary['skipped_count']}，"
        f"not_run={summary['not_run_count']}"
    )
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
