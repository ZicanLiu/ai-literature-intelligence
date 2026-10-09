# 数据来源与修订语义

schema_version = comparison-workspace/v0.1。这是产品合同，不是研究标注或 benchmark 合同。

Project 的 question / scope 决定本次比较语境。每篇 Paper 包含稳定 Result 候选集合，
并只有一个 active_target_result_id。候选 / 活动身份由该显式 ID 关联，不从字符串反推。
每个论文身份字段保存 value 与来源（filename、synthetic-fixture、user-correction）。

SourceSnapshot 保存原始 SHA256、文件名、pypdf 版本、页数、每页提取文本 / 文本哈希、
提取状态与错误。原始 PDF 不原地覆盖。
NO_TEXT、PARTIAL、EXTRACTION_FAILED 为技术状态；它们不产生“论文未报告”的科学结论。
自动 provider 要求页面文本完整可提取；受限源仍可阅读并手工整理。

EvidenceSpan 保存 paper ID、source snapshot ID、0 起算的 PDF 页、提取文本哈希、
[start, end) Unicode code-point offsets 和 exact quote。
后台只接受该论文的当前源身份，精确匹配页面文本；
越界、缺失、重复引文保留 INVALID / review_reason、空 offsets。跨论文身份直接拒绝。
Python 使用 code point 索引，前端使用 Array.from，包含 emoji / 非 BMP 字符亦保持一致。
“已定位”仅证明出现，不证明推理 / 解释正确。任一支持引文无效的自动判断进入未决复核，
不作为已支持前提或阻断展示；有效定位也不等于人工批准。

Observation 的 PRESENT、NOT_LOCATED、AMBIGUOUS、NOT_APPLICABLE 表达不同信息状态。
未定位不等于已知冲突；字段不同不自动构成阻断。
Finding 四类可同时存在，且保存 affected_result_ids、问题相关范围、理由、证据。
单个已确认的协议阻断不会被另一个无关字段的未知状态覆盖。

provenance.mode 为 manual / demo / import / api，包含 actor、model、run_id 与 UTC 时间。
API 和导入都是需复核的提议；用户修订独立标识 local-user，不把模型记录升级为 human gold。
Correction 只追加：before、after、理由、独立证据、操作者和时间。结果 / 字段 / 判断 / 身份
的原记录保留，当前 UI 和输入投影叠加修订。历史 Run 的结构化输出不被修改。
本地单用户操作者标识不是经认证的真实研究人员署名。

Run 保存输入 revision / 全快照、mode / stage / provider / model、status、输出、时间、
request ID、返回 token usage、失败原因。费用未可靠计算，保持 unknown。
Run.output.provider_output 保存提供方原始结构化提议，独立于带 locator 的验证投影。
无效引文导致“未决”时，原先的类别和解释仍可在运行详情与全部导出中审阅。
晚到结果为 STALE，不覆盖新 revision；过期历史运行保留可查。
重启中断不会自动重试可能计费的请求。
手工保存只记录输入快照，不清空既有模型提议，也不把它们改为用户批准。

Markdown / JSON / CSV 同时保留有效投影、原记录、corrections 与历史 Run 输出。
报告含源哈希、活动结果 ID、证据 locator、mode、STALE 标志。可识别的敏感文本遮盖不会
修改本地原件 / 哈希；遮盖后的引用须回本地原文复核。CSV 的 record_json 保留完整对象结构。

三个合成 PDF 由本项目自制；每页明确 SYNTHETIC DEMO / NOT RESEARCH EVIDENCE。
确定性演示状态不是 gold、真实研究证据或科研优越性结论。目标切换 / 用户修订后，
演示不套用固定数值结论，改为提醒复核；不冒充任意 PDF 的离线自动 AI 分析。
没有接触 W4/W5/W6 label、Hidden、冻结 evidence、historical first-look 或旧方法实验。

## v0.1.1 live 运行

provider 为 openai / deepseek，requested_model 固定入队时的请求配置；provider_reported_model
只来自实际响应明确报告的模型。认证 / 超时 / 网络 / 发送前授权失败未取得响应时保持 null，
不以 requested_model 补值；响应已报告模型但拒绝 / incomplete / 本地 schema 或身份校验失败时，
仍保留安全模型标识、request ID 与数值 usage。OpenAI 通过同一次 SDK parse 的 raw-response
包装在本地解析前取得元数据，不另发请求、不保存原始响应体。
model 仅为兼容字段：新运行只写真实报告值，旧记录保留原值且来源不由此推断，不回填两个明确字段。
UI 未取得报告值时显示“未取得服务端返回模型”；Markdown / JSON / CSV 区分请求与报告字段。
reasoning_effort 仅记录显式使用的 DeepSeek 参数，None 表示服务默认 / 未发送。
input_modality=EXTRACTED_TEXT 表示实际发送的论文模态。source ID / hash 与 active result ID
仍在不可变 input_snapshot 中；耗时、request ID、token usage 与工程状态保留。
失败保留安全原因及可用的安全 request ID；不复制 SDK 原始异常或认证头。

credential source、session Key、环境变量内容和数据发送确认不写入项目或 Run。
确认只对当前进程 / provider 有效，不是人类批准模型输出，更不是 pure-human gold。
省略 acknowledge 不改变确认；显式 false 撤回确认并关闭 Live，即使同时提交 live_enabled=true。
确认撤回、Live off、清 Key、换凭据、切走 provider 与进程关闭永久失效旧的未发送授权，
以后重新确认 / 开启只授权新任务。授权代次与凭据只在进程内，不写入 Run 或数据库。
请求、返回和 JSON Schema 通过不构成科学解释正确性证明。

API 证据采用本次请求的页面 evidence_handle / quote。paper/source/page 由输入快照中的真实
页面关系确定性查表绑定；该 handle 只确认候选页来源，exact locator 另外验证引文出现位置。
Run.output.provider_output 保存该 wire 提议，evidence_handle_sources 保存对应查表，验证投影
仍含明确 paper/source/page/hash/offset 与 host 分配的 EvidenceSpan ID。其他论文的 handle 不会
被强行改到当前论文；未知/伪造/跨请求 handle 和重复引用均拒绝。既有历史提议及 Import
继续使用原身份合同，不迁移或重写。失败响应原文仍不持久化，安全诊断不能替代缺失的 raw。
