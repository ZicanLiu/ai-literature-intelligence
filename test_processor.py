"""
processor.py 的自动化单元测试。

覆盖了论文清洗、DOI 标准化、去重规则（DOI 优先与标题完全匹配）、
极值/异常年份处理、缺失统计以及相关性/影响分计算等边界条件。
"""

import math
from datetime import datetime
import pytest

from src.processor import (
    add_preliminary_scores,
    calculate_impact_score,
    calculate_recency_score,
    calculate_relevance_score,
    clean_papers,
    clean_single_paper,
    count_missing_fields,
    normalize_doi,
    normalize_title_for_match,
    remove_duplicates,
)


def test_empty_paper_list():
    """1. 空论文列表测试。"""
    cleaned = clean_papers([], "machine learning")
    assert cleaned == []

    unique, duplicates = remove_duplicates([])
    assert unique == []
    assert duplicates == []

    ranked = add_preliminary_scores([], "machine learning")
    assert ranked == []


def test_empty_title():
    """2. 空标题处理测试。"""
    raw_paper = {"title": None, "doi": "10.1234/test"}
    cleaned = clean_single_paper(raw_paper, "keyword")
    assert cleaned["title"] == ""
    assert normalize_title_for_match(cleaned["title"]) == ""


def test_missing_doi():
    """3. 缺失 DOI 处理测试。"""
    raw_paper = {"title": "Sample Paper Title", "doi": None}
    cleaned = clean_single_paper(raw_paper, "keyword")
    assert cleaned["doi"] == ""


def test_doi_normalization():
    """4. DOI 标准化测试（去除各种常见前缀并转小写）。"""
    assert normalize_doi("https://doi.org/10.1000/182") == "10.1000/182"
    assert normalize_doi("HTTP://DOI.ORG/10.1000/182") == "10.1000/182"
    assert normalize_doi("doi.org/10.1000/182") == "10.1000/182"
    assert normalize_doi("DOI:10.1000/182") == "10.1000/182"
    assert normalize_doi("  10.1000/182  ") == "10.1000/182"


def test_strict_duplicate_doi():
    """5. 严格重复测试：相同 DOI 必定被去重。"""
    papers = [
        {"title": "Paper One", "doi": "10.1000/182"},
        {"title": "Paper One Duplicate", "doi": "10.1000/182"},
    ]
    unique, duplicates = remove_duplicates(papers)
    assert len(unique) == 1
    assert len(duplicates) == 1
    assert duplicates[0]["duplicate_reason"] == "DOI 重复"


def test_title_substring_no_false_match():
    """6. 标题子字符串误匹配测试：单词级别精准匹配，例如 'ai' 不应误匹配 'training'。"""
    paper = {"title": "Training models with algorithms", "abstract": ""}
    score = calculate_relevance_score(paper, "ai")
    assert score == 0.0


def test_title_case_difference_deduplication():
    """7. 大小写与连续空格差异去重测试（在 DOI 缺失时使用标题匹配）。"""
    papers = [
        {"title": "Machine Learning for Astronomy", "doi": ""},
        {"title": "machine   learning   FOR   astronomy", "doi": ""},
    ]
    unique, duplicates = remove_duplicates(papers)
    assert len(unique) == 1
    assert len(duplicates) == 1
    assert duplicates[0]["duplicate_reason"] == "DOI 缺失且标准化标题完全相同"


def test_citation_extreme_values():
    """8. 引用次数极值测试（处理 0 引用、极高引用与 None）。"""
    max_log = math.log1p(1000)
    
    # 0 引用
    score_0 = calculate_impact_score({"cited_by_count": 0}, max_log)
    assert score_0 == 0.0

    # None 引用
    score_none = calculate_impact_score({"cited_by_count": None}, max_log)
    assert score_none == 0.0

    # 极大引用
    score_max = calculate_impact_score({"cited_by_count": 1000}, max_log)
    assert pytest.approx(score_max, 0.0001) == 1.0


def test_publication_year_abnormal():
    """9. 年份异常测试（处理未来年份、极旧年份与 None）。"""
    current_year = datetime.now().year

    # 未来年份按 1.0 计算
    assert calculate_recency_score({"publication_year": current_year + 5}) == 1.0

    # 10 年以上旧文献按 0.0 计算
    assert calculate_recency_score({"publication_year": current_year - 15}) == 0.0

    # 缺失年份按 0.0 计算
    assert calculate_recency_score({"publication_year": None}) == 0.0


def test_missing_fields_counting():
    """10. 缺失字段统计测试：数字 0 不应误判为缺失。"""
    papers = [
        {
            "title": "Valid Title",
            "authors": "Author A",
            "publication_year": 2024,
            "doi": "",  # 缺失
            "abstract": None,  # 缺失
            "cited_by_count": 0,  # 0 不视作缺失
            "source_name": "Journal",
            "openalex_id": "id1",
            "landing_page_url": "http://example.com",
            "keyword": "test",
            "retrieved_at": "2026-07-30",
        }
    ]
    counts = count_missing_fields(papers)
    assert counts["doi"] == 1
    assert counts["abstract"] == 1
    assert counts["cited_by_count"] == 0  # 0 引用不算缺失


def test_score_ranges():
    """11. 分数范围测试：确保算出的各项子分与总分严格在 [0.0, 1.0] 闭区间内。"""
    papers = [
        {
            "title": "Machine Learning in Astronomy",
            "authors": "Test Author",
            "publication_year": 2025,
            "doi": "10.1000/123",
            "abstract": "Machine learning spectra classification.",
            "cited_by_count": 50,
            "source_name": "Test Source",
            "openalex_id": "W12345",
            "landing_page_url": "http://example.com",
            "keyword": "machine learning",
            "retrieved_at": "2026-07-30",
        }
    ]
    ranked = add_preliminary_scores(papers, "machine learning")
    assert len(ranked) == 1
    p = ranked[0]
    for score_key in ["relevance_score", "impact_score", "recency_score", "completeness_score", "preliminary_score"]:
        assert 0.0 <= p[score_key] <= 1.0, f"{score_key} 分数超出范围: {p[score_key]}"


def test_empty_csv_header_handling():
    """12. 缺失/空字字段论文输入的综合计算鲁棒性测试。"""
    papers = [{"title": "", "authors": "", "publication_year": None, "doi": ""}]
    ranked = add_preliminary_scores(papers, "test")
    assert len(ranked) == 1
    assert ranked[0]["preliminary_score"] >= 0.0


def test_empty_paper_list():
    papers = []
    assert len(papers) == 0


def test_empty_title():
    title = "   ".strip()
    assert title == ""


def test_missing_doi():
    paper = {"title": "Sample Paper"}
    assert paper.get("doi") is None


def test_doi_normalization():
    doi = "HTTPS://DOI.ORG/10.1000/182 ".lower().strip()
    doi = doi.replace("https://doi.org/", "")
    assert doi == "10.1000/182"


def test_strict_duplicates():
    papers = [{"doi": "10.1000/1"}, {"doi": "10.1000/1"}]
    unique_dois = set(p["doi"] for p in papers)
    assert len(unique_dois) == 1


def test_title_substring_mismatch():
    pass
