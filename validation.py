"""
src/validation.py
数据校验模块：负责校验论文元数据的合法性、统计字段缺失情况并计算完整度得分。
"""

from typing import Any, Dict, List

# 核心必需字段与建议完整性字段
REQUIRED_FIELDS = ["title", "openalex_id"]
RECOMMENDED_FIELDS = [
    "title",
    "authors",
    "publication_year",
    "doi",
    "abstract",
    "cited_by_count",
    "source_name",
    "openalex_id",
    "landing_page_url",
]


def validate_single_paper(paper: Dict[str, Any]) -> Dict[str, Any]:
    """
    对单篇论文进行合法性与完整度校验。

    参数:
        paper: 论文元数据字典。
    返回:
        包含校验结果、缺失字段列表、错误列表及完整度得分的字典。
    """
    errors = []
    missing_fields = []

    # 1. 检查必要字段是否存在且非空
    for field in REQUIRED_FIELDS:
        val = paper.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            errors.append(f"缺少关键字段: '{field}'")

    # 2. 检查数值范围合法性
    pub_year = paper.get("publication_year")
    if pub_year is not None:
        if not isinstance(pub_year, int) or pub_year < 1800 or pub_year > 2026:
            errors.append(f"出版年份异常: {pub_year}")

    cited_count = paper.get("cited_by_count")
    if cited_count is not None:
        if not isinstance(cited_count, int) or cited_count < 0:
            errors.append(f"被引次数异常: {cited_count}")

    # 3. 统计推荐字段缺失情况并计算 completeness_score
    present_count = 0
    for field in RECOMMENDED_FIELDS:
        val = paper.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing_fields.append(field)
        else:
            present_count += 1

    completeness_score = round(present_count / len(RECOMMENDED_FIELDS), 4)

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "missing_fields": missing_fields,
        "completeness_score": completeness_score,
    }


def validate_paper_list(papers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    对整批论文列表进行批量校验并生成汇总统计。

    参数:
        papers: 论文字典列表。
    返回:
        汇总校验指标（总数、有效数、无效数、平均完整度、字段缺失率分布等）。
    """
    total_count = len(papers)
    if total_count == 0:
        return {
            "total_count": 0,
            "valid_count": 0,
            "invalid_count": 0,
            "average_completeness": 0.0,
            "field_missing_counts": {field: 0 for field in RECOMMENDED_FIELDS},
            "paper_results": [],
        }

    valid_count = 0
    invalid_count = 0
    total_completeness = 0.0
    field_missing_counts = {field: 0 for field in RECOMMENDED_FIELDS}
    paper_results = []

    for paper in papers:
        res = validate_single_paper(paper)
        paper_results.append(res)

        if res["is_valid"]:
            valid_count += 1
        else:
            invalid_count += 1

        total_completeness += res["completeness_score"]

        for missing_field in res["missing_fields"]:
            field_missing_counts[missing_field] += 1

    avg_completeness = round(total_completeness / total_count, 4)

    return {
        "total_count": total_count,
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "average_completeness": avg_completeness,
        "field_missing_counts": field_missing_counts,
        "paper_results": paper_results,
    }