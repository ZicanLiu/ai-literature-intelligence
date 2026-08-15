import argparse
from pathlib import Path
from src.annotation_agreement import AgreementAnalyzer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "annotation_tasks" / "w4"

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="分析 W4 双重标注的一致性与分歧"
    )
    parser.add_argument(
        "--assignments",
        type=Path,
        default=DEFAULT_DATA_DIR / "assignments_v0.1.csv",
        help="任务分配文件路径"
    )
    parser.add_argument(
        "--annotations-dir",
        type=Path,
        default=DEFAULT_DATA_DIR / "annotations",
        help="所有成员标注结果所在的目录"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "analysis" / "w4_annotation_agreement",
        help="分析结果输出目录"
    )
    return parser.parse_args(argv)

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    
    analyzer = AgreementAnalyzer(
        assignments_path=str(args.assignments),
        annotations_dir=str(args.annotations_dir)
    )
    
    print("⏳ 正在分析标注一致性...")
    analyzer.analyze(output_dir=str(args.output_dir))
    print(f"✅ 分析完成！报告已保存至 {args.output_dir}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())