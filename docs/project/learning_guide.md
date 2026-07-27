# 学习指南

这份指南面向刚开始学习 Python 项目的本科生。建议按下面顺序阅读：

阅读前先确认项目边界：真实数据来自 OpenAlex，不是 OpenAI；当前稳定功能不包含 PDF 解析。`preliminary_score` 只负责初步排序，不能解释为论文真实学术价值。

```text
1. app/main.py
2. src/mock_client.py
3. src/openalex_client.py
4. src/processor.py
5. src/storage.py
6. src/visualizer.py
7. README.md
```

## 1. app/main.py

它解决的问题：把整个流程串起来，让用户可以用一条命令运行项目。

输入：命令行参数，包括 `--mode`、`--keyword`、`--max-results`。

输出：调用其他模块后生成 CSV、SQLite、图表和运行摘要。

重点阅读函数：

- `parse_args`
- `main`
- `build_run_summary`

修改时注意：先看清楚 6 个步骤注释，不要把所有逻辑都塞进主程序。主程序应负责“串流程”，细节应放在 `src/` 模块。

## 2. src/mock_client.py

它解决的问题：在没有网络和 API Key 时读取本地 mock 数据，让项目稳定跑通。

输入：`data/mock_papers.json`、关键词、最大结果数。

输出：`raw_response` 和 `papers`。

重点阅读函数：

- `load_mock_papers`

修改时注意：mock 数据可以用来演示缺失字段和重复记录，但不要让代码在这里补造真实 DOI、作者或摘要。

## 3. src/openalex_client.py

它解决的问题：live 模式请求 OpenAlex，并把复杂 JSON 转成项目统一字段。

输入：关键词、最大结果数、环境变量 `OPENALEX_API_KEY`。

输出：`raw_response` 和统一字段论文列表。

重点阅读函数：

- `fetch_openalex_papers`
- `convert_openalex_work`
- `rebuild_abstract`

修改时注意：OpenAlex 返回字段可能缺失。字段缺失时保持为空或 `None`，不要猜测或编造。摘要的 `abstract_inverted_index` 是倒排索引，需要按位置还原。

v0.2 还应注意 `per_page` 单次最多为 100，当前没有实现分页；大于 100 的输入会被安全限制。

## 4. src/processor.py

它解决的问题：清洗字段、去重、统计缺失字段、计算初步文献排序分。

输入：原始论文列表和关键词。

输出：清洗论文、被去重记录、缺失统计、排序论文。

重点阅读函数：

- `clean_single_paper`
- `normalize_doi`
- `remove_duplicates`
- `add_preliminary_scores`
- `calculate_relevance_score`

修改时注意：这是最核心的教学模块。请优先保持规则简单、透明、可解释。不要在第一版加入模糊匹配、Embedding 或复杂评价模型。

重点观察 v0.2 的 `tokenize_english_text`：它让相关性评分比较完整英文数字词项，而不是用子字符串误匹配单词内部。

## 5. src/storage.py

它解决的问题：把内存里的结果保存成文件。

输入：原始响应、排序论文、去重记录、摘要文本。

输出：JSON、CSV、SQLite、txt。

重点阅读函数：

- `save_raw_response`
- `save_ranked_csv`
- `save_duplicates_csv`
- `save_to_sqlite`

修改时注意：SQLite 建表字段要和论文记录字段保持一致。第一版不使用 ORM，是为了让数据库写入逻辑更直接。

v0.2 的两个 CSV 使用固定字段列表，因此空结果也会保留可读表头。

## 6. src/visualizer.py

它解决的问题：生成两张基础柱状图，帮助演示结果。

输入：排序论文列表。

输出：两个 PNG 图表文件。

重点阅读函数：

- `generate_charts`
- `plot_top10_citations`
- `plot_top10_preliminary_scores`

修改时注意：第一版图表不追求复杂美化，优先保证标题、坐标轴和文件名清楚。

v0.2 会在图表标题中明确标记 `[MOCK DATA]` 或 `[OPENALEX LIVE]`，阅读图表时先确认数据来源。

## 7. README.md

它解决的问题：给第一次使用项目的人解释项目目标、安装方式、运行命令、输出文件和局限性。

输入：无。

输出：项目说明。

重点阅读内容：

- mock/live 运行命令
- 初步排序公式
- 评分局限性
- 后续可扩展方向

修改时注意：README 应保持面向使用者，不要写成代码内部实现细节清单。

## 8. 团队协作文档

开始修改前继续阅读：

- `contributing.md`：分支、Pull Request、安全和验证规则；
- `docs/collaboration/team_git_guide.md`：从 clone 到合并后同步 `main` 的命令；
- `docs/reports/week1/weekly_report_20260725.md`：第一周实际交付、核查结论和待确认事项；
- `docs/current_status.md`：第二周开始前的当前基线与下一步重点。
