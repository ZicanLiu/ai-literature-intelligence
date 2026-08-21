# Week 5: CI and Reproducibility Gate

## 任务完成摘要
本项目已成功引入 GitHub Actions CI 流水线，实现了工程保障的自动化，核心目标在于确保 `main` 分支的稳定性及 PR 的自动化验证。

## CI 核心配置说明
*   **触发条件**: `push to main` 和 `pull_request`。
*   **环境隔离**: 强制使用 Python 3.13，并仅依赖 `requirements.txt` 进行构建，彻底剥离对 GPU 包、SPECTER2 及 Cross-Encoder 模型权重的依赖。
*   **网络隔离**: 禁用一切 Live 服务（OpenAlex、Semantic Scholar、Hugging Face），强制要求测试使用 mock/fixture。未配置任何 secrets。

## 验证流程 (Workflow Steps)
1.  **Git Diff 检查**: 对 PR 自动运行 `git diff --check`，防止合并带有尾随空格或冲突标记的代码。
2.  **依赖安装**: 极速安装 Core 依赖。
3.  **W4 Approved Benchmark**: 自动执行 `python -m app.validate_w4_benchmark`。
4.  **全量离线测试**: 运行 `unittest discover`，任何 Error/Failure 将直接中断 CI。
5.  **Basic Quality Gate**: 执行 `python -m app.quality_gate --level basic` 门禁。
6.  **W5 Artifact 检查**: 引入轻量级柔性检查脚本 `scripts/check_w5_method_artifacts.py`。当仓库无正式 W5 manifest 时返回 PASS，存在时则自动触发 `app.validate_w5_method`。
