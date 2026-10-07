# Astra 复审交接

更新日期：2026-10-07。**状态：`READY_FOR_ASTRA_DIFF_REVIEW = YES`。**
实际 API 调用 **0**。该状态只表示可进入 diff review，S0 仍需另行明确用户授权。

- D 盘 Git CLI linked worktree：`comparison-workspace-v011-live-safety-fix`。
- branch：`codex/comparison-workspace-v011-live-safety-fix`。
- base HEAD：`4f7bf7a46a89fe3db5141a300889f4b008ce71fc`。
- new implementation HEAD：`cd43fccc1b6649b1ec93b76c989f469529426688`。
- 本轮完整 suite / 两级 Gate 被验 HEAD：`dfa507822036846b1ea33cc6b05d498c3b059263`，
  原真实 D 盘 linked worktree，运行前及验收后 clean。
- 最终分支 HEAD 含随后仅修改两份报告的提交，使用 `git rev-parse codex/comparison-workspace-v011-live-safety-fix`
  取得；避免报告内自引用自身 commit SHA。最终精确 SHA 另在交付答复列出。
- files changed：19 个实现 / 测试 / 必要文档，另 4 份报告；清单见 [实施报告](IMPLEMENTATION_REPORT.md)。

| Fix | 行为 / 精确复审位置 |
| --- | --- |
| F1 | omitted 不变，false 撤回并覆盖 live=true；即时 UI 撤回、成功 / 失败权威同步。`services/live_ai.py:67`、`app/comparison_workspace_api.py:103`、`web/comparison-workspace/src/AISettings.tsx:16,27,62` |
| F2 | provider 代次永久失效旧授权，含同 Key / 环境 fallback / 切回；入队模型 / effort / 输入保持快照。`services/live_ai.py:28,44,110,119,151`、`services/workspace.py:264` |
| F3 | SDK 紧前短锁授权判定，网络锁外；连接测试独立操作且受撤销约束。`providers/openai_provider.py:65,79,145`、`providers/deepseek_provider.py:16`、`services/live_ai.py:135` |
| F4 | 无响应 reported=null，响应后失败保留真实安全元数据；UI / export 不作 requested / legacy fallback。`providers/openai_provider.py:79,119,162`、`services/workspace.py:286,397`、`export/reports.py:95`、`web/comparison-workspace/src/App.tsx:212` |

上表 `services/`、`providers/`、`export/` 均相对 `src/comparison_workspace/`。
定向测试主要在 `tests/automated/test_comparison_workspace_live_safety.py`；HTTP false 在
`test_comparison_workspace_live_ai.py:335`；浏览器在 `web/comparison-workspace/tests/live-ai.spec.ts:143,182,219,237`。

**当前 canonical 验收：** 仅完整运行 **1 次**，**1158 tests / 0 failures / 0 errors / 15 skipped，
335.733s，PASS，exit=0**。随后依次 Basic PASS（0 错误 / 0 警告）、Full PASS（0 错误 / 3 条历史警告），
均 `--skip-tests`；git diff --check PASS，git status clean。
明确清除 shell 的 PYTHONIOENCODING，未设置任何额外 Python 编码环境变量：
Python 3.13.9，Windows 11 / AMD64，locale cp936、stdout / stderr gbk，UTF-8 mode=0，
PYTHONIOENCODING / PYTHONUTF8 等编码变量未设置；DISABLE_LIVE_API=true。
环境审计仅使用非敏感白名单，不读取或输出 API Key。日志直接保存原始字节，按实际 cp936 解码。
本地证据在 `temp/live-safety-canonical-final-dfa5078/`，环境 / suite / Gate / Git 状态均绑定上述 HEAD。
Full 的 W1 CSV 结构、19 个 W1 ID、历史已跟踪 experiment 三条警告原样保留。
临时 Gate 汇总脚本有一条非阻断 SyntaxWarning，Gate 的原始输出及退出码均 PASS。

2026-10-06 历史验收：**79 项定向 PASS**；浏览器 **16 个独立用例 PASS**；build PASS；
hard offline / provider isolation / sentinel PASS。Basic PASS（0 警告）；Full PASS（3 条历史警告），均 `--skip-tests`。
完整 base diff / `git diff --check` PASS；交付工作树 clean；源工作树干净、HEAD 未变。

2026-10-06 首次 canonical suite：**1158 tests / 2 failures / 15 skipped**，真实 Git 上下文、当时 clean。
两个 W5 CLI 失败由新增 SDK mock 测试清空 Windows OS 环境引入的平台缓存污染，已修复；
安全模块后跟两个受影响用例的同进程 79 项复测 PASS。

2026-10-07 上一轮用户授权后的复验在 `9214024` 运行 **1 次**（保留历史失败）：
**1158 tests / 0 failures / 5 errors / 15 skipped，379.525s，exit=1**。此前 W5 失败未重现。
五个 error 来自 `ExternalCoordinatorCliSequenceTests.test_real_cli_sequence_stays_external_and_git_clean`
的 import / compare / adjudication_task / adjudication_import / final 子用例。
验证启动为日志强制 `PYTHONIOENCODING=utf-8`，子进程 UTF-8 stderr 被默认 cp936 / GBK 解码；
读取线程 UnicodeDecodeError 导致 stderr=None，`:1094` 的 assertIn 随后 TypeError。
具体位置：`tests/automated/test_pilot_selection_context.py:1076,1094`、`app/pilot_curator_workflow.py:278`。
原始字节诊断复现编码冲突；移除该覆盖后，原完整方法及五个 subTest **1 test / PASS / 8.627s**。
该轮没有修改源码或断言，没有追加第二次完整 suite；**该轮 Basic / Full Gate NOT_RUN**。
其原始日志在 `temp/live-safety-final-validation-20261007/`；本轮最终 PASS 不改写该轮失败，
详见 [测试报告](TEST_REPORT.md)。此前 W5 缓存问题及五个编码 error 均未在本次全量复验重现。

后续为 Astra diff review；S0 需要另行明确授权。
本轮仅更新 TEST_REPORT 与本交接，源码 / 测试 / 依赖 / 冻结 artifact 相对被验 HEAD 不变。
限制：已进入发送阶段可能在进行，无法承诺召回；未观察的部署环境瞬间变化不追溯；
真实 API 未验证；R4 / parser / locator / multimodal / 历史 evidence 未改变。未 push / PR / merge。
