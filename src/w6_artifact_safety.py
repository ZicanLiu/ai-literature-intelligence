"""Filesystem safety helpers for W6 frozen-input workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


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
        if output == root or output.is_relative_to(root) or root.is_relative_to(output):
            raise ValueError(
                "output 与 frozen input tree 重合，拒绝污染输入 artifact："
                f"output={output}, input_root={root}"
            )
    return output
