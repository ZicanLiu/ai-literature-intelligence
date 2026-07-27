# 第一周测试补充报告

日期：2026-07-27
性质：第二周基线整理时补做，不追溯为第一周原成员交付

## 背景

第一周合并到根目录的 `week1_test_cases.csv` 和 `week1_test_report.md` 均为 0 字节，
没有可执行用例或结果。本次删除两个空占位文件，改为：

- `tests/automated/test_output_runs.py`
- `tests/manual/week1_test_cases.csv`
- 本报告

## 测试环境

- Windows 11 家庭中文版
- Python 3.13.9
- 项目版本 v0.2.0
- 数据源：本地 `data/mock_papers.json`
- 网络与真实 OpenAlex Key：未使用

自动测试命令：

```powershell
python -m unittest discover -s tests/automated -p "test_*.py" -v
```

最终结果：共 7 个测试，7 通过、0 失败、0 跳过，用时约 15 秒。

## 自动测试覆盖

1. mock 20 条完整运行，检查 JSON、CSV、SQLite、两张图和摘要。
2. CSV 行数、SQLite 行数与 `run_config.json` 的去重后数量一致。
3. 相同关键词连续运行两次，生成不同 run_id，第一次 CSV 哈希不变。
4. 不同英文关键词分别保存，配置保留各自关键词。
5. 中文和特殊字符关键词生成 Windows 安全路径，原始关键词不丢失。
6. `max-results` 为 0、负数或非整数时返回非零，且不生成伪成功目录。
7. 空关键词被明确拒绝。
8. `--output-root` 与 `--run-name` 可用，且测试只写入临时目录。

上面的行为由 7 个测试方法组合覆盖，不对应“一项一个方法”。

## 手工与 CLI 验证

`tests/manual/week1_test_cases.csv` 共 12 条：11 条实际通过，1 条 live 缺少 Key 场景
按安全边界标为“未执行”。已实际运行的两个原始 CLI 关键词为：

```powershell
python -m app.main --mode mock --keyword "machine learning astronomical spectra" --max-results 20
python -m app.main --mode mock --keyword "machine learning stellar spectra" --max-results 20
```

另对 `machine learning stellar spectra` 连续运行两次。四次运行均返回 0，每次统计均为：

- 原始 20 条
- 清洗后 20 条
- 去重后 18 条
- 重复 2 条
- 排序 CSV 18 条
- SQLite 18 条

四次均生成独立 run_id，且配置状态为 `completed`。JSON、两张 CSV、SQLite、两张图和
摘要均存在且非空；配置中的输出路径均为相对路径。本次验证目录核对后已精确清理，
没有保留为正式实验或基线。

## 发现与修复

- 原实现把输出写到固定目录，多次运行会覆盖 CSV、图表、摘要和数据库。本次改为唯一
  run 目录，并增加 `run_config.json`。
- 原程序没有拒绝空关键词。本次在创建 run 目录前校验，避免生成伪成功实验。
- 第一轮自动测试为 6 通过、1 错误。错误来自测试读取 SQLite 后没有显式关闭连接，
  Windows 无法清理临时数据库；修复测试夹具并全量重跑后 7 个全部通过。该错误不影响
  应用保存结果，但属于有效的测试生命周期问题。

## 未覆盖范围

- 本次没有调用 OpenAlex live，也没有读取真实 API Key。
- 未测试 OpenAlex 网络超时、限流和远端字段变化。
- 未对人工相关性标签或排序质量计算准确率。
- 处理、去重和各子分数仍需要更细粒度单元测试。
- 没有测试高并发写入；当前目标是本地单进程 CLI 实验。

自动测试使用 `TemporaryDirectory`，没有污染正式 `outputs/experiments/`。普通运行结果
默认被 `.gitignore` 忽略，不能直接作为稳定基线提交。
