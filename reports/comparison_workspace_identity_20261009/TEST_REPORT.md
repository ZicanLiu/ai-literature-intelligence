# 本轮离线验证

日期：2026-10-09，Asia/Shanghai。代码基线 867a0db；当前补丁详见 DIAGNOSIS_AND_REPAIR.md。
使用既有 live-safety Python 3.13 环境，仅复用安装依赖，cwd 为本任务独立工作树。
所有 SDK 调用均 mock / in-memory HTTP transport；新增回归同时阻断 socket connect。
子进程移除 provider Key / model 环境并设置 DISABLE_LIVE_API=true，不读取 .env。

## 定向测试

执行 unittest 的五个模块：test_comparison_workspace_identity、test_comparison_workspace_s1_diagnostics、
test_comparison_workspace_live_ai、test_comparison_workspace_live_safety、test_comparison_workspace。

最终定向测试 100 项通过，0 skipped，unittest 耗时 14.401 秒（包装进程 16.221 秒）。
含保存 S1-A 两阶段提议经两家 adapter 的四次离线回放，以及真实 OpenAI SDK 的非空引用
schema parsing / DeepSeek local parsing，全部使用 in-memory transport，零真实网络请求。
保存 S1-B 诊断只能复现已知 guard 失败，缺失 raw 不能完整回放；没有把 scaffold 当真实响应。

compileall 和 git diff --check 通过。定向验证前后核对原 pilot 的 13 个 capture JSON / PDF /
SQLite 文件 SHA256，均未变化。永久回归 fixture 只有原生安全诊断，原论文、响应和数据库未提交。

## Canonical sequence

为满足已有 Git-clean 测试，先精确 stage 本任务文件并作本地提交，然后执行：

```powershell
python -m unittest discover -s tests/automated -p "test_*.py" -q
python -m app.quality_gate --level basic --skip-tests
python -m app.quality_gate --level full --skip-tests
git diff --check
```

完整 suite / Gate 尚待本地提交后执行；此处不提前声明通过。最终结果将在验证完成后补记。
完整 suite 只运行一次，Gate 均跳过重复 unittest。

可选外部 replay 需配置 COMPARISON_IDENTITY_REPLAY_ROOT 为已有双族 pilot 目录；未配置时
只跳过该一个历史回放测试，核心合成离线回归仍执行。不提交私人绝对路径或外部原文。

已见既有环境输出：Starlette httpx deprecation、损坏 PDF 负面测试的 EOF marker。
它们不代表模型调用或身份校验失败。本轮没有删除断言、放宽 validator 或改历史 evidence。
