# 项目质量门禁使用说明

## 模块分工

- `src/validation.py`：不退出进程的纯验证函数，统一返回 `status`、`errors`、`warnings`
  和 `details`；
- `app/quality_gate.py`：选择 basic/full 检查、汇总结果、打印安全摘要并返回退出码；
- `tests/fixtures/validation/`：正常和故意失败的离线 fixture；
- `tests/automated/test_quality_gate.py`：validator、编排、递归保护和返回码测试。

validator 不负责命令行输出，也不会打印疑似密钥原文。CLI 在没有严重错误时返回 0，
存在 error 时返回 1；warning 会显示，但不会单独导致失败。

## 运行

```bash
python -m app.quality_gate --level basic
python -m app.quality_gate --level full
```

需要检查另一个项目根目录时可以使用 `--root`。默认根目录由模块位置确定，不依赖当前
终端所在目录。

## basic

basic 检查：

1. `app/`、`src/`、`tests/`、`docs/`、`data/` 是否存在；
2. 正式 JSON 是否可解析；
3. `app.main`、`app.quality_gate`、`src.processor`、`src.validation` 是否可导入；
4. 正式 Markdown 本地链接是否存在；
5. 已跟踪或未忽略文件中是否存在敏感文件名、明显凭据模式或个人绝对路径；
6. 标准 unittest discovery 是否通过。

质量门禁执行测试时设置内部环境标记。若测试中的代码再次进入测试执行器，内层只返回
warning，不再次启动 unittest，从而避免
`test_quality_gate -> quality_gate -> test_quality_gate` 的递归。

## full

full 包含全部 basic 检查，并增加：

- 正式 CSV 的表头、重复表头和行列一致性；
- `annotation_id`、`case_id`、`term_id` 等稳定 ID 的唯一性；
- 中文相关性标签合法性；
- W2 标注 ID 到提交样例的关联；
- `similarity_score`、Precision、NDCG 及 `*_score` 的 `[0,1]` 范围；
- 已提交 `run_config.json` 的基本状态；
- 普通 experiment 是否已经进入版本控制。

当前 main 中 W1 标注有一行 CSV 逗号未转义，且 OpenAlex ID 与统一样例未对齐；full
把它们记录为历史 warning，而不是让 W2 门禁无法运行。未来 W2 标注文件存在时，同类
结构或关联失败会作为 error。历史已跟踪的
`outputs/experiments/openalex_stellar_spectra_60` 同样以 warning 报告，不会把既有成果
当作本次新增污染。

故意失败的 fixture 位于 `tests/fixtures/validation/invalid/`，只由单元测试读取，不参与
项目正式 JSON、CSV 和 Markdown 扫描；其余文件仍参与敏感模式检查。

## 增加 validator

1. 在 `src/validation.py` 增加返回 `ValidationResult` 的小函数；
2. 错误信息只包含相对文件和字段位置，不回显敏感值；
3. 在 `tests/fixtures/validation/` 准备正常和失败样例；
4. 在 `tests/automated/test_quality_gate.py` 同时断言通过和失败路径；
5. 仅在确属项目级 P0 检查时，将函数接入 basic 或 full。

## 当前限制

- Markdown 只验证本地文件路径，不验证章节锚点是否存在；
- secret 扫描只识别明显模式，不能代替 GitHub secret scanning；
- full 采用项目当前字段约定，不是通用科研数据 schema；
- warning 需要人工阅读，不能只看退出码。
