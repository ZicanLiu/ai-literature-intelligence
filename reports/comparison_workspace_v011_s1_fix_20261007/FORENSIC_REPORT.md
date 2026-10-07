# S1 离线失败取证

日期：2026-10-07（Asia/Shanghai）。基线：`d818eb1194bc418ebb01b1d59b0a748fe543513b`。
任务分支：`codex/comparison-workspace-v011-s1-diagnostics-fix`；按本任务指定的已审核 S1 HEAD 建立 D 盘 linked worktree。
没有改写原工作树、历史 Run、源、提取候选、源审计或冻结科研 artifact。真实 API 调用：**0**。

## 已读取的证据与限制

输入是仓外 `deepseek_s1_reasoning_diagnostic_20261007` 的五份报告、`request_register.csv`、
`source_audit.csv`、Run / project captures、两套导出、安全 provider metadata、request contract 与验证摘要。
逐项检索该目录的 **41 个 JSON 文件**：唯一非空 provider proposal 来自成功 extraction；
没有 Call 2 / Call 3 的失败 structured proposal、`output_text` 或原始响应。
两套分析导出没有可用 observations / findings。没有读取 `.env`、凭据、数据库或 PDF。

Call 2 和 Call 3 的 `input_snapshot` 完全相等。Call 3 request contract 的 instructions / schema
SHA256 与基线实际源码一致。没有从失败句或成功 extraction 的第三候选补造失败 analysis 内容。
既有 `S1_RECOVERED` 只指 extraction 恢复；完整工作流没有 PASS。

| 历史调用 | effort / cap | provider 状态 | 产品状态 | 已保存事实 |
| --- | --- | --- | --- | --- |
| 1 extraction | none / 12000 | 产品未保存 | COMPLETED | 3 候选；5 LOCATED / 3 INVALID；1480 output / 0 reasoning tokens |
| 2 analysis | high / 12000 | 未保存，不能补写 | FAILED | 12000 output / 12000 reasoning tokens；无可用结构化输出 |
| 3 analysis | high / 32000 | completed，由仓外安全观察捕获 | FAILED | 24482 output / 17276 reasoning tokens；18104 可见字符；证据论文身份错误 |

历史 Call 3 request_id 为 null，耗时 86.597 秒。以上不是本任务的新请求。

## 修改前的八个问题

1. **是哪条 evidence？不能确定。** Call 3 的 `output=null`，安全观察只保存可见字符数，
   没有 candidate、数组位置或嵌套关系。能够确定的是 `Workspace.validate_output.bind` 的
   `c.paper_id not in allowed_papers` guard 产生了“提供方引用了其他论文的证据。”。
2. **模型错了还是约定有歧义？** 返回值违反产品的 evidence ownership contract；
   provider schema 的 ID 是普通字符串，prompt 要求精确身份，但没有逐条明说
   observation 的证据只能属于该 result 的论文、finding 的证据只能属于 affected results 的论文。
   这是源码中可见的隐含约定，无法证明它导致了 Call 3，也无法区分串 ID、嵌套归属误解等生成原因。
   本补丁不改变 prompt/schema；缺失 payload 不足以支持归因性修改。
3. **是哪种 mismatch？** 已知触发条件是 paper_id 对允许论文集合的 membership 不满足。
   在该 candidate 上，这个 guard 先于 `locate` 的 source_snapshot_id / page / exact quote 检查。
   不能声称源快照或 quote 正确，也不能把那些后续检查当成本次错误的来源。
4. **validator 是否正确？是。** Observation 是单个活动 Result 的观察，证据必须来自该 Result
   的论文；Finding 可以引用其 affected results 对应论文的并集，不能任意引用整个项目。
   拒绝保护了科学身份边界；不改为 warning，不扩大允许集合。
5. **能否原样离线重放？不能。** 原失败 payload 未保存。修改前用捕获的 input_snapshot 和一个
   明确标注为合成的跨论文 observation 探针，离线复现了完全相同的错误句；这只复现失败类别，
   不是 Call 3 原响应。永久回归使用合成 PDF/SDK，未把探针冒充 captured fixture。
6. **最少应保存什么？** Provider status、受约束 incomplete_details.reason、请求/返回模型、
   request_id、数值 usage、elapsed；本地失败的字段路径、validator rule、预期 paper/source 配对
   与返回的已知项目身份。未知返回值不直接持久化，避免包含凭据或私人文本。
7. **是否支持 extraction 默认 none？支持有限产品选择。** 同一冻结输入 none 恢复可用候选，
   支持把 DeepSeek 的未指定设置改为按操作默认，并保留显式 override；不证明全部论文或任务有效。
   Analysis 默认 high 保留任务指定的行为，不声称该配置已端到端成功。
8. **是否支持本补丁提高 analysis cap？否。** 32000 已到 provider completed，Call 3 的拒绝层是
   本地身份校验。本次两家 provider 的 cap 都保持 12000；不会靠提高预算掩盖身份错误。

## 最小修复决策

复用现有 provider metadata → Run → API/UI/export 链，补充操作默认和安全诊断。
失败 proposal 无需另建原始输出存储：新身份诊断足以定位已展示的 guard 风险；`Run.output` 仍为 null，
不追加无效 evidence / observation / finding，不更换 active result 或 current analysis，不增加重试。
旧 Run 的新字段默认 null，不将历史 unknown 改写成 completed / incomplete。
