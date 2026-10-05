# Scientific Comparison Workspace v0.1 实施报告

本任务依据经审查的 2026-10-05 Sol handoff 实施本地产品，没有重新进行产品战略规划。

## 基线与隔离

Fetch origin main 后基线为 5876190f9c2f959d37a2755274298a7138f9af51。
使用独立 managed worktree comparison-workspace-v01 和 codex/comparison-workspace-v01 分支。
原主工作区的 docs/reports/reentry_20261002/ 未跟踪目录保持原状；没有复制进本分支。
没有 push、PR、merge、tag 或 release。没有读取 .env、Codex 登录态或外部研究 evidence。

## 交付

- FastAPI / Pydantic / sqlite3 / pypdf 后端，单进程后台执行与 revision 冲突保护。
- React / TypeScript / Vite 中文 UI，本地 PDF.js，三个验收尺寸的矩阵与证据检查。
- 三个带每页警示的自制合成 PDF、多个结果候选、三个问题、四类审查状态。
- 真实 PDF 上传接口与浏览器路径，手工结果 / 观察 / 证据 / 判断、追加修订、
  仓外保存、重开、Markdown / JSON / CSV 导出。
- Demo / PrecomputedImport / OpenAI 三个 provider；默认硬离线、显式启用、
  SDK structured output、store=false、零自动重试、安全失败原因与返回元信息。
- 源字节 / 页面文本身份，Unicode code-point 定位，跨论文与导入身份校验。
- CI 仅增加产品依赖与浏览器回归；原统一测试 / Gate 步骤保持阻断顺序。

启动：python -m app.comparison_workspace_main。详见
[使用指南](../../docs/comparison_workspace/PRODUCT_GUIDE.md)、
[架构](../../docs/comparison_workspace/ARCHITECTURE.md)、
[数据来源](../../docs/comparison_workspace/DATA_PROVENANCE.md)、
[组会脚本](../../docs/comparison_workspace/DEMO_SCRIPT.md)。

## 文件归属

app/comparison_workspace_api.py、app/comparison_workspace_main.py；
src/comparison_workspace 下 domain、storage、pdf、providers、services、export、demo；
web/comparison-workspace 下 React 页面 / CSS、PDF 组件、Vite / TS / npm 配置与浏览器测试；
tests/automated/test_comparison_workspace.py；requirements-workspace.txt；
docs/comparison_workspace 五份文档；本 reports 目录的验收报告与合成演示截图。
现有文件的修改限 .gitignore、README.md、.github/workflows/ci.yml。

## 研究边界与验收范围

定位、结构 / 工程通过不升级为研究有效性。没有修改 frozen / historical evidence、
manifest、annotation、judgement、treatment mapping、W4/W5/W6 合同或旧算法。
没有添加外部账号或云服务。PDF.js 曾被 npm audit 标为高风险；已选择修复版本 6.2.108+
并在本地 npm audit 复查为 0，依据
[官方漏洞公告](https://github.com/advisories/GHSA-hq66-cqwq-w95j)。

后端 36 项定向测试、4 条浏览器回归与视觉验收已通过。
最终仓库验证：1117 tests / 15 skipped，Basic 与 Full PASS；Full 有 3 条历史警告。
精确命令、复验原因和环境限制见 [TEST_REPORT](TEST_REPORT.md)；未执行 live API。
后续审查仅应核对 [NEXT_STEPS](NEXT_STEPS.md)，v0.1 后停止功能扩展。

## 精确变更文件清单

```text
M	.github/workflows/ci.yml
M	.gitignore
M	README.md
A	app/comparison_workspace_api.py
A	app/comparison_workspace_main.py
A	docs/comparison_workspace/ARCHITECTURE.md
A	docs/comparison_workspace/DATA_PROVENANCE.md
A	docs/comparison_workspace/DEMO_SCRIPT.md
A	docs/comparison_workspace/LIMITATIONS.md
A	docs/comparison_workspace/PRODUCT_GUIDE.md
A	reports/comparison_workspace_20261005/IMPLEMENTATION_REPORT.md
A	reports/comparison_workspace_20261005/NEXT_STEPS.md
A	reports/comparison_workspace_20261005/SCREENSHOT_CHECKLIST.md
A	reports/comparison_workspace_20261005/TEST_REPORT.md
A	reports/comparison_workspace_20261005/screenshots/evidence-narrow.jpg
A	reports/comparison_workspace_20261005/screenshots/home-1440.jpg
A	reports/comparison_workspace_20261005/screenshots/pdf-evidence.jpg
A	reports/comparison_workspace_20261005/screenshots/workspace-1280.jpg
A	reports/comparison_workspace_20261005/screenshots/workspace-1440.jpg
A	reports/comparison_workspace_20261005/screenshots/workspace-narrow.jpg
A	requirements-workspace.txt
A	src/comparison_workspace/__init__.py
A	src/comparison_workspace/demo/__init__.py
A	src/comparison_workspace/demo/build_pdfs.py
A	src/comparison_workspace/demo/content.py
A	src/comparison_workspace/demo/fixtures/paper_A.pdf
A	src/comparison_workspace/demo/fixtures/paper_B.pdf
A	src/comparison_workspace/demo/fixtures/paper_C.pdf
A	src/comparison_workspace/domain/__init__.py
A	src/comparison_workspace/domain/models.py
A	src/comparison_workspace/export/__init__.py
A	src/comparison_workspace/export/reports.py
A	src/comparison_workspace/pdf/__init__.py
A	src/comparison_workspace/pdf/sources.py
A	src/comparison_workspace/providers/__init__.py
A	src/comparison_workspace/providers/base.py
A	src/comparison_workspace/providers/demo.py
A	src/comparison_workspace/providers/imported.py
A	src/comparison_workspace/providers/openai_provider.py
A	src/comparison_workspace/services/__init__.py
A	src/comparison_workspace/services/workspace.py
A	src/comparison_workspace/storage/__init__.py
A	src/comparison_workspace/storage/repository.py
A	tests/automated/test_comparison_workspace.py
A	web/comparison-workspace/index.html
A	web/comparison-workspace/package-lock.json
A	web/comparison-workspace/package.json
A	web/comparison-workspace/playwright.config.ts
A	web/comparison-workspace/src/App.tsx
A	web/comparison-workspace/src/PdfPage.tsx
A	web/comparison-workspace/src/main.tsx
A	web/comparison-workspace/src/styles.css
A	web/comparison-workspace/src/types.ts
A	web/comparison-workspace/src/vite-env.d.ts
A	web/comparison-workspace/tests/workspace.spec.ts
A	web/comparison-workspace/tsconfig.json
A	web/comparison-workspace/vite.config.ts
```

## v0.1 验收结论

十四项 handoff 验收均完成，环境限制在测试报告中明示。启动 / 无 Key demo / 真实上传路径 /
单活动目标 / 矩阵 / 页码与片段 / 四类状态 / 独立修订 / 实际重启持久化 / 三格式导出 /
三种尺寸视觉检查 / 历史 evidence 保护 / 现有验证 / 功能限定 diff 均有对应实现与验证。
不提供科学认证；没有研究新颖性或用户有效性主张。API 接口只通过 mock，没有 live 验证。

原工作区最终核验仍为 codex/srtp-reentry-audit-20261002，HEAD / origin/main 5876190f，
仅 docs/reports/reentry_20261002/ 未跟踪；目录仍在。独立功能分支的提交限定上述 57 个文件，
工作区在交付报告本地提交后为 clean。最后只更新报告；不扩展功能、不 push、不创建 PR。

## 2026-10-05 独立终审修复补记

以上为初次交付快照。独立终审在 e0d9480 上复现了现有测试未覆盖的问题，进行了 v0.1 范围内修复：

- 判断修订保留原始提议作为稳定修订目标，重跑后仍可展示、再次修订和导出。
- 手工判断及被修订的判断在问题、范围、活动目标或观察改变后标记 STALE；
  UI 当前四类审查与 Markdown 当前结论排除过期判断，另保留历史区域；JSON / CSV 保留状态。
  无当前语境标识的旧手工记录保守视为过期。原始 Run 输出不改写。
- 修订过的非活动观察不再使 Demo 运行失败；范围或内容修订后所有固定演示叙述暂停，改为未决。
- 自动 PRESENT 观察若没有有效引文，或引文混有无效定位，改为 AMBIGUOUS；原提议单独保留。
- 观察维度的重命名和添加按有效投影检查冲突，重跑不产生重复单元格。
- 内置合成 PDF 按已有源 SHA256 识别，改名后通过普通上传仍显示非研究证据标识。
- 本地服务使用 TrustedHostMiddleware 限制为 127.0.0.1 / localhost，保留现有同源写入检查。
- 输入变动或运行结束后清除旧检查器选择；证据勾选框显示论文编号及标题，便于区分同页同文引文。
- CSV 项目行只保留项目元信息，子记录仍独立导出，避免重复塞入整个运行历史。

未添加研究算法、外部服务或新产品范围。定向测试扩展为 45 项，浏览器流程为 6 条；
最终统一仓库验证和演示结论以独立终审报告及下方测试补记为准。
