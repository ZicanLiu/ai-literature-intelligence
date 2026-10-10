# 第三方依赖与分发边界

本工作台的 React 组件、样式和三篇 Synthetic Demo PDF 为本仓库编写；未复制第三方论文或界面源码。
源码预览通过 npm / pip 下载第三方包，保留其包内许可文件，不提交 node_modules 或 dist。
package-lock.json 固定前端解析版本；以下是此次干净 npm ci 安装核对的主要前端依赖：

| 包 | 版本 | 许可 / 安装包内原文 |
| --- | --- | --- |
| react / react-dom | 19.3.0 | MIT，各自 LICENSE |
| scheduler | 0.28.0 | MIT，LICENSE |
| lucide-react | 0.468.0 | ISC；部分 Feather 为 MIT，LICENSE 保留两段说明 |
| pdfjs-dist | 6.4.299 | Apache-2.0，LICENSE；PDF.js 与 worker 保留其源码许可头 |
| Vite | 7.3.6 | MIT，LICENSE.md 含捆绑依赖说明 |

上述原文随对应包从 registry 安装；本预览不重新分发构建产物。将来若分享独立 dist / 二进制，
应随包提供 React / ReactDOM / scheduler / Lucide 版权许可与完整 Apache-2.0 文本，
保留 PDF.js 许可头和适用 NOTICE；不能仅依赖此摘要代替原文。

Python 直接依赖许可：FastAPI、Pydantic、OpenAI SDK 为 MIT，Uvicorn、httpx 为 BSD-3-Clause，
pypdf 为 BSD-3-Clause，python-multipart 为 Apache-2.0；各包及传递依赖的原文随 pip 安装保留。
测试 Playwright 为 Apache-2.0；TypeScript 为 Apache-2.0；测试工具不捆绑进产品页面。

项目根目录目前未声明整仓开源许可证。团队获取代码不表示获得第三方论文再发布授权，
也不替项目所有者选择许可证；公开软件发行前需另行明确项目许可。
