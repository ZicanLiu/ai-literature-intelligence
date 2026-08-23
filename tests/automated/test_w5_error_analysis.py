import pytest
from pathlib import Path
from src.w5_error_analysis import load_error_cases, build_query_error_matrix, build_error_method_matrix

TEST_ERROR_CASES = Path(__file__).parent.parent.parent / "data" / "w5_error_cases.csv"


def test_load_error_cases():
    error_map = load_error_cases()
    assert len(error_map) == 12
    for oa_id, info in error_map.items():
        assert "pair_id" in info
        assert "research_query_id" in info
        assert "error_type" in info
        assert info["error_type"] in ["hard_negative", "topic_drift", "term_ambiguity", "unclassified"]


def test_build_query_error_matrix():
    error_map = load_error_cases()
    matrix, header = build_query_error_matrix(error_map)
    assert "research_query_id" in header
    assert "hard_negative" in header
    assert "total" in header
    assert len(matrix) == 3
    total = sum(row["total"] for row in matrix)
    assert total == 12


def test_build_error_method_matrix():
    error_map = load_error_cases()
    ranking_dict = {"sparse": {}, "dense": {}, "hybrid": {}}
    matrix, header = build_error_method_matrix(error_map, ranking_dict)
    assert "error_type" in header
    assert "total_count" in header
    assert "sparse_total" in header
    assert len(matrix) == 4
    for row in matrix:
        if row["error_type"] == "hard_negative":
            assert row["total_count"] == 5
        elif row["error_type"] == "topic_drift":
            assert row["total_count"] == 5
        elif row["error_type"] == "term_ambiguity":
            assert row["total_count"] == 2
        elif row["error_type"] == "unclassified":
            assert row["total_count"] == 0
