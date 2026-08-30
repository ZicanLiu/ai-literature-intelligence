"""Shared resolved-path safety helpers for W6 artifact generation.

The public helpers intentionally preserve their caller-specific contracts:
PR #71 workflows declare individual frozen input paths and receive the resolved
output path, while the merged Fusion/Synthesis workflows also reject an existing
non-empty output directory. Both use the same symmetric tree-overlap predicate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def ensure_output_separate_from_inputs(
    output_dir: str | Path,
    *,
    input_paths: Iterable[str | Path],
) -> Path:
    """Resolve paths and reject any output/input tree overlap.

    Callers declare the intended protection granularity: a package/evidence tree
    is passed as its root directory, while a standalone frozen config is passed
    as the file itself. Resolving both sides also covers existing symlink/junction
    aliases without forbidding harmless sibling paths beside standalone files.
    """

    output = Path(output_dir).resolve()
    protected_roots: set[Path] = set()
    for raw_path in input_paths:
        path = Path(raw_path).resolve()
        if not path.exists():
            raise ValueError(f"frozen input path 不存在：{path}")
        protected_roots.add(path)

    for root in sorted(protected_roots, key=str):
        if _paths_overlap(output, root):
            raise ValueError(
                "output 与 frozen input tree 重合，拒绝污染输入 artifact："
                f"output={output}, input_root={root}"
            )
    return output


def check_output_dir_safe(output_dir: Path, protected_dirs: list[Path]) -> None:
    """Reject overlap with protected directories and non-empty output reuse."""

    resolved = Path(output_dir).resolve()
    for protected in protected_dirs:
        frozen_dir = Path(protected).resolve()
        if _paths_overlap(resolved, frozen_dir):
            raise ValueError(
                f"输出目录与冻结输入 artifact 目录重合，禁止写入：{frozen_dir}"
            )
    if resolved.exists() and any(resolved.iterdir()):
        raise ValueError(f"输出目录已存在且非空，拒绝覆盖：{resolved}")
