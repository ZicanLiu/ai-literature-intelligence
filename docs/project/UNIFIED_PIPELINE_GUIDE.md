# W2 统一 Pipeline 使用与复现

统一入口是 `python -m app.run_pipeline`。它负责把已经进入 `main` 的五项 W2 能力串成
一个 parent run；旧 `python -m app.main` 保留为 v0.2.0 baseline，不受影响。

## 查询的两种用途

- acquisition query：由领域词表生成，可一次选择多组，用于扩大获取覆盖；
- ranking keyword：对合并候选集统一打分，必须显式传入，不能由 acquisition query
  的先后顺序推断。

每个请求都有独立 child run ID。论文清洗完成后才附加 `source_query_ids`、
`source_run_ids` 和 `source_keywords`；跨查询精确重复会把这三个 list 合并到首条保留
记录。兼容字段 `keyword` 和 `run_id` 仍保留，但不再承担完整来源信息。

## 离线复现

```powershell
python -m app.run_pipeline --query-ids q01_broad_ml q02_classification `
  --ranking-keyword "machine learning stellar parameter estimation spectra" `
  --mode offline --max-results-per-query 10 `
  --terms tests/fixtures/pipeline/domain_terms.csv `
  --offline-fixture tests/fixtures/pipeline/offline_queries.json `
  --labels tests/fixtures/pipeline/labels.csv `
  --run-name issue21-offline-e2e
```

fixture 按 `queries.<query_id>.papers` 保存已转换的论文对象。离线模式通过同一个 Pipeline
API 运行完整链路，只替换 fetcher，不访问网络，也不读取 `.env`。

## 小规模 live

本地合法配置 OpenAlex Key 后，可以先用两组查询、每组 20 条验证：

```powershell
python -m app.run_pipeline --query-ids q02_classification q03_parameters `
  --ranking-keyword "machine learning stellar parameter estimation spectra" `
  --mode live --max-results-per-query 20 --from-year 2015 `
  --run-name issue21-live-e2e
```

不要把 Key 写进命令、配置或报告。live 只应写入新的
`outputs/experiments/<run_id>/`，不得覆盖历史 evidence 或 baseline。

## 数据流和边界

```text
domain terms → query set → selected acquisition queries → OpenAlex v2/offline fetcher
→ clean → attach provenance → combine → exact dedup + provenance union
→ suspected review queue → preliminary baseline → TF-IDF → Stage 1 → Stage 2
→ optional judged evaluation → parent run outputs
```

Exact 按现有 OpenAlex ID、DOI、无 ID/DOI 时同标题规则自动应用。Suspected 只写人工复核
队列，不减少候选数。本次没有 metadata fusion，也没有应用人工 review decision。

排序继续使用现有参数：旧 `preliminary_score` 权重不变，TF-IDF 标题/摘要权重、Stage 1
阈值与 gate、Stage 2 权重均由 `src/ranking.py` 导入并写入 `run_config.json`。
`preliminary_score` 只是项目内部可解释 baseline，不代表论文真实学术价值。

## 输出与 CSV

一次 run 的结构见 [`outputs/README.md`](../../outputs/README.md)。最终
`ranking/ranked_papers.csv` 保留基础元数据、三组 provenance、五个 baseline 分数字段、
旧排名、TF-IDF/Stage 1/Stage 2 字段、新排名和名次变化。

三个 provenance 字段在内存中是 `list[str]`，CSV 中是 JSON array string。需要重新读取
时使用 `src.pipeline.load_pipeline_csv()`，不要按逗号手工拆分。

## 可选评价

只有提供 `--labels` 才执行评价。默认排除 `annotator=AI-assisted-draft` 和
`review_status` 含“待人工复核”的行；如确需探索性使用，必须显式添加
`--include-unverified-labels`。未标注论文不会被当作不相关，标签也不会进入评分公式。

当前 `data/manual/relevance_labels_w2_baseline.csv` 有 50 行，其中 37 行来自原 PR 人工
判断映射，13 行是 AI-assisted draft/待复核。即使使用默认 37 行，也应在正式科研结论前
完成组长抽查，不能表述为 50 条正式 ground truth。自定义标签文件如出现重复
`openalex_id` 会直接失败，不采用 last-row-wins。

## 验收

```powershell
python -m unittest discover -s tests/automated -p "test_*.py" -v
python -m app.quality_gate --level basic
python -m app.quality_gate --level full
git diff --check
```

Quality Gate 是 run 完成后的工程验收，不参与每篇论文的评分流程。
