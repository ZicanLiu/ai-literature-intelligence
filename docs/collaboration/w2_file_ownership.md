# 第二周文件归属与协作边界

本表用于减少多人同时修改同一文件造成的冲突。归属表示主要维护责任，不限制成员阅读
和提出建议；正式实现仍以对应 GitHub Issue 和 Pull Request 为准。

## 主要文件归属

| 负责人 | 方向 | 主要维护路径 |
| --- | --- | --- |
| 刘子璨 | 批量实验与最终集成 | `app/batch_runner.py`、`src/batch_runner.py`、`configs/w2/integration_batch.example.json`、`tests/automated/test_batch_runner.py`、`data/samples/w2/integration/`、第二周最终索引、总结和集成文档 |
| 武子恒 | OpenAlex v2 分页、筛选与重试 | `src/openalex_client_v2.py`、`app/openalex_fetch_v2.py`、`tests/automated/test_openalex_client_v2.py`、`tests/fixtures/openalex/`、`data/samples/w2/openalex_client/`、OpenAlex v2 设计与报告 |
| 贾馥诚 | 确定重复与疑似重复复核 | `src/deduplication.py`、`app/review_duplicates.py`、`tests/automated/test_deduplication.py`、`tests/fixtures/dedup/`、`data/samples/w2/dedup/`、`data/review/`、`data/analysis/w2_dedup/`、去重设计与报告 |
| 陈星妤 | 领域查询与人工标注 | `src/domain_query.py`、`app/build_domain_queries.py`、`tests/automated/test_domain_query.py`、`tests/fixtures/domain_query/`、`data/domain/`、`data/samples/w2/domain_query/`、`data/manual/relevance_labels_w2_baseline.csv`、`data/manual/hard_negative_cases_w2.csv`、`configs/w2/domain_query_set.json`、领域查询与标注报告 |
| 黄斌 | 质量门禁与回归测试 | `src/validation.py`、`app/quality_gate.py`、`tests/automated/test_processor.py`、`tests/automated/test_quality_gate.py`、`tests/fixtures/validation/`、`data/samples/w2/quality_gate/`、`tests/manual/week2_test_cases.csv`、质量门禁设计与报告 |
| 蒲正杰 | TF-IDF 与两阶段排序 | `src/text_relevance.py`、`src/evaluation.py`、`app/evaluate_ranking.py`、`tests/automated/test_text_relevance.py`、`tests/automated/test_evaluation.py`、`tests/fixtures/ranking/`、`data/samples/w2/ranking/`、`data/analysis/w2_ranking/`、两阶段排序设计与报告 |

上述业务文件和成员专用目录均由负责人在各自分支中创建，本次脚手架不预先生成。

## 共享文件

以下文件默认由组长在集成时最终修改：

- `app/main.py`
- `src/processor.py`
- `src/run_context.py`
- `src/storage.py`
- `README.md`
- `docs/README.md`
- `docs/current_status.md`
- `data/README.md`
- `tests/README.md`
- `outputs/README.md`
- `.gitignore`
- `.gitattributes`
- `requirements.txt`
- `project_requirements.md`

蒲正杰若确实需要 `scikit-learn`，可在 PR 中修改 `requirements.txt`，但必须说明引入原因、
版本兼容性和验证结果。其他成员若认为共享文件需要调整，应在 PR 描述中提出建议，由
组长集成，不直接改写。所有人都可以读取其他模块，但不得擅自覆盖他人成果。

除各目录的 `README.md` 外，仓库中的英文文件名统一使用小写；新增文件也应遵守这一
约定。

## 冲突处理

1. 优先新增任务归属明确的独立文件；
2. 不复制旧模块形成多个失控版本；
3. 发现接口问题先在 PR 中说明，并引用数据接口约定；
4. 正式 CLI 入口由组长在集成阶段连接；
5. 不为了避免冲突而省略必要测试；
6. 合并前同步最新 `main` 并重新测试，不自行重写他人成果。
