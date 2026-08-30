"""W6 generation 输出目录的共享路径安全策略。

Fusion 与 Synthesis 两个 generation 入口必须使用**完全一致**的
resolved-path overlap policy，避免两套安全逻辑漂移（曾出现一边修好、
另一边漏掉的问题）。策略：

- 对 resolved 路径做对称检查：``output == protected``、``output`` 在
  ``protected`` 内、``protected`` 在 ``output`` 内，全部拒绝；
- ``protected`` 必须覆盖整个 frozen bundle 目录与相关 frozen method package 目录，
  防止 generation 输出污染冻结证据树；
- 已存在且非空的输出目录拒绝覆盖。
"""

from __future__ import annotations

from pathlib import Path


def check_output_dir_safe(output_dir: Path, protected_dirs: list[Path]) -> None:
    resolved = Path(output_dir).resolve()
    for protected in protected_dirs:
        frozen_dir = Path(protected).resolve()
        if (
            resolved == frozen_dir
            or resolved.is_relative_to(frozen_dir)
            or frozen_dir.is_relative_to(resolved)
        ):
            raise ValueError(
                f"输出目录与冻结输入 artifact 目录重合，禁止写入：{frozen_dir}"
            )
    if resolved.exists() and any(resolved.iterdir()):
        raise ValueError(f"输出目录已存在且非空，拒绝覆盖：{resolved}")
