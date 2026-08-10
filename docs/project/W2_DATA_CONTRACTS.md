# 第二周数据接口约定

本文统一第二周模块之间共享字段的名称和含义。它是协作接口，不要求每个文件都包含
全部字段；各模块可以增加任务专用字段，但不得随意改名或改变下列公共字段的含义。

## 1. OpenAlex 整理样例

| 字段 | 推荐格式 | 含义与约束 |
| --- | --- | --- |
| `query_id` | 非空字符串 | 查询配置中的稳定、唯一编号 |
| `keyword` | 字符串 | 实际发送的完整关键词，不用简称替代 |
| `run_id` | 非空字符串 | 产生该记录的实验目录编号 |
| `openalex_id` | OpenAlex URL | 使用统一的 `https://openalex.org/W...` 形式；缺失时留空 |
| `doi` | 字符串 | 推荐使用去掉 URL 前缀并转为小写的 DOI；文件说明必须写明是否已标准化 |
| `title` | 字符串 | 论文标题；缺失时留空，不编造 |
| `authors` | 字符串或数组 | CSV 沿用以 `; ` 分隔的作者字符串，JSON 推荐使用字符串数组；文件说明应明确形式 |
| `publication_year` | 四位整数或空值 | 不用当前年份替代缺失年份 |
| `abstract` | 字符串 | OpenAlex 可用摘要；缺失时留空 |
| `cited_by_count` | 非负整数或空值 | 不用 `0` 伪装未知值 |
| `source_name` | 字符串 | 期刊、会议或其他来源名称 |
| `landing_page_url` | URL 或空值 | 公开落地页链接 |

这些字段描述公开论文元数据和来源，不代表论文内容已经经过人工确认。

## 2. 来源追踪

| 字段 | 含义 |
| --- | --- |
| `query_id` | 查询配置中的稳定编号 |
| `keyword` | 实际发送的完整关键词 |
| `run_id` | 实际实验目录编号 |
| `source_query_ids` | 同一论文来自多组查询时的 `query_id` 集合；序列化方式须在文件说明中注明 |
| `source_run_ids` | 实际产生该论文的 child request/run ID 集合，不从字符串反向解析 query ID |
| `source_keywords` | 命中该论文的 acquisition keyword 集合 |
| `first_seen_run_id` | 候选记录在当前项目中首次出现的实验编号 |
| `evidence_source` | 人工判断依据，例如标题、摘要、落地页或人工阅读记录 |

来源字段必须能从配置、实验目录或说明文件追溯。无法确认的值留空并说明，不自行推断。
统一 Pipeline 内存中三个 `source_*` 字段均为 `list[str]`；写入 CSV 时使用 JSON array
字符串，读取时必须解析回数组。`query_id`、child run ID 和 parent run ID 是三类不同标识。

## 3. 人工标注

| 字段 | 含义 |
| --- | --- |
| `annotation_id` | 一条标注的稳定唯一编号 |
| `openalex_id` | 被标注论文的稳定 OpenAlex ID |
| `label` | 领域相关性标签 |
| `reason` | 标注理由或证据摘要 |
| `annotator` | 项目内约定的标注者标识 |
| `review_status` | `待复核`、`已确认` 或 `有争议` |

第二周允许的 `label` 值只有：

- `高度相关`
- `部分相关`
- `不相关`
- `待讨论`

`preliminary_score` 不能自动生成标签；未标注论文也不能自动视为不相关。

## 4. 疑似重复

| 字段 | 推荐格式与含义 |
| --- | --- |
| `pair_id` | 一组候选记录的稳定唯一编号 |
| `left_id` | 左侧论文的稳定标识，优先 OpenAlex ID |
| `right_id` | 右侧论文的稳定标识，优先 OpenAlex ID |
| `title_similarity` | 标题相似度；取值范围和算法必须在报告中说明 |
| `author_overlap` | 作者重合指标；计算方式必须在报告中说明 |
| `year_difference` | 两条记录发表年份差的绝对值，缺失时留空 |
| `suspected_reason` | 进入疑似队列的可解释原因 |
| `review_status` | `待复核`、`已确认` 或 `有争议` |

疑似重复只用于生成复核队列，不得自动删除。确定重复与疑似重复必须在报告中分别统计。

## 5. 排序与评价

| 字段 | 含义 |
| --- | --- |
| `baseline_preliminary_score` | v0.2.0 当前 `preliminary_score` 的基线副本 |
| `title_relevance_score` | 标题的词法相关性分数 |
| `abstract_relevance_score` | 摘要的词法相关性分数 |
| `combined_relevance_score` | 标题和摘要相关性的组合分数 |
| `stage1_relevance_score` | 第一阶段相关性筛选分数 |
| `stage1_relevance_level` | 固定阈值产生的 `high`、`medium` 或 `low` 分层 |
| `stage2_ranking_score` | 第二阶段综合排序分数 |
| `old_rank` | 基线排序名次，使用从 1 开始的整数 |
| `new_rank` | 新方案排序名次，使用从 1 开始的整数 |
| `rank_change` | `old_rank - new_rank`，正数表示新排序上升 |

分数字段的取值范围、缺失值处理和计算版本必须在对应报告中说明。TF-IDF 只是词法相关性
基线，不代表真正的语义理解；人工标签只用于离线评价，不直接进入线上评分。

## 6. 通用格式

- CSV 使用 UTF-8 或 UTF-8 with BOM，第一行必须是唯一、非空表头；
- 逗号、换行和双引号按 CSV 规则转义；
- JSON 使用 UTF-8；
- 缺失值留空或使用文档明确约定的表示，不使用虚构默认值；
- 路径优先写成相对仓库根目录的形式，不写个人绝对路径；
- 文件不得包含 API Key、Token 或 `.env` 内容；
- 时间使用 ISO 8601，或在文件说明中写明统一格式和时区；
- 所有统计数字必须可以从实际文件重新计算。
