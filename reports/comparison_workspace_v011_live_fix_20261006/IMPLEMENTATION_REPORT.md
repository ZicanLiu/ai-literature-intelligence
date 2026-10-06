# v0.1.1 Live 安全修复实施报告

日期：2026-10-06（Asia/Shanghai）。范围：F1–F4。

- Git CLI linked worktree：`comparison-workspace-v011-live-safety-fix`，位于用户指定的 D 盘 MVP 目录。
- 分支：`codex/comparison-workspace-v011-live-safety-fix`。
- base HEAD：`4f7bf7a46a89fe3db5141a300889f4b008ce71fc`。
- new implementation HEAD：`cd43fccc1b6649b1ec93b76c989f469529426688`。
- 原 v0.1.1 工作树保持干净且 HEAD 不变；PR #87 未触碰。没有 push、PR、merge、tag 或 release。
- 实际 OpenAI / DeepSeek API 请求数：**0**。

## 实现

| 项 | 最终行为 | 主要消费者 / 风险 |
| --- | --- | --- |
| F1 | omitted acknowledgement 保留原值；true 记录确认；false 撤回并关闭 Live，覆盖同请求的 live=true。UI 取消确认立即 PATCH false，成功同步后端响应，失败回读 capabilities。 | AI 设置、API、新 generation；防止明确撤回后继续发送及前端假成功。 |
| F2 | 每 provider 的内存授权代次单调递增。撤回、off、clear、换 Key、切走 provider、关闭进程使旧授权失效；同值 Key、同值环境 fallback、切回和重新启用都不能恢复旧任务。 | 实际 executor 队列及已捕获适配器；防止旧布尔状态重建后旧任务复活。 |
| F3 | 内容序列化、客户端 / SDK 方法 / 本地 schema 准备后，SDK 调用紧前核验代次、凭据值及来源、所选 provider、hard offline。generation 还要求 Live / consent。 | 两家 generation 与 models.list；消除准备阶段发生撤回后的外发。 |
| F4 | requested_model 固定入队值。provider_reported_model 只来自实际响应；未取得响应失败为 null。响应后拒绝、incomplete、schema / 身份校验失败保留安全模型、request ID、数值 usage。 | Run、UI、Markdown / JSON / CSV；避免 requested 冒充 returned 或失败时丢失真实元数据。 |

授权代次只服务已经出现的旧适配器复活风险，没有新增持久化授权框架或自定义 integrity layer。
代次、Key 和 credential source 不写入 Project / Run / 数据库。
model / reasoning / provider / input_snapshot 保持入队快照，后来的设置修改不改写任务。

最终授权判定和进入 `send_started` 阶段在短暂 settings 锁内排序，然后释放锁立即调用 SDK。
撤回在此判定前完成时，SDK 调用数为 0；进入该阶段后，请求可能正在进行，不能承诺召回。
网络等待不持 settings 锁。连接测试拥有独立 metadata 操作授权，不要求论文确认，不能借其发送论文。

OpenAI 保留同一次 Responses parse / store=false 请求，改用 raw-response 包装取得安全元数据后再解析。
本地 SDK 2.54.0 的真实 MockTransport 用例验证了解析失败分支；没有增加请求或保存原始响应体。
官方说明明确 SDK parse 包含 schema 转换与解析，见 [OpenAI 官方结构化输出文档](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)。
DeepSeek 保留 create + JSON Schema + 本地 JSON 校验；reasoning 参数及零自动重试未改变。

旧 Run 的 raw `model` 原值保留；不回填 requested / provider-reported。
UI 和 Markdown 标明来源不明 / 未取得返回；JSON / CSV 保持两个明确字段的 null，不能从 raw model 推断。
Repository 仍用原 JSON 存储，无迁移或历史记录回写。

## 修改文件

实现提交共 19 个文件；另新增本目录四份报告。

| 文件 | 用途 |
| --- | --- |
| `app/comparison_workspace_api.py` | acknowledge 的 omitted / false 区分 |
| `src/comparison_workspace/services/live_ai.py` | 撤回、代次、凭据身份及短锁发送判定 |
| `src/comparison_workspace/providers/openai_provider.py` | SDK 紧前检查、raw parse 元数据、安全失败 |
| `src/comparison_workspace/providers/deepseek_provider.py` | schema 准备后的最终检查 |
| `src/comparison_workspace/providers/base.py` | ProviderFailure 的 model 来源语义 |
| `src/comparison_workspace/services/workspace.py` | 队列 requested 快照、失败 reported 记录 |
| `src/comparison_workspace/domain/models.py` | legacy model 兼容说明，无 schema 字段新增 |
| `src/comparison_workspace/export/reports.py` | Markdown 明确 requested / reported / legacy |
| `web/comparison-workspace/src/AISettings.tsx` | 即时撤回及权威状态同步 |
| `web/comparison-workspace/src/App.tsx` | 不从 requested / legacy 推断返回模型 |
| `tests/automated/test_comparison_workspace_live_safety.py` | 双 provider 队列、barrier、MockTransport、重启和 provenance |
| `tests/automated/test_comparison_workspace_live_ai.py` | HTTP false / omitted 回归及 sentinel 扩展 |
| `tests/automated/test_comparison_workspace.py` | 适配同一次 SDK raw parse 的既有 mock |
| `tests/fixtures/comparison_workspace/mock_live_sdk.py` | raw-response double |
| `tests/fixtures/comparison_workspace/mock_live_server.py` | 仅 mock 测试服务的 barrier / failure 控制 |
| `web/comparison-workspace/tests/live-ai.spec.ts` | 撤回、旧队列、失败同步、模型与 legacy 展示 |
| `docs/comparison_workspace/ARCHITECTURE.md` | 代次 / SDK 边界及连接授权 |
| `docs/comparison_workspace/DATA_PROVENANCE.md` | 成功、失败和 legacy 模型来源 |
| `docs/comparison_workspace/PRODUCT_GUIDE.md` | 撤回 / 已发送限制 / 导出说明 |

## 验收限制

F1–F4 定向验收通过；最终 79 项定向回归通过，浏览器 16 项独立用例通过。
完整 suite 的唯一一次运行为 **1158 项 / 2 failures / 15 skipped**，详见 [TEST_REPORT](TEST_REPORT.md)。
两项失败由本次 SDK 测试清空 Windows OS 环境导致缓存污染，已修复并按同进程顺序复测通过；
按“完整 suite 只运行一次”约束未再次运行完整 suite，不能把这个结果改记为全套 PASS。

本次只保留真实系统架构变量来隔离测试环境，不伪造平台字段，不修改 W5 校验、断言或冻结 artifact。
完整 suite 当时的 HEAD `771e423aa133624052422d840a99363afafab6d5` 后续 amend 为上述实施 HEAD；
差异只在新增测试的 OS 环境隔离及假凭据占位命名，产品代码字节未再改变。

仍需成功的完整 canonical 复验；当前 `READY_FOR_ASTRA_DIFF_REVIEW = NO`。
已发送请求无法保证召回；环境硬离线未被服务观察的瞬间变化不能被追溯记录，发送边界检查当前值。
parser、locator、历史 evidence、R4 中性输入冻结、实验基础设施和多模态均未改动。
