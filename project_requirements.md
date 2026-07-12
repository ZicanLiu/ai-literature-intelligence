你现在作为本项目的开发助手，请从零开始创建一个独立、简单、可运行、结构清晰、适合本科生逐步学习和后续二次开发的 Python 项目。

项目名称：

astro-spectrum-literature-mvp

项目主题：

“AI 在天文光谱数据处理中的应用文献的智能检索、结构化处理与初步排序”。

这是 SRTP 项目的第一阶段 MVP。第一版的核心目标不是追求复杂功能，而是先做出一条完整、稳定、能演示、能逐步读懂的最小流程。

请严格控制复杂度。第一版暂时不要实现 LangGraph、多 Agent、RAG、PDF 全文解析、Embedding、TF-IDF、Crossref 二次校验、模糊语义去重、网页前端、Streamlit、知识图谱、复杂测试框架或大模型 API。

项目应完成以下流程：

用户输入关键词
→ 从 OpenAlex 获取论文，或读取本地 mock 数据
→ 标准化论文元数据
→ 按 DOI 和标题去重
→ 根据简单可解释规则计算初步排序分
→ 保存到 CSV 和 SQLite
→ 生成两张基础图表和一份运行摘要

项目最终运行效果示例：

```powershell
python -m app.main --mode mock --keyword "machine learning astronomical spectra" --max-results 20
```

或：

```powershell
python -m app.main --mode live --keyword "machine learning astronomical spectra" --max-results 20
```

其中：

* `mock` 模式必须不依赖网络、不依赖 API Key，也能完整跑通；
* `live` 模式调用 OpenAlex；
* OpenAlex 的接口地址、认证方式和请求参数，请优先查询当前官方文档实现；
* API Key 如有需要，只能从 `.env` 或环境变量读取；
* 不要在代码、README、日志、mock 数据中写入真实 Key；
* 不要修改当前目录之外的文件；
* 不要修改或复制 da-agents 项目；
* 不要执行 git push 或删除已有文件。

第一版只需要提取和保存以下字段：

* title
* authors
* publication_year
* doi
* abstract
* cited_by_count
* source_name
* openalex_id
* landing_page_url
* keyword
* retrieved_at

数据清洗要求：

1. 去除标题、作者、DOI 前后的多余空格；
2. DOI 统一为小写、去除 `https://doi.org/` 前缀；
3. 缺失字段统一为 None 或空字符串；
4. 不允许编造 DOI、作者、摘要、期刊、引用量等信息；
5. 输出缺失字段数量统计；
6. 对 DOI 重复的论文直接去重；
7. DOI 缺失时，按标准化标题完全相同去重；
8. 只做简单可靠的去重，不做模糊匹配或语义相似度匹配；
9. 保留被去重记录及其去重原因。

初步排序要求：

第一版不要叫“论文价值评价”，统一叫：

“初步文献排序”或“初步辅助评价”。

请使用简单、透明、可解释的规则计算：

```text
preliminary_score =
0.40 × relevance_score
+ 0.30 × impact_score
+ 0.20 × recency_score
+ 0.10 × completeness_score
```

其中：

* relevance_score：根据用户关键词在论文标题和摘要中出现的情况计算；
* impact_score：根据 cited_by_count 经 log1p 和归一化处理计算；
* recency_score：根据 publication_year 计算，较近论文分数更高；
* completeness_score：DOI、摘要、作者、年份、来源、链接等字段越完整，得分越高；
* 所有评分逻辑都必须写得简单、透明，并在 README 中说明局限性；
* 不要让 AI 或程序直接宣称某篇论文“学术价值更高”。

请使用尽量少、容易理解的依赖：

```text
requests
pandas
matplotlib
python-dotenv
```

数据库请使用 Python 自带的 `sqlite3`，不要额外安装 ORM。

建议目录结构如下，不要为了炫技拆得过细：

```text
astro-spectrum-literature-mvp/
├─ README.md
├─ requirements.txt
├─ .gitignore
├─ .env.example
├─ data/
│  ├─ mock_papers.json
│  └─ literature.db
├─ app/
│  ├─ __init__.py
│  └─ main.py
├─ src/
│  ├─ __init__.py
│  ├─ openalex_client.py
│  ├─ mock_client.py
│  ├─ processor.py
│  ├─ storage.py
│  ├─ visualizer.py
│  └─ utils.py
├─ outputs/
│  ├─ raw/
│  ├─ tables/
│  ├─ figures/
│  └─ reports/
└─ docs/
   ├─ architecture.md
   ├─ learning_guide.md
   └─ future_roadmap.md
```

每个文件的职责建议如下：

* `app/main.py`：命令行入口，串起完整流程；
* `src/openalex_client.py`：请求 OpenAlex 并转换原始数据；
* `src/mock_client.py`：读取本地 mock 数据；
* `src/processor.py`：清洗、去重、缺失统计、初步排序；
* `src/storage.py`：保存 CSV、SQLite、原始 JSON；
* `src/visualizer.py`：生成图表；
* `src/utils.py`：通用小函数，避免主程序太乱。

运行结束后至少生成：

```text
outputs/raw/raw_response.json
outputs/tables/papers_ranked.csv
outputs/tables/duplicates_removed.csv
outputs/figures/top10_citations.png
outputs/figures/top10_preliminary_score.png
outputs/reports/run_summary.txt
data/literature.db
```

图表要求：

1. 引用量最高的 Top 10 文献柱状图；
2. preliminary_score 最高的 Top 10 文献柱状图；
3. 使用 matplotlib；
4. 图表标题、坐标轴和文件名清楚；
5. 不要求复杂美化，优先保证可读。

异常处理要求：

* 网络请求失败时给出清楚提示；
* live 模式无法访问 OpenAlex 时提示改用 mock 模式；
* 返回论文为空时不要崩溃；
* 字段缺失时正常处理；
* SQLite 写入失败时给出可读报错；
* 在主程序终端输出每一步正在做什么。

代码可读性和注释要求非常重要：

1. 所有代码使用清晰、基础的 Python 写法，不要使用难懂的高级语法、复杂继承、过度封装、异步代码或花哨设计模式。

2. 每一个 Python 文件开头都必须有一段中文模块说明，写清楚：

   * 这个文件负责什么；
   * 它在整个项目流程中的位置；
   * 它的输入和输出大致是什么。

3. 每一个核心函数必须有中文 docstring，至少说明：

   * 函数做什么；
   * 参数含义；
   * 返回什么；
   * 可能出现什么异常或特殊情况。

4. 对以下位置必须写详细中文行内注释：

   * OpenAlex 返回 JSON 如何提取字段；
   * DOI 和标题如何标准化；
   * 去重判断为什么这样写；
   * 分数如何计算；
   * SQLite 建表和写入逻辑；
   * 图表数据如何筛选和排序；
   * 主程序每一步的数据流向。

5. 不要求每一行都写无意义注释，例如不要写：
   `i = i + 1  # i 加 1`
   而是要在关键逻辑块前写“为什么这么做”。

6. `app/main.py` 中请明确用步骤注释分隔流程，例如：

```python
# 第 1 步：读取命令行参数
# 第 2 步：获取 OpenAlex 或 mock 文献数据
# 第 3 步：清洗字段并完成去重
# 第 4 步：计算初步排序分
# 第 5 步：保存结果
# 第 6 步：生成图表和运行摘要
```

7. 单个函数尽量不要过长；当一个函数超过约 50 行时，优先拆成更容易理解的小函数。

8. 变量命名必须清晰，例如：

   * `raw_papers`
   * `cleaned_papers`
   * `ranked_papers`
   * `duplicate_records`
     不要使用 `a`、`b`、`data1`、`tmp` 这种难以理解的命名。

9. 每个核心模块都要让初学者能够单独运行、单独阅读和单独修改。

README 必须包含：

1. 项目简介；
2. MVP 的输入、处理过程和输出；
3. 为什么选择“AI 在天文光谱数据处理中的应用”作为验证场景；
4. 与 DaAgents 的关系：

   * 借鉴“数据获取—处理—结构化保存”的思想；
   * 不直接复制数据库网页爬取；
   * 改为科研文献 API 获取、清洗、排序和展示；
5. 安装步骤；
6. mock 模式运行命令；
7. live 模式运行命令；
8. 输出文件说明；
9. 初步排序公式；
10. 评分局限性；
11. 常见问题；
12. 后续可扩展方向。

`docs/architecture.md` 必须用中文解释完整数据流：

```text
关键词输入
→ OpenAlex 或 mock 数据
→ 字段标准化
→ DOI/标题去重
→ 缺失字段统计
→ 初步排序
→ CSV/SQLite 保存
→ 图表和运行摘要
```

`docs/learning_guide.md` 必须面向刚学习 Python 项目的本科生，说明推荐阅读顺序：

```text
1. app/main.py
2. src/mock_client.py
3. src/openalex_client.py
4. src/processor.py
5. src/storage.py
6. src/visualizer.py
7. README.md
```

并对每个文件说明：

* 它解决什么问题；
* 输入和输出是什么；
* 最值得重点读的函数；
* 初学者修改它时应注意什么。

`docs/future_roadmap.md` 请明确列出第一版暂时不做、后续再做的功能：

* Crossref DOI 二次校验；
* 标题模糊去重；
* TF-IDF 或 Embedding 语义相关性；
* 摘要大模型结构化提取；
* 人工评价样本；
* 更完善的价值评价模型；
* 多领域主题切换；
* Web 前端；
* PDF 全文解析；
* RAG；
* 多 Agent。

工作流程要求：

1. 先简要展示你准备创建的目录结构和开发计划；
2. 随后直接在一个新的独立项目文件夹中创建所有文件；
3. 创建真实、可运行的代码，不要只给伪代码；
4. 可以执行必要的创建文件、安装依赖和运行命令；
5. 在安装依赖前先简要说明将安装哪些包；
6. 使用 mock 模式完整运行一次；
7. 修复普通运行错误；
8. 最后输出：

   * 最终文件树；
   * mock 模式运行结果摘要；
   * 生成了哪些 CSV、SQLite、图表和报告；
   * 后续最值得先读的三个文件；
   * 第一版已完成内容；
   * 第一版刻意未实现的内容。
