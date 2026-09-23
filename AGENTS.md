# 项目开发与 AI Agent 规则

本文件规定长期边界；[接手导航](docs/project/AI_PROJECT_ONBOARDING.md) 提供按任务选读的协议。
项目研究 AI 驱动的科研文献获取、清洗、去重、排序、离线评价与辅助分析。
分数只用于可解释初筛，不代表论文真实学术价值。

## 1. 事实与开始任务

事实优先级：当前源码/测试/Git → 当前 Issue 或用户任务 →
[当前状态](docs/CURRENT_STATUS.md) → 协议/使用文档 → 历史记录与聊天。
文档与源码冲突时报告差异，不把历史测试数、SHA 或状态当作永久事实。

先只读核对：

```powershell
git status
git branch --show-current
git log -5 --oneline --decorate
```

然后阅读本文件、精简接手导航、当前状态和当前任务；按导航补读相关协议。
里程碑任务还须读当前状态指向的阶段计划。保护所有不属于本任务的工作区修改。
同步 main 后建立独立任务分支；禁止直接在 main 开发或推送。
并行分支只能依赖公共 main 和冻结 contract/fixture，不读取未合并 sibling code/artifact；
用仅复制声明输入的隔离测试证明依赖闭包。

## 2. 架构与实现

- `app/` 是 CLI/参数/用户入口，`src/` 是可复用业务逻辑；依赖只能 `app → src`。
- 保留 `app.main` 的历史 baseline；统一主链为 `app.run_pipeline`，批量入口
  `app.batch_runner` 复用同一 Pipeline。Quality Gate 是工程验收，不是论文评分步骤。
- acquisition query 与 ranking keyword 不同；query/run/batch/item 身份不得混用或靠字符串反推。
- 保留来源 `source_query_ids/source_run_ids/source_keywords`；获取层 ID 防重复不等于 entity dedup。
- Stage 1 分层不等于人工相关性标签；suspected duplicate 只进入复核队列，不自动删除。
- 先搜索调用关系，复用现有模块，做任务范围内的最小修改；不擅自换算法、调权重或扩范围。

## 3. 科研不可变边界

- 冻结 evidence、manifest/hash、raw annotation/judgement、treatment mapping 和历史结论
  不得为修复代码或通过测试而改写；不静默合并/删除冻结 benchmark 的已知 same-paper alias。
- 原始 annotation、AI assistance、review/adjudication 各有独立 provenance；保留
  actor/model/tool/evidence/review，不把 AI proposal 写成人类最终裁决或 pure-human gold。
- Query Relevance 使用明确的 graded contract；未知、未完成裁决、draft/proposed label
  不进入正式 benchmark。正式实验必须通过对应 approved/identity/hash validator；版本特定的
  cardinality、trust anchors 和 promotion 规则见相关协议。
- ranking/retrieval/fusion generation 只能读声明的冻结、无标签输入；参数、模型与 artifact
  先冻结，再评价。不得依据正式 label 或指标回调方法、挑 run，或混用不同 Pool/Query。
- Dev/Hidden 按 topic 隔离；真实 split 在 labels 和 label-aware selection 前冻结。
  Hidden labels 不进入 method development、generation 或普通仓库；遵守 seal/reveal 协议。
- blind annotation view 不暴露 retriever/method、source rank/score、ranking/fusion signal。
- synthesis relevance 不等于事实正确性；supported/partially-supported claim 必须绑定
  具体 paper identity 和 evidence reference。
- 阶段的 human Gate、sensitivity evaluator、prospective rubric 与解释限制以当前状态和
  冻结协议为准；不得把工程 PASS 提升为研究优越性或外部有效性结论。

## 4. 精简原则

Prefer the simplest mechanism that protects a demonstrated risk.

- 新 manifest/hash/gate/compatibility layer 必须说明具体风险、实际消费者和失败后果。
- Git 跟踪的普通源码/配置通常无需额外自定义 integrity 层；属于冻结科研身份的输入除外。
- 跨信任边界重新验证；同一不可变进程内快照复用已经完成的验证结果。
- 永久回归测试保护持久行为或真实回归，不绑定某次 PR 的格式。
- 新抽象必须降低整体理解成本；不建立 Complexity Gate。

## 5. 验证、安全与交付

行为变更补定向回归。交付前按[唯一的本地验证顺序](CONTRIBUTING.md#5-修改与验证)
运行完整离线 unittest 一次，再运行适用 Gate 并明确跳过重复测试，检查完整 diff。
不得删断言、放宽错误、降级为 warning 或修改历史 evidence 来换取通过。

`.env` 不得读取、输出、复制或记录；不泄露 API Key、Token、密码、个人绝对路径、
临时 live 配置、未经授权 PDF 或私人材料。Live 只在任务必要、用户明确授权且配置合法时最小运行。
普通 experiment/batch 输出、本地数据库、私人 evidence 不提交。

提交说明默认简洁中文。精确 stage 本任务文件；不以破坏性命令丢弃已有修改。
未获用户明确授权不 push、merge、tag 或 release；PR 等待审核，不自动合并。
