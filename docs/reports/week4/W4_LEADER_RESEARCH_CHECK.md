# W4 组长科研问题框架核查

核查日期：2026-08-15

对应 Issue：#36

实际基线：`8466440`（PR #35 已合并到 `main`）

任务分支：`feature/w4-leader-research-integration`

## 1. 核查结论

当前三个 Research Question 的分工清楚，可以继续作为 W4 及后续排序实验的研究框架，
本次没有修改 [`W4_RESEARCH_PLAN.md`](../../project/W4_RESEARCH_PLAN.md) 中的正式定义。
三者分别回答“相关论文能否检得更准”“相关论文能否排得更适合阅读”和“专业领域中的
同义表达、术语及表面相关错误能否被更好处理”，形成从 Query Relevance 到 Reading
Priority，再到错误类型与领域知识作用的递进关系。

需要区分两组概念：

- RQ1、RQ2、RQ3 是项目层面的研究问题，未来需要对照实验回答；
- `rq01_stellar_classification`、`rq02_stellar_parameters`、
  `rq03_spectral_preprocessing` 是 Pilot 中三个具体 research query，用于生成和标注
  query-paper pair，不是三个项目 RQ 的一一替代。

当前 `docs/CURRENT_STATUS.md` 仍保留“W4 bootstrap 尚未合并”的 2026-08-10 快照；实际
Git 状态显示 PR #35 已进入 `main`，HEAD 为 `8466440`。本报告按实际 Git 和源码状态记录。

## 2. 三个 Research Question 分别解决什么问题

| Research Question | 核心问题 | 合理的未来证据 |
| --- | --- | --- |
| RQ1：检索方法比较 | 在低标注专业领域，词法、语义和混合检索谁更能找到与具体科研问题真正相关的论文 | 固定 research query、candidate pool、人工 relevance benchmark 和相同评价口径下的 BM25、Dense、Hybrid 对照 |
| RQ2：阅读优先级 | 在主题相关性得到保证后，引用影响、时效性等信号能否改善阅读顺序，并避免高引用偏题论文进入 Top-K | 相关性门控前后的排序对照、Top-K 偏题数量、NDCG/Precision、阅读优先级判断及偏差分析 |
| RQ3：领域术语与 hard negatives | 领域术语、同义表达和 hard negatives 能否帮助系统识别“词面相似但任务不同”等专业错误 | 术语扩展与 hard-negative 处理的消融实验，以及按错误类型整理的人工案例分析 |

这三个问题目前都是待实验验证的研究问题，不能由现有 Pipeline 的单次分数或个别案例
直接回答。

## 3. 当前 Pipeline 已经支持什么

当前 [`src.pipeline.run_unified_pipeline()`](../../../src/pipeline.py) 已提供后续实验所需的
工程底座：

1. 以多个 acquisition query 获取候选，并显式要求单独提供 `ranking_keyword`；
2. 在清洗后保存 `source_query_ids`、`source_run_ids`、`source_keywords`，支持来源审计；
3. 合并候选后执行 exact dedup，并把 suspected duplicate 留在人工复核队列，不自动删除；
4. 保留 v0.2 `preliminary_score` baseline，并运行 TF-IDF 词法相关性、Stage 1 分层和
   Stage 2 排序；
5. Stage 2 当前以词法相关性为主，同时使用引用影响、时效性和完整度信号；Stage 1
   只降权，不删除候选；
6. 在提供标签时，可以分别评价 baseline 和 two-stage 排序，输出 judged Precision@K、
   judged NDCG@K、coverage、Top-K 明确不相关数量等指标；
7. Pipeline、Batch Runner、阶段化输出和 Quality Gate 支持可追溯、可重复的离线实验。

这些能力能够支撑实验执行，但不能等同于实验结论。TF-IDF 只衡量词项重合，不具备语义
理解；当前权重是可解释 baseline，并未被 W4 benchmark 证明为最优。Quality Gate 只负责
工程验收，不参与论文相关性或阅读优先级判断。

## 4. 当前还缺什么证据

### RQ1

- 六人个人标注尚未全部合并，agreement、分歧裁决和必要的专家复核尚未完成；
- 当前目录仍是 Pilot Annotation task，不能称为 gold、ground truth 或正式 benchmark；
- 尚无 BM25、Dense 或 Hybrid 实现，也没有在同一 benchmark 上完成公平对照；
- 当前三个具体 research query 和 60 个 pair 适合试运行协议，规模不足以支持广泛算法
  优劣结论。

### RQ2

- 现有 Stage 2 确实使用引用、年份和完整度，但尚无证据证明这些信号改善了真实阅读顺序；
- W4 个人标注只判断 Query Relevance，不是 Reading Priority，也不是论文绝对质量；
- 还缺主题相关性门控、文献计量信号增量贡献、高引用偏题风险和不同学科/年份偏差的
  对照分析；
- 仅比较当前 baseline 与 two-stage 不能证明现有权重最优。

### RQ3

- 项目已有领域词表和显式 query set，但尚未通过消融实验证明领域术语带来改进；
- Candidate Pool 可以暴露潜在的表面相关错误，但当前没有正式 hard-negative 标签或
  hard-negative 训练/重排机制；
- 尚未形成同义表达、缩写、数据模态错配、对象错配、任务错配等统一错误分类；
- TF-IDF 不做词干还原、同义词扩展或语义理解，因此不能把当前结果描述为已解决 RQ3。

## 5. 本周 Pilot 的边界

W4 Pilot v0.1 使用三个具体 research query、60 个 query-paper pair 和均衡双标分配，
目的是试运行：

- Query Relevance 定义和 `0/1/2/?` 标注口径；
- Title + Abstract → 外部页面 → 全文关键部分的证据升级流程；
- 独立双标、AI assistance 记录和个人 Validator；
- 后续 agreement、分歧裁决和 benchmark 提升所需的数据接口。

Pilot 选样使用 retrieval provenance 和既有排序覆盖不同候选位置，但个人任务不显示分数、
排名、引用信号、selection bucket、assignment role 或旧标签。选样策略不构成人工答案，
个人 Validator 通过也不表示标签已经成为正式 benchmark。

## 6. 为什么先做 benchmark，而不是继续加算法

如果没有固定 research query、独立人工 relevance 判断和统一指标，新算法产生的分数变化
无法解释：它可能来自候选集变化、标签覆盖变化、查询差异或偶然调参，而不是真实改进。
先建立 benchmark 和评价协议有四个直接作用：

1. 为“更好”提供可复核定义，避免只凭示例或单次 Top-K 下结论；
2. 让所有候选方法在同一数据、同一标签和同一指标下比较；
3. 先暴露标注分歧和任务边界问题，避免把不稳定答案用于算法调参；
4. 支持按误差类型分析失败原因，从而决定下一步需要 BM25、语义检索、领域词还是
   hard-negative 机制。

因此 W4 的优先级不是“停止算法研究”，而是先补齐算法研究能够成立的评价基础。

## 7. 留到 BM25 / Dense / Hybrid 等后续阶段的工作

只有在个人结果全部合并、agreement 计算、分歧裁决和 benchmark 版本冻结后，才适合开展：

| 后续阶段 | 要回答的问题 | 必须保持的实验约束 |
| --- | --- | --- |
| BM25 | 更成熟的词法检索是否优于当前 TF-IDF baseline | 固定 query、candidate pool、benchmark、K 和指标 |
| Dense retrieval | 语义表示是否改善同义表达、缩写和低词面重合样例 | 不用评价集标签训练或调参；单独记录模型和版本 |
| Hybrid retrieval/ranking | 词法精确匹配与语义召回能否互补 | 与 BM25、Dense 分别做对照和消融，不只报告最佳结果 |
| Domain-term ablation | 领域术语扩展是否真正改善 RQ3 | 比较有/无领域词的固定实验，并按错误类型分析 |
| Hard-negative experiment | 表面相关负例能否降低偏题 Top-K | 先定义并裁决 hard negatives，防止把未裁决样例当训练真值 |
| Reading-priority experiment | 引用、时效性等信号是否改善相关论文的阅读顺序 | 先保证 Query Relevance，再评估增量效果和高引用偏题风险 |
| Learning-to-rank | 多信号权重能否从数据中学习 | 需要更大、分割明确且无泄漏的 judged 数据；当前 Pilot 不足 |

不得一边查看同一 Pilot 的评价结果，一边无记录地调整权重并把最终结果当作独立验证。

## 8. 周六组会说明口径

可以向老师概括为：前三周解决“Pipeline 能不能完整、可追溯地跑起来”，第四周开始解决
“以后说检索或排序更好时，依据是什么”。当前已有词法 baseline 和多信号排序，但缺少
独立、稳定的人工评价基准。继续加入 BM25、Embedding 或 Hybrid 只会增加待比较方法，
不会自动产生可信结论。因此本周先用小规模 Pilot 校准科研问题、标注规则和双标流程；
待 agreement 与分歧裁决完成后，再在固定 benchmark 上开展公平算法实验和错误分析。

## 9. 本 Issue 的核查结论

- 三个项目 RQ 无需重写，当前定义与项目阶段一致；
- 三个具体 research query 适合作为 Pilot 标注场景，但不能代表全部天文光谱任务；
- 当前 Pipeline 足以作为词法 baseline 和可重复实验底座；
- 当前证据不足以声称语义/混合检索、领域术语、hard negatives 或现有多信号权重已经有效；
- W4 应先完成个人标注、agreement 和裁决，再进入 BM25 / Dense / Hybrid 对照实验。
