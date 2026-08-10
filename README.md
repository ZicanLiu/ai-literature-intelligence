# astro-spectrum-literature-mvp

## 开发者 / AI Agent 开始前必读

如果准备开发新 Issue、让代码 AI 修改项目、从旧分支同步最新代码，或接手其他成员成果，请先阅读：

1. [`AGENTS.md`](AGENTS.md)：高优先级开发规则与安全边界；
2. [`AI Project Onboarding`](docs/project/AI_PROJECT_ONBOARDING.md)：当前架构、数据流和交接上下文；
3. [`Current Status`](docs/CURRENT_STATUS.md)：分支、版本、验证和待办快照。

不要直接根据旧代码、旧压缩包或历史聊天开始修改。

## 1. 项目简介

本项目是一个面向 SRTP 第一阶段演示的 Python MVP，用于完成“AI 在天文光谱数据处理中的应用文献”的智能检索、结构化处理与初步文献排序。

第一版目标是做出一条简单、稳定、可运行、适合本科生逐步读懂和二次开发的最小流程，而不是追求复杂系统。

兼容 baseline 为 **v0.2.0**；当前 `main` 已正式包含 W2 五项模块、Unified Pipeline 与
Batch Runner，并标记为 **v0.3.0**。W4 开始从工程集成转向科研问题、评价基准和 Pilot
Annotation。运行环境要求 **Python 3.10 或更高版本**。

当前验证状态：

- mock 模式已经完成完整流程验证，相关图表由教学样例生成；
- live 模式已使用 OpenAlex 完成小规模真实测试，详见
  [`docs/reports/live/LIVE_TEST_REPORT_20260718.md`](docs/reports/live/LIVE_TEST_REPORT_20260718.md)；
- `preliminary_score` 是透明的 baseline 排序规则，尚未经过人工评价数据验证；
- 当前结果不代表真实论文价值评价，mock 图表也不代表真实学术结论。

当前真实文献数据来自 **OpenAlex**，不是 OpenAI。稳定基线只包括文献获取、字段清洗、严格规则去重、初步排序、CSV、SQLite、图表和运行摘要。此前展示过的 PDF 解析只是临时演示，相关代码和文件已删除，不属于 v0.2.0 功能。

## 2. MVP 的输入、处理过程和输出

输入：

- 用户关键词，例如 `machine learning astronomical spectra`
- 运行模式：`mock` 或 `live`
- 最大结果数：例如 `20`

处理过程：

```text
关键词输入
→ OpenAlex 或 mock 数据
→ 字段标准化
→ DOI/标题去重
→ 缺失字段统计
→ 初步文献排序
→ CSV/SQLite 保存
→ 图表和运行摘要
```

输出：

- 每次运行对应一个 `outputs/experiments/<run_id>/`；
- 同一目录内保存运行配置、原始响应、CSV、SQLite、图表和运行摘要；
- `run_id` 包含时间、模式、关键词片段、请求数量和短随机标识，连续运行不会覆盖。

## 3. 为什么选择这个验证场景

“AI 在天文光谱数据处理中的应用”适合作为第一版验证场景，因为它同时具备明确的科研主题、相对稳定的文献元数据来源，以及可解释的基础处理流程。文献检索、元数据清洗、结构化保存和初步排序都能在较小代码量内演示出来，也方便后续扩展到摘要结构化、人工评价样本、PDF 全文解析等方向。

## 4. 与 DaAgents 的关系

本项目借鉴“数据获取—处理—结构化保存”的思想，但不直接复制数据库网页爬取流程，也不复制 da-agents 项目代码。

本项目把场景改为科研文献 API 获取、字段清洗、简单去重、初步排序和图表展示。第一版只保留最小可演示流程，避免多 Agent、RAG、复杂爬虫和大模型 API。

## 5. 安装步骤

建议在项目根目录运行：

```powershell
python -m pip install -r requirements.txt
```

依赖只有：

- `requests`
- `pandas`
- `matplotlib`
- `python-dotenv`

SQLite 使用 Python 自带的 `sqlite3`，不需要安装 ORM。

## 6. mock 模式运行命令

mock 模式不依赖网络，也不依赖 API Key：

```powershell
python -m app.main --mode mock --keyword "machine learning astronomical spectra" --max-results 20
```

程序会自动创建唯一实验目录。如需把验证结果写入临时位置，可使用：

```powershell
python -m app.main --mode mock --keyword "machine learning stellar spectra" --max-results 20 --output-root temp/test-runs --run-name readme-check
```

`--run-name` 可选；中文或特殊字符会被转换成安全目录片段，完整关键词始终保存在
`run_config.json`。

运行离线自动测试：

```powershell
python -m unittest discover -s tests/automated -p "test_*.py" -v
```

### W2 统一 Pipeline（v0.3.0）

离线端到端示例不会联网，也不会读取 API Key：

```powershell
python -m app.run_pipeline --query-ids q01_broad_ml q02_classification `
  --ranking-keyword "machine learning stellar parameter estimation spectra" `
  --mode offline --max-results-per-query 10 `
  --terms tests/fixtures/pipeline/domain_terms.csv `
  --offline-fixture tests/fixtures/pipeline/offline_queries.json `
  --labels tests/fixtures/pipeline/labels.csv
```

`--query-ids` 只决定获取范围；`--ranking-keyword` 必须显式提供，并统一用于合并候选集的
baseline 与两阶段排序。详细说明见
[`docs/project/UNIFIED_PIPELINE_GUIDE.md`](docs/project/UNIFIED_PIPELINE_GUIDE.md)。

三条离线 batch 示例：

```powershell
python -m app.batch_runner --config configs/w2/integration_batch.example.json
```

## 7. live 模式运行命令

live 模式会请求 OpenAlex：

```powershell
python -m app.main --mode live --keyword "machine learning astronomical spectra" --max-results 20
```

OpenAlex 当前官方文档要求 API key 通过 `api_key` 查询参数传入。请创建本地 `.env` 文件：

```text
OPENALEX_API_KEY=your_openalex_api_key_here
```

不要把真实 Key 写入代码、README、日志或 mock 数据。

OpenAlex 的 `per_page` 范围为 1—100。旧 `python -m app.main` 是 v0.2 baseline，单次
最多请求 100 条且不分页；如果 `--max-results` 大于 100，会自动限制为 100 条。新的
`python -m app.run_pipeline` 使用 OpenAlex v2，支持 cursor pagination 和多组
acquisition query。

## 8. 输出文件说明

| 文件（相对 `<run_id>/`） | 说明 |
| --- | --- |
| `run_config.json` | 参数、评分权重、数量、耗时、状态和输出文件相对路径 |
| `raw/raw_response.json` | 保存 OpenAlex 或 mock 的原始响应 |
| `tables/papers_ranked.csv` | 保存清洗、去重并完成初步排序后的论文表 |
| `tables/duplicates_removed.csv` | 保存被去重的论文及去重原因 |
| `figures/top10_citations.png` | 引用量最高的 Top 10 文献图 |
| `figures/top10_preliminary_score.png` | preliminary_score 最高的 Top 10 文献图 |
| `reports/run_summary.txt` | 保存数量统计、缺失字段统计和相对输出路径 |
| `data/literature.db` | 只保存本次运行排序论文的 SQLite 数据库 |

普通实验写入 `outputs/experiments/`，默认不提交。经过来源、安全和可复现性检查后，
确需长期保留的稳定结果才能提升到 `outputs/baselines/`。现有
`outputs/live_test_20260718/` 和已跟踪历史实验保留原路径，详情见
[`outputs/README.md`](outputs/README.md)。

### 当前目录分工

```text
app/                         命令行入口
src/                         获取、处理、输出管理、存储与可视化
data/{samples,manual,analysis}/ 固定样例、人工数据与分析表
docs/project/                长期项目说明
docs/collaboration/          Git 与团队协作规范
docs/reports/                周报、分析与 live 验证记录
tests/{automated,manual}/     离线自动测试与手工测试记录
outputs/baselines/           经确认的稳定基线
outputs/experiments/         默认生成、通常不提交的独立实验
outputs/batches/             默认生成、通常不提交的批量摘要
```

## 9. 初步排序公式

本项目统一称为“初步文献排序”或“初步辅助评价”，不称为“论文价值评价”。

```text
preliminary_score =
0.40 × relevance_score
+ 0.30 × impact_score
+ 0.20 × recency_score
+ 0.10 × completeness_score
```

其中：

- `relevance_score`：根据关键词词项在标题和摘要中是否出现计算，标题权重更高。
- `impact_score`：根据 `cited_by_count` 进行 `log1p` 转换，并在本批论文中归一化。
- `recency_score`：根据 `publication_year` 计算，近 10 年内越新的论文分数越高。
- `completeness_score`：根据 DOI、摘要、作者、年份、来源、链接等字段是否完整计算。

## 10. 评分局限性

这个分数只服务于第一版演示，不能说明某篇论文“学术价值更高”。它只利用标题、摘要、引用量、年份和字段完整度等有限信息，无法理解论文贡献、实验质量、方法创新性、领域影响或人工阅读后的判断。

v0.2 没有使用 TF-IDF、Embedding、RAG、大模型 API、Crossref 二次校验或人工标注样本，因此排序结果只适合作为初筛参考。

## 11. v0.2 更新内容

- 修正 OpenAlex 单页数量上限为 100，暂不实现分页；
- 修复关键词子字符串误匹配，改为完整英文数字词项匹配；
- 排序和去重 CSV 在零数据时仍保留稳定表头；
- 图表标题增加 `[MOCK DATA]` 或 `[OPENALEX LIVE]` 数据来源标识；
- 增加版本号和当前验证状态说明。
- 第二周开始前增加独立实验目录和离线自动测试，不改变评分公式的业务含义。

## 12. 常见问题

### mock 模式需要网络吗？

不需要。mock 模式只读取 `data/mock_papers.json`。

### live 模式失败怎么办？

请检查网络和 `.env` 中的 `OPENALEX_API_KEY`。如果只是演示流程，可以改用 `--mode mock`。

### 为什么去重规则这么简单？

第一版只做可靠、可解释的去重：有 DOI 时按 DOI 完全匹配；没有 DOI 时按标准化标题完全相同匹配。暂时不做模糊标题匹配或语义相似度匹配，避免误删。

### mock 数据是真实论文吗？

不是。`data/mock_papers.json` 是教学样例数据，用来稳定演示清洗、去重、缺失统计和排序流程。真实检索请使用 live 模式。

### 当前项目支持 PDF 解析吗？

不支持。此前的 PDF 解析只是临时演示，已从公开仓库中删除；当前稳定基线只处理文献元数据和摘要。

## 13. 六人协作入口

- 贡献规则：[`CONTRIBUTING.md`](CONTRIBUTING.md)
- 文档索引：[`docs/README.md`](docs/README.md)
- 当前状态：[`docs/CURRENT_STATUS.md`](docs/CURRENT_STATUS.md)
- Git 操作指南：[`docs/collaboration/TEAM_GIT_GUIDE.md`](docs/collaboration/TEAM_GIT_GUIDE.md)
- 第一周总结：[`docs/reports/week1/WEEKLY_REPORT_20260725.md`](docs/reports/week1/WEEKLY_REPORT_20260725.md)

所有任务都应从最新 `main` 创建短期分支，通过 Pull Request 合并，禁止直接向 `main` 推送。

### 第二周协作入口

- [第二周成果索引](docs/reports/week2/README.md)
- [第二周文件归属与协作边界](docs/collaboration/W2_FILE_OWNERSHIP.md)
- [第二周数据接口约定](docs/project/W2_DATA_CONTRACTS.md)

OpenAlex v2、两级去重、领域查询、质量门禁和 TF-IDF 两阶段排序已经进入 `main`；统一
Pipeline 与批量集成的实际状态、验证记录和限制见第二周成果索引。v0.2.0 入口继续保留
作为兼容 baseline。

### 第四周协作入口

- [W4 研究计划](docs/project/W4_RESEARCH_PLAN.md)
- [W4 Query Relevance 标注指南](docs/project/W4_ANNOTATION_GUIDELINE.md)
- [W4 Pilot Annotation 公共数据与任务命令](data/annotation_tasks/w4/README.md)

第四周公共准备只冻结研究问题、60 个 query-paper pair、双标 assignment、个人任务生成器
和格式 validator。当前仍是 Pilot Annotation 准备，不是已完成 benchmark、gold standard
或算法优劣结论。

## 14. 后续可扩展方向

- Crossref DOI 二次校验
- metadata fusion 与人工去重结论应用
- BM25、Embedding、混合排序或 learning-to-rank 对照实验
- 摘要大模型结构化提取
- 扩大并复核人工评价 benchmark
- Unified Pipeline 的 SQLite 与排序可视化
- 更完善的价值评价模型
- 多领域主题切换
- Web 前端
- PDF 全文解析
- RAG
- 多 Agent
