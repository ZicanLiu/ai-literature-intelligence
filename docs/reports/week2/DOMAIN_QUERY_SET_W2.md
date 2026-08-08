# 第二周天文光谱领域词典与查询集合

## 本周交付

- 领域词典：`data/domain/stellar_spectra_terms_w2.csv`，42 个有效词项；
- 查询配置：`configs/w2/domain_query_set.json`，6 组稳定查询；
- 生成模块：`src/domain_query.py`；
- 命令行入口：`app/build_domain_queries.py`；
- live 样例：`data/samples/w2/domain_query/live_query_sample.csv`；
- live 摘要：`data/samples/w2/domain_query/query_results_summary.csv`。

词典使用统一英文字段名。`term_id` 和 `normalized_term` 必须唯一，`category` 只能取
代码中集中定义的合法值，`include_in_query` 只接受 `true` 或 `false`。词项的 `source`
记录为“陈星妤 W2 原始领域词典”，表示项目内整理来源，不冒充正式文献引用。

## 查询生成

运行：

```bash
python -m app.build_domain_queries \
  --terms "data/domain/stellar_spectra_terms_w2.csv" \
  --output "configs/w2/domain_query_set.json"
```

输入相同词典时，JSON 字节内容稳定。正式查询是项目现有 OpenAlex 客户端可直接放入
`search` 参数的普通关键词，不使用未经验证的 `title_abstract:` 语法。

| query_id | keyword | 目的 |
| --- | --- | --- |
| `q01_broad_ml` | `stellar spectrum machine learning` | 宽泛覆盖交叉研究 |
| `q02_classification` | `stellar spectrum spectral classification machine learning` | 光谱分类 |
| `q03_parameters` | `stellar spectrum effective temperature surface gravity machine learning` | 参数估计 |
| `q04_preprocessing` | `stellar spectrum spectral denoising normalization machine learning` | 降噪和归一化 |
| `q05_spectral_lines` | `stellar spectrum absorption line emission line feature extraction` | 谱线和特征提取 |
| `q06_library_matching` | `stellar spectrum spectral library template matching radial velocity metal abundance` | 光谱库和物理量测定 |

每条 JSON 查询保存 `query_id`、`keyword`、说明、词项 ID、词项文本和类别。6 组查询使用
不同的研究意图，不通过交换词序制造伪差异。`include_in_query=false` 的弱相关、负面或
边界词不能进入正式查询。

## 2026-08-08 live 验证

从正式查询中选择 3 组，每组请求 30 条，均通过 `python -m app.main --mode live` 执行。
本次只提交整理后的公共元数据和摘要，不提交完整实验目录。

| query_id | 原始 | 去重后 | 状态 | run_id |
| --- | ---: | ---: | --- | --- |
| `q02_classification` | 30 | 30 | success | `20260808_144344224124_live_pr31-q01_stellar-spectrum-spectral-classification-machine_n30_dae3d3` |
| `q03_parameters` | 30 | 30 | success | `20260808_144349256507_live_pr31-q02_stellar-spectrum-effective-temperature-surface-g_n30_3f6cf2` |
| `q04_preprocessing` | 30 | 30 | success | `20260808_144352575552_live_pr31-q03_stellar-spectrum-spectral-denoising-normalizatio_n30_e4e706` |

三次运行共返回 90 行，跨查询按 OpenAlex ID 合并后形成 82 条可追溯 live 样例。摘要中的
相关性数量只统计已进入标注集的子集；其余记录计入 `pending_review_count`，不能解释成
已经完成全部人工标注。

## 当前限制

- 查询扩展是可解释的有限配置，不是自动生成无限组合；
- OpenAlex 排名与索引会变化，未来同一关键词不保证返回完全相同的论文；
- live 样例是阶段测试数据，不是完整或权威的天文光谱文献集；
- 查询效果仍需结合人工标注持续比较 precision 和 recall。
