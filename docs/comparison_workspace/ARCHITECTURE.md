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

## v0.1.1 BYO API

services/live_ai.py 管理单后台进程的 provider / model / reasoning / consent / Live 状态。
两家 session Key 是私有内存字典，不进入 Pydantic Project、Run 或 Repository。
GET capabilities 返回两家安全状态；PATCH ai-settings 接收 SecretStr，拒绝额外字段与任意 base URL；
DELETE ai-settings/{provider}/key 只清除一个 session Key；POST ai-settings/test-connection 仅显式 models.list。
HTTP request validation errors 使用固定安全说明，避免 FastAPI 默认错误包含提交的秘密；API 响应 no-store。

OpenAI / DeepSeek 共享声明输入、容量限制、安全错误及认证模型检查。
DeepSeekProvider 独立实现 responses.create + text.format JSON Schema + 本地 Pydantic JSON 校验，
仅它映射 reasoning.effort；OpenAI 保留 parse / store=false。服务端 URL 固定，无用户 endpoint。
SDK 仍零自动重试；连接测试与生成都在 SDK 调用入口做最终硬离线检查。

Live 默认关闭，后端同时要求凭据、模型和 provider 数据发送确认。工作流 start_run 捕获新 adapter，
冻结 Key / credential source / model / reasoning、provider 授权代次与输入快照。
确认撤回、Live off、清 Key、替换凭据、切走 provider 与进程关闭递增相关代次，
重新授权不恢复旧适配器。服务观察到硬离线开启也作废两家旧代次；部署环境的未被观察的
开关变化不属于设置服务持有的状态，SDK 入口仍读取当前硬离线值。
省略 acknowledge 不变，显式 false 撤回并关闭 Live，覆盖同请求里的 enable。
同一 provider 在排队后改 model / reasoning，不改写该 Run 的配置。

发送边界：声明输入序列化、JSON Schema / 客户端 / SDK 方法准备完成后，紧接 SDK 请求调用前，
在短暂 settings 锁内核验 provider、授权代次、凭据值及来源、hard offline；生成再要求 Live 与确认。
通过判定时进入 send_started 阶段，随后释放锁调用 SDK。撤回先于此判定完成则零发送；
进入该阶段后的撤回不能承诺召回，请求可能已在进行。网络等待期间不持 settings 锁。
连接适配器只持显式 metadata 操作授权，不要求论文确认；也检查代次、凭据、provider 与硬离线，
不能借其执行内容生成。
前端取消确认立即 PATCH false；保存成功使用后端响应同步，失败回读 capabilities，回读失败明确状态未确认。

Run 的新可选字段 requested_model / provider_reported_model / reasoning_effort / input_modality
允许旧 v0.1 记录继续读取；Project schema 仍 v0.1，没有修改冻结研究合同或历史 Run。
requested_model 始终为入队配置；provider_reported_model 只来自实际响应，包括后处理失败的响应。
SDK 无响应失败保持 unknown；legacy model 保留原值，不猜测其历史来源。
workspace_input_mode 能力元数据固定 extracted_text，当前 Run 模态 EXTRACTED_TEXT。
图像能力按具体 DeepSeek 模型标记；OpenAI 任意 ID 的 image / json_schema 能力保持未知，
由用户选型与实际结构化请求验证，不自动宣称兼容。
