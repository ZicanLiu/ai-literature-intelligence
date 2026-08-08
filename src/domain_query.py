"""天文光谱领域词典、查询扩展与标注集校验。

本模块只处理可复现的本地数据转换，不执行网络请求。OpenAlex 查询字符串使用项目
现有客户端可直接接受的 ``search`` 关键词，不构造未经验证的字段查询语法。
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


TERM_FIELDS = (
    "term_id",
    "term",
    "normalized_term",
    "category",
    "strength",
    "include_in_query",
    "example",
    "note",
    "source",
)
OPTIONAL_TERM_FIELDS = ("synonym",)
ALLOWED_CATEGORIES = frozenset(
    {
        "object_term",
        "spectrum_term",
        "method_term",
        "task_term",
        "positive_term",
        "weak_term",
        "negative_term",
        "synonym",
        "abbreviation",
    }
)
ALLOWED_LABELS = frozenset({"高度相关", "部分相关", "不相关", "待讨论"})
LABEL_FIELDS = (
    "annotation_id",
    "openalex_id",
    "source_query_ids",
    "title",
    "label",
    "reason",
    "object_type",
    "task_type",
    "matched_positive_terms",
    "matched_negative_terms",
    "evidence_source",
    "annotator",
    "review_status",
)
OPENALEX_ID_PATTERN = re.compile(r"^https://openalex\.org/W\d+$")


@dataclass(frozen=True)
class DomainTerm:
    """经过严格校验的一条领域词典记录。"""

    term_id: str
    term: str
    normalized_term: str
    category: str
    strength: int
    include_in_query: bool
    example: str
    note: str
    source: str
    synonym: str = ""


@dataclass(frozen=True)
class QueryBlueprint:
    """一条可解释查询的稳定配置。"""

    query_id: str
    description: str
    normalized_terms: tuple[str, ...]


DEFAULT_QUERY_BLUEPRINTS = (
    QueryBlueprint(
        "q01_broad_ml",
        "宽泛覆盖恒星光谱与机器学习交叉研究。",
        ("stellar spectrum", "machine learning"),
    ),
    QueryBlueprint(
        "q02_classification",
        "聚焦恒星光谱自动分类。",
        ("stellar spectrum", "spectral classification", "machine learning"),
    ),
    QueryBlueprint(
        "q03_parameters",
        "聚焦恒星参数估计。",
        (
            "stellar spectrum",
            "effective temperature",
            "surface gravity",
            "machine learning",
        ),
    ),
    QueryBlueprint(
        "q04_preprocessing",
        "聚焦光谱降噪与归一化预处理。",
        (
            "stellar spectrum",
            "spectral denoising",
            "normalization",
            "machine learning",
        ),
    ),
    QueryBlueprint(
        "q05_spectral_lines",
        "聚焦谱线与特征提取。",
        ("stellar spectrum", "absorption line", "emission line", "feature extraction"),
    ),
    QueryBlueprint(
        "q06_library_matching",
        "聚焦光谱库、模板匹配和物理量测定。",
        (
            "stellar spectrum",
            "spectral library",
            "template matching",
            "radial velocity",
            "metal abundance",
        ),
    ),
)


def load_domain_terms(path: str | Path) -> list[DomainTerm]:
    """读取并严格校验 UTF-8 CSV 领域词典。"""
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _require_columns(reader.fieldnames, TERM_FIELDS, csv_path)
        terms: list[DomainTerm] = []
        seen_ids: set[str] = set()
        seen_normalized: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            term_id = _required_text(row, "term_id", row_number)
            term = _required_text(row, "term", row_number)
            normalized_term = _required_text(row, "normalized_term", row_number)
            category = _required_text(row, "category", row_number)
            if category not in ALLOWED_CATEGORIES:
                raise ValueError(f"第 {row_number} 行 category 非法：{category}")
            if term_id in seen_ids:
                raise ValueError(f"第 {row_number} 行 term_id 重复：{term_id}")
            normalized_key = normalized_term.casefold()
            if normalized_key in seen_normalized:
                raise ValueError(
                    f"第 {row_number} 行 normalized_term 重复：{normalized_term}"
                )
            strength = _parse_strength(row.get("strength", ""), row_number)
            include_in_query = _parse_bool(
                row.get("include_in_query", ""), row_number
            )
            terms.append(
                DomainTerm(
                    term_id=term_id,
                    term=term,
                    normalized_term=normalized_term,
                    category=category,
                    strength=strength,
                    include_in_query=include_in_query,
                    example=(row.get("example") or "").strip(),
                    note=(row.get("note") or "").strip(),
                    source=(row.get("source") or "").strip(),
                    synonym=(row.get("synonym") or "").strip(),
                )
            )
            seen_ids.add(term_id)
            seen_normalized.add(normalized_key)
    if not terms:
        raise ValueError("领域词典不能为空。")
    return terms


def build_query_set(
    terms: Sequence[DomainTerm],
    blueprints: Sequence[QueryBlueprint] = DEFAULT_QUERY_BLUEPRINTS,
    source_path: str = "data/domain/stellar_spectra_terms_w2.csv",
) -> dict:
    """根据稳定蓝图生成可读、可解释且可重复的 OpenAlex 查询集合。"""
    if not blueprints:
        raise ValueError("查询蓝图不能为空。")
    term_by_normalized = {term.normalized_term.casefold(): term for term in terms}
    query_ids: set[str] = set()
    keywords: set[str] = set()
    queries: list[dict] = []

    for blueprint in blueprints:
        if not blueprint.query_id.strip() or blueprint.query_id in query_ids:
            raise ValueError(f"query_id 为空或重复：{blueprint.query_id!r}")
        selected: list[DomainTerm] = []
        for normalized_term in blueprint.normalized_terms:
            term = term_by_normalized.get(normalized_term.casefold())
            if term is None:
                raise ValueError(
                    f"查询 {blueprint.query_id} 引用了词典中不存在的词：{normalized_term}"
                )
            if not term.include_in_query:
                raise ValueError(
                    f"查询 {blueprint.query_id} 引用了 include_in_query=false 的词："
                    f"{term.term_id}"
                )
            selected.append(term)

        keyword = _normalize_whitespace(" ".join(term.term for term in selected))
        keyword_key = keyword.casefold()
        if not keyword:
            raise ValueError(f"查询 {blueprint.query_id} 生成了空 keyword。")
        if keyword_key in keywords:
            raise ValueError(f"查询 keyword 重复：{keyword}")
        queries.append(
            {
                "query_id": blueprint.query_id,
                "keyword": keyword,
                "description": blueprint.description,
                "included_term_ids": [term.term_id for term in selected],
                "included_terms": [term.term for term in selected],
                "categories": list(dict.fromkeys(term.category for term in selected)),
            }
        )
        query_ids.add(blueprint.query_id)
        keywords.add(keyword_key)

    return {
        "schema_version": "1.0",
        "source_terms": source_path.replace("\\", "/"),
        "query_count": len(queries),
        "queries": queries,
    }


def write_query_set(query_set: dict, path: str | Path) -> None:
    """以稳定 UTF-8 JSON 格式写出查询集合。"""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(query_set, ensure_ascii=False, indent=2) + "\n"
    output_path.write_text(rendered, encoding="utf-8", newline="\n")


def load_relevance_labels(
    path: str | Path, sample_paths: Iterable[str | Path] = ()
) -> list[dict[str, str]]:
    """严格解析标注 CSV，并可校验 OpenAlex ID 能否追溯到样例。"""
    csv_path = Path(path)
    traceable_ids = _load_sample_ids(sample_paths)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _require_columns(reader.fieldnames, LABEL_FIELDS, csv_path)
        labels: list[dict[str, str]] = []
        annotation_ids: set[str] = set()
        openalex_ids: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            cleaned = {field: (row.get(field) or "").strip() for field in LABEL_FIELDS}
            annotation_id = _required_text(cleaned, "annotation_id", row_number)
            openalex_id = _required_text(cleaned, "openalex_id", row_number)
            label = _required_text(cleaned, "label", row_number)
            for field in (
                "source_query_ids",
                "title",
                "reason",
                "evidence_source",
                "annotator",
                "review_status",
            ):
                _required_text(cleaned, field, row_number)
            if annotation_id in annotation_ids:
                raise ValueError(f"第 {row_number} 行 annotation_id 重复：{annotation_id}")
            if openalex_id in openalex_ids:
                raise ValueError(f"第 {row_number} 行 openalex_id 重复：{openalex_id}")
            if not OPENALEX_ID_PATTERN.fullmatch(openalex_id):
                raise ValueError(f"第 {row_number} 行不是有效 OpenAlex Work ID。")
            if label not in ALLOWED_LABELS:
                raise ValueError(f"第 {row_number} 行 label 非法：{label}")
            if traceable_ids and openalex_id not in traceable_ids:
                raise ValueError(f"第 {row_number} 行 OpenAlex ID 无法追溯到提交样例。")
            labels.append(cleaned)
            annotation_ids.add(annotation_id)
            openalex_ids.add(openalex_id)
    if not labels:
        raise ValueError("标注集不能为空。")
    return labels


def _load_sample_ids(paths: Iterable[str | Path]) -> set[str]:
    ids: set[str] = set()
    for path in paths:
        sample_path = Path(path)
        with sample_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            _require_columns(reader.fieldnames, ("openalex_id",), sample_path)
            for row in reader:
                openalex_id = (row.get("openalex_id") or "").strip()
                if openalex_id:
                    ids.add(openalex_id)
    return ids


def _require_columns(
    fieldnames: Sequence[str] | None, required: Sequence[str], path: Path
) -> None:
    available = set(fieldnames or ())
    missing = [field for field in required if field not in available]
    if missing:
        raise ValueError(f"{path.as_posix()} 缺少字段：{', '.join(missing)}")


def _required_text(row: dict[str, str], field: str, row_number: int) -> str:
    value = (row.get(field) or "").strip()
    if not value:
        raise ValueError(f"第 {row_number} 行 {field} 不能为空。")
    return value


def _parse_bool(value: str, row_number: int) -> bool:
    normalized = (value or "").strip().casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(
        f"第 {row_number} 行 include_in_query 必须严格使用 true 或 false。"
    )


def _parse_strength(value: str, row_number: int) -> int:
    try:
        strength = int((value or "").strip())
    except ValueError as error:
        raise ValueError(f"第 {row_number} 行 strength 必须是 1 到 10 的整数。") from error
    if not 1 <= strength <= 10:
        raise ValueError(f"第 {row_number} 行 strength 必须在 1 到 10 之间。")
    return strength


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split())
