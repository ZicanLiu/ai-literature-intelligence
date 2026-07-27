"""
单次实验输出上下文。

该模块只负责生成安全、唯一的 run_id，创建本次运行目录，以及维护
run_config.json。业务处理与评分逻辑仍由原有模块负责。
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


def keyword_slug(keyword: str, max_length: int = 48) -> str:
    """把关键词转换成短小、Windows 安全的 ASCII 目录片段。"""
    normalized = unicodedata.normalize("NFKD", keyword)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    terms = re.findall(r"[a-z0-9]+", ascii_text)
    slug = "-".join(terms)[:max_length].strip("-")
    if slug:
        return slug

    digest = hashlib.sha256(keyword.encode("utf-8")).hexdigest()[:8]
    return f"query-{digest}"


def safe_run_name(run_name: str) -> str:
    """清理可选的自定义运行名称；纯中文名称使用短哈希表示。"""
    return keyword_slug(run_name, max_length=32)


def build_run_id(
    mode: str,
    keyword: str,
    max_results: int,
    run_name: str | None = None,
) -> str:
    """生成包含时间、模式、关键词和数量的唯一 run_id。"""
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S%f")
    parts = [timestamp, mode]
    if run_name:
        parts.append(safe_run_name(run_name))
    parts.extend(
        [
            keyword_slug(keyword),
            f"n{max_results}",
            uuid.uuid4().hex[:6],
        ]
    )
    return "_".join(parts)


def safe_error_summary(error: Exception, project_root: Path, run_dir: Path) -> str:
    """生成不包含本地绝对路径或疑似密钥值的短错误摘要。"""
    message = str(error).replace("\r", " ").replace("\n", " ").strip()
    for path, replacement in (
        (run_dir, "<run_dir>"),
        (project_root, "<project_root>"),
        (Path.home(), "<home>"),
    ):
        message = message.replace(str(path), replacement)
        message = message.replace(str(path).replace("\\", "/"), replacement)

    message = re.sub(
        r"(?i)(api[_-]?key|token|password)\s*[:=]\s*\S+",
        r"\1=<redacted>",
        message,
    )
    if len(message) > 300:
        message = message[:297] + "..."
    return f"{type(error).__name__}: {message or '未提供错误详情'}"


@dataclass
class RunContext:
    """集中保存一次运行的目录、文件路径与配置状态。"""

    project_root: Path
    run_id: str
    run_dir: Path
    config_file: Path
    raw_response_file: Path
    ranked_csv_file: Path
    duplicates_csv_file: Path
    figures_dir: Path
    citations_chart_file: Path
    score_chart_file: Path
    summary_file: Path
    database_file: Path
    config: dict
    started_at: datetime

    @classmethod
    def create(
        cls,
        *,
        project_root: Path,
        output_root: Path,
        mode: str,
        keyword: str,
        max_results: int,
        project_version: str,
        scoring_weights: dict[str, float],
        run_name: str | None = None,
    ) -> "RunContext":
        """创建唯一实验目录，并写入初始的 running 状态配置。"""
        output_root.mkdir(parents=True, exist_ok=True)
        started_at = datetime.now().astimezone()

        for _ in range(5):
            run_id = build_run_id(mode, keyword, max_results, run_name)
            run_dir = output_root / run_id
            try:
                run_dir.mkdir(exist_ok=False)
                break
            except FileExistsError:
                continue
        else:
            raise OSError("连续生成的实验目录均已存在，请稍后重试。")

        raw_dir = run_dir / "raw"
        tables_dir = run_dir / "tables"
        figures_dir = run_dir / "figures"
        reports_dir = run_dir / "reports"
        data_dir = run_dir / "data"
        for directory in (raw_dir, tables_dir, figures_dir, reports_dir, data_dir):
            directory.mkdir()

        context = cls(
            project_root=project_root,
            run_id=run_id,
            run_dir=run_dir,
            config_file=run_dir / "run_config.json",
            raw_response_file=raw_dir / "raw_response.json",
            ranked_csv_file=tables_dir / "papers_ranked.csv",
            duplicates_csv_file=tables_dir / "duplicates_removed.csv",
            figures_dir=figures_dir,
            citations_chart_file=figures_dir / "top10_citations.png",
            score_chart_file=figures_dir / "top10_preliminary_score.png",
            summary_file=reports_dir / "run_summary.txt",
            database_file=data_dir / "literature.db",
            config={},
            started_at=started_at,
        )
        context.config = {
            "run_id": run_id,
            "created_at": started_at.isoformat(timespec="seconds"),
            "mode": mode,
            "keyword": keyword,
            "max_results": max_results,
            "run_name": run_name,
            "project_version": project_version,
            "python_version": platform.python_version(),
            "scoring_weights": scoring_weights,
            "output_files": {
                name: path.relative_to(run_dir).as_posix()
                for name, path in context.output_files().items()
            },
            "status": "running",
            "success": False,
            "counts": {
                "raw": None,
                "cleaned": None,
                "unique": None,
                "duplicates": None,
            },
            "duration_seconds": None,
            "error": None,
        }
        context.write_config()
        return context

    def output_files(self) -> dict[str, Path]:
        """返回本次运行全部约定产物的路径。"""
        return {
            "run_config": self.config_file,
            "raw_response": self.raw_response_file,
            "papers_ranked": self.ranked_csv_file,
            "duplicates_removed": self.duplicates_csv_file,
            "top10_citations": self.citations_chart_file,
            "top10_preliminary_score": self.score_chart_file,
            "run_summary": self.summary_file,
            "database": self.database_file,
        }

    def write_config(self) -> None:
        """原子写入配置，避免留下半截 JSON。"""
        temporary_file = self.config_file.with_suffix(".json.tmp")
        with temporary_file.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(self.config, file, ensure_ascii=False, indent=2)
            file.write("\n")
        temporary_file.replace(self.config_file)

    def record_success(
        self,
        *,
        raw_count: int,
        cleaned_count: int,
        unique_count: int,
        duplicate_count: int,
    ) -> None:
        """将运行配置更新为成功完成。"""
        self.config.update(
            {
                "status": "completed",
                "success": True,
                "counts": {
                    "raw": raw_count,
                    "cleaned": cleaned_count,
                    "unique": unique_count,
                    "duplicates": duplicate_count,
                },
                "duration_seconds": self.elapsed_seconds(),
                "error": None,
            }
        )
        self.write_config()

    def record_counts(
        self,
        *,
        raw_count: int,
        cleaned_count: int,
        unique_count: int,
        duplicate_count: int,
    ) -> None:
        """在产物保存前记录已经确定的处理数量。"""
        self.config["counts"] = {
            "raw": raw_count,
            "cleaned": cleaned_count,
            "unique": unique_count,
            "duplicates": duplicate_count,
        }
        self.write_config()

    def record_failure(self, error: Exception) -> None:
        """将运行配置更新为失败，并只保存经过脱敏的错误摘要。"""
        self.config.update(
            {
                "status": "failed",
                "success": False,
                "duration_seconds": self.elapsed_seconds(),
                "error": safe_error_summary(error, self.project_root, self.run_dir),
            }
        )
        self.write_config()

    def elapsed_seconds(self) -> float:
        """返回从创建上下文到当前时刻的耗时。"""
        duration = datetime.now().astimezone() - self.started_at
        return round(duration.total_seconds(), 3)
