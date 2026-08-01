"""
app/quality_gate.py
质量门禁控制模块：判断本次获取的数据流是否达到质量红线阈值。
"""

from typing import Any, Dict, List
from src.validation import validate_paper_list


# 默认质量门禁规则阈值
DEFAULT_GATE_CONFIG = {
    "min_total_papers": 1,          # 至少获取到 1 条论文
    "max_invalid_ratio": 0.20,      # 不合法论文比例不超过 20%
    "min_avg_completeness": 0.50,   # 平均字段完整度不低于 50%
}


def evaluate_quality_gate(
    papers: List[Dict[str, Any]],
    config: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    评估论文数据集是否能通过质量门禁。

    参数:
        papers: 原始/预处理后的论文列表。
        config: 门禁配置参数（可覆盖默认阈值）。
    返回:
        包含 passed(bool)、闸门检查详情与失败原因的分析字典。
    """
    gate_config = DEFAULT_GATE_CONFIG.copy()
    if config:
        gate_config.update(config)

    # 调用 validation 模块获取基准校验数据
    stats = validate_paper_list(papers)
    total_count = stats["total_count"]
    
    checks = []
    failure_reasons = []

    # 检查 1：总论文数阈值
    passed_count_check = total_count >= gate_config["min_total_papers"]
    checks.append({
        "check_name": "min_total_papers",
        "target": f">= {gate_config['min_total_papers']}",
        "actual": total_count,
        "passed": passed_count_check,
    })
    if not passed_count_check:
        failure_reasons.append(
            f"数据量不足: 实际 {total_count} 条，最小期望 {gate_config['min_total_papers']} 条。"
        )

    # 检查 2：无效论文比例红线
    invalid_ratio = (stats["invalid_count"] / total_count) if total_count > 0 else 1.0
    passed_invalid_check = invalid_ratio <= gate_config["max_invalid_ratio"]
    checks.append({
        "check_name": "max_invalid_ratio",
        "target": f"<= {gate_config['max_invalid_ratio']:.0%}",
        "actual": f"{invalid_ratio:.2%}",
        "passed": passed_invalid_check,
    })
    if not passed_invalid_check:
        failure_reasons.append(
            f"异常数据过多: 包含 {invalid_ratio:.2%} 的无效论文（最高容忍 {gate_config['max_invalid_ratio']:.0%}）。"
        )

    # 检查 3：数据平均完整度红线
    avg_completeness = stats["average_completeness"]
    passed_completeness_check = avg_completeness >= gate_config["min_avg_completeness"]
    checks.append({
        "check_name": "min_avg_completeness",
        "target": f">= {gate_config['min_avg_completeness']:.0%}",
        "actual": f"{avg_completeness:.2%}",
        "passed": passed_completeness_check,
    })
    if not passed_completeness_check:
        failure_reasons.append(
            f"平均字段完整度过低: 实际 {avg_completeness:.2%}（要求最低 {gate_config['min_avg_completeness']:.0%}）。"
        )

    gate_passed = len(failure_reasons) == 0

    return {
        "passed": gate_passed,
        "summary": {
            "total_papers": total_count,
            "valid_papers": stats["valid_count"],
            "invalid_papers": stats["invalid_count"],
            "average_completeness": avg_completeness,
            "field_missing_counts": stats["field_missing_counts"],
        },
        "checks": checks,
        "failure_reasons": failure_reasons,
    }


if __name__ == "__main__":
    import json

    # 快速自测示范
    sample_papers = [
        {
            "title": "Machine Learning for Astronomical Spectra Classification",
            "authors": "Lin Chen; Maya Patel",
            "publication_year": 2024,
            "doi": "https://doi.org/10.0000/example.astro.001",
            "abstract": "This teaching sample studies how machine learning can classify astronomical spectra.",
            "cited_by_count": 42,
            "source_name": "Example Journal of Astronomical Data",
            "openalex_id": "mock-W001",
            "landing_page_url": "https://example.org/papers/mock-W001",
        }
    ]

    report = evaluate_quality_gate(sample_papers)
    print("=== 质量门禁自测结果 ===")
    print(json.dumps(report, indent=2, ensure_ascii=False))