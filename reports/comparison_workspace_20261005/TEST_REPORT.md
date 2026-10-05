# v0.1 验证记录

日期：2026-10-05。Python 3.13.9、Node.js 22.21.0、npm 10.9.4。
测试通过本分支 .venv 执行（复用机器已有的历史核心依赖）；没有读取 .env 或执行 live API。

## 定向验证（已执行）

| 命令 | 结果 |
| --- | --- |
| python -m unittest discover -s tests/automated -p test_comparison_workspace.py -q | 36 tests，OK；最近一次 4.732s |
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

初次完整顺序在 clean commit ac5760a 上执行：1117 tests in 253.699s，
OK (skipped=15)；Basic 0 errors / 0 warnings；Full 0 errors / 3 historical warnings；
git diff --check 与 git diff --check origin/main...HEAD 均 exit 0。

随后交付复核发现 locator 验证改变类别时也须保留原始提议，补入 provider_output 与
该失败路径的回归断言。因必要的代码变更，将在新 clean commit 上重新执行最终完整顺序，
不会将初次通过结果冒充修订后的结果。最终结果在执行后追加。

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

## 最终复验（全部 exit 0）

代码基准：13bf593（随后仅更新交付报告）。按 CONTRIBUTING 顺序实际执行：

```powershell
python -m unittest discover -s tests/automated -p "test_*.py" -q
python -m app.quality_gate --level basic --skip-tests
python -m app.quality_gate --level full --skip-tests
git diff --check
```

- unittest：Ran 1117 tests in 250.603s；OK (skipped=15)。36 项产品测试包含其中。
- Basic：562 files，0 errors / 0 warnings，PASSED；测试明确 SKIPPED。
- Full：562 files，0 errors / 3 warnings，PASSED；测试明确 SKIPPED。
- git diff --check、git diff --check origin/main...HEAD：均 exit 0。
- 实际停止 / 重启默认启动进程，重开同一项目后 3 篇 / 21 观察 / 3 活动目标 / revision 1
  保留，数据目录确认在 Git 之外；最终代码的 demo 再次 COMPLETED，原始提议字段保留。
- 没有 live API；GitHub CI 未运行。两次完整顺序均成功，第二次由必要的 provenance 修复触发；
  没有以第一次结果替代第二次。没有借 Gate 重复运行 unittest。

Full 原样警告：

```text
WARNING: 历史 W1 标注存在 1 个 CSV 结构问题；保留原始交付物并作为遗留问题记录。
WARNING: 历史标注 data/manual/relevance_labels_w1.csv 有 19 个 ID 未在当前统一样例中找到；作为 W1 遗留问题记录。
WARNING: 检测到历史已跟踪 experiments：openalex_stellar_spectra_60
```

15 skips：静态 suite 标记核对显示 10 项 TestRealEvidenceIdentity 因
SRTP_DOWNSTREAM_EVIDENCE_ROOT not set or missing 跳过；剩余 5 项为当前 Windows 的
大小写别名 / symlink / junction 能力限制（与源中仅有的五个动态 skip 调用对应）。
没有配置或读取私人 evidence root，没有绕过 skip 条件；不宣称真实外部 evidence 回归已执行。

本地 staging 曾发现新增文件 EOF 多余空行，已在初次代码提交前清除；最终分支 diff 检查通过。
Git 在前端文本 staging 时提示 LF will be replaced by CRLF the next time Git touches it；
这来自当前 Windows checkout 的行尾设置。最终内容没有空白差异错误。

## 2026-10-05 独立终审复验

从 e0d9480 重新验证，未直接采用初次交付报告中的通过结论：

- 修复前：36 项后端测试通过；前端构建通过；4 条浏览器流程通过（8.6s）；npm audit 0 漏洞。
- 红队额外复现：判断修订重跑失去有效投影、手工判断过期遗漏、修订后切换目标导致 Demo 失败、
  固定演示叙述忽略修订、普通上传丢失合成身份、非本地 Host 可读写接口等问题。
- 修复后定向测试：45 tests in 6.466s，OK；新增 9 项持久行为回归。
- 修复后 TypeScript / Vite 构建通过；6 条浏览器流程通过（15.1s）。
  新流程覆盖判断修订重跑、问题改变后的历史分区、来源可辨识的证据选择、
  修订观察后切换目标并重跑；原流程补验普通上传的合成警示。
- npm audit：0 vulnerabilities；python -m pip check：No broken requirements found。
- 新测试首次暴露 CSV 项目行重复完整历史导致普通 CSV reader 超过字段长度，
  已去除项目行的重复子集合，保留各类独立记录，再次通过。未删除断言或放宽产品错误。
- 最终统一验证须在本次修复的本地 clean commit 上执行一次；结果在执行后追加。
  未执行 live API，未读取私人 evidence，未运行 GitHub CI。
