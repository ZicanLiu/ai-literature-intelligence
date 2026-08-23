"""Frozen Cross-Encoder ranking generation for the W5 candidate pool.

The generation path reads only the frozen research-query configuration and
candidate pool.  Model imports and weight loading are deliberately delayed until
``SentenceTransformersCrossEncoderScorer.score_pairs`` is called, so core imports
and automated tests remain offline.
"""

from __future__ import annotations

import importlib.metadata
import json
import math
import platform
import re
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from src.annotation_tasks import (
    load_research_queries,
    read_csv_rows,
    sha256_file,
    write_csv_rows,
)
from src.w4_benchmark_validation import TRUSTED_W4_V01_INPUTS
from src.w5_method_contract import (
    RANKING_FIELDS,
    RANKING_ROW_COUNT,
    RANKING_ROWS_PER_QUERY,
    SCORE_DIRECTION,
    TIE_BREAKING,
)


METHOD_ID = "cross_encoder_msmarco_v1"
DISPLAY_NAME = "Cross-Encoder MS MARCO MiniLM-L6 v1"
METHOD_FAMILY = "neural"
MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L6-v2"
MODEL_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
QUERY_FIELD = "question_en"
PAPER_TEXT_DEFINITION = (
    "title + two newlines + abstract; title only when abstract is missing"
)
MAX_LENGTH = 512
TRUNCATION = True
SCORE_DEFINITION = "raw sequence-classification relevance logit"
ACTIVATION = "identity"
APPLY_SOFTMAX = False
BATCH_SIZE = 16
DEVICE = "cpu"

CANDIDATE_POOL_PATH = Path("data/annotation_tasks/w4/candidate_pool_v0.1.csv")
RESEARCH_QUERIES_PATH = Path("configs/w4/research_queries.json")
OUTPUT_DIR = Path("data/analysis/w5_methods") / METHOD_ID

MODEL_DEPENDENCIES = (
    "sentence-transformers",
    "torch",
    "transformers",
    "huggingface-hub",
    "numpy",
)
MODEL_FIELDS = frozenset({"name", "revision", "adapter"})
GIT_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class PairScorer(Protocol):
    """Replaceable scorer used by the ranking generator."""

    def score_pairs(
        self,
        pairs: Sequence[tuple[str, str]],
        *,
        batch_size: int,
    ) -> Sequence[object]:
        """Return one higher-is-better score for each query-paper pair."""


@dataclass(frozen=True)
class PairInput:
    """The only query and candidate fields exposed to a scorer."""

    pair_id: str
    research_query_id: str
    query_text: str
    paper_text: str
    title_only: bool


FROZEN_MODEL: Mapping[str, object] = {
    "name": MODEL_NAME,
    "revision": MODEL_REVISION,
    "adapter": None,
}


class SentenceTransformersCrossEncoderScorer:
    """Lazy Sentence Transformers backend for the preregistered model."""

    def __init__(self) -> None:
        self._model: Any | None = None
        self._identity: Any | None = None

    def _load_model(self) -> tuple[Any, Any]:
        if self._model is None:
            import torch
            from sentence_transformers import CrossEncoder

            identity = torch.nn.Identity()
            self._model = CrossEncoder(
                MODEL_NAME,
                revision=MODEL_REVISION,
                max_length=MAX_LENGTH,
                activation_fn=identity,
                device=DEVICE,
            )
            self._identity = identity
        return self._model, self._identity

    def score_pairs(
        self,
        pairs: Sequence[tuple[str, str]],
        *,
        batch_size: int,
    ) -> Sequence[object]:
        model, identity = self._load_model()
        scores = model.predict(
            list(pairs),
            batch_size=batch_size,
            show_progress_bar=True,
            activation_fn=identity,
            apply_softmax=APPLY_SOFTMAX,
            convert_to_numpy=True,
        )
        if hasattr(scores, "tolist"):
            return scores.tolist()
        return scores


def frozen_method_parameters() -> dict[str, object]:
    """Return the exact preregistered method parameters for the manifest."""
    return {
        "query_field": QUERY_FIELD,
        "paper_text": PAPER_TEXT_DEFINITION,
        "tokenizer_name": MODEL_NAME,
        "tokenizer_revision": MODEL_REVISION,
        "max_length": MAX_LENGTH,
        "truncation": TRUNCATION,
        "score_definition": SCORE_DEFINITION,
        "activation": ACTIVATION,
        "apply_softmax": APPLY_SOFTMAX,
        "batch_size": BATCH_SIZE,
        "device": DEVICE,
    }


def validate_frozen_model_metadata(model: Mapping[str, object]) -> dict[str, object]:
    """Reject model metadata that differs from the preregistered model."""
    if set(model) != MODEL_FIELDS:
        raise ValueError("Cross-Encoder model metadata 必须严格包含 name/revision/adapter。")
    normalized = {field: model[field] for field in ("name", "revision", "adapter")}
    if normalized != dict(FROZEN_MODEL):
        raise ValueError("Cross-Encoder model metadata 偏离预注册模型或完整 revision。")
    return normalized


def load_pair_inputs(
    candidate_pool_path: str | Path,
    research_queries_path: str | Path,
) -> list[PairInput]:
    """Load only question_en and the four allowed candidate fields."""
    query_payload = load_research_queries(Path(research_queries_path))
    query_text_by_id: dict[str, str] = {}
    for query in query_payload["queries"]:
        query_id = str(query["research_query_id"]).strip()
        question = str(query[QUERY_FIELD]).strip()
        if not question:
            raise ValueError(f"{query_id} 的 {QUERY_FIELD} 不能为空。")
        query_text_by_id[query_id] = question

    fields, rows = read_csv_rows(Path(candidate_pool_path))
    required_fields = {"pair_id", "research_query_id", "title", "abstract"}
    missing_fields = sorted(required_fields.difference(fields))
    if missing_fields:
        raise ValueError(
            "Candidate Pool 缺少 Cross-Encoder 输入字段："
            + ", ".join(missing_fields)
            + "。"
        )
    if len(rows) != RANKING_ROW_COUNT:
        raise ValueError(f"Candidate Pool 必须恰好 {RANKING_ROW_COUNT} 条。")

    seen_pairs: set[str] = set()
    counts: Counter[str] = Counter()
    inputs: list[PairInput] = []
    for row_number, row in enumerate(rows, start=2):
        pair_id = row["pair_id"].strip()
        query_id = row["research_query_id"].strip()
        title = row["title"].strip()
        abstract = row["abstract"].strip()
        if not pair_id or pair_id in seen_pairs:
            raise ValueError(
                f"Candidate Pool 第 {row_number} 行 pair_id 为空或重复：{pair_id!r}。"
            )
        if query_id not in query_text_by_id:
            raise ValueError(f"pair {pair_id} 引用了未知 research_query_id：{query_id}。")
        if not title:
            raise ValueError(f"pair {pair_id} 缺少 title，无法构造 paper text。")
        paper_text = title if not abstract else f"{title}\n\n{abstract}"
        inputs.append(
            PairInput(
                pair_id=pair_id,
                research_query_id=query_id,
                query_text=query_text_by_id[query_id],
                paper_text=paper_text,
                title_only=not bool(abstract),
            )
        )
        seen_pairs.add(pair_id)
        counts[query_id] += 1

    expected_query_ids = set(query_text_by_id)
    if set(counts) != expected_query_ids or any(
        counts[query_id] != RANKING_ROWS_PER_QUERY for query_id in expected_query_ids
    ):
        raise ValueError(f"Candidate Pool 每个 Research Query 必须恰好 20 条：{dict(counts)}。")
    return sorted(inputs, key=lambda item: item.pair_id)


def score_and_rank(
    inputs: Sequence[PairInput],
    scorer: PairScorer,
) -> list[dict[str, object]]:
    """Score every pair once and apply the deterministic W5 ranking rule."""
    canonical_inputs = sorted(inputs, key=lambda item: item.pair_id)
    pairs = [(item.query_text, item.paper_text) for item in canonical_inputs]
    try:
        returned_scores = list(scorer.score_pairs(pairs, batch_size=BATCH_SIZE))
    except TypeError as error:
        raise ValueError("scorer 必须返回可迭代的一维数值序列。") from error
    if len(returned_scores) != len(canonical_inputs):
        raise ValueError(
            "scorer 返回数量与输入 pair 数不一致："
            f"{len(returned_scores)} != {len(canonical_inputs)}。"
        )

    scored_by_query: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item, value in zip(canonical_inputs, returned_scores, strict=True):
        if isinstance(value, (bool, str, bytes)) or not hasattr(value, "__float__"):
            raise ValueError(f"pair {item.pair_id} 的 scorer 返回值不是数值。")
        try:
            score = float(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"pair {item.pair_id} 的 scorer 返回值不是数值。") from error
        if not math.isfinite(score):
            raise ValueError(f"pair {item.pair_id} 的 scorer 返回值必须是有限数值。")
        scored_by_query[item.research_query_id].append(
            {
                "pair_id": item.pair_id,
                "research_query_id": item.research_query_id,
                "method_id": METHOD_ID,
                "score": score,
            }
        )

    ranking_rows: list[dict[str, object]] = []
    for query_id in sorted(scored_by_query):
        query_rows = sorted(
            scored_by_query[query_id],
            key=lambda row: (-float(row["score"]), str(row["pair_id"])),
        )
        for rank, row in enumerate(query_rows, start=1):
            ranking_rows.append({**row, "rank": rank})
    return ranking_rows


def capture_generation_environment(*, project_root: str | Path) -> dict[str, object]:
    """Capture clean Git and runtime provenance before model scoring starts."""
    root = Path(project_root).resolve()
    revision = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    git_revision = revision.stdout.strip() if revision.returncode == 0 else ""
    if not GIT_REVISION_PATTERN.fullmatch(git_revision):
        raise ValueError("无法记录完整 Git revision，拒绝生成正式 ranking。")
    if status.returncode != 0:
        raise ValueError("无法确认 Git 工作树状态，拒绝生成正式 ranking。")
    if status.stdout.strip():
        raise ValueError("正式 Cross-Encoder ranking 必须在 clean Git 工作树生成。")

    dependencies: dict[str, str] = {}
    for distribution in MODEL_DEPENDENCIES:
        try:
            dependencies[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as error:
            raise ValueError(f"正式模型环境缺少依赖：{distribution}。") from error
    return {
        "git_revision": git_revision,
        "git_worktree_clean": True,
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "dependencies": dependencies,
    }


def generate_cross_encoder_artifact(
    *,
    project_root: str | Path,
    output_dir: str | Path,
    scorer: PairScorer,
    environment_snapshot: Mapping[str, object] | None = None,
    model_metadata: Mapping[str, object] = FROZEN_MODEL,
) -> dict[str, object]:
    """Generate one formal, label-free Cross-Encoder method package."""
    root = Path(project_root).resolve()
    package_dir = Path(output_dir).resolve()
    manifest_path = package_dir / "manifest.json"
    ranking_path = package_dir / "ranking.csv"
    if manifest_path.exists() or ranking_path.exists():
        raise ValueError("目标 method package 已存在；正式 artifact 不允许原地覆盖。")

    started_at = datetime.now().astimezone()
    timer_started = time.perf_counter()
    environment = dict(
        environment_snapshot
        if environment_snapshot is not None
        else capture_generation_environment(project_root=root)
    )
    _validate_environment_snapshot(environment)
    normalized_model = validate_frozen_model_metadata(model_metadata)
    candidate_pool_path = root / CANDIDATE_POOL_PATH
    research_queries_path = root / RESEARCH_QUERIES_PATH
    _validate_frozen_input_file(candidate_pool_path, "candidate_pool")
    _validate_frozen_input_file(research_queries_path, "research_queries")

    pair_inputs = load_pair_inputs(candidate_pool_path, research_queries_path)
    ranking_rows = score_and_rank(pair_inputs, scorer)
    if len(ranking_rows) != RANKING_ROW_COUNT:
        raise ValueError(f"Cross-Encoder ranking 必须恰好 {RANKING_ROW_COUNT} 条。")

    package_dir.mkdir(parents=True, exist_ok=True)
    write_csv_rows(ranking_path, RANKING_FIELDS, ranking_rows)
    ranking_hash = sha256_file(ranking_path)
    duration_seconds = round(time.perf_counter() - timer_started, 6)
    manifest = {
        "schema_version": "1.0",
        "contract_name": "w5_method_ranking",
        "contract_version": "1.0",
        "artifact_type": "method_ranking",
        "method": {
            "method_id": METHOD_ID,
            "display_name": DISPLAY_NAME,
            "family": METHOD_FAMILY,
            "parameters": frozen_method_parameters(),
            "model": normalized_model,
        },
        "inputs": {
            "candidate_pool": {
                "path": CANDIDATE_POOL_PATH.as_posix(),
                "sha256": TRUSTED_W4_V01_INPUTS["candidate_pool"]["sha256"],
                "version": "w4_pilot_v0.1",
            },
            "research_queries": {
                "path": RESEARCH_QUERIES_PATH.as_posix(),
                "sha256": TRUSTED_W4_V01_INPUTS["research_queries"]["sha256"],
                "version": "w4_pilot_v0.1",
            },
        },
        "ranking": {
            "path": "ranking.csv",
            "sha256": ranking_hash,
            "row_count": len(ranking_rows),
            "score_direction": SCORE_DIRECTION,
            "tie_breaking": TIE_BREAKING,
        },
        "generation": {
            "generated_at": started_at.isoformat(timespec="seconds"),
            "duration_seconds": duration_seconds,
            "git_revision": environment["git_revision"],
            "git_worktree_clean": environment["git_worktree_clean"],
            "python": environment["python"],
            "platform": environment["platform"],
            "dependencies": environment["dependencies"],
        },
        "label_access": {
            "benchmark_labels_read": False,
            "declaration": (
                "Ranking generation read only the frozen Candidate Pool and Research "
                "Query configuration; it did not read benchmark labels or judgements."
            ),
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "manifest_path": manifest_path,
        "ranking_path": ranking_path,
        "manifest": manifest,
        "ranking_rows": ranking_rows,
        "ranking_sha256": ranking_hash,
        "title_only_count": sum(item.title_only for item in pair_inputs),
    }


def _validate_frozen_input_file(path: Path, trusted_name: str) -> None:
    trusted = TRUSTED_W4_V01_INPUTS[trusted_name]
    if not path.is_file() or sha256_file(path) != trusted["sha256"]:
        raise ValueError(f"冻结 {trusted_name} 不存在或 SHA-256 已漂移。")


def _validate_environment_snapshot(environment: Mapping[str, object]) -> None:
    required = {
        "git_revision",
        "git_worktree_clean",
        "python",
        "platform",
        "dependencies",
    }
    if set(environment) != required:
        raise ValueError("generation environment snapshot 字段不完整。")
    revision = environment["git_revision"]
    if not isinstance(revision, str) or not GIT_REVISION_PATTERN.fullmatch(revision):
        raise ValueError("generation environment 缺少完整 Git SHA。")
    if environment["git_worktree_clean"] is not True:
        raise ValueError("正式 Cross-Encoder ranking 必须记录 clean Git 工作树。")
    python_data = environment["python"]
    platform_data = environment["platform"]
    dependencies = environment["dependencies"]
    if not isinstance(python_data, dict) or set(python_data) != {
        "version",
        "implementation",
    }:
        raise ValueError("generation environment 的 Python 信息不完整。")
    if not isinstance(platform_data, dict) or set(platform_data) != {
        "system",
        "release",
        "machine",
    }:
        raise ValueError("generation environment 的 platform 信息不完整。")
    if not isinstance(dependencies, dict) or set(dependencies) != set(
        MODEL_DEPENDENCIES
    ):
        raise ValueError("generation environment 的模型依赖信息不完整。")
    values = [*python_data.values(), *platform_data.values(), *dependencies.values()]
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError("generation environment 的版本字段不能为空。")
