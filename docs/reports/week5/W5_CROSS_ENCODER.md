# W5 Cross-Encoder 神经重排

状态：实现、实验定义与正式 ranking artifact 已冻结，公共 W5 validator 已通过。

## 1. 实验边界

本实验是冻结 Candidate Pool 内的 Query-Relevance reranking，不是完整 OpenAlex 检索，也不评价
retrieval recall。输入固定为 60 个 record-level query-paper pair，三个 Research Query 各 20
条；已知 same-paper alias 保留，不合并或删除。

Ranking generation 只读取：

- `configs/w4/research_queries.json` 中的 `research_query_id` 和 `question_en`；
- `data/annotation_tasks/w4/candidate_pool_v0.1.csv` 中的 `pair_id`、
  `research_query_id`、`title` 和 `abstract`。

它不读取 approved benchmark label/judgement、annotation、Blind AI Audit、adjudication、error
analysis 或既有 W5 指标。正式 ranking hash 冻结后，评价阶段才能连接 benchmark。

## 2. 冻结方法定义

| 项目 | 固定值 |
| --- | --- |
| method_id / family | `cross_encoder_msmarco_v1` / `neural` |
| 模型 | `cross-encoder/ms-marco-MiniLM-L6-v2` |
| exact revision | `233902d25c440f23af6f7d6e94d2946bac0bee0a` |
| Query | `question_en` 原文，不改写 |
| Paper text | 有摘要时 `title + "\n\n" + abstract`；缺摘要时只用 `title` |
| tokenizer | 与模型同名、同一 exact revision |
| max length / truncation | `512` / `true` |
| score | raw sequence-classification relevance logit |
| activation / softmax | `torch.nn.Identity()` / `apply_softmax=False` |
| direction | `higher_is_better` |
| tie-breaking | `score desc → pair_id asc` |
| device / batch size | `cpu` / `16` |

冻结池有 0 条缺标题、3 条缺摘要；缺摘要 fallback 会在正式 60-pair 运行中实际触发。

## 3. 实现与离线测试设计

业务逻辑位于 `src/cross_encoder_ranking.py`，CLI
`python -m app.run_cross_encoder_ranking` 不暴露 benchmark、label、模型或参数入口。scorer 通过
`PairScorer` 接口注入，自动测试使用 deterministic fake backend；只有真实 CLI 调用
`score_pairs()` 时才延迟导入 Sentence Transformers、PyTorch 并加载固定 revision。因此核心
测试与模块 import 不下载模型。

正式生成开始时，程序先采集完整 Git SHA、clean worktree、Python、平台和五项模型依赖版本；
工作树 dirty、依赖缺失、冻结输入 hash 漂移或目标 artifact 已存在时直接拒绝生成。

## 4. 独立环境与正式命令

模型依赖固定在 `requirements/w5-cross-encoder.txt`，不修改根 `requirements.txt`。正式运行：

```bash
python -m pip install -r requirements/w5-cross-encoder.txt
python -m app.run_cross_encoder_ranking
python -m app.validate_w5_method \
  --manifest data/analysis/w5_methods/cross_encoder_msmarco_v1/manifest.json
```

## 5. 正式运行记录

正式 CLI 在第一次实现提交后、artifact 尚不存在且 Git 工作树 clean 时启动。程序在写输出前
记录环境，随后 artifact 自身使工作树变为 dirty；manifest 中的状态是生成开始前的快照。

- 生成 commit：`c8be0550be8b180f51356987d44d70ff9f40c8ce`；
- 开始时间：`2026-08-23T15:58:27+08:00`；
- 耗时：`17.794164` 秒（包含固定 revision 加载、60-pair 推理和 ranking 写入）；
- Python：CPython `3.13.7`；
- 平台：Linux `6.17.0-41-generic`，`x86_64`；
- 依赖：Sentence Transformers `5.2.3`、PyTorch `2.9.1+cpu`、Transformers `4.57.6`、
  Hugging Face Hub `0.36.2`、NumPy `2.3.5`；
- pair：60/60，三个 RQ 各 20/20，3 条缺摘要使用 title-only；
- ranking SHA-256：
  `2562de52955ecfba552fe6a465c5cd0996c0018c75ae5b75f4a1092f2976b241`；
- manifest SHA-256：
  `4a7b34a2b5689df1e4d5b3d8ae5c13a6925a589432ae7fc070e3a34d9e5694fb`；
- 公共 W5 validator：PASS。

正式产物位于 `data/analysis/w5_methods/cross_encoder_msmarco_v1/`，ranking CSV 只有 Contract
规定的五列。模型缓存和独立虚拟环境不提交仓库。

## 6. 验收结果

- W4 approved benchmark strict validator：PASS，60/60；
- W5 method-output validator：PASS，60/60、20×3；
- 新增 Cross-Encoder 定向测试：15/15 PASS；
- 全量离线自动测试：342/342 PASS；
- Basic Quality Gate：249 个文件，0 error、0 warning，PASS；
- Full Quality Gate：249 个文件，0 error、3 个既有 W1/历史 experiment warning，PASS。

Full Gate 的三个 warning 与任务开始前的公共基线一致：W1 历史 CSV 结构问题、19 个历史标注 ID
未对齐当前统一样例、已跟踪历史 experiment。本任务没有修改这些历史 evidence，也没有引入新
warning。

## 7. 解释限制

该模型在通用 MS MARCO Passage Ranking 数据上训练，是一个通用 neural reranker baseline，
不是天文学或科研文献专用模型，不代表 astronomy/scientific-domain optimum。模型输入上限固定为
512 token，较长的题目—论文文本会被 tokenizer 截断；本实验也只能说明固定 60-pair 池内的排序
行为，不能外推为对整个 OpenAlex 文献空间的检索能力。

参考：

- [模型卡](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2)
- [Sentence Transformers CrossEncoder API](https://www.sbert.net/docs/package_reference/cross_encoder/cross_encoder.html)
- [Hugging Face Hub 固定 revision 下载](https://huggingface.co/docs/huggingface_hub/en/guides/download)
