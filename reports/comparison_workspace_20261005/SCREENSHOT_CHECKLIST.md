# v0.1 视觉验收

2026-10-05 实际启动应用，以 Codex 内置浏览器检查。没有只从源码判断 UI。

- [x] 1440×900 首页：中文层级、项目入口、无 Key CTA、三篇合成示意与警示。
- [x] 1440×900 工作区：问题 / 范围、活动结果下拉、粘性矩阵表头、四类审查 tabs、
  问题相对阻断、右侧原文引文 / SHA / 页码。
- [x] 1280×800：列收窄与矩阵内部滚动，主操作与证据检查器可读，无页面横向溢出。
- [x] 390×844：侧边栏隐藏，矩阵横向滚动，证据检查器改为可关闭抽屉。
- [x] 本地 PDF.js 第 2 页实际渲染；原文页文本 exact quote 单独突出。
- [x] 修订弹窗 / 用户修订来源 / 追加历史 / STALE，以及离线手工表单。
- [x] 合成项目持久化、重开、三个导出下载；对应 browser regression 通过。
- [x] 浏览器无未捕获 JS error；演示外部网络请求阻断后完整运行。
- [x] 默认实际启动只需一个后台服务；前端已本地构建。
- [x] 合成 PDF 每页都有 SYNTHETIC DEMO / NOT RESEARCH EVIDENCE；已检查 PDF 页渲染。
- [x] 修正视觉检查发现的小字 / 对比度问题后重新构建并刷新检查。

截图均为本任务自制合成数据，不含私人 PDF 或密钥：

| 截图 | 内容 |
| --- | --- |
| [首页](screenshots/home-1440.jpg) | 1440 桌面入口 |
| [工作区](screenshots/workspace-1440.jpg) | 1440 矩阵与第 2 页证据 |
| [较窄桌面](screenshots/workspace-1280.jpg) | 1280 工作区 |
| [窄屏矩阵](screenshots/workspace-narrow.jpg) | 390 响应式滚动 |
| [窄屏检查器](screenshots/evidence-narrow.jpg) | 390 证据抽屉 |
| [PDF 页](screenshots/pdf-evidence.jpg) | 本地 PDF.js 来源页 |

截图可见区域 / 全页高度不同；尺寸指设置的浏览器 viewport，长页使用 full-page capture。
PDF 页面上的文字不提供 bbox highlight，文本高亮发生在独立的提取页面文本中。
