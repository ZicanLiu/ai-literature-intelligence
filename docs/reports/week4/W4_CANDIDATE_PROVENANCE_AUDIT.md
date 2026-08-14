# W4 Candidate Pool 来源与 Provenance 核查

## 1. 目的与范围

本报告核查冻结的 W4 Pilot Candidate Pool v0.1 的来源、Research Query 覆盖、
provenance 结构和元数据完整性，服务于 RQ1 的后续检索方式比较及 Candidate Pool
扩充设计。本次只分析已提交数据，不修改 Candidate Pool，不重新运行选样排序，不评价论文
绝对质量，也没有发起 OpenAlex live 请求。

核查输入如下：

- `data/annotation_tasks/w4/candidate_pool_v0.1.csv`；
- `data/annotation_tasks/w4/pool_manifest_v0.1.json`；
- `configs/w4/research_queries.json`；
- `data/samples/w2/domain_query/live_query_sample.csv`；
- `data/annotation_tasks/w4/assignments_v0.1.csv`；
- `data/annotation_tasks/w4/annotation_template.csv`。

逐 pair 的核查结果见 `data/analysis/w4_candidate_provenance_audit.csv`。

## 2. 核查方法与数据约定

CSV 按 UTF-8 with BOM 兼容方式读取，`source_query_ids` 和 `source_run_ids` 按 JSON
array string 解析。与 W2 来源样例对照时，来源样例中的分号序列先解析为列表，再做语义
比较，不把两种序列化文本的字面差异视为 provenance 漂移。

核查内容包括：

1. pair 总数、每个 Research Query 的 pair 数和 `research_query_id + openalex_id`
   唯一性；
2. OpenAlex ID 的完整性及 `https://openalex.org/W...` 格式；
3. DOI、abstract 和 landing page 的缺失情况；
4. `acquisition_query_id` 与机器可读配置是否一致，且是否实际存在于
   `source_query_ids`；
5. 两个 provenance 数组是否非空、可解析、无重复，并保持相同元素数量；
6. Candidate Pool 的标题、摘要、年份、DOI、landing page 和 provenance 是否与 W2
   来源样例一致；
7. 同一 OpenAlex work 跨 Research Query 共现时，各 pair 的元数据和 provenance 是否
   一致；
8. manifest 中来源文件和冻结产物的 SHA-256 是否与当前文件一致。

审计 CSV 中的布尔值统一为小写 `true`/`false`，数组继续使用 JSON array string。缺失
信息保留为空，不生成替代值。`provenance_status=ok` 只表示上述结构与来源对照通过，不
表示论文与 Research Query 相关。

## 3. Candidate Pool 总体统计

| Research Query | Pair 数 | RQ 内 unique paper | DOI 缺失 | Abstract 缺失 | Landing page 缺失 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `rq01_stellar_classification` | 20 | 20 | 0 | 1 | 0 |
| `rq02_stellar_parameters` | 20 | 20 | 0 | 2 | 0 |
| `rq03_spectral_preprocessing` | 20 | 20 | 0 | 0 | 1 |
| 合计 | 60 | 57（跨 RQ 去重） | 0 | 3 | 1 |

三个 Research Query 均为 20 个 pair，符合 Pilot v0.1 的 3×20 设计。60 个 pair 对应
57 个唯一 OpenAlex work；同一个 `research_query_id + openalex_id` 没有重复。

60 条记录的 OpenAlex ID 均非空且格式有效；所有 DOI 均非空、使用小写且没有 DOI URL
前缀。59 个非空 landing page 均为 HTTP(S) URL。没有发现因为 ID 缺失而无法稳定对齐
论文的记录。

## 4. 来源 Query 覆盖

### 4.1 每个 Research Query 的来源覆盖

| Research Query | 配置的 acquisition query | 预期来源覆盖 | 额外来源 provenance |
| --- | --- | ---: | --- |
| `rq01_stellar_classification` | `q02_classification` | 20/20 | `q03_parameters`: 3；`q04_preprocessing`: 2 |
| `rq02_stellar_parameters` | `q03_parameters` | 20/20 | `q02_classification`: 3 |
| `rq03_spectral_preprocessing` | `q04_preprocessing` | 20/20 | `q02_classification`: 2 |

每个 pair 的 `acquisition_query_id` 均与 `research_queries.json` 一致，并且都存在于该
pair 的 `source_query_ids` 中。W2 来源样例对 q02、q03、q04 各有 30 个 eligible work，
与 manifest 记录一致。

### 4.2 全池 provenance 分布

| Source query | 按 60 个 pair 统计的 membership | 按 57 篇 unique paper 统计的 membership |
| --- | ---: | ---: |
| `q02_classification` | 25 | 22 |
| `q03_parameters` | 23 | 22 |
| `q04_preprocessing` | 22 | 20 |

这些 membership 不能相加解释为论文总数，因为一个 work 可以由多个 acquisition query
共同命中，同一 work 也可能在不同 Research Query 下形成不同 pair。57 篇 unique work 中
有 7 篇具有多 query provenance，其中 3 篇最终跨 Research Query 进入 Candidate Pool。

所有 `source_query_ids` 和 `source_run_ids` 均可解析、非空且没有重复值；两者在每条记录
中的元素数量一致。审计没有通过 run ID 字符串反推 query ID，只核对已保存数组的结构与
来源样例。

## 5. 跨 Research Query 共现

| OpenAlex ID | Pair | 共现 Research Query | Source query | 核查判断 |
| --- | --- | --- | --- | --- |
| `W2777402735` | `w4_rq01_011`、`w4_rq02_014` | RQ01、RQ02 | q02、q03 | Carbon star 识别同时被分类与参数检索命中，跨 RQ provenance 完整；两个 pair 应独立判断 relevance。 |
| `W3155899199` | `w4_rq01_014`、`w4_rq03_003` | RQ01、RQ03 | q02、q04 | 标题显示为无线通信调制识别综述，属于检索可能产生的领域外/hard-negative 型命中；来源记录本身一致，不是重复错误。 |
| `W4384201335` | `w4_rq01_006`、`w4_rq03_020` | RQ01、RQ03 | q02、q04 | 主题为 solar physics，属于相邻领域的宽泛命中；跨 RQ provenance 有来源支持，不能在审计阶段删除。 |

三篇共现 work 的标题、摘要、年份、DOI、landing page、`source_query_ids` 和
`source_run_ids` 在各自 pair 间均一致。跨 RQ 共现反映同一论文被多个 acquisition query
命中并在不同 query-dependent relevance 场景中入选，不构成 Candidate Pool 重复错误。

## 6. 元数据缺失与标注影响

| Pair | Research Query | 缺失字段 | 可能影响 |
| --- | --- | --- | --- |
| `w4_rq01_017` | RQ01 | abstract | 只有标题不足以确认任务边界时，需要升级到 ADS/SciX、arXiv、publisher 或 DOI 页面。 |
| `w4_rq02_001` | RQ02 | abstract | 无法仅凭池内摘要判断是否从恒星光谱估计参数，建议使用外部可靠页面。 |
| `w4_rq02_015` | RQ02 | abstract | 无法仅凭池内摘要确认参数推断的输入与核心输出，建议使用外部可靠页面。 |
| `w4_rq03_004` | RQ03 | landing page | 摘要和 DOI 均存在；Title + Abstract 足够时不影响 A 级判断，需要外部证据时可从 DOI 页面继续。 |

缺失元数据只影响可用证据，不代表论文不相关。前三条缺摘要记录更可能增加人工判断成本；
缺 landing page 的一条记录仍保留摘要与 DOI，影响相对有限。

## 7. Manifest 与来源一致性

| 文件 | 当前 SHA-256 | 与 manifest 一致 |
| --- | --- | --- |
| `candidate_pool_v0.1.csv` | `25f608eb4c94218dfa220ba108b15ec846b2bd418174501420a468c376ed17cc` | 是 |
| `live_query_sample.csv` | `d9179396b22b223e58a730fc41a97f6c7f6a5c976042a97a881e51bc956eda34` | 是 |
| `research_queries.json` | `c77ec74ef4567614d3dfb6dab937b85398f95128cdb29e823587715002d99ab1` | 是 |
| `assignments_v0.1.csv` | `5cbeccf6c48c92517df57804d07aa9bcf3f359abad2b4d18d9f7c7b271fa46a2` | 是 |
| `annotation_template.csv` | `62283283eff245bf3c787c4fac09ead906e0690e95140eb4fd7f63b2dc9c99da` | 是 |

Candidate Pool 的 60 个 pair 均可在 82 条 W2 来源样例中按 OpenAlex ID 找到。标题、摘要、
年份、DOI、landing page 及两个 provenance 数组经过序列化归一化后全部一致，没有发现
生成 Candidate Pool 时引入的字段漂移。

Manifest 的 `git_revision` 指向生成冻结文件前的公共基线，且 manifest 已在说明中明确该
语义，因此它与包含 W4 文件的后续提交不同不构成 provenance 异常。

## 8. 异常、限制与结论

本次没有发现明显的结构性 provenance 异常：Research Query 到 acquisition query 的映射
完整，所有 pair 都可追溯到 W2 来源样例，冻结文件哈希与 manifest 一致。需要关注的是 3
条 abstract 缺失和 1 条 landing page 缺失，以及宽泛检索带来的领域外或相邻领域候选；
这些问题应在人工 Query Relevance 标注和后续检索误差分析中处理，而不是修改或删除冻结
候选。

Candidate Pool 没有保存 `source_keywords`、`first_seen_run_id` 等其他可选 provenance
字段，本报告不对不存在的字段作推断。本次也没有重新访问 OpenAlex 验证最新外部元数据，
因此结论限定为已提交冻结数据的内部一致性与可追溯性核查，不代表对外部数据库当前状态
的审计。
