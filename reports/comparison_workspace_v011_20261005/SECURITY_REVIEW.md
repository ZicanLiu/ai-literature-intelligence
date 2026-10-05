# v0.1.1 安全自检

日期：2026-10-05。实施者自检；独立审查尚未执行。

## 凭据生命周期

password input → 显式回环同源请求 → LiveAISettings 私有内存 → 官方固定端点 SDK 认证。
保存、测试、切换或关闭 modal 后清空密码输入。session Key 优先对应环境 Key。
两家分别配置 / 清除；进程关闭清除内存状态，环境凭据仍由进程环境管理。
清除 session Key 可能回退到环境 Key，UI 明示该行为并关闭当前 Live / 撤销确认。
API 从不返回密钥。Project / Run / Repository 均没有 credential 配置字段。

## 外发控制

Live 默认关闭；后端要求 Key、model、当前服务的发送确认与显式 Live。
DISABLE_LIVE_API=true / 1 是两家共同硬禁止，models.list 也禁止；session Key 不能绕过。
模型测试不会自动执行，不发送论文或生成内容。
后台捕获凭据和配置，执行前再次检查授权；关闭 Live、切换服务或替换 / 清除 Key 使旧凭据任务不可调用。
已在进行的请求不能撤回。本地单用户进程会话不是多用户认证隔离。

## HTTP 与 endpoint

只接受 localhost / 127.0.0.1 Host，同源写入检查及 CSP connect-src self 保留。
前端不能指定 base_url；请求合同 extra=forbid。OpenAI / DeepSeek URL 由服务器类固定。
API Key 使用 SecretStr 请求合同，所有 request validation errors 用固定安全错误，
避免 FastAPI 默认 input 回显。禁止把 Key 粘进模型 ID 字段。API 响应 Cache-Control=no-store。
SDK 错误正文 / header 不回传、不打印；只保留格式安全且不含已知 Key 的 request ID。

## 实测

两套运行时拼接的 sentinel 在 SQLite / WAL / 保存项目 / Run / GET / 错误 / 三种导出 / 捕获日志中均未出现。
SDK 认证错误正文及 request header 含 sentinel 时，HTTP / Run 只留安全原因。
浏览器验证 localStorage、sessionStorage、cookies 与 IndexedDB，无凭据持久化；密码输入保存后为空。
新 live 浏览器测试关闭 trace 与 screenshot，避免工具把含凭据请求写入测试产物。
产品源码 / frontend build / 新报告 / mock fixture 的完整 sentinel 扫描通过；交付前另检 Git diff。
旧 offline 浏览器测试不输入凭据，保留其原失败诊断设置。
测试使用合成 PDF，未读取 .env、私人 evidence 或用户真实 Key；没有真实付费请求。

## 审查范围限制

没有证明系统对所有攻击、恶意 PDF、外部调试日志或多用户部署安全。
本实现依赖本地受信进程及官方固定 HTTPS 服务端；本轮不是 penetration test。
store=false / stateless 均不能推导服务整体零留存，UI 分 provider 解释。
