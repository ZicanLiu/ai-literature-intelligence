# astro-spectrum-literature-mvp

## 1. 项目简介

本项目是一个面向 SRTP 第一阶段演示的 Python MVP，用于完成“AI 在天文光谱数据处理中的应用文献”的智能检索、结构化处理与初步文献排序。

第一版目标是做出一条简单、稳定、可运行、适合本科生逐步读懂和二次开发的最小流程，而不是追求复杂系统。

当前版本：**v0.2**。运行环境要求 **Python 3.10 或更高版本**。

当前验证状态：

- mock 模式已经完成完整流程验证，相关图表由教学样例生成；
- live 模式代码入口已实现，但必须使用真实网络环境和合法 API Key 单独验证；
- `preliminary_score` 是透明的 baseline 排序规则，尚未经过人工评价数据验证；
- 当前结果不代表真实论文价值评价，mock 图表也不代表真实学术结论。

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

- `outputs/raw/raw_response.json`
- `outputs/tables/papers_ranked.csv`
- `outputs/tables/duplicates_removed.csv`
- `outputs/figures/top10_citations.png`
- `outputs/figures/top10_preliminary_score.png`
- `outputs/reports/run_summary.txt`
- `data/literature.db`

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

OpenAlex 的 `per_page` 范围为 1—100。本项目 v0.2 单次最多请求 100 条；如果 `--max-results` 大于 100，live 请求会自动限制为 100 条。当前暂不实现分页。

## 8. 输出文件说明

| 文件 | 说明 |
| --- | --- |
| `outputs/raw/raw_response.json` | 保存 OpenAlex 或 mock 的原始响应 |
| `outputs/tables/papers_ranked.csv` | 保存清洗、去重并完成初步排序后的论文表 |
| `outputs/tables/duplicates_removed.csv` | 保存被去重的论文及去重原因 |
| `outputs/figures/top10_citations.png` | 引用量最高的 Top 10 文献图 |
| `outputs/figures/top10_preliminary_score.png` | preliminary_score 最高的 Top 10 文献图 |
| `outputs/reports/run_summary.txt` | 保存本次运行的数量统计、缺失字段统计和输出路径 |
| `data/literature.db` | SQLite 数据库，保存最近一次运行的排序论文 |

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

## 12. 常见问题

### mock 模式需要网络吗？

不需要。mock 模式只读取 `data/mock_papers.json`。

### live 模式失败怎么办？

请检查网络和 `.env` 中的 `OPENALEX_API_KEY`。如果只是演示流程，可以改用 `--mode mock`。

### 为什么去重规则这么简单？

第一版只做可靠、可解释的去重：有 DOI 时按 DOI 完全匹配；没有 DOI 时按标准化标题完全相同匹配。暂时不做模糊标题匹配或语义相似度匹配，避免误删。

### mock 数据是真实论文吗？

不是。`data/mock_papers.json` 是教学样例数据，用来稳定演示清洗、去重、缺失统计和排序流程。真实检索请使用 live 模式。

## 13. 后续可扩展方向

- Crossref DOI 二次校验
- 标题模糊去重
- TF-IDF 或 Embedding 语义相关性
- 摘要大模型结构化提取
- 人工评价样本
- 更完善的价值评价模型
- 多领域主题切换
- Web 前端
- PDF 全文解析
- RAG
- 多 Agent
