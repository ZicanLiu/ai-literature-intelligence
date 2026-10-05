# v0.1 验证记录

日期：2026-10-05。Python 3.13.9、Node.js 22.21.0、npm 10.9.4。
测试通过本分支 .venv 执行（复用机器已有的历史核心依赖）；没有读取 .env 或执行 live API。

## 定向验证（已执行）

| 命令 | 结果 |
| --- | --- |
| python -m unittest discover -s tests/automated -p test_comparison_workspace.py -q | 36 tests，OK；最近一次 4.602s |
| npm run build（web/comparison-workspace） | TypeScript + Vite 通过；PDF.js 异步分包后无 bundle size 警告 |
| npm test（同目录） | 4 passed，11.1s |
| npm audit | 更新 PDF.js 后 0 vulnerabilities |
| python -m app.comparison_workspace_main | 默认 loopback / 仓外数据目录实际启动成功 |
| Git diff --check | 定向阶段通过；最终检查另记录 |

36 项覆盖：有效 / 损坏 / 加密 / 大小 / 页数 / 重复 / Unicode 上传；
准确 / 越界 / 缺失 / 重复 / Unicode / 跨论文 evidence；
多个候选、单活动目标、未选拒绝与旧结果 stale；缺失与冲突、差异与阻断的区别；
四类状态并存、资源未知与技术失败区分；原记录 / 追加修订 / 重开 / 409 / 晚到输出；
离线 / Key / malformed / timeout / refusal / 元信息 / 零重试；
导入 question / revision / SHA / IDs / schema 校验；三种导出身份 / 修订 / stale / 遮盖；
HTTP 项目范围、同源保护与只复制声明输入的 dependency closure。

4 条 Chromium 流程：

1. 首页 → demo → 结果选择 → 矩阵 → 原文 / PDF → 修订 → 重开 → Markdown / JSON / CSV 下载。
   对非本地 HTTP(S) 请求直接阻断，并断言没有任何远端请求及页面 JS error。
2. 三个问题的条件状态、阻断与未知并存、固定 A/B 证据并排阅读。
3. 从文件上传路径导入 PDF → 手工结果 / evidence / fields → 结果修订 → 保存 / 刷新。
   文件为已授权自制 synthetic 源，用于验证真实上传机制，没有使用私人 PDF。
4. 1440×900、1280×800、390×844 无页面横向溢出；矩阵容器允许横向滚动，抽屉可关闭。

所有 OpenAI 请求验证均为 mock：没有凭据时不请求、hard offline 生效、SDK max_retries=0、
structured output / store=false、timeout / refusal / incomplete / malformed 路径及元信息。
真实账户 / 模型 / 计费未验证，不能宣称 live smoke 通过。

## 最终仓库顺序

将先本地提交取得 clean worktree，再执行 CONTRIBUTING 中的完整离线 unittest 一次，
然后 Basic / Full --skip-tests 与 git diff --check。执行后在此记录真实结果，不以旧报告替代。

## 已见诊断

- StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
  来自已安装 Starlette 1.7.0 测试客户端；测试仍通过。
- EOF marker not found：有意损坏 PDF 的拒绝用例由 pypdf 输出，随后断言通过。
- (node:…) Warning: The 'NO_COLOR' env is ignored due to the 'FORCE_COLOR' env being set.
  来自 Playwright runner 的终端颜色设置，不是浏览器应用错误。
- 初始 npm audit 的 PDF.js 高风险已修复并复查为 0；初始 Vite bundle 警告已通过按需加载
  PDF.js 消除。早期 Pydantic 序列化警告已通过先验证修订字段而消除。
- Poppler 渲染三篇 / 六页时每篇各输出一次：
  Syntax Error: No display font for 'Symbol'
  Syntax Error: No display font for 'ArialUnicode'
  两种配置字体均未用于合成正文；六页实际渲染后检查清晰，没有缺字 / 重叠 / 截断。

UI 的最终检查与截图见 [SCREENSHOT_CHECKLIST](SCREENSHOT_CHECKLIST.md)。
