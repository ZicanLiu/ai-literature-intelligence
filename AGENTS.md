# 项目开发与 AI Agent 规则

本文件是开发者、Codex、ChatGPT、Claude Code 等工具接手仓库时的第一入口。它只保留高优先级、长期有效的规则；完整上下文见
[AI 项目交接文档](docs/project/AI_PROJECT_ONBOARDING.md)。

## 1. 项目定位

本项目研究 AI 驱动的科研文献全流程获取与辅助评估。当前 MVP 聚焦“AI 在天文光谱数据处理中的应用”，主链覆盖：

```text
获取 → 清洗 → 去重 → 排序 → 离线评价 → 后续科研分析
```

当前分数和排序只用于可解释的文献初筛，不代表论文真实学术价值。

## 2. 事实优先级

发生冲突时，按以下顺序判断：

1. 当前工作区实际代码、测试与 Git 状态；
2. 当前正在执行的 GitHub Issue；
3. [`docs/CURRENT_STATUS.md`](docs/CURRENT_STATUS.md)；
4. [`docs/project/AI_PROJECT_ONBOARDING.md`](docs/project/AI_PROJECT_ONBOARDING.md)；
5. 其他设计与使用文档；
6. 历史周报、会议记录和旧聊天。

文档与源码冲突时，以当前源码和实际测试为准，并明确报告差异。不要把文档中的测试数、提交号或快照状态当作永久事实。

## 3. 开始任务前

先只读核对：

```powershell
git status
git branch --show-current
git log -5 --oneline --decorate
```

确认分支、HEAD 和未提交修改后，依次阅读本文件、[详细交接文档](docs/project/AI_PROJECT_ONBOARDING.md)、[当前状态](docs/CURRENT_STATUS.md)及当前 Issue。不得覆盖不属于本任务的工作区修改。

## 4. 架构边界

- `app/`：CLI、参数解析和用户入口；
- `src/`：可复用业务逻辑；
- 依赖方向只能是 `app → src`，不得新增 `src → app`；
- `python -m app.main` 保留 v0.2.0 baseline；
- `python -m app.run_pipeline` 是 W2/v0.3.0 Unified Pipeline 候选入口；
- `python -m app.batch_runner` 是复用统一 Pipeline 的批量实验入口；
- Quality Gate 是工程验收工具，不是论文处理或评分步骤。

当前 Unified Pipeline 高层数据流：

```text
Domain Terms → Domain Query Set → Acquisition Queries → OpenAlex v2
→ Processor Clean → Attach Provenance → Combine → Exact Dedup
→ Suspected Review Queue → Baseline preliminary_score
→ TF-IDF / Stage 1 / Stage 2 → Optional Evaluation → Outputs → Quality Gate
```

## 5. 必须区分的概念

- acquisition query 用于获取候选；ranking keyword 用于对合并候选集统一排序，二者不等同；
- `query_id`、parent `run_id`、child `run_id`、`batch_id`、`item_id` 是不同标识；
- `source_query_ids`、`source_run_ids`、`source_keywords` 是 provenance，不得丢失或靠字符串反推；
- Stage 1 的 `high/medium/low` 是算法分层，不是人工的“高度相关/部分相关/不相关”标签；
- OpenAlex v2 的页内/跨页 ID 去重是获取层防重复，不等于 W2 entity exact dedup；
- suspected duplicate 只进入人工复核队列，不得自动删除。

## 6. 开发边界

不要：

- 把业务逻辑复制进 `app/main.py` 或其他 CLI；
- 删除或暗改 v0.2.0 baseline；
- 为通过测试修改历史 fixture/evidence 的原始结论；
- 隐式选择 ranking keyword，丢弃 provenance，或自动删除 suspected duplicate；
- 把 AI-assisted label 表述为人工 ground truth；
- 为“更高级”而擅自替换算法、调权重或扩大 Issue 范围；
- 删除断言、放宽错误或把 error 降级为 warning 来换取通过；
- 提交普通 `outputs/experiments/`、`outputs/batches/` 或本地数据库。

优先复用现有模块，先搜索调用关系，再做最小修改；接口冲突要报告真实原因，不按常见项目结构猜测不存在的代码。修改行为时补定向测试，并在交付前运行全量离线测试和适用的 Quality Gate。

## 7. AI 使用与安全

AI 可以读取项目文件、搜索调用关系、运行离线测试与安全 fixture，并在 Issue 范围内修改代码、测试和文档。live 请求只有在任务确有必要、用户明确授权且本地配置合法时才运行，并保持最小规模。

`.env` 可能存在，但不得读取、输出、复制或记录其中内容。不得提交或泄露 `.env`、API Key、Token、密码、个人绝对路径、临时 live 配置、未经授权的 PDF 或个人敏感材料。

## 8. Git 工作流

```text
同步 main → 从 main 建独立任务分支 → 完成 Issue → 测试与门禁
→ 人工检查 diff → commit → push → PR → 审核 → main
```

禁止直接在 `main` 开发或推送。提交说明默认使用简洁中文。没有用户明确授权时，AI 不执行 `push`、合并、建标签或发布；不得用破坏性命令丢弃现有修改。

## 9. 必读导航

- [详细项目交接与 AI 开发入口](docs/project/AI_PROJECT_ONBOARDING.md)
- [当前仓库状态](docs/CURRENT_STATUS.md)
- [Unified Pipeline 使用与复现](docs/project/UNIFIED_PIPELINE_GUIDE.md)
- [批量实验指南](docs/project/BATCH_EXPERIMENT_GUIDE.md)
- [W2 数据接口约定](docs/project/W2_DATA_CONTRACTS.md)
- [v0.3.0 候选发布说明](docs/reports/week2/V0.3.0_RELEASE_NOTES.md)
- [贡献指南](CONTRIBUTING.md)
