# 第二周质量门禁与回归测试报告

## 环境与命令

- 日期：2026-08-08；
- 测试框架：Python 标准库 `unittest`；
- 自动测试不依赖网络或真实 API Key；
- live 验证单独执行，完整实验保存在系统临时目录。

```bash
python -m unittest discover -s tests/automated -p "test_processor.py" -v
python -m unittest discover -s tests/automated -p "test_quality_gate.py" -v
python -m unittest discover -s tests/automated -p "test_*.py" -v
python -m app.quality_gate --level basic
python -m app.quality_gate --level full
```

## 自动测试结果

| 测试组 | 数量 | 结果 |
| --- | ---: | --- |
| processor 回归 | 14 | 14/14 通过 |
| quality gate/validation | 18 | 18/18 通过 |
| main 原有输出测试 | 7 | 7/7 通过 |
| 全量 | 39 | 39/39 通过 |

processor 回归覆盖空输入、空标题、缺失 DOI、DOI 标准化、严格重复、标题子字符串、
大小写差异、引用极值、异常年份、缺失字段、评分范围和稀疏输入字段。没有修改
`src/processor.py`。

quality gate 测试覆盖正常 fixture、缺列、重复 ID、非法标签、关联失败、相似度和指标
越界、失效 Markdown 链接、敏感文件名、安全摘要、run_config、返回码和递归保护。故意
失败的 fixture 均被 validator 拦截。

## OpenAlex live

实际命令：

```bash
python -m app.main --mode live \
  --keyword "astronomical spectral classification machine learning" \
  --max-results 25
```

结果：原始 25 条、去重后 25 条、重复 0 条，运行成功。整理后的
`data/samples/w2/quality_gate/live_validation_summary.csv` 显示：

- CSV 表头和 25 行结构通过；
- 25 个 OpenAlex ID 非空且唯一；
- 五个项目分数字段均在 `[0,1]`；
- run_config 状态通过；
- 仅 1 条摘要缺失，其他项目字段缺失数为 0。

没有提交完整实验目录，也没有在测试或文档中记录 API Key。

## 门禁结果

basic：

- 命令：`python -m app.quality_gate --level basic`；
- 错误 0、警告 0；
- 退出码 0，PASSED。

full：

- 命令：`python -m app.quality_gate --level full`；
- 错误 0、警告 3；
- 退出码 0，PASSED。

full 的 3 个 warning 均来自 main 已有内容：W1 标注有 1 行 CSV 列数异常；其余可解析的
19 个 W1 标注 ID 未在当前统一样例中找到；历史 experiment
`openalex_stellar_spectra_60` 已被 Git 跟踪。本次没有修改这些历史交付物，也没有把
warning 隐藏成“无问题”。

## 已知问题

- 当前 W1 标注存在一行 CSV 结构问题，且 OpenAlex ID 与统一 100 条样例未对齐，full
  记录为 warning；
- main 历史上已跟踪一个普通 experiment，full 记录为 warning；
- 本次只验证一次 25 条 live，不代表 OpenAlex 服务长期稳定；
- 质量门禁不能替代人工科研判断或 GitHub 平台侧安全扫描。
