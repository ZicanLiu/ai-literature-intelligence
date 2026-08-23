# W5 SPECTER2 Scientific Dense Ranking

状态：Issue #50 实现、参数冻结与正式 60-pair artifact 已完成；W5 method validator PASS。

## 1. 实验边界

本方法只在 W5 冻结的 60-pair Candidate Pool 内做 Query-Relevance reranking，不是端到端
OpenAlex retrieval，也不评价未进入 Candidate Pool 的相关论文。Ranking generation 只读取：

- `data/annotation_tasks/w4/candidate_pool_v0.1.csv`；
- `configs/w4/research_queries.json`。

Approved benchmark、原始 annotation、agreement、Blind AI Audit、review queue、adjudication 与
既有正式 metrics 都不进入 generation API。Method artifact 先生成、hash 冻结并通过 W5
validator；之后 multi-method experiment runner 才验证 approved benchmark 并连接 label。

## 2. 首次正式运行前冻结的配置

以下配置依据 AllenAI 官方模型卡和 SciRepEval 官方 evaluator，在查看 W5 benchmark 指标前确定：

| 配置 | 冻结值 |
| --- | --- |
| Base model | `allenai/specter2_base` |
| Base revision / tokenizer revision | `3447645e1def9117997203454fa4495937bfbd83` |
| Research Query adapter | `allenai/specter2_adhoc_query@3f4448817028388648a74349ece07af4518ec5bd` |
| Candidate Paper adapter | `allenai/specter2@2081559630a80fc5851d8f798a05ba81e9468089` |
| Query text | `question_en` 原文，不改写 |
| Paper text | `title + tokenizer.sep_token + abstract` |
| Missing abstract | `title_only`，不删除 pair |
| Max length | 512 tokens，padding + truncation |
| Pooling | 最后隐层第一个 token（CLS） |
| Similarity / score | negative Euclidean distance；higher-is-better |
| Tie-breaking | `score desc → pair_id asc` |
| Device / dtype | CPU / float32 |
| Batch size | 8 |
| Randomness | seed 0；PyTorch deterministic algorithms |

官方依据：

- [AllenAI SPECTER2 repository](https://github.com/allenai/SPECTER2/tree/fac1cb0940fe7bd3c0db00973f6889ca0b481b63)
  明确短文本 query 使用 adhoc query adapter、candidate paper 使用 proximity adapter，论文输入为
  title + abstract，示例使用 CLS embedding；
- [AllenAI proximity adapter model card](https://huggingface.co/allenai/specter2/tree/2081559630a80fc5851d8f798a05ba81e9468089)
  说明 `allenai/specter2` 是 `specter2_base` 的 retrieval/proximity adapter；
- [AllenAI adhoc query adapter](https://huggingface.co/allenai/specter2_adhoc_query/tree/3f4448817028388648a74349ece07af4518ec5bd)
  用于短原始文本查询；candidate 仍由 proximity adapter 编码；
- [SciRepEval official evaluator](https://github.com/allenai/scirepeval/blob/e04594e6401cb68fb4ddf6daa801fb219cccc0bb/evaluation/evaluator.py)
  的 IR path 使用 Euclidean distance 并取负值作为 higher-is-better run score。

没有运行 cosine、dot product 或其他配置后再按正式 benchmark 指标选择。SPECTER2 自身没有
针对本项目 60 条 label 训练或调参。

## 3. 缺摘要与输入事实

冻结 Candidate Pool 共 60 条、三个 RQ 各 20 条。缺摘要 3 条：

- `w4_rq01_017`；
- `w4_rq02_001`；
- `w4_rq02_015`。

这三条只编码 title；其余 57 条编码 title + separator + abstract。所有 60 个 record-level pair
均保留，包括 W4 v0.1 明示的 same-paper alias。

## 4. 实现与运行

真实模型依赖不进入核心 `requirements.txt`。建议独立环境：

```powershell
conda create -n w5-specter2 python=3.12 pip
conda run -n w5-specter2 python -m pip install -r requirements/w5-specter2.txt
conda run -n w5-specter2 python -m app.run_specter2_ranking
```

核心模块在 import 时不导入 PyTorch、Transformers 或 Adapters，也不会下载模型。自动测试注入
deterministic fake embedding backend，因此完全离线。正式 CLI 固定上述 v1 配置，并在任何输出
前拒绝 dirty/未知 Git 状态；已有非空 package 也不会被覆盖。

正式 artifact 目标目录：

```text
data/analysis/w5_methods/specter2_adhoc_v1/
├─ manifest.json
└─ ranking.csv
```

## 5. Multi-method Experiment Runner

`python -m app.evaluate_w5_methods` 接受任意数量的 `--method-manifest`，不硬编码 BM25、
SPECTER2、Cross-Encoder 或 RRF。执行顺序固定为：

1. 逐项调用 W5 method validator；
2. 拒绝 duplicate `method_id`，核对 Candidate Pool / Research Query identity；
3. 全部方法通过后才 strict 验证并读取 approved benchmark；
4. 对每个方法调用现有 `evaluate_contract_ranking()`；
5. 输出每方法 3 个 per-RQ 行和 1 个 macro 行，以及可复现实验 manifest。

示例：

```powershell
python -m app.evaluate_w5_methods `
  --method-manifest <method-a>/manifest.json `
  --method-manifest <method-b>/manifest.json `
  --output-dir <new-experiment-dir>
```

Runner 只报告统一的 NDCG@5/10、Precision@5/10、Coverage@5/10 与 irrelevant Top-K，不自动
挑选或宣称“最佳方法”。

## 6. 正式 artifact 记录

正式模型运行在实现提交形成的 clean tree 上启动，未读取 benchmark label，也没有试跑其他
similarity 后择优。真实记录如下：

| 项目 | 结果 |
| --- | --- |
| Generation Git revision | `2e879e5c5c27c342f22e642a5cad00e4cd6dcccc` |
| Python | CPython 3.12.13（独立 Conda 环境 `w5-specter2`） |
| Dependencies | `torch 2.13.0+cpu`、`transformers 4.57.6`、`adapters 1.3.0` |
| Device / batch size | CPU / 8 |
| Embedding dimension | 768 |
| Model generation duration | 13.994535 seconds（模型已在本地 cache） |
| Ranking rows | 60；三个 RQ 各 20 |
| Ranking SHA-256 | `7bd205cfaa8ecb559e4a90fee0583dceb18a3ef8ef1f1bcbb0a632ea837b575b` |
| Manifest SHA-256 | `a917bfb3ed545428441bdd9d821f179ae96ddb9abeeb4ca11458c300d641fbee` |
| Validator | PASS |

Artifact：

- `data/analysis/w5_methods/specter2_adhoc_v1/ranking.csv`；
- `data/analysis/w5_methods/specter2_adhoc_v1/manifest.json`。

实际验证命令：

```powershell
python -m app.validate_w5_method `
  --manifest data/analysis/w5_methods/specter2_adhoc_v1/manifest.json
```

Validator 重新核对了冻结输入 hash、严格五列表头、60/60 pair identity、3×20、有限 score、
higher-is-better rank、`pair_id` tie-breaking、clean generation revision、ranking hash 与
label-access declaration。

Windows 上首次下载 paper adapter 时，Hugging Face Hub 的 symlink 降级路径曾触发一次
`WinError 1314`；新进程使用已下载的普通 cache 文件后加载成功。正式模型进程随后成功生成并在
进程内验证 artifact。`conda run` 在转发含 replacement character 的模型日志时又触发 GBK
`UnicodeEncodeError`，但该错误发生在 Conda 打印已经完成的子进程 stdout 阶段；上述独立
validator、文件时间、完整 manifest 与 hash 是正式成功状态的判据。该编码问题不影响 ranking
内容或复现配置，但 Windows 用户可直接激活环境后运行 CLI，以避免 Conda stdout wrapper。
