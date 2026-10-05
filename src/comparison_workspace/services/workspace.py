"""Small application service: revisions, source binding, corrections and background runs."""
from __future__ import annotations

import copy
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.utils import current_timestamp
from ..demo.content import PAPERS, QUESTIONS, pdf_path
from ..domain.models import (
    AnalysisOutput, Category, Correction, EvidenceCandidate, ExtractionOutput, Finding,
    IdentityField, Mode, Observation, Paper, Project, Provenance, Result, Run, WorkspaceError,
)
from ..pdf.sources import locate, parse_pdf, store_raw
from ..providers.base import ProviderFailure, ProviderResult
from ..providers.demo import DemoProvider
from ..storage.repository import Repository


class Workspace:
    def __init__(self, repo: Repository, providers: dict | None = None):
        self.repo = repo
        self.providers = {"demo": DemoProvider(), **(providers or {})}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="comparison")
        repo.interrupt_unfinished()

    def close(self):
        self.executor.shutdown(wait=True)

    @staticmethod
    def paper(project, paper_id):
        match = next((p for p in project.papers if p.id == paper_id), None)
        if match is None:
            raise WorkspaceError("本项目没有这篇论文。", 404)
        return match

    @staticmethod
    def result(project, result_id):
        match = next((r for p in project.papers for r in p.results if r.id == result_id), None)
        if match is None:
            raise WorkspaceError("目标结果不属于本项目。")
        return match

    @staticmethod
    def check_evidence(project, ids, allowed_papers):
        spans = {e.id: e for e in project.evidence}
        for eid in ids:
            if eid not in spans or spans[eid].paper_id not in allowed_papers:
                raise WorkspaceError("证据身份不属于受影响论文。")

    def effective(self, p: Project, findings: list[Finding] | None = None) -> Project:
        p = p.model_copy(deep=True)
        if findings is not None:
            p.manual_findings = p.manual_findings + copy.deepcopy(findings)
        for c in p.corrections:
            if c.target_kind == "identity":
                self.paper(p, c.target_id).identity = {k: IdentityField.model_validate(v) for k, v in c.after.items()}
                continue
            records = ([r for paper in p.papers for r in paper.results] if c.target_kind == "result"
                       else p.observations if c.target_kind == "observation" else p.manual_findings)
            for i, item in enumerate(records):
                if item.id == c.target_id:
                    validated = type(item).model_validate({**item.model_dump(mode="json"), **c.after})
                    if c.target_kind == "result":
                        paper = self.paper(p, item.paper_id)
                        paper.results = [validated if r.id == item.id else r for r in paper.results]
                    else:
                        records[i] = validated
        return p

    def view(self, project_id):
        original = self.repo.get(project_id)
        runs = self.repo.runs(project_id)
        analysis = next((r for r in runs if r.id == original.current_analysis_run_id), None)
        findings = [Finding.model_validate(f) for f in (analysis.output or {}).get("findings", [])] if analysis else []
        current = self.effective(original, findings)
        result = current.model_dump(mode="json")
        result["findings"] = result.pop("manual_findings")
        result["original_papers"] = [p.model_dump(mode="json") for p in original.papers]
        result["original_observations"] = [o.model_dump(mode="json") for o in original.observations]
        result["original_findings"] = [f.model_dump(mode="json") for f in original.manual_findings + findings]
        result["analysis_stale"] = bool(analysis and analysis.input_revision != original.revision)
        # Run histories retain complete snapshots internally; avoid copying every page into the UI list.
        result["runs"] = [r.model_dump(mode="json", exclude={"input_snapshot"}) for r in runs]
        for r in result["runs"]:
            if r["stage"] == "analysis" and r["status"] == "COMPLETED" and r["input_revision"] != original.revision:
                r["status"] = "STALE"
        return result

    def create(self, title, question, scope=""):
        return self.repo.create(Project(title=title, question=question, scope=scope))

    def patch(self, project_id, expected, changes):
        def update(p):
            if "demo_question" in changes:
                if p.demo_question is None:
                    raise WorkspaceError("真实项目不能切换到合成演示。")
                p.demo_question = changes["demo_question"]
                p.question = QUESTIONS[p.demo_question]
            for k, v in changes.items():
                if k == "demo_question":
                    continue
                if k not in {"title", "question", "scope"}:
                    raise WorkspaceError("不可修改字段。")
                setattr(p, k, v)
        return self.repo.mutate(project_id, expected, update)

    def upload(self, project_id, expected, data, filename):
        p = self.repo.get(project_id)
        self.repo.expect(p, expected)
        if len(p.papers) >= 10:
            raise WorkspaceError("每个项目最多 10 篇论文。")
        source = parse_pdf(data, filename)
        if any(paper.source.sha256 == source.sha256 for paper in p.papers):
            raise WorkspaceError("同一 PDF 已在本项目上传。", 409)
        paper = Paper(identity={"title": IdentityField(value=source.original_filename, source="filename")},
                      source=source)
        def add(current):
            if len(current.papers) >= 10:
                raise WorkspaceError("每个项目最多 10 篇论文。")
            if any(x.source.sha256 == source.sha256 for x in current.papers):
                raise WorkspaceError("同一 PDF 已在本项目上传。", 409)
            store_raw(self.repo.sources_dir, source, data)
            current.papers.append(paper)
        return self.repo.mutate(project_id, expected, add)

    def add_evidence(self, project_id, expected, candidate):
        def add(p):
            p.evidence.append(locate(candidate, self.paper(p, candidate.paper_id)))
        return self.repo.mutate(project_id, expected, add)

    def add_result(self, project_id, expected, paper_id, fields):
        def add(p):
            paper = self.paper(p, paper_id)
            result = Result(paper_id=paper_id, **fields)
            self.check_evidence(p, result.evidence_ids, {paper_id})
            paper.results.append(result)
            if len(paper.results) == 1:
                paper.active_target_result_id = result.id
        return self.repo.mutate(project_id, expected, add)

    def select(self, project_id, expected, paper_id, result_id):
        def update(p):
            paper = self.paper(p, paper_id)
            if result_id is not None and not any(r.id == result_id for r in paper.results):
                raise WorkspaceError("活动结果不属于该论文。")
            paper.active_target_result_id = result_id
        return self.repo.mutate(project_id, expected, update)

    def add_observation(self, project_id, expected, fields):
        def add(p):
            obs = Observation(**fields)
            paper_id = self.result(p, obs.result_id).paper_id
            self.check_evidence(p, obs.evidence_ids, {paper_id})
            if any((o.result_id, o.dimension) == (obs.result_id, obs.dimension) for o in p.observations):
                raise WorkspaceError("该维度已有观察，请通过修订保留原记录。", 409)
            p.observations.append(obs)
        return self.repo.mutate(project_id, expected, add)

    def add_finding(self, project_id, expected, fields):
        def add(p):
            f = Finding(**fields)
            self.validate_finding(p, f)
            p.manual_findings.append(f)
        return self.repo.mutate(project_id, expected, add)

    def validate_finding(self, p, f):
        active = {paper.active_target_result_id for paper in p.papers}
        if any(rid not in active for rid in f.affected_result_ids):
            raise WorkspaceError("手工判断只能引用当前活动目标结果。")
        papers = {self.result(p, rid).paper_id for rid in f.affected_result_ids}
        self.check_evidence(p, f.evidence_ids, papers)
        if f.category != Category.UNRESOLVED and (not f.evidence_ids or any(
                e.id in f.evidence_ids and e.locator_status != "LOCATED" for e in p.evidence)):
            raise WorkspaceError("支持前提、阻断和允许差异须绑定已定位证据；否则请记录为未决。")

    def correct(self, project_id, expected, kind, target_id, after, rationale, evidence_ids):
        def add(p):
            view = self.view(project_id)
            effective = self.effective(p, [Finding.model_validate(f) for f in
                                          view["original_findings"] if f["id"] not in {x.id for x in p.manual_findings}])
            fields = {
                "result": {"title", "description", "experiment_identity", "evidence_ids"},
                "observation": {"dimension", "value", "state", "evidence_ids"},
                "finding": {"category", "scope", "explanation", "evidence_ids"},
                "identity": {"title", "doi", "authors", "year"},
            }[kind]
            if not after or set(after) - fields:
                raise WorkspaceError("修订包含不可修改字段。")
            if kind == "identity":
                paper = self.paper(effective, target_id)
                before = {k: v.model_dump() for k, v in paper.identity.items()}
                normalized = {**before, **{k: {"value": str(v), "source": "user-correction"} for k, v in after.items()}}
                papers = {paper.id}
            else:
                records = ([r for paper in effective.papers for r in paper.results] if kind == "result"
                           else effective.observations if kind == "observation" else effective.manual_findings)
                target = next((x for x in records if x.id == target_id), None)
                if not target:
                    raise WorkspaceError("修订目标不存在。", 404)
                before = target.model_dump(mode="json")
                normalized = {**before, **after}
                normalized["provenance"] = Provenance(mode=Mode.MANUAL, actor="local-user").model_dump(mode="json")
                obj = type(target).model_validate(normalized)
                if kind == "result":
                    papers = {obj.paper_id}
                elif kind == "observation":
                    papers = {self.result(p, obj.result_id).paper_id}
                else:
                    papers = {self.result(p, rid).paper_id for rid in obj.affected_result_ids}
                    self.validate_finding(p, obj)
                self.check_evidence(p, normalized.get("evidence_ids", []), papers)
            self.check_evidence(p, evidence_ids, papers)
            p.corrections.append(Correction(target_kind=kind, target_id=target_id, before=before,
                                            after=normalized, rationale=rationale, evidence_ids=evidence_ids))
        return self.repo.mutate(project_id, expected, add)

    def snapshot(self, p):
        return self.effective(p).model_dump(mode="json")

    def start_run(self, project_id, expected, stage, mode, *, provider=None):
        p = self.repo.get(project_id)
        self.repo.expect(p, expected)
        if len(p.papers) < 2:
            raise WorkspaceError("请先添加 2–10 篇论文。")
        if stage == "analysis" and any(not paper.active_target_result_id for paper in p.papers):
            raise WorkspaceError("每篇论文须选择一个活动目标结果后才能对照。")
        if mode not in {"demo", "api", "import", "manual"}:
            raise WorkspaceError("未知运行模式。")
        if mode == "manual" and stage != "analysis":
            raise WorkspaceError("离线真实 PDF 请手工创建结果；未自动生成 AI 分析。")
        selected = provider or self.providers.get(mode)
        if mode != "manual" and selected is None:
            raise WorkspaceError("该提供方未启用；请使用手工流程或导入。")
        if mode != "manual" and any(paper.source.parse_status != "TEXT_EXTRACTED" for paper in p.papers):
            raise WorkspaceError("有 PDF 文本未完整提取；这是技术限制，请使用手工阅读与整理。")
        if mode == "demo":
            selected.check(self.snapshot(p))
        if hasattr(selected, "ensure_enabled"):
            selected.ensure_enabled()
        run = Run(project_id=project_id, input_revision=p.revision, input_snapshot=self.snapshot(p),
                  mode=mode, stage=stage, provider=type(selected).__name__ if selected else "Manual",
                  model=getattr(selected, "model", None))
        self.repo.add_run(run)
        self.executor.submit(self.execute, run.id, selected)
        return run

    def validate_output(self, p, run, response):
        """Reject malformed identities; keep invalid locator candidates for review."""
        prov = Provenance(mode=run.mode, actor=run.provider, model=response.model, run_id=run.id)
        evidence = []
        def bind(candidates, allowed_papers):
            ids = []
            for c in candidates:
                if c.paper_id not in allowed_papers:
                    raise WorkspaceError("提供方引用了其他论文的证据。")
                e = locate(c, self.paper(p, c.paper_id))
                evidence.append(e)
                ids.append(e.id)
            return ids
        if run.stage == "extraction":
            parsed = ExtractionOutput.model_validate(response.output.model_dump())
            results = []
            for c in parsed.results:
                self.paper(p, c.paper_id)
                results.append(Result(paper_id=c.paper_id, title=c.title, description=c.description,
                                      experiment_identity=c.experiment_identity,
                                      evidence_ids=bind(c.evidence, {c.paper_id}), provenance=prov))
            if not results:
                raise WorkspaceError("未返回结果候选；请手工创建。")
            output = {"results": [r.model_dump(mode="json") for r in results],
                      "evidence": [e.model_dump(mode="json") for e in evidence]}
        else:
            parsed = AnalysisOutput.model_validate(response.output.model_dump())
            active = {paper.active_target_result_id: paper.id for paper in p.papers}
            observations, findings = [], []
            seen = set()
            for c in parsed.observations:
                if c.result_id not in active:
                    raise WorkspaceError("分析引用了非活动目标结果。")
                key = (c.result_id, c.dimension)
                if key in seen:
                    raise WorkspaceError("分析包含重复结果维度。")
                seen.add(key)
                observations.append(Observation(result_id=c.result_id, dimension=c.dimension,
                                                value=c.value, state=c.state,
                                                evidence_ids=bind(c.evidence, {active[c.result_id]}), provenance=prov))
            for c in parsed.findings:
                if not c.affected_result_ids or any(rid not in active for rid in c.affected_result_ids):
                    raise WorkspaceError("分析结论引用了非活动目标结果。")
                f = Finding(category=c.category, affected_result_ids=c.affected_result_ids, scope=c.scope,
                            explanation=c.explanation,
                            evidence_ids=bind(c.evidence, {active[rid] for rid in c.affected_result_ids}), provenance=prov)
                # Unverified provider interpretation remains reviewable, never promoted to located support.
                if f.category != Category.UNRESOLVED and (not f.evidence_ids or any(
                        e.id in f.evidence_ids and e.locator_status != "LOCATED" for e in evidence)):
                    f.category = Category.UNRESOLVED
                    f.explanation = "证据定位无效，原提供方解释待复核：" + f.explanation
                findings.append(f)
            output = {"observations": [o.model_dump(mode="json") for o in observations],
                      "findings": [f.model_dump(mode="json") for f in findings],
                      "evidence": [e.model_dump(mode="json") for e in evidence]}
        # Keep the original proposal before locator validation changes a review category.
        # Run detail and all exports consume this, independently of the validated projection.
        output["provider_output"] = parsed.model_dump(mode="json")
        return output

    def execute(self, run_id, provider):
        run = self.repo.get_run(run_id)
        run.status = "RUNNING"
        self.repo.update_run(run)
        started = time.monotonic()
        try:
            p = Project.model_validate(run.input_snapshot)
            active = [r.model_dump(mode="json") for paper in p.papers for r in paper.results
                      if r.id == paper.active_target_result_id]
            if run.mode == Mode.MANUAL:
                response = ProviderResult(AnalysisOutput(observations=[], findings=[]))
            elif run.stage == "extraction":
                response = provider.extract_results(run.input_snapshot)
            else:
                response = provider.analyze_comparison(run.input_snapshot, active,
                                                       [c.model_dump(mode="json") for c in p.corrections])
            run.model, run.request_id, run.token_usage = response.model, response.request_id, response.token_usage
            run.output = self.validate_output(p, run, response)
            run.finished_at = current_timestamp()
            run.elapsed_seconds = round(time.monotonic() - started, 3)
            def attach(current):
                if run.mode == Mode.MANUAL:
                    return
                current.evidence.extend(self._evidence(e) for e in run.output["evidence"])
                if run.stage == "extraction":
                    for raw in run.output["results"]:
                        r = Result.model_validate(raw)
                        self.paper(current, r.paper_id).results.append(r)
                else:
                    # Preserve user observations and every correction target as original records.
                    corrected_ids = {c.target_id for c in current.corrections if c.target_kind == "observation"}
                    retained = [o for o in current.observations if o.id in corrected_ids or o.provenance.mode == Mode.MANUAL]
                    retained_keys = {(o.result_id, o.dimension) for o in retained}
                    current.observations = retained + [Observation.model_validate(o) for o in run.output["observations"]
                                                      if (o["result_id"], o["dimension"]) not in retained_keys]
            self.repo.finish(run, attach)
        except Exception as exc:
            run.status = "FAILED"
            if isinstance(exc, ProviderFailure):
                run.model = exc.model or run.model
                run.request_id = exc.request_id
                run.token_usage = exc.token_usage
            # SDK/parser messages can contain credentials, paths or source content.
            run.failure_reason = (str(exc) if isinstance(exc, (WorkspaceError, ProviderFailure))
                                  else "提供方结构无效或运行失败；项目输入已保留。")
            run.finished_at = current_timestamp()
            run.elapsed_seconds = round(time.monotonic() - started, 3)
            self.repo.update_run(run)

    @staticmethod
    def _evidence(raw):
        from ..domain.models import EvidenceSpan
        return EvidenceSpan.model_validate(raw)

    def seed_demo(self, question_key="reported"):
        if question_key not in QUESTIONS:
            raise WorkspaceError("未知演示问题。")
        p = Project(title="三篇文献，一张可复核的对照表", question=QUESTIONS[question_key],
                    scope="合成分类实验 · Dataset X · 仅演示工作流，不作研究结论", demo_question=question_key)
        for spec in PAPERS:
            raw = pdf_path(spec["letter"]).read_bytes()
            source = parse_pdf(raw, f"SYNTHETIC_DEMO_{spec['letter']}.pdf")
            paper = Paper(identity={"title": IdentityField(value=spec["title"], source="synthetic-fixture"),
                                    "authors": IdentityField(value="Synthetic Demo Authors", source="synthetic-fixture")},
                          source=source, synthetic=True)
            store_raw(self.repo.sources_dir, source, raw)
            p.papers.append(paper)
        snapshot = self.snapshot(p)
        response = self.providers["demo"].extract_results(snapshot)
        synthetic_run = Run(project_id=p.id, input_revision=0, input_snapshot=snapshot,
                            stage="extraction", mode=Mode.DEMO, provider="DemoProvider")
        output = self.validate_output(p, synthetic_run, response)
        p.evidence.extend(self._evidence(e) for e in output["evidence"])
        for raw in output["results"]:
            r = Result.model_validate(raw)
            self.paper(p, r.paper_id).results.append(r)
        for paper in p.papers:
            paper.active_target_result_id = paper.results[0].id
        self.repo.create(p)
        synthetic_run.status = "COMPLETED"
        synthetic_run.model = response.model
        synthetic_run.output = output
        synthetic_run.finished_at = current_timestamp()
        synthetic_run.elapsed_seconds = 0.0
        self.repo.add_run(synthetic_run)
        run = self.start_run(p.id, p.revision, "analysis", "demo")
        return p, run
