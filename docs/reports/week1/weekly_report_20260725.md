# SRTP 项目第 1 周工作总结

时间：2026 年 7 月 20 日—2026 年 7 月 25 日
项目：astro-spectrum-literature-mvp

## 一、本周目标

本周的重点是把已经可运行的 MVP 放进一轮可追溯的团队协作中：使用统一的 OpenAlex 真实样例，分别完成字段核查、领域检索词与人工相关性记录、测试材料和排序复核，并通过任务分支和 Pull Request 留下交付痕迹。

本周没有把重点放在增加复杂功能。当前稳定范围仍是文献获取、清洗、严格去重、初步排序、CSV、SQLite、图表和运行摘要。真实数据来源是 OpenAlex；`preliminary_score` 仅用于项目内部初步排序，不表示论文的真实学术价值。

## 二、GitHub 协作流程

本地 `main` 的最近历史中可以确认，成员交付对应的 Pull Request #10—#13 和 Pull Request #16 已合并。PR #14 和第一版周报 PR #15 后续分别由 PR #18 和 #17 回退，因此本报告只按当前 `main` 中仍然有效的文件统计。以合并统一 100 条样例的 PR #9（提交 `1b5c62f`）作为本轮成员交付前的可追溯基线，当前共新增 9 个有效交付文件：字段审计、排序复核、检索词与标注材料、测试占位文件，以及 Git 协作说明。

从合并记录可以确认，本周完成了一轮“任务分支 → Pull Request → 合并到 main”的协作闭环。当前本地 Git 历史不能可靠统计 GitHub Issue 总数、每个 PR 的在线审核讨论或参与成员人数，因此本报告不对这些数量作猜测，具体状态以 GitHub 页面为准。

武子恒提交的协作规范现归档在 `docs/collaboration/team_git_guide.md`。文档覆盖 Issue 确认、同步 `main`、创建短期分支、精确暂存、Commit、Push、创建 PR、处理审核意见、冲突和异常处理、安全边界，以及提交前检查清单。该文档明确不包含 Python 环境配置、依赖安装或项目运行方法。

## 三、成员交付成果核查

### 1. Git 协作规范

- `docs/collaboration/team_git_guide.md`：面向团队成员的 GitHub、VS Code 和终端协作说明。

文档给出了完整的标准协作顺序，说明了 `main` 与任务分支的边界，并提供分支命名、提交信息、PR 内容、安全检查、冲突处理和高风险命令提示。内容与当前团队通过 Issue、任务分支和 PR 开展协作的方向一致，基本满足本周 Git 协作说明的验收要求。

当前仓库中没有与该成员交付配套的全新环境复现报告或运行证据，因此本报告不再将环境复现写成该项已完成成果。

### 2. OpenAlex 字段质量检查

- `data/samples/openalex_stellar_spectra_100.csv`：统一样例，实际读取为 100 条、16 列，关键词均为 `machine learning stellar spectra`，100 个 OpenAlex ID 均不重复。
- `docs/reports/week1/openalex_field_audit_w1.md`：对全体样例的缺失统计，并对前 20 条进行逐条抽查。
- `data/analysis/openalex_field_audit_w1.csv`：18 条异常记录，对应 16 个不同的样例 ID；这 16 个 ID 都能在统一样例中找到。

本次实际重新统计与报告中的主要缺失数一致：`landing_page_url` 缺失 1 条、`source_name` 缺失 2 条、`doi` 缺失 4 条、`abstract` 缺失 4 条；标题、作者、年份、引用量和 OpenAlex ID 没有缺失。报告还记录了主题混入、标题 HTML 标记、摘要前缀和引用量极值等问题。字段核查有明确的数据来源和可复查记录，基本满足验收要求。

### 3. 领域检索词与人工相关性标注

- `docs/reports/week1/domain_query_guide_w1.md`：实际列出 5 条领域检索词，覆盖恒星光谱分类、大气参数估计、降噪、异常检测和特征提取。
- `data/manual/relevance_labels_w1.csv`：文件中有 20 条物理数据行。

这里需要保留一个待确认事项。该标注 CSV 第 17 行列数不符合表头：标题中的逗号未按 CSV 规则转义，因此只有 19 条记录可被严格解析；这 19 条的标签分布为高度相关 11 条、部分相关 4 条、不相关 4 条。更重要的是，这 19 个可解析的 OpenAlex ID 与统一 100 条样例没有重合。因此可以确认“已提交一份人工标注文件”，但目前不能确认它是否针对本周统一样例，也不应把它的标签比例写成对该样例的客观统计。该项状态为待人工确认。

### 4. MVP 测试

- `tests/manual/week1_test_cases.csv`
- `docs/reports/week1/test_report_w1_completed.md`

第一周合并时，根目录中的 `week1_test_cases.csv` 和 `week1_test_report.md` 均为
0 字节，因此本周总结当时无法确认独立测试交付。第二周基线整理已保留这一历史判断，
删除空占位，并补充离线自动测试、实际手工测试记录和报告；补充结果不追溯为原成员交付。

作为合并后的整合验证，本次在当前代码上实际运行：

```powershell
python -m app.main --mode mock --keyword "machine learning astronomical spectra" --max-results 20
```

返回码为 0；原始 20 条、清洗后 20 条、去重后 18 条、重复 2 条；CSV、SQLite、两张图表和运行摘要均生成。这是项目负责人进行的回归检查，不替代尚未确认的成员测试记录。

### 5. 初步排序结果分析

- `docs/reports/week1/ranking_analysis_w1.md`
- `data/analysis/ranking_cases_w1.csv`

排序复核表实际包含 20 条、10 列，20 个 OpenAlex ID 均能在统一样例中找到。文件中的人工判断为相关 13 条、部分相关 2 条、不相关 5 条；问题标记包括 3 条相关性词项误匹配、3 条由高引用或新近性带入前列的情况、2 条边界案例和 1 条星系光谱对象不匹配。

这些是成员对前 20 名的人工复核结果，不是对整个 100 条样例的客观准确率。它揭示了词项匹配会把 `power spectra`、`stellar masses` 等语境误判为主题相关，也说明引用量和年份可以抬高通用机器学习论文的位置。报告没有把 `preliminary_score` 表述为论文价值评价，基本满足本周排序分析要求。

## 四、组长整合工作

本次整合以已合并的 `main`、实际文件和可重复的统计为依据完成：

- 核对 PR #10—#13、PR #16 合并后仍然有效的文件和路径；
- 检查统一 OpenAlex 样例、字段审计、排序复核和标注文件的行数、列数、ID 关联与格式；
- 区分可验证结论、成员人工判断与暂未确认事项；
- 运行一次不依赖真实 API Key 的 mock 回归；
- 根据武子恒实际提交的 Git 协作说明修订本周总结和组会展示提纲。

分支保护设置、Issue 的创建与分配过程、线上审核讨论等 GitHub 页面信息无法仅凭本地仓库确认，未在本报告中写成既成事实。

## 五、本周形成的阶段成果

- 一轮可在 Git 历史中确认的成员 PR 合并记录（PR #10—#13、PR #16）。
- 100 条统一 OpenAlex live 样例：`data/samples/openalex_stellar_spectra_100.csv`。
- OpenAlex 字段质量检查材料：`docs/reports/week1/openalex_field_audit_w1.md`、`data/analysis/openalex_field_audit_w1.csv`。
- 5 条领域检索词：`docs/reports/week1/domain_query_guide_w1.md`。
- 一份需要继续核对来源和格式的人工相关性标注文件：`data/manual/relevance_labels_w1.csv`。
- 前 20 名初步排序人工复核：`docs/reports/week1/ranking_analysis_w1.md`、`data/analysis/ranking_cases_w1.csv`。
- 团队 Git 协作规范：`docs/collaboration/team_git_guide.md`。

## 六、本周主要发现

1. 统一样例的核心字段缺失率较低，但 DOI 和摘要各有 4 条缺失，来源和落地页也有少量缺失，后续需要在不编造数据的前提下处理。
2. OpenAlex 普通关键词检索会混入跨领域论文；字段审计和前 20 名复核都发现了与恒星光谱无关的记录。
3. 当前完整词项相关性不能理解词义边界，`spectra`、`stellar` 等词在不同天文或非天文学语境中会造成误匹配。
4. 当前影响力和新近性分数与主题相关性解耦，可能把高被引的非主题论文推高；`completeness_score` 在前 20 名中没有提供区分度。
5. 人工标注文件尚未与统一样例建立可复查关联，且存在 CSV 转义问题；测试方向目前没有可验证的仓库内容。

## 七、当前不足

- 真实统一样例只有 100 条，且只代表一次检索与排序结果，不是完整或权威的天文光谱文献集。
- 人工相关性标注数量和格式尚不稳定，当前无法作为排序验证集。
- 初步排序权重尚未经过可追溯的人工评价数据验证；严格去重仍主要依据 DOI 或完全相同标题。
- 第一周结束时默认运行结果会被后续运行覆盖；第二周基线整理已改为每次创建唯一
  `outputs/experiments/<run_id>/`，普通实验仍默认不提交。
- 测试 PR 的两个根目录文件在第一周合并时为空；第二周基线整理已用实际测试成果替代，
  但该补充不改变第一周原交付的核查结论。
- 当前 Git 协作说明没有覆盖 Python 环境复现，后续如需形成统一环境记录，应单独安排并保留实际运行证据。

## 八、下一周计划

1. 先修复并核对人工标注 CSV：使用统一样例中的 OpenAlex ID，明确标注口径，并重新统计可用样本。
2. 把字段核查和排序复核中已经确认的问题转成独立 Issue，优先讨论主题相关性门槛、标题 HTML 清理和摘要文本处理，不直接调整评分权重。
3. 为每次实验使用独立输出目录和简短说明，避免默认运行结果互相覆盖。
4. 补充实际可执行的命令行测试用例和测试报告，覆盖 mock 正常流程、参数边界和空结果等场景。
5. 在人工标注样本扩大后，再设计“确定重复 + 疑似重复人工复核”的小规模机制。
6. 继续按照 `docs/collaboration/team_git_guide.md`，使用 Issue、短期分支和 Pull Request 管理每个可验收任务。

本周不建议直接加入 RAG、知识图谱、多 Agent 或 PDF 全文解析。这些方向应建立在检索质量、人工标注和基础测试更稳定之后。

## 九、本周交付文件索引

| 任务方向 | 文件路径 | 内容概括 | 状态 |
| --- | --- | --- | --- |
| 统一真实样例 | `data/samples/openalex_stellar_spectra_100.csv` | 100 条 OpenAlex live 元数据与项目评分字段 | 已完成 |
| Git 协作规范 | `docs/collaboration/team_git_guide.md` | Issue、分支、Commit、Push、PR、审核、安全和异常处理说明 | 已完成 |
| 字段质量 | `docs/reports/week1/openalex_field_audit_w1.md`、`data/analysis/openalex_field_audit_w1.csv` | 100 条样例缺失统计、前 20 抽查与异常记录 | 已完成但需继续完善 |
| 检索词 | `docs/reports/week1/domain_query_guide_w1.md` | 5 条天文光谱领域检索词 | 已完成 |
| 人工相关性标注 | `data/manual/relevance_labels_w1.csv` | 20 条物理行；其中 1 行格式异常，且无法关联统一样例 | 待人工确认 |
| 排序复核 | `docs/reports/week1/ranking_analysis_w1.md`、`data/analysis/ranking_cases_w1.csv` | 前 20 名人工复核与透明改进建议 | 已完成但需继续完善 |
| 命令行测试 | `tests/manual/week1_test_cases.csv`、`docs/reports/week1/test_report_w1_completed.md` | 第二周基线整理补充的实际测试，不追溯为原成员交付 | 已补充 |
