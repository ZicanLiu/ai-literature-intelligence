"""SPECTER2 dense ranking for the frozen W5 Candidate Pool.

Ranking generation deliberately accepts only the two W5 Contract generation
inputs: the frozen Candidate Pool and Research Query configuration.  Approved
benchmark judgements are joined later by the experiment runner.
"""

from __future__ import annotations

import importlib.metadata
import json
import math
import platform
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, Sequence

from src.annotation_tasks import (
    load_research_queries,
    read_csv_rows,
    sha256_file,
    validate_candidate_pool,
    write_csv_rows,
)
from src.w4_benchmark_validation import TRUSTED_W4_V01_INPUTS
from src.w5_method_contract import RANKING_FIELDS, validate_method_output


METHOD_ID = "specter2_adhoc_v1"
METHOD_DISPLAY_NAME = "SPECTER2 Adhoc Scientific Dense Ranking v1"

BASE_MODEL_ID = "allenai/specter2_base"
BASE_MODEL_REVISION = "3447645e1def9117997203454fa4495937bfbd83"
QUERY_ADAPTER_ID = "allenai/specter2_adhoc_query"
QUERY_ADAPTER_REVISION = "3f4448817028388648a74349ece07af4518ec5bd"
PAPER_ADAPTER_ID = "allenai/specter2"
PAPER_ADAPTER_REVISION = "2081559630a80fc5851d8f798a05ba81e9468089"

FROZEN_MAX_LENGTH = 512
FROZEN_POOLING = "cls"
FROZEN_SIMILARITY = "negative_euclidean_distance"
FROZEN_QUERY_FIELD = "question_en"
FROZEN_BATCH_SIZE = 8
FROZEN_DEVICE = "cpu"
FROZEN_DTYPE = "float32"
MISSING_ABSTRACT_FALLBACK = "title_only"


class EmbeddingBackend(Protocol):
    """Minimal backend interface used by production and deterministic tests."""

    separator_token: str
    model_manifest: dict[str, Any]
    parameters_manifest: dict[str, Any]
    dependencies: dict[str, str]

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        """Encode short natural-language Research Questions."""

    def embed_papers(self, texts: Sequence[str]) -> list[list[float]]:
        """Encode candidate-paper title/abstract strings."""


class Specter2EmbeddingBackend:
    """Real AllenAI SPECTER2 backend with separately activated adapters.

    Heavy optional dependencies are imported only when this class is instantiated,
    so importing the ranking module and running fake-backend tests never downloads a
    model or requires PyTorch.
    """

    def __init__(
        self,
        *,
        device: str = FROZEN_DEVICE,
        batch_size: int = FROZEN_BATCH_SIZE,
        max_length: int = FROZEN_MAX_LENGTH,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size 必须是正整数。")
        if max_length != FROZEN_MAX_LENGTH:
            raise ValueError(f"正式 SPECTER2 配置的 max_length 固定为 {FROZEN_MAX_LENGTH}。")
        try:
            import torch
            from adapters import AutoAdapterModel
            from transformers import AutoTokenizer
        except ImportError as error:
            raise ImportError(
                "真实 SPECTER2 运行需要 requirements/w5-specter2.txt 中的可选依赖。"
            ) from error

        requested_device = str(device).strip().lower()
        if requested_device == "auto":
            actual_device = "cuda" if torch.cuda.is_available() else "cpu"
        elif requested_device in {"cpu", "cuda"}:
            actual_device = requested_device
        else:
            raise ValueError("device 必须是 cpu、cuda 或 auto。")
        if actual_device == "cuda" and not torch.cuda.is_available():
            raise ValueError("请求了 CUDA，但当前 PyTorch 环境没有可用 CUDA device。")

        torch.manual_seed(0)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(0)
        torch.use_deterministic_algorithms(True)

        tokenizer = AutoTokenizer.from_pretrained(
            BASE_MODEL_ID,
            revision=BASE_MODEL_REVISION,
        )
        model = AutoAdapterModel.from_pretrained(
            BASE_MODEL_ID,
            revision=BASE_MODEL_REVISION,
        )
        query_adapter_name = model.load_adapter(
            QUERY_ADAPTER_ID,
            revision=QUERY_ADAPTER_REVISION,
            source="hf",
            load_as="w5_query",
            set_active=False,
        )
        paper_adapter_name = model.load_adapter(
            PAPER_ADAPTER_ID,
            revision=PAPER_ADAPTER_REVISION,
            source="hf",
            load_as="w5_paper",
            set_active=False,
        )
        model.to(actual_device)
        model.eval()

        separator_token = str(tokenizer.sep_token or "").strip()
        if not separator_token:
            raise ValueError("SPECTER2 tokenizer 未提供 sep_token。")

        self._torch = torch
        self._tokenizer = tokenizer
        self._model = model
        self._query_adapter_name = str(query_adapter_name)
        self._paper_adapter_name = str(paper_adapter_name)
        self._device = actual_device
        self._batch_size = int(batch_size)
        self._max_length = int(max_length)
        self.separator_token = separator_token
        self.model_manifest = {
            "name": BASE_MODEL_ID,
            "revision": BASE_MODEL_REVISION,
            "adapter": (
                f"query={QUERY_ADAPTER_ID}@{QUERY_ADAPTER_REVISION};"
                f"paper={PAPER_ADAPTER_ID}@{PAPER_ADAPTER_REVISION}"
            ),
        }
        self.parameters_manifest = {
            "query_text_field": FROZEN_QUERY_FIELD,
            "paper_input": "title + tokenizer.sep_token + abstract",
            "missing_abstract_fallback": MISSING_ABSTRACT_FALLBACK,
            "tokenizer": {
                "name": BASE_MODEL_ID,
                "revision": BASE_MODEL_REVISION,
            },
            "query_adapter": {
                "name": QUERY_ADAPTER_ID,
                "revision": QUERY_ADAPTER_REVISION,
            },
            "paper_adapter": {
                "name": PAPER_ADAPTER_ID,
                "revision": PAPER_ADAPTER_REVISION,
            },
            "max_length": self._max_length,
            "pooling": FROZEN_POOLING,
            "similarity": FROZEN_SIMILARITY,
            "score_direction": "higher_is_better",
            "batch_size": self._batch_size,
            "device": self._device,
            "dtype": FROZEN_DTYPE,
            "random_seed": 0,
            "deterministic_algorithms": True,
        }
        self.dependencies = {
            "torch": str(torch.__version__),
            "transformers": importlib.metadata.version("transformers"),
            "adapters": importlib.metadata.version("adapters"),
        }

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts, adapter_name=self._query_adapter_name)

    def embed_papers(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts, adapter_name=self._paper_adapter_name)

    def _embed(
        self, texts: Sequence[str], *, adapter_name: str
    ) -> list[list[float]]:
        self._model.set_active_adapters(adapter_name)
        embeddings: list[list[float]] = []
        for offset in range(0, len(texts), self._batch_size):
            batch = list(texts[offset : offset + self._batch_size])
            encoded = self._tokenizer(
                batch,
                padding=True,
                truncation=True,
                return_tensors="pt",
                return_token_type_ids=False,
                max_length=self._max_length,
            )
            encoded = {name: value.to(self._device) for name, value in encoded.items()}
            with self._torch.inference_mode():
                output = self._model(**encoded)
                pooled = output.last_hidden_state[:, 0, :]
            embeddings.extend(pooled.float().cpu().tolist())
        return embeddings


def validate_generation_inputs(
    *,
    project_root: str | Path,
    candidate_pool_path: str | Path,
    research_queries_path: str | Path,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Validate and load only the two frozen, label-free generation inputs."""
    root = Path(project_root).resolve()
    candidate_pool = Path(candidate_pool_path).resolve()
    research_queries_file = Path(research_queries_path).resolve()
    for name, supplied in (
        ("candidate_pool", candidate_pool),
        ("research_queries", research_queries_file),
    ):
        trusted = TRUSTED_W4_V01_INPUTS[name]
        expected = (root / trusted["path"]).resolve()
        if supplied != expected:
            raise ValueError(f"{name} 必须使用 W5 Contract 冻结路径。")
        if not supplied.is_file() or sha256_file(supplied) != trusted["sha256"]:
            raise ValueError(f"{name} 已偏离 W5 Contract 冻结 SHA-256。")

    _fields, pool_rows = read_csv_rows(candidate_pool)
    pool_errors = validate_candidate_pool(pool_rows)
    if pool_errors:
        raise ValueError("冻结 Candidate Pool 无效：" + "; ".join(pool_errors))
    research_queries = load_research_queries(research_queries_file)
    formal_query_ids = {
        str(item["research_query_id"]) for item in research_queries["queries"]
    }
    pool_query_ids = {row["research_query_id"] for row in pool_rows}
    if pool_query_ids != formal_query_ids:
        raise ValueError("Candidate Pool 与 Research Query identity 不一致。")
    required_fields = {"pair_id", "research_query_id", "title", "abstract"}
    if pool_rows and not required_fields <= set(pool_rows[0]):
        raise ValueError("Candidate Pool 缺少 SPECTER2 generation 必需字段。")
    return pool_rows, research_queries


def build_paper_text(title: object, abstract: object, *, separator: str) -> str:
    """Apply the frozen title/abstract rule, including title-only fallback."""
    title_text = str(title or "").strip()
    abstract_text = str(abstract or "").strip()
    if not title_text:
        raise ValueError("Candidate Paper title 不能为空。")
    if not abstract_text:
        return title_text
    return title_text + separator + abstract_text


def generate_ranking_rows(
    *,
    pool_rows: list[dict[str, str]],
    research_queries: dict[str, Any],
    backend: EmbeddingBackend,
    method_id: str = METHOD_ID,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Generate deterministic 3×20 dense scores without reading any labels."""
    query_items = research_queries["queries"]
    query_ids = [str(item["research_query_id"]) for item in query_items]
    query_texts = [str(item[FROZEN_QUERY_FIELD]).strip() for item in query_items]
    if any(not value for value in query_texts):
        raise ValueError(f"Research Query 的 {FROZEN_QUERY_FIELD} 不能为空。")

    paper_texts = [
        build_paper_text(
            row.get("title"),
            row.get("abstract"),
            separator=backend.separator_token,
        )
        for row in pool_rows
    ]
    query_vectors = backend.embed_queries(query_texts)
    paper_vectors = backend.embed_papers(paper_texts)
    query_dimension = _validate_vectors(query_vectors, expected_count=len(query_ids))
    paper_dimension = _validate_vectors(paper_vectors, expected_count=len(pool_rows))
    if query_dimension != paper_dimension:
        raise ValueError("query 与 paper embedding dimension 不一致。")

    query_vector_by_id = dict(zip(query_ids, query_vectors))
    scored_by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row, paper_vector in zip(pool_rows, paper_vectors):
        query_id = row["research_query_id"]
        if query_id not in query_vector_by_id:
            raise ValueError(f"Candidate Pool 包含未知 Research Query：{query_id}。")
        score = _negative_euclidean(query_vector_by_id[query_id], paper_vector)
        score_text = format(score, ".12g")
        scored_by_query[query_id].append(
            {
                "pair_id": row["pair_id"],
                "research_query_id": query_id,
                "method_id": method_id,
                "score": score_text,
            }
        )

    ranking_rows: list[dict[str, Any]] = []
    for query_id in query_ids:
        ordered = sorted(
            scored_by_query[query_id],
            key=lambda row: (-float(row["score"]), row["pair_id"]),
        )
        for rank, row in enumerate(ordered, start=1):
            ranking_rows.append({**row, "rank": rank})
    missing_abstract_ids = [
        row["pair_id"] for row in pool_rows if not str(row.get("abstract") or "").strip()
    ]
    return ranking_rows, {
        "embedding_dimension": query_dimension,
        "missing_abstract_count": len(missing_abstract_ids),
        "missing_abstract_pair_ids": missing_abstract_ids,
        "counts_by_query": dict(Counter(row["research_query_id"] for row in ranking_rows)),
    }


def generate_specter2_artifact(
    *,
    project_root: str | Path,
    candidate_pool_path: str | Path,
    research_queries_path: str | Path,
    output_dir: str | Path,
    backend: EmbeddingBackend,
    method_id: str = METHOD_ID,
) -> dict[str, Any]:
    """Generate, freeze, and validate one W5 SPECTER2 method package."""
    root = Path(project_root).resolve()
    pool_rows, research_queries = validate_generation_inputs(
        project_root=root,
        candidate_pool_path=candidate_pool_path,
        research_queries_path=research_queries_path,
    )
    environment = _capture_generation_environment(root, backend.dependencies)
    if environment["git_worktree_clean"] is not True:
        raise ValueError("正式 SPECTER2 artifact 必须在 clean Git working tree 生成。")
    if not environment["git_revision"]:
        raise ValueError("无法记录正式 SPECTER2 artifact 的 Git revision。")

    package_dir = Path(output_dir).resolve()
    if package_dir.exists() and any(package_dir.iterdir()):
        raise FileExistsError(f"拒绝覆盖已有 method output package：{package_dir}")
    package_dir.mkdir(parents=True, exist_ok=True)
    ranking_path = package_dir / "ranking.csv"
    manifest_path = package_dir / "manifest.json"

    started = time.perf_counter()
    ranking_rows, stats = generate_ranking_rows(
        pool_rows=pool_rows,
        research_queries=research_queries,
        backend=backend,
        method_id=method_id,
    )
    duration_seconds = time.perf_counter() - started
    write_csv_rows(ranking_path, RANKING_FIELDS, ranking_rows)

    parameters = json.loads(json.dumps(backend.parameters_manifest))
    parameters.update(
        {
            "embedding_dimension": stats["embedding_dimension"],
            "missing_abstract_count": stats["missing_abstract_count"],
            "missing_abstract_pair_ids": stats["missing_abstract_pair_ids"],
        }
    )
    manifest = {
        "schema_version": "1.0",
        "contract_name": "w5_method_ranking",
        "contract_version": "1.0",
        "artifact_type": "method_ranking",
        "method": {
            "method_id": method_id,
            "display_name": METHOD_DISPLAY_NAME,
            "family": "dense",
            "parameters": parameters,
            "model": backend.model_manifest,
        },
        "inputs": {
            "candidate_pool": {
                **TRUSTED_W4_V01_INPUTS["candidate_pool"],
                "version": "w4_pilot_v0.1",
            },
            "research_queries": {
                **TRUSTED_W4_V01_INPUTS["research_queries"],
                "version": "w4_pilot_v0.1",
            },
        },
        "ranking": {
            "path": "ranking.csv",
            "sha256": sha256_file(ranking_path),
            "row_count": len(ranking_rows),
            "score_direction": "higher_is_better",
            "tie_breaking": ["score_desc", "pair_id_asc"],
        },
        "generation": {
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "duration_seconds": round(duration_seconds, 6),
            **environment,
        },
        "label_access": {
            "benchmark_labels_read": False,
            "declaration": (
                "Ranking generation read only the frozen Candidate Pool and Research "
                "Query configuration; no benchmark labels or judgements were read."
            ),
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    validated = validate_method_output(manifest_path, project_root=root)
    return {**validated, "stats": stats}


def _validate_vectors(
    vectors: Sequence[Sequence[float]], *, expected_count: int
) -> int:
    if len(vectors) != expected_count:
        raise ValueError(f"embedding backend 应返回 {expected_count} 个向量，实际 {len(vectors)}。")
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) != 1 or not dimensions or next(iter(dimensions)) <= 0:
        raise ValueError("embedding backend 返回了空向量或不一致的维度。")
    for vector in vectors:
        if any(not math.isfinite(float(value)) for value in vector):
            raise ValueError("embedding backend 返回了非有限数值。")
    return next(iter(dimensions))


def _negative_euclidean(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("无法计算不同维度 embedding 的距离。")
    distance = math.sqrt(
        math.fsum((float(a) - float(b)) ** 2 for a, b in zip(left, right))
    )
    return -distance


def _capture_generation_environment(
    project_root: Path, dependencies: dict[str, str]
) -> dict[str, Any]:
    revision = subprocess.run(
        ["git", "-C", str(project_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    status = subprocess.run(
        ["git", "-C", str(project_root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        "git_revision": revision.stdout.strip() if revision.returncode == 0 else None,
        "git_worktree_clean": status.returncode == 0 and not status.stdout.strip(),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "dependencies": dict(dependencies),
    }
