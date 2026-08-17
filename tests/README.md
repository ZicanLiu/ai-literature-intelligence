# 测试说明

## 自动测试

自动测试位于 `tests/automated/`，只使用 mock 数据和临时输出目录，不依赖网络，不读取
真实 API Key，也不会写入正式 `outputs/experiments/`。

在项目根目录运行：

```powershell
python -m unittest discover -s tests/automated -p "test_*.py" -v
```

当前重点覆盖：mock CLI 成功运行、完整产物、运行计数、相同关键词连续运行不覆盖、
不同关键词隔离、中文或特殊字符关键词、非法数量、空关键词和自定义输出目录；W2 还覆盖
多查询 provenance 合并、OpenAlex ID/DOI 精确去重、疑似队列不删除、显式 ranking
keyword、Pipeline CSV 往返、可选评价，以及 Batch Runner 的独立 run 和失败继续策略。
W4 还覆盖 Candidate Pool 冻结不变量、60/30/90 双标分配、六人个人任务生成、默认拒绝
覆盖、只读字段保护和标注枚举/证据契约；W5 覆盖统一 method ranking/manifest validator、
无标签 fixture 和 evaluator adapter。全部使用既有公开样例和临时目录，不联网。

## 第二周 fixture

`tests/fixtures/` 保存小型、可解释的离线测试输入。OpenAlex、去重、领域查询、质量验收
排序与统一 Pipeline 任务各自使用独立子目录，具体约定见
[`fixtures/README.md`](fixtures/README.md)。成员不修改其他任务的 fixture。

自动测试不得联网、不得读取 `.env` 或真实 API Key。live 验证属于单独的人工验证，
不能放入自动测试，也不能在缺少合法本地配置时擅自执行。

## 手工测试

手工测试记录位于 `tests/manual/week1_test_cases.csv`。每条记录至少包含命令、前置条件、
预期结果、实际结果、状态和证据；没有实际运行的项目必须写“未执行”或“不适用”，
不能填写为通过。补充报告见
`docs/reports/week1/TEST_REPORT_W1_COMPLETED.md`。

新增测试也应使用临时输出目录。需要 live 的场景不得把 Key 写入命令或报告；没有合法
本地配置时只记录预期行为，不擅自请求真实 API。
