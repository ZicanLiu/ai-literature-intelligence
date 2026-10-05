"""SQLite aggregate storage with transactional revisions and immutable run snapshots."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from src.utils import current_timestamp
from ..domain.models import Mode, Project, Run, WorkspaceError


class Repository:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sources_dir = self.data_dir / "sources"
        self.sources_dir.mkdir(exist_ok=True)
        self.db = self.data_dir / "workspace.sqlite3"
        with self.connection() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS projects(
                    id TEXT PRIMARY KEY, revision INTEGER NOT NULL, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs(
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                    state TEXT NOT NULL, FOREIGN KEY(project_id) REFERENCES projects(id));
            """)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db, timeout=20)
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def create(self, project: Project):
        with self.connection() as conn:
            conn.execute("INSERT INTO projects VALUES(?,?,?)",
                         (project.id, project.revision, project.model_dump_json()))
        return project

    def get(self, project_id: str, conn=None) -> Project:
        if conn is None:
            with self.connection() as own:
                return self.get(project_id, own)
        row = conn.execute("SELECT state FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise WorkspaceError("项目不存在。", 404)
        return Project.model_validate_json(row[0])

    def list(self) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute("SELECT state FROM projects").fetchall()
        items = []
        for row in rows:
            p = Project.model_validate_json(row[0])
            items.append({"id": p.id, "title": p.title, "question": p.question,
                          "revision": p.revision, "updated_at": p.updated_at,
                          "paper_count": len(p.papers), "synthetic": any(paper.synthetic for paper in p.papers)})
        return sorted(items, key=lambda p: p["updated_at"], reverse=True)

    @staticmethod
    def expect(project: Project, expected_revision: int):
        if project.revision != expected_revision:
            raise WorkspaceError("项目已更新，请重新载入后再提交。", 409)

    def mutate(self, project_id: str, expected_revision: int,
               change: Callable[[Project], None], *, bump=True) -> Project:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            p = self.get(project_id, conn)
            self.expect(p, expected_revision)
            change(p)
            if bump:
                p.revision += 1
                p.updated_at = current_timestamp()
            p = Project.model_validate(p.model_dump())
            self._save(conn, p)
            return p

    @staticmethod
    def _save(conn, project):
        conn.execute("UPDATE projects SET revision=?, state=? WHERE id=?",
                     (project.revision, project.model_dump_json(), project.id))

    def add_run(self, run: Run):
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self.expect(self.get(run.project_id, conn), run.input_revision)
            conn.execute("INSERT INTO runs VALUES(?,?,?)",
                         (run.id, run.project_id, run.model_dump_json()))
        return run

    def get_run(self, run_id: str, conn=None) -> Run:
        if conn is None:
            with self.connection() as own:
                return self.get_run(run_id, own)
        row = conn.execute("SELECT state FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise WorkspaceError("运行不存在。", 404)
        return Run.model_validate_json(row[0])

    def runs(self, project_id: str) -> list[Run]:
        with self.connection() as conn:
            rows = conn.execute("SELECT state FROM runs WHERE project_id=? ORDER BY rowid DESC",
                                (project_id,)).fetchall()
        return [Run.model_validate_json(row[0]) for row in rows]

    def update_run(self, run: Run):
        with self.connection() as conn:
            conn.execute("UPDATE runs SET state=? WHERE id=?", (run.model_dump_json(), run.id))

    def finish(self, run: Run, apply: Callable[[Project], None]):
        """Compare revision and attach output in the same transaction."""
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            p = self.get(run.project_id, conn)
            if p.revision != run.input_revision:
                run.status = "STALE"
            else:
                apply(p)
                if run.stage == "extraction":
                    p.revision += 1
                    p.updated_at = current_timestamp()
                elif run.mode != Mode.MANUAL:
                    p.current_analysis_run_id = run.id
                p = Project.model_validate(p.model_dump())
                self._save(conn, p)
                run.status = "COMPLETED"
            conn.execute("UPDATE runs SET state=? WHERE id=?", (run.model_dump_json(), run.id))

    def interrupt_unfinished(self):
        with self.connection() as conn:
            rows = conn.execute("SELECT state FROM runs").fetchall()
            for row in rows:
                run = Run.model_validate_json(row[0])
                if run.status in {"QUEUED", "RUNNING"}:
                    run.status = "INTERRUPTED"
                    run.finished_at = current_timestamp()
                    run.failure_reason = "服务重启中断；未自动重试。"
                    conn.execute("UPDATE runs SET state=? WHERE id=?",
                                 (run.model_dump_json(), run.id))
