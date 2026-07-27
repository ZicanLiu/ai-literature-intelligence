"""
结果保存模块说明：

这个文件负责把原始响应、排序表、去重记录、SQLite 数据库和运行摘要写入本地。
它位于处理完成之后，把内存中的论文列表变成后续可查看、可复用的文件。
输入是论文列表、去重记录、原始响应和摘要文本，输出是 CSV、JSON、SQLite 和 txt 文件。
"""

import json
import sqlite3
from pathlib import Path

import pandas as pd

from src.processor import OUTPUT_FIELDS


SCORE_FIELDS = [
    "relevance_score",
    "impact_score",
    "recency_score",
    "completeness_score",
    "preliminary_score",
]
RANKED_OUTPUT_FIELDS = OUTPUT_FIELDS + SCORE_FIELDS
DUPLICATE_OUTPUT_FIELDS = OUTPUT_FIELDS + [
    "duplicate_reason",
    "kept_openalex_id",
    "kept_title",
]


def save_raw_response(raw_response: dict, output_file: Path) -> None:
    """
    保存原始响应 JSON。

    参数：
        raw_response：OpenAlex 或 mock 的原始响应。
        output_file：输出 JSON 文件路径。
    返回：无。
    异常或特殊情况：磁盘不可写时会抛出 OSError。
    """
    with output_file.open("w", encoding="utf-8") as file:
        json.dump(raw_response, file, ensure_ascii=False, indent=2)


def save_ranked_csv(ranked_papers: list[dict], output_file: Path) -> None:
    """
    保存排序后的论文 CSV。

    参数：
        ranked_papers：已计算初步排序分的论文列表。
        output_file：输出 CSV 文件路径。
    返回：无。
    异常或特殊情况：论文为空时仍会保存一个空表，方便确认流程已运行。
    """
    dataframe = pd.DataFrame(ranked_papers, columns=RANKED_OUTPUT_FIELDS)
    dataframe.to_csv(output_file, index=False, encoding="utf-8-sig")


def save_duplicates_csv(duplicate_records: list[dict], output_file: Path) -> None:
    """
    保存被去重记录 CSV。

    参数：
        duplicate_records：被去重的论文及原因。
        output_file：输出 CSV 文件路径。
    返回：无。
    异常或特殊情况：没有重复记录时仍会保存空表。
    """
    dataframe = pd.DataFrame(duplicate_records, columns=DUPLICATE_OUTPUT_FIELDS)
    dataframe.to_csv(output_file, index=False, encoding="utf-8-sig")


def save_to_sqlite(ranked_papers: list[dict], database_file: Path) -> None:
    """
    保存排序后的论文到 SQLite。

    参数：
        ranked_papers：已排序论文列表。
        database_file：SQLite 数据库文件路径。
    返回：无。
    异常或特殊情况：
        SQLite 建表或写入失败时抛出 RuntimeError，主程序会显示可读报错。
    """
    try:
        connection = sqlite3.connect(database_file)
        cursor = connection.cursor()

        # SQLite 建表逻辑：第一版只建一张 papers 表。
        # 文本字段用 TEXT，年份和引用量用 INTEGER，分数字段用 REAL，方便后续查询和教学演示。
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                authors TEXT,
                publication_year INTEGER,
                doi TEXT,
                abstract TEXT,
                cited_by_count INTEGER,
                source_name TEXT,
                openalex_id TEXT,
                landing_page_url TEXT,
                keyword TEXT,
                retrieved_at TEXT,
                relevance_score REAL,
                impact_score REAL,
                recency_score REAL,
                completeness_score REAL,
                preliminary_score REAL
            )
            """
        )

        # 每个 run 使用独立数据库；写入前清空表，保证数据库只表示本次实验。
        # 这也让重复执行保存函数时不会在同一个 run 内累计旧记录。
        cursor.execute("DELETE FROM papers")

        insert_sql = """
            INSERT INTO papers (
                title, authors, publication_year, doi, abstract, cited_by_count,
                source_name, openalex_id, landing_page_url, keyword, retrieved_at,
                relevance_score, impact_score, recency_score, completeness_score,
                preliminary_score
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        # SQLite 写入逻辑：把每篇论文转成固定顺序的元组，避免字段顺序变化导致错列。
        rows = []
        for paper in ranked_papers:
            rows.append(
                (
                    paper.get("title"),
                    paper.get("authors"),
                    paper.get("publication_year"),
                    paper.get("doi"),
                    paper.get("abstract"),
                    paper.get("cited_by_count"),
                    paper.get("source_name"),
                    paper.get("openalex_id"),
                    paper.get("landing_page_url"),
                    paper.get("keyword"),
                    paper.get("retrieved_at"),
                    paper.get("relevance_score"),
                    paper.get("impact_score"),
                    paper.get("recency_score"),
                    paper.get("completeness_score"),
                    paper.get("preliminary_score"),
                )
            )

        cursor.executemany(insert_sql, rows)
        connection.commit()
    except sqlite3.Error as error:
        raise RuntimeError(f"SQLite 写入失败：{error}") from error
    finally:
        try:
            connection.close()
        except UnboundLocalError:
            pass


def save_run_summary(summary_text: str, output_file: Path) -> None:
    """
    保存运行摘要。

    参数：
        summary_text：主程序生成的摘要文本。
        output_file：输出 txt 文件路径。
    返回：无。
    异常或特殊情况：磁盘不可写时会抛出 OSError。
    """
    with output_file.open("w", encoding="utf-8") as file:
        file.write(summary_text)


if __name__ == "__main__":
    print("storage.py 负责保存 JSON、CSV、SQLite 和运行摘要。")
    print("请通过 python -m app.main 触发完整保存流程。")
