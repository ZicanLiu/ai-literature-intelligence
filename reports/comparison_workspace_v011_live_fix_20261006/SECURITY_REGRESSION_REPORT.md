# 安全回归报告

日期：2026-10-06（Asia/Shanghai）。实施 HEAD：`cd43fccc1b6649b1ec93b76c989f469529426688`。
OpenAI / DeepSeek 实际 API 请求：**0**。材料均为项目合成 fixture。

## 授权和发送

| 检查 | 结果 |
| --- | --- |
| 两家显式 false；false + live=true；omitted 配置更新 | PASS：撤回后三个授权布尔值 false，新生成拒绝，SDK 0 次；omitted 保留确认 |
| 实际队列：consent / off / clear / switch / replace 后重建同值配置 | PASS：两家旧 Run FAILED、SDK 0 次；新 Run 才可发送 |
| clear 后同值环境 Key fallback | PASS：旧 generation / connection 均失效；新适配器可 mock 发送 |
| 生成最终 barrier：consent / clear / switch / offline | PASS：两家均 SDK 0 次 |
| 连接最终 barrier：clear / switch / offline | PASS：两家均 models.list 0 次 |
| 客户端准备期间 clear | PASS：生成 / 连接均 0 次 SDK 请求 |
| metadata 操作授权不能调用 generation | PASS |
| 已进入 SDK 的请求期间撤回 | PASS：设置操作及时完成，旧请求可返回，无取消前发送的假状态 |
| 重启 / close | PASS：两家会话授权消失，QUEUED / RUNNING 改 INTERRUPTED，无自动 SDK 重试 |
| provider 隔离及 hard offline | PASS：既有回归和新增 barrier 覆盖 |

最小机制是 provider 内存代次；旧授权不靠当前 booleans 或 Key 相等恢复。
最终判定同 settings mutation 共用短锁；SDK / 网络等待在锁外。
硬离线为部署环境变量，状态服务观察到开启会作废旧代次，SDK 入口还检查当前值。

## 凭据与元数据

sentinel 只在测试执行时拼接；未写入完整 sentinel 常量。
配置失败不回传 SecretStr 输入、SDK 原异常、认证头或 raw body。
request ID / reported model 使用安全标识过滤，usage 只保存已知数值计数。
未取得响应的 auth / timeout / network / SDK 失败 reported model 为 null。

| 介质 | 核验 |
| --- | --- |
| SQLite / synthetic source files | HTTP 成功及失败 Run 扫描；浏览器测试数据库字节扫描，0 findings |
| Markdown / JSON / CSV / 下载 | 两家成功和失败用例验证字段并检查 sentinel，0 findings |
| 日志 | HTTP capture 和本次本地验证日志扫描，0 findings |
| localStorage / sessionStorage / cookies / IndexedDB | BYO 浏览器流程断言，无凭据持久化；failure provenance 再查 local / session |
| 前端 dist | 完整 sentinel 字节扫描，0 findings |
| test-results / playwright-report / mock fixture | 扫描测试输出与声明 fixture，0 findings；Live 用例 trace / screenshot 关闭 |
| 新报告 / 本次完整 Git diff | 完整 sentinel 字节扫描，0 findings |

本地审计脚本 `temp/live-safety-validation/scan_sentinels.py` 只扫描声明的产品 / 合成输出，
Git diff 使用 base HEAD；输出只有文件计数、相对路径和 finding 布尔值，不输出 Key。
`.env` 未读取、复制或记录，未输出环境 Key 值；新环境只保留实际非敏感 Windows 系统变量。
源工作树没有修改；只提交源码、测试、必要文档和四份报告，无数据库、普通实验或 private evidence。

## 解释边界

这证明离线工程条件下的授权与来源语义。真实 provider 请求未执行；不证明真实余额、兼容性或科学质量。
完整 suite 的一次运行失败及已修复的环境污染详见 [TEST_REPORT](TEST_REPORT.md)，不因安全回归 PASS 被覆盖。
S0 仍需成功完整复验、Astra 定向复审和独立用户授权。
