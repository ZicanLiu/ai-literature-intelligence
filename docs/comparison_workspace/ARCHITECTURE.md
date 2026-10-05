# v0.1 架构与实现边界

app.comparison_workspace_main 是启动入口，app.comparison_workspace_api 是 HTTP adapter。
可复用业务全部位于 src/comparison_workspace。依赖方向 app → src；旧 CLI / 研究模块
不导入 FastAPI、PDF、前端或 OpenAI SDK。唯一复用的旧模块为 src.utils.current_timestamp。

## 模块

| 模块 | 责任 |
| --- | --- |
| domain/models.py | Pydantic v2 合同、稳定 ID、字段状态、四类判断、来源与修订 |
| storage/repository.py | sqlite3 聚合存储、事务 revision、Run 快照 / 状态 / 重启中断 |
| pdf/sources.py | 有限上传、pypdf 页面提取、原字节保存、精确 Unicode 定位 |
| services/workspace.py | 项目、上传、目标选择、手工观察、追加修订、后台执行与输出绑定 |
| providers/base.py | 提取 / 比较接口与安全错误类型 |
| providers/demo.py | 只对三个合成源和三个内置问题工作 |
| providers/imported.py | 导入同一候选合同，严格校验输入身份 |
| providers/openai_provider.py | 显式配置的 Responses adapter，无自动重试 |
| export/reports.py | Markdown / JSON / CSV、原记录与修订、敏感字符串遮盖 |
| demo/ | 三个自制合成源、内容与可选开发用 PDF 生成脚本 |
| web/comparison-workspace | React / TypeScript / Vite；本地 PDF.js；响应式矩阵与检查器 |

采用一个 SQLite 数据库：projects 保存结构化聚合 JSON 与 revision，runs 保存不可替换的
输入快照、输出及运行元信息。无需 ORM 或迁移框架。原 PDF 单独存储，以服务器生成的
source ID 命名、独占创建，客户端文件名只作展示。没有浏览器任意路径接口。

输入变更在 BEGIN IMMEDIATE 事务中校验 expected_revision，再递增 revision。
分析完成时在同一事务对比输入 revision；过期输出只保存在 Run 中，状态 STALE，
不能覆盖当前项目。已完成分析在后续输入变更后亦显示 STALE。
corrections 追加保存 before / after / 理由 / 证据 / 操作者 / UTC 时间；
展示及 generation 使用当前修订投影，原记录和历史输出保留。

单个 ThreadPoolExecutor 执行后台工作，HTTP 返回 202 / run_id。进程重启将
QUEUED / RUNNING 改为 INTERRUPTED。没有 Redis、Celery、自动外部重试。
API 请求异常使用安全原因，不回传 SDK 原始异常 / 配置 / 密钥。
源、证据与结果引用跨 provider / import 信任边界再次校验。

## HTTP

所有产品接口位于 /api：

- GET capabilities；GET / POST projects；GET / PATCH projects/{id}。
- POST demo；POST projects/{id}/papers（multipart + expected_revision）。
- GET projects/{id}/papers/{paper_id}/source；GET .../pages/{zero_based_index}。
- POST .../papers/{paper_id}/results；PATCH .../active-result。
- POST .../evidence、observations、findings、corrections。
- POST .../extractions、analyses、imports；GET runs/{id}。
- GET .../import-template；GET .../exports/{markdown|json|csv}。

已有项目写入携带 expected_revision，冲突 409；新项目 / 新 demo 使用创建 revision 0。
FastAPI 自动 /docs 提供完整请求 schema。源按 project / paper 双重绑定。
拒绝跨源网页写入，静态响应有 CSP；PDF.js 独立异步 chunk 和本地 worker，
不加载 CDN / 外部字体，不执行 PDF 脚本。

default_data_dir 位于仓外；开发测试目录 temp/ 被忽略。前端依赖、dist、
浏览器临时报告和 tsbuildinfo 被忽略；package-lock.json 提交。
历史 requirements.txt 保持原样，产品依赖在 requirements-workspace.txt。
CI 增加产品依赖和浏览器步骤，原统一 unittest 仍只运行一次，Gate 明确 --skip-tests。

## 具体完整性机制

仅源 SHA256 与页面文本 SHA256 服务于浏览器证据、导入源字节校验和可移植报告；
它们防止引文跨源 / 跨解析结果绑定。项目 revision 服务于真实的并发修改和晚到输出；
失效会导致旧模型结论覆盖新输入。没有为普通源码增加 manifest 或自定义 Integrity Gate。
独立复制测试只携带本产品模块、src.utils、包初始化文件和 API adapter，即可完成 demo，
证明未依赖旧研究 artifact 或未合并的 sibling。
