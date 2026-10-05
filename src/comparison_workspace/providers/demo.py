"""Deterministic synthetic walkthrough; field differences are question relative."""
from ..demo.content import PAPERS, QUESTIONS, statements
from ..domain.models import (
    AnalysisOutput, Category, ConditionState, EvidenceCandidate, ExtractionOutput,
    FindingCandidate, ObservationCandidate, ResultCandidate,
)
from .base import ProviderFailure, ProviderResult

DIMENSIONS = {
    "dataset": "数据集 / 人群", "split": "评估划分", "metric": "指标定义",
    "training": "训练数据", "result": "报告结果", "resources": "资源 / 预算",
    "preprocessing": "预处理",
}


class DemoProvider:
    @staticmethod
    def check(snapshot):
        if (snapshot.get("demo_question") not in QUESTIONS
                or snapshot["question"] != QUESTIONS[snapshot["demo_question"]]
                or len(snapshot["papers"]) != 3
                or not all(p["synthetic"] for p in snapshot["papers"])):
            raise ProviderFailure("合成演示仅支持内置三篇文献和三个问题；其他项目请手工整理或显式配置 API。")

    @staticmethod
    def quote(paper, text):
        if not text:
            return []
        return [EvidenceCandidate(paper_id=paper["id"], source_snapshot_id=paper["source"]["id"],
                                  page_index=1, quote=text)]

    def extract_results(self, input_snapshot):
        self.check(input_snapshot)
        candidates = []
        for p, spec in zip(input_snapshot["papers"], PAPERS):
            for alternate in (False, True):
                s = statements(spec, alternate)
                candidates.append(ResultCandidate(
                    paper_id=p["id"], title="消融实验" if alternate else "主实验",
                    description=s["result"], experiment_identity=f"{spec['letter']} / {'ablation' if alternate else 'primary'}",
                    evidence=self.quote(p, s["result"])))
        return ProviderResult(ExtractionOutput(results=candidates), model="synthetic-fixture-v0.1")

    def analyze_comparison(self, input_snapshot, active_results, corrections):
        self.check(input_snapshot)
        observations, refs = [], {}
        for p, spec in zip(input_snapshot["papers"], PAPERS):
            result = next(r for r in active_results if r["paper_id"] == p["id"])
            alternate = result["experiment_identity"].endswith("ablation")
            s = statements(spec, alternate)
            for key, text in s.items():
                ev = self.quote(p, text)
                refs[(spec["letter"], key)] = ev
                observations.append(ObservationCandidate(
                    result_id=result["id"], dimension=DIMENSIONS[key], value=text,
                    state=ConditionState.PRESENT if text else ConditionState.NOT_LOCATED, evidence=ev))
        # Corrected inputs are carried into the deterministic output, never reset by a rerun.
        for corrected in input_snapshot["observations"]:
            if any(c["target_id"] == corrected["id"] for c in corrections):
                replacement = ObservationCandidate(
                    result_id=corrected["result_id"], dimension=corrected["dimension"],
                    value=corrected["value"], state=corrected["state"],
                    evidence=[EvidenceCandidate(paper_id=e["paper_id"], source_snapshot_id=e["source_snapshot_id"],
                                                page_index=e["page_index"], quote=e["quote"])
                              for e in input_snapshot["evidence"] if e["id"] in corrected["evidence_ids"]])
                observations = [o for o in observations if (o.result_id, o.dimension) !=
                                (replacement.result_id, replacement.dimension)]
                observations.append(replacement)
        ids = {s["letter"]: p["active_target_result_id"] for p, s in zip(input_snapshot["papers"], PAPERS)}
        all_ids = list(ids.values())
        def finding(category, affected, explanation, keys):
            return FindingCandidate(category=category, affected_result_ids=affected,
                                    scope=input_snapshot["question"], explanation=explanation,
                                    evidence=[e for key in keys for e in refs[key]])
        findings = [
            finding(Category.SUPPORTED, all_ids,
                    "三篇合成文献均定位到 Dataset X 和 Accuracy 定义。定位证明文字出现，解释仍需复核。",
                    [(l, k) for l in ids for k in ("dataset", "metric")]),
        ]
        q = input_snapshot["demo_question"]
        # Expected demo narratives are intentionally suspended after relevant edits.
        if corrections or any(not r["experiment_identity"].endswith("primary") for r in active_results):
            findings.append(finding(Category.UNRESOLVED, all_ids,
                                    "目标或提取信息已修订；内置演示结论不再适用，请复核后记录手工判断。",
                                    [(l, "result") for l in ids]))
        elif q == "reported":
            findings.append(finding(Category.SUPPORTED, all_ids,
                                    "仅比较报告数字：A 92%，C 91%，B 89%。此顺序不表示相同条件下的方法优劣。",
                                    [(l, "result") for l in ids]))
            findings.append(finding(Category.ALLOWED, all_ids,
                                    "本问题只询问报告数字；随机 / 时间划分和额外训练数据作为背景差异展示。",
                                    [(l, "split") for l in ids] + [("C", "training")]))
        elif q == "protocol":
            findings.append(finding(Category.BLOCKER, [ids["A"], ids["B"]],
                                    "A 使用随机划分，B 使用时间划分。当前证据不满足本问题要求的相同评估协议。",
                                    [("A", "split"), ("B", "split")]))
            findings.append(finding(Category.ALLOWED, [ids["A"], ids["C"]],
                                    "A/C 的额外训练数据差异可保留为方法背景；它不能证明评估条件已全部一致。",
                                    [("A", "training"), ("C", "training")]))
        elif q == "efficiency":
            findings.append(finding(Category.UNRESOLVED, all_ids,
                                    "B/C 的设备、时长和预算未在合成文本中定位。无法计算或推断资源效率。",
                                    [("A", "resources")]))
            findings.append(finding(Category.ALLOWED, [ids["A"], ids["C"]],
                                    "训练数据不同可以作为背景记录；资源证据缺口仍须单独解决。",
                                    [("A", "training"), ("C", "training")]))
        findings.append(finding(Category.UNRESOLVED, [ids["B"]],
                                "B 的预处理说明未定位；这是证据缺口，不是已知冲突，也不会覆盖已确认的阻断。",
                                []))
        return ProviderResult(AnalysisOutput(observations=observations, findings=findings),
                              model="synthetic-fixture-v0.1")
