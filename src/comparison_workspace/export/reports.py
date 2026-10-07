"""Portable reports retain identities, raw/effective records and provenance."""
import csv
import io
import json
import re

from ..demo.content import DEMO_WARNING

CATEGORY_LABELS = {"SUPPORTED_PREREQUISITE": "已支持前提", "BLOCKER": "阻断",
                   "UNRESOLVED": "未决", "ALLOWED_HETEROGENEITY": "允许差异"}


def portable(view: dict) -> dict:
    # No filesystem paths or provider configuration are part of the public view.
    result = dict(view)
    result["export_notice"] = "定位仅证明原文出现；AI 解释与用户修订均需复核。"
    if any(p["synthetic"] for p in view["papers"]):
        result["synthetic_warning"] = DEMO_WARNING
    redactions = [0]
    patterns = (
        r"sk-[A-Za-z0-9_-]{20,}",
        r"gh[pousr]_[A-Za-z0-9]{20,}",
        r"(?i)(?:api[_-]?key|password|token)\s*[:=]\s*[\"']?[A-Za-z0-9_./+-]{16,}",
        r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"'<>|,;]+",
        r"/(?:home|Users)/[^\s\"'<>|,;]+",
    )
    def scrub(value):
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        if isinstance(value, str):
            for pattern in patterns:
                value, count = re.subn(pattern, "[REDACTED]", value)
                redactions[0] += count
        return value
    result = scrub(result)
    result["export_redactions"] = redactions[0]
    if redactions[0]:
        result["export_notice"] += " 敏感字符串已遮盖；遮盖引文请在本地原文复核，原始身份哈希未改变。"
    return result


def markdown(view: dict) -> str:
    view = portable(view)
    def clean(s):
        return str(s).replace("|", "\\|").replace("\n", " ")
    lines = [f"# {clean(view['title'])}", "", f"比较问题：{clean(view['question'])}",
             f"范围：{clean(view['scope'])}", f"Revision：{view['revision']}",
             f"分析状态：{'STALE / 输入已变更' if view['analysis_stale'] else '当前快照'}", ""]
    if any(p["synthetic"] for p in view["papers"]):
        lines += [f"**{DEMO_WARNING}**", ""]
    lines += ["定位仅证明文字出现；本报告不提供普遍科学可比性认证。", "", "## 源与活动目标", ""]
    active = {}
    for p in view["papers"]:
        r = next((r for r in p["results"] if r["id"] == p["active_target_result_id"]), None)
        if r:
            active[r["id"]] = p["id"]
        lines += [f"- {clean(p['identity']['title']['value'])} · paper={p['id']}",
                  f"  source={p['source']['id']} · SHA256={p['source']['sha256']} · parser={p['source']['parser']}",
                  f"  active={r['id'] if r else '未选择'} · {clean(r['title']) if r else ''}"]
    lines += ["", "## 对照观察", "", "| 目标结果 | 维度 | 值 / 状态 | 来源 | 证据 |",
              "| --- | --- | --- | --- | --- |"]
    for o in view["observations"]:
        if o["result_id"] in active:
            lines.append(f"| {o['result_id']} | {clean(o['dimension'])} | {clean(o['value'])} / {o['state']} | "
                         f"{o['provenance']['mode']} | {', '.join(o['evidence_ids'])} |")
    for cat, label in CATEGORY_LABELS.items():
        lines += ["", f"## {label}", ""]
        items = [f for f in view["findings"] if f["category"] == cat and not f["stale"]]
        lines += [f"- {clean(f['explanation'])} · affected={','.join(f['affected_result_ids'])} · "
                  f"scope={clean(f['scope'])} · mode={f['provenance']['mode']} · evidence={','.join(f['evidence_ids'])}"
                  for f in items] or ["尚无记录（不表示已通过）。"]
    lines += ["", "## STALE / 历史判断（不适用于当前输入）", ""]
    lines += [f"- {clean(f['explanation'])} · category={f['category']} · "
              f"scope={clean(f['scope'])} · affected={','.join(f['affected_result_ids'])} · STALE"
              for f in view["findings"] if f["stale"]] or ["无过期判断。"]
    lines += ["", "## 原文定位", ""]
    for e in view["evidence"]:
        lines += [f"- {e['id']} · paper={e['paper_id']} · source={e['source_snapshot_id']} · "
                  f"PDF 第 {e['page_index'] + 1} 页 · page_text_sha256={e['page_text_sha256']} · "
                  f"codepoints=[{e['start']}, {e['end']}) · {e['locator_status']}",
                  f"  引文：{clean(e['quote'])}"]
        if e["review_reason"]:
            lines.append(f"  复核：{clean(e['review_reason'])}")
    lines += ["", "## 追加修订记录", ""]
    for c in view["corrections"]:
        lines += [f"- {c['id']} · target={c['target_id']} · {c['operator']} · {c['timestamp']}",
                  f"  原因：{clean(c['rationale'])} · evidence={','.join(c['evidence_ids'])}",
                  f"  before={clean(json.dumps(c['before'], ensure_ascii=False))}",
                  f"  after={clean(json.dumps(c['after'], ensure_ascii=False))}"]
    lines += ["", "## 运行记录", ""]
    for r in view["runs"]:
        lines.append(f"- {r['id']} · {r['mode']} / {r['provider']} · {r['stage']} · {r['status']} · "
                     f"revision={r['input_revision']} · requested_model={clean(r.get('requested_model') or 'unknown')} · "
                     f"provider_reported_model={clean(r.get('provider_reported_model') or '未取得服务端返回模型')} · "
                     f"legacy model={clean(r['model'])}（仅兼容保留，来源不由此字段推断） · request={r['request_id']} · "
                     f"reasoning_effort={clean(r.get('reasoning_effort'))} · "
                     f"provider_status={clean(r.get('provider_status') or 'unknown')} · "
                     f"incomplete_details={clean(json.dumps(r.get('incomplete_details'), ensure_ascii=False))} · "
                     f"elapsed={r['elapsed_seconds']} · tokens={json.dumps(r['token_usage'])} · cost={r['cost']}")
        if r.get("failure_reason"):
            lines.append(f"  失败：{clean(r['failure_reason'])}")
        if r.get("validation_diagnostic"):
            lines.append(f"  本地校验：{clean(json.dumps(r['validation_diagnostic'], ensure_ascii=False))}")
    # Full original records are portable in all three formats.
    lines += ["", "## 原记录与完整快照", "", "```json",
              json.dumps(portable(view), ensure_ascii=False, indent=2), "```", ""]
    return "\n".join(lines)


def csv_report(view: dict) -> str:
    view = portable(view)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["record_type", "id", "project_question", "revision", "analysis_stale",
                     "paper_id", "source_id", "source_sha256", "result_id", "dimension",
                     "value", "state_or_category", "provenance_mode", "evidence_ids", "record_json"])
    def cell(value):
        # Neutralize spreadsheet formulas in all user-controlled CSV fields.
        value = str(value) if value is not None else ""
        return "'" + value if re.match(r"^[\s]*[=+@-]", value) else value
    def row(kind, item, **fields):
        values = [kind, item.get("id", ""), view["question"], view["revision"], view["analysis_stale"],
                  fields.get("paper_id", ""), fields.get("source_id", ""), fields.get("source_sha256", ""),
                  fields.get("result_id", ""), fields.get("dimension", ""), fields.get("value", ""),
                  fields.get("state", ""), fields.get("mode", ""), ";".join(item.get("evidence_ids", [])),
                  json.dumps(item, ensure_ascii=False)]
        writer.writerow([cell(v) for v in values])
    collections = {"papers", "observations", "findings", "evidence", "corrections", "runs",
                   "original_observations", "original_findings", "original_papers"}
    # Child records already have their own rows; do not duplicate the entire
    # growing project/run history in a single oversized CSV cell.
    row("project", {k: v for k, v in view.items() if k not in collections})
    for p in view["papers"]:
        source = p["source"]
        row("paper", p, paper_id=p["id"], source_id=source["id"], source_sha256=source["sha256"])
        for r in p["results"]:
            row("result", r, paper_id=p["id"], result_id=r["id"], value=r["title"],
                mode=r["provenance"]["mode"])
    for o in view["observations"]:
        row("observation", o, result_id=o["result_id"], dimension=o["dimension"],
            value=o["value"], state=o["state"], mode=o["provenance"]["mode"])
    for f in view["findings"]:
        row("finding", f, value=f["explanation"], state=("STALE / " if f["stale"] else "") + f["category"],
            mode=f["provenance"]["mode"])
    for name in ("evidence", "corrections", "runs", "original_observations", "original_findings", "original_papers"):
        for item in view[name]:
            row(name, item)
    return stream.getvalue()
