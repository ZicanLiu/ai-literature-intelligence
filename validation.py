"""
质量门禁核心校验模块。

提供针对配置、Python 模块、文件格式、CSV 表头与数据有效性、ID 唯一性、
数据关联关系以及敏感信息/隐私文件的通用校验逻辑。
"""

from __future__ import annotations

import csv
import importlib
import json
import re
from pathlib import Path
from typing import Any


# 常见敏感信息/秘钥正则模式
SENSITIVE_PATTERNS = [
    re.compile(r"api[_-]?key\s*[:=]\s*['\"]?([a-zA-Z0-9_\-]{16,})['\"]?", re.IGNORECASE),
    re.compile(r"secret[_-]?key\s*[:=]\s*['\"]?([a-zA-Z0-9_\-]{16,})['\"]?", re.IGNORECASE),
    re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]{20,}", re.IGNORECASE),
]

# 常见不应提交的敏感/环境变量文件名
SENSITIVE_FILENAME_PATTERNS = [
    r"^\.env$",
    r"^\.env\..+$",
    r"^id_rsa$",
    r"^id_rsa\.pub$",
    r"^.*\.pem$",
    r"^.*\.key$",
]


def check_required_directories(base_dir: Path, required_dirs: list[str]) -> tuple[list[str], list[str]]:
    """检查必需目录是否存在。"""
    errors, warnings = [], []
    for d in required_dirs:
        dir_path = base_dir / d
        if not dir_path.is_dir():
            errors.append(f"缺失必需目录: {d}")
    return errors, warnings


def check_json_syntax(file_path: Path) -> tuple[list[str], list[str]]:
    """检查 JSON 文件格式是否合法。"""
    errors, warnings = [], []
    if not file_path.exists():
        errors.append(f"JSON 文件不存在: {file_path}")
        return errors, warnings
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            json.load(f)
    except Exception as e:
        errors.append(f"JSON 格式错误 [{file_path.name}]: {e}")
    return errors, warnings


def check_python_modules_importable(modules: list[str]) -> tuple[list[str], list[str]]:
    """检查指定的 Python 模块是否可导入。"""
    errors, warnings = [], []
    for mod in modules:
        try:
            importlib.import_module(mod)
        except Exception as e:
            errors.append(f"Python 模块无法导入 [{mod}]: {e}")
    return errors, warnings


def check_markdown_links(base_dir: Path, markdown_files: list[Path]) -> tuple[list[str], list[str]]:
    """检查 Markdown 文件中的本地相对链接是否存在。"""
    errors, warnings = [], []
    link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

    for md_file in markdown_files:
        if not md_file.exists():
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception as e:
            errors.append(f"读取 Markdown 文件失败 [{md_file.name}]: {e}")
            continue

        for match in link_pattern.finditer(content):
            link_text, link_target = match.group(1), match.group(2)
            # 忽略网络链接与锚点
            if link_target.startswith("http://") or link_target.startswith("https://") or link_target.startswith("#"):
                continue
            
            # 去除 URL 片段/锚点
            clean_target = link_target.split("#")[0]
            if not clean_target:
                continue

            target_path = (md_file.parent / clean_target).resolve()
            if not target_path.exists():
                errors.append(f"Markdown 失效链接 [{md_file.name}]: -> '{link_target}' (路径不存在: {target_path})")

    return errors, warnings


def check_sensitive_files_and_secrets(base_dir: Path) -> tuple[list[str], list[str]]:
    """扫描项目目录下是否存在敏感文件或暴露的 API Key。"""
    errors, warnings = [], []
    
    # 扫描敏感文件名
    for path in base_dir.rglob("*"):
        if ".git" in path.parts or ".pytest_cache" in path.parts or "__pycache__" in path.parts:
            continue
        
        for pat in SENSITIVE_FILENAME_PATTERNS:
            if re.match(pat, path.name, re.IGNORECASE):
                errors.append(f"发现敏感文件风险: {path.relative_to(base_dir)}")
                break

        # 检查文本文件是否硬编码 Key
        if path.is_file() and path.suffix in [".py", ".json", ".yaml", ".yml", ".env", ".md", ".csv"]:
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                for pattern in SENSITIVE_PATTERNS:
                    if pattern.search(content):
                        errors.append(f"文件中发现疑似硬编码敏感信息/API Key: {path.relative_to(base_dir)}")
                        break
            except Exception:
                pass

    return errors, warnings


def validate_csv_structure(
    csv_path: Path,
    expected_headers: list[str] | None = None
) -> tuple[list[str], list[str], list[dict[str, str]]]:
    """
    检查 CSV 文件的表头、行列一致性。
    返回: (errors, warnings, rows)
    """
    errors, warnings = [], []
    rows: list[dict[str, str]] = []

    if not csv_path.exists():
        errors.append(f"CSV 文件不存在: {csv_path}")
        return errors, warnings, rows

    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                errors.append(f"CSV 文件为空或缺失表头: {csv_path.name}")
                return errors, warnings, rows

            if expected_headers is not None:
                for req in expected_headers:
                    if req not in header:
                        errors.append(f"CSV 缺失必需表头列 [{csv_path.name}]: '{req}'")

            expected_col_count = len(header)
            row_idx = 2  # 表头占第 1 行
            f.seek(0)
            dict_reader = csv.DictReader(f)
            for row in dict_reader:
                # 行列一致性检查
                if len(row) != expected_col_count or None in row.values():
                    errors.append(f"CSV 列数不一致 [{csv_path.name} 行 {row_idx}]: 期望 {expected_col_count} 列")
                rows.append(row)
                row_idx += 1

    except Exception as e:
        errors.append(f"读取 CSV 文件失败 [{csv_path.name}]: {e}")

    return errors, warnings, rows


def validate_id_uniqueness(rows: list[dict[str, str]], id_column: str, filename: str) -> tuple[list[str], list[str]]:
    """检查 CSV 行数据中 ID 列的唯一性。"""
    errors, warnings = [], []
    seen_ids = set()
    for idx, row in enumerate(rows, start=2):
        val = row.get(id_column, "").strip()
        if not val:
            warnings.append(f"CSV 存在空 ID [{filename} 行 {idx}]: 列 '{id_column}'")
            continue
        if val in seen_ids:
            errors.append(f"重复 ID [{filename} 行 {idx}]: '{val}' 在 '{id_column}' 列重复")
        else:
            seen_ids.add(val)
    return errors, warnings


def validate_label_values(
    rows: list[dict[str, str]],
    label_column: str,
    allowed_labels: set[str],
    filename: str
) -> tuple[list[str], list[str]]:
    """检查枚举标签的合法性。"""
    errors, warnings = [], []
    for idx, row in enumerate(rows, start=2):
        val = row.get(label_column, "").strip()
        if val and val not in allowed_labels:
            errors.append(f"非法标签数值 [{filename} 行 {idx}]: '{val}' 不在合法集合 {allowed_labels} 中")
    return errors, warnings


def validate_foreign_key_relation(
    source_rows: list[dict[str, str]],
    fk_column: str,
    target_ids: set[str],
    source_name: str,
    target_name: str
) -> tuple[list[str], list[str]]:
    """检查数据关联性（外键存在性校验）。"""
    errors, warnings = [], []
    for idx, row in enumerate(source_rows, start=2):
        fk_val = row.get(fk_column, "").strip()
        if fk_val and fk_val not in target_ids:
            errors.append(f"标注 ID 不存在/外键关联失效 [{source_name} 行 {idx}]: '{fk_val}' 未在 {target_name} 中找到")
    return errors, warnings


def validate_numeric_range(
    rows: list[dict[str, str]],
    column_name: str,
    min_val: float,
    max_val: float,
    filename: str
) -> tuple[list[str], list[str]]:
    """检查数值列是否在指定闭区间 [min_val, max_val] 内。"""
    errors, warnings = [], []
    for idx, row in enumerate(rows, start=2):
        raw_val = row.get(column_name, "").strip()
        if not raw_val:
            continue
        try:
            val = float(raw_val)
            if val < min_val or val > max_val:
                errors.append(
                    f"数值超出范围 [{filename} 行 {idx}]: 列 '{column_name}' 值为 {val} (合法范围 [{min_val}, {max_val}])"
                )
        except ValueError:
            errors.append(f"无法解析为数值 [{filename} 行 {idx}]: 列 '{column_name}' 值为 '{raw_val}'")
    return errors, warnings


def check_git_purity(base_dir: Path) -> tuple[list[str], list[str]]:
    """检查普通完整实验输出目录是否误入 Git 版本库。"""
    errors, warnings = [], []
    exp_dir = base_dir / "outputs" / "experiments"
    if exp_dir.exists():
        # 如果 outputs/experiments 下除了 .gitkeep 还有具体的运行文件夹
        subdirs = [p for p in exp_dir.iterdir() if p.is_dir() and p.name != ".gitkeep"]
        if subdirs:
            warnings.append(f"发现可能误提交入 Git 的实验输出目录: {[s.name for s in subdirs]}")
    return errors, warnings
