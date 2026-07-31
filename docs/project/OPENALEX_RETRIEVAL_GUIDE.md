# OpenAlex v2 检索与可靠性指南

本文说明独立 OpenAlex v2 客户端的接口、分页、筛选、有限重试、统计和安全约定。
它面向开发、测试和 live 验证，不代表已经接入正式入口。

相关文件：

- `src/openalex_client_v2.py`：请求、cursor 分页、去重、重试和统计；
- `app/openalex_fetch_v2.py`：独立命令行入口和 live 摘要 CSV；
- `tests/automated/test_openalex_client_v2.py`：不联网的自动测试；
- `tests/fixtures/openalex/`：自动测试使用的响应 fixture；
- `data/samples/w2/openalex_client/live_pagination_summary.csv`：整理后的 live 运行摘要。

`app/main.py`、`src/processor.py` 和旧版 `src/openalex_client.py` 不在本客户端的接入范围内。
是否替换或并入正式入口，由组长在集成阶段决定。

## 1. REST 请求和响应在本客户端中的含义

OpenAlex Works 是一个基于 HTTP 的 REST API。本客户端发送只读 `GET` 请求：

```text
GET https://api.openalex.org/works
```

请求由以下部分组成：

| 部分 | 本客户端中的用途 |
| --- | --- |
| HTTP 方法 | `GET`，读取 Works，不创建或修改服务器资源 |
| URL | `https://api.openalex.org/works` |
| 查询参数 | `search`、`select`、`filter`、`cursor`、`per_page` 和 `api_key` |
| 超时 | 每次 `requests.get` 都显式传入 `timeout`，默认 20 秒 |
| 请求体 | 没有；查询条件通过查询参数发送 |

成功响应应为 JSON 对象，并至少包含：

- `results`：当前页 Work 对象列表；
- `meta`：分页元数据，其中 `next_cursor` 指向下一页。

客户端先判断 HTTP 状态码，再解析 JSON，最后校验顶层对象、`results`、`meta` 和每条
结果的基本类型。状态码为 2xx 并不等于数据一定可用；结构不符合预期时仍会安全失败。

请求只通过 `requests` 的 `params` 参数构造，不手工拼接带 Key 的 URL。调试时也不得打印
`params`、`response.request.url`、完整异常对象或 HTTP 抓包内容，因为认证 Key 位于查询
参数中。

## 2. 调用接口与返回值

核心函数是：

```python
fetch_openalex_papers_v2(
    keyword,
    max_results=20,
    *,
    from_year=None,
    to_year=None,
    timeout_seconds=20,
    max_retries=3,
    backoff_base_seconds=1.0,
    max_backoff_seconds=30.0,
    api_key=None,
)
```

成功时返回三个键：

| 键 | 含义 |
| --- | --- |
| `papers` | 经旧版 `convert_openalex_work` 转换后的去重论文列表 |
| `raw_response` | 多页聚合结果，包含简化后的总体 `meta`、`page_meta` 和合并后的 `results` |
| `stats` | 脱敏的请求统计 |

这里的 `raw_response` 为兼容旧调用习惯而保留键名，但它不是服务器某一页响应的逐字副本。
`page_meta` 只保存每页的 `count`、`per_page` 和 `next_cursor`。

最终失败时抛出 `OpenAlexClientV2Error`。异常的 `summary` 和 `stats` 可以显示或写入报告，
但不包含 Key、完整请求 URL或个人绝对路径。

## 3. Cursor 分页与停止规则

OpenAlex 单页 `per_page` 的上限是 100。页码分页适合浅层浏览；cursor 由服务器描述当前
读取位置，更适合连续获取多页结果。本客户端按以下过程工作：

1. 第一页发送 `cursor=*`；
2. 每页请求量为 `min(100, max_results - 当前唯一结果数)`；
3. 读取响应 `meta.next_cursor`，原样用于下一页；
4. 按非空 OpenAlex ID 跨页去重；
5. 达到目标数量、结果耗尽或 cursor 结束时停止。

在没有重复且结果充足时，典型请求量如下：

| `max_results` | 典型页面请求量 |
| ---: | --- |
| 20 | 20 |
| 100 | 100 |
| 120 | 100 + 20 |
| 150 | 100 + 50 |

表中页数不是承诺值。若第二页含有跨页重复 ID，客户端会跳过重复记录，并在存在
`next_cursor` 时继续请求，直到收集到足够的唯一记录或数据确实耗尽。它不会复制记录
凑够 `max_results`。

成功停止原因：

| `stopped_reason` | 含义 |
| --- | --- |
| `max_results_reached` | 已取得 `max_results` 条去重记录 |
| `results_exhausted` | 当前页 `results` 为空，实际结果可能小于目标 |
| `cursor_exhausted` | 当前页非空，但 `next_cursor` 为 `null` 或空字符串 |

失败停止原因：

| `stopped_reason` | 含义 |
| --- | --- |
| `invalid_parameters` | 本地参数校验失败，未发出请求 |
| `missing_api_key` | 未取得可用的 `OPENALEX_API_KEY`，未发出请求 |
| `request_failed` | 网络、HTTP、JSON 或响应结构最终失败 |
| `cursor_stalled` | 服务端返回已经使用过的 cursor；为避免死循环而停止 |
| `response_invalid` | Work 内部字段结构无法安全转换，停止并返回脱敏摘要 |

去重只适用于非空 OpenAlex ID。ID 缺失或为空的记录无法可靠判定是否相同，因此会保留；
这也是当前实现不能保证消除所有内容重复的边界。

## 4. 年份筛选

`from_year` 和 `to_year` 都是包含端点的四位整数年份：

```text
--from-year 2018 --to-year 2025
```

客户端将它们转换为 OpenAlex 日期筛选：

```text
filter=from_publication_date:2018-01-01,to_publication_date:2025-12-31
```

只指定一个端点也有效。不指定时不发送 `filter`，保留按关键词检索的原行为。

以下情况会在本地拒绝，且不会发出 HTTP 请求：

- 年份不是整数或不在 1000—9999；
- `from_year` 晚于 `to_year`；
- `keyword` 为空；
- `max_results` 不是正整数；
- 超时、重试次数或退避参数越界，或时间参数为 NaN、无穷大等非有限数值。

## 5. 有限重试

`max_retries` 表示每一页在首次请求之外允许的额外尝试次数。默认值 3 因而意味着单页
最多发送 4 次 HTTP 请求，而不是总共只发送 3 次。每页成功后，下一页重新计算自己的
重试次数；全程的实际请求数和重试数累计到统计中。

### 5.1 错误分类

| 情况 | 是否重试 | 当前处理 |
| --- | --- | --- |
| `requests.Timeout` | 是 | 有限指数退避后重试 |
| `requests.ConnectionError` | 是 | 有限指数退避后重试 |
| `requests.ChunkedEncodingError` | 是 | 把响应截断视为临时连接失败并有限重试 |
| HTTP 408 | 是 | 有限指数退避后重试 |
| HTTP 429 | 是 | 优先使用可解析的 `Retry-After` 后重试 |
| HTTP 5xx | 是 | 有限指数退避后重试 |
| 2xx 但 JSON 无效 | 是 | 视作可能的临时响应损坏，有限重试 |
| HTTP 400 | 否 | 参数或筛选有误，应先修正请求 |
| HTTP 401、403 | 否 | 认证或访问问题，原样重试通常无效 |
| HTTP 404 | 否 | 接口资源不存在，应检查路径 |
| 其他非 2xx | 否 | 返回脱敏摘要后停止 |
| JSON 结构错误 | 否 | 响应契约不匹配，需要检查客户端或 API 变化 |
| 其他 `RequestException` | 否 | 原因不明确时不盲目重试 |

OpenAlex 的错误说明可能随服务策略变化。当前实现把 429 作为可有限重试的限流信号，
但不会重试 403；如果服务端使用 403 表示额度限制，本次调用会直接失败。这一选择避免
在认证、权限或长期额度问题上重复消耗请求，后续如需细分，应结合响应头和官方文档调整。

### 5.2 等待策略

无 `Retry-After` 时，第 `i` 次重试等待：

```text
min(max_backoff_seconds, backoff_base_seconds × 2^i)
```

`i` 从 0 开始。使用默认参数时，前三次等待为 1、2、4 秒。若响应头提供可解析的非负
数值 `Retry-After`，则优先采用该秒数，但仍受 `max_backoff_seconds` 限制。

当前版本不加入随机抖动，只识别数值秒数形式的 `Retry-After`，不识别 HTTP 日期形式。
这些是已知限制。测试通过注入 `sleep_fn` 避免真实等待，并断言等待序列，不连接网络。

### 5.3 为什么不能无限重试

超时、429 和 5xx 可能是短暂故障，适合等待后再次尝试；400、认证失败和无效筛选不会
因为等待自动修复。有限次数既给临时故障恢复机会，也能保证命令在可预期时间内结束。
本任务只有幂等的 `GET`，重复读取通常不会创建重复的服务器资源，但仍会消耗额度，
所以必须限制次数并记录重试。

## 6. 请求统计

`stats` 至少包含任务要求的九个字段，并增加去重诊断字段：

| 字段 | 含义 |
| --- | --- |
| `requested_max_results` | 调用方要求的最大唯一结果数 |
| `actual_result_count` | 成功时实际返回数；失败时为失败前已聚合数 |
| `page_count` | 已成功解析并通过结构校验的响应页数 |
| `request_count` | HTTP 尝试总数，包含失败尝试和重试 |
| `retry_count` | 实际进入等待并再次尝试的次数 |
| `applied_filters` | 已应用的本地筛选字典，目前可含 `from_year`、`to_year` |
| `elapsed_seconds` | 单调时钟测得的总耗时，含退避等待，保留三位小数 |
| `stopped_reason` | 停止原因，见前文枚举 |
| `status` | `success` 或 `failed` |
| `duplicate_records_skipped` | 聚合时因非空 OpenAlex ID 重复而跳过的记录数 |
| `output_duplicate_id_count` | 最终输出中非空 OpenAlex ID 的重复数量 |

`page_count` 与 `request_count` 不能互换。例如第一页先超时一次、第二次成功，则
`page_count=1`、`request_count=2`、`retry_count=1`。

外部 API 的索引会更新，同一关键词未来可能返回不同结果。统计无法让外部数据静止，
但可以说明当时请求了多少、实际得到多少、是否发生重试，以及为什么停止。这些信息有助于
区分“查询或时间导致的差异”和“程序提前失败”，是实验复现和数据质量检查的一部分。

## 7. API Key 与日志安全

命令行入口只从仓库根目录的 `.env` 或当前环境变量读取 `OPENALEX_API_KEY`：

```dotenv
OPENALEX_API_KEY=在本地填写，不要提交或粘贴到报告
```

Key 相当于访问凭据。若出现在 Git、CI 日志、终端截图或共享报告中，可能导致额度被冒用，
而且从最新文件删除后仍可能残留在提交历史和日志备份中。因此：

- 不把 Key 写入代码、CSV、JSON、文档、测试 fixture 或命令行参数；
- 不打印请求参数、带查询字符串的完整 URL、请求头或底层异常详情；
- CLI 失败只输出固定安全摘要和脱敏统计；
- 意外异常只显示通用错误，不暴露本地路径和库异常内容；
- 提交前确认 `.env` 被 Git 忽略，并精确暂存任务文件，不使用 `git add .`；
- 一旦发现泄露，应立即轮换 Key；只删除文本不能撤销已经泄露的凭据。

## 8. 命令行使用

从仓库根目录运行。20 条默认兼容行为：

```bash
python3 -m app.openalex_fetch_v2 \
  --keyword "machine learning stellar spectra"
```

120 条 cursor 分页 live 验证并写出一行摘要：

```bash
python3 -m app.openalex_fetch_v2 \
  --keyword "machine learning stellar spectra" \
  --max-results 120 \
  --summary-output data/samples/w2/openalex_client/live_pagination_summary.csv
```

带年份筛选：

```bash
python3 -m app.openalex_fetch_v2 \
  --keyword "machine learning stellar spectra" \
  --max-results 120 \
  --from-year 2018 \
  --to-year 2025 \
  --summary-output data/samples/w2/openalex_client/live_pagination_summary.csv
```

可靠性参数：

| 参数 | 默认值 | 含义 |
| --- | ---: | --- |
| `--timeout-seconds` | 20 | 每次 HTTP 请求的超时秒数 |
| `--max-retries` | 3 | 每页首次请求之外的最大重试次数 |
| `--backoff-base-seconds` | 1 | 指数退避基础秒数 |
| `--max-backoff-seconds` | 30 | 单次等待上限秒数 |

成功时，标准输出为不含 Key 的 JSON 摘要。指定 `--summary-output` 后，CSV 使用 UTF-8
with BOM、唯一表头和 ISO 8601 UTC 时间，`applied_filters` 以紧凑 JSON 对象序列化。
写入采用临时文件替换目标文件，降低中途中断留下半份 CSV 的概率。

摘要 CSV 字段为：

```text
query_id,run_id,retrieved_at,keyword,requested_max_results,
actual_result_count,page_count,request_count,retry_count,applied_filters,
elapsed_seconds,stopped_reason,status,duplicate_ids_present
```

`query_id` 由关键词、目标数量和筛选配置计算，便于识别相同查询配置；`run_id` 是该独立
summary-only CLI 每次运行的逻辑标识。它当前不对应一个同名实验目录；正式接入项目运行
目录后，应改为复用 run context 的目录编号。CSV 不保存 Key、请求 URL或本地路径。应优先
使用仓库相对输出路径。

## 9. 自动测试

自动测试必须使用 mock HTTP 响应，不能依赖 OpenAlex、网络、真实 Key 或真实等待。
客户端提供 `request_get`、`sleep_fn` 和 `monotonic_fn` 注入点，用来稳定模拟分页、异常、
退避和耗时。

建议分别运行：

```bash
python3 -m unittest discover -s tests/automated -p "test_openalex_client_v2.py" -v
python3 -m unittest discover -s tests/automated -p "test_*.py" -v
```

覆盖范围至少包括：单页、多页、达到上限、最后一页不足、跨页重复 ID、临时错误后成功、
超过上限失败、非法筛选、统计、输出脱敏、20 条兼容行为，以及原有自动测试回归。

## 10. 数据字段约定

论文转换沿用 `src.openalex_client.convert_openalex_work`：

- `authors` 在 CSV 风格字段中以 `; ` 拼接；
- 缺失标题、作者、摘要、来源或链接时留空，不编造；
- 缺失 `publication_year` 和 `cited_by_count` 时保留 `None`，不以当前年份或 0 代替；
- `openalex_id` 保留 OpenAlex 返回的 URL 形式；
- DOI 当前保留 OpenAlex 返回值，未去掉 `https://doi.org/` 前缀，也未强制转小写。

最后一点是当前实现的明确约定。如果后续把论文记录写入 CSV，必须在文件说明中注明 DOI
未标准化，或先实现并测试统一标准化，不能悄悄改变语义。其他公共字段、编码、缺失值、
相对路径和安全要求以 `docs/project/W2_DATA_CONTRACTS.md` 为准。

## 11. 当前限制与后续接入

- v2 是独立客户端和验证 CLI，尚未接入 `app.main`；
- 请求为串行，不支持并发、缓存、断点续传或失败请求明细日志；
- 没有随机抖动、累计等待时间和状态码次数统计；
- 只支持起止年份筛选，尚无类型或“必须有摘要”筛选；
- 去重依据只有非空 OpenAlex ID，不做标题、DOI 或作者相似度去重；
- CLI 只保存一行运行摘要，不保存完整论文列表或前 20—30 条样例；
- 独立 CLI 的 `run_id` 是逻辑运行标识，尚未对应项目实验目录；
- `query_id` 只覆盖关键词、目标数量和筛选，不包含超时与重试参数；
- 摘要未记录逐页返回量、状态码次数、累计等待、代码版本或产物校验值；
- OpenAlex 结果会随索引更新，无法保证不同日期获得完全相同的记录；
- 本客户端适合有限结果检索，不应用 cursor 抓取整个 OpenAlex；大规模下载应使用官方 snapshot。

组长接入正式入口前，应确认返回值兼容范围、错误类型、统计如何进入现有 run context，
以及是否需要在正式实验中保存代码版本、配置版本和状态码统计。

## 12. 参考资料

- [OpenAlex：List works](https://developers.openalex.org/api-reference/works/list-works)
- [OpenAlex：Page through Results](https://developers.openalex.org/guides/page-through-results)
- [OpenAlex：Filter](https://developers.openalex.org/guides/filtering)
- [OpenAlex：Error Handling](https://developers.openalex.org/api-reference/errors)
- [OpenAlex：Authentication & Pricing](https://developers.openalex.org/api-reference/authentication)
- [OpenAlex：Select Fields](https://developers.openalex.org/guides/selecting-fields)
- [第二周数据接口约定](W2_DATA_CONTRACTS.md)

官方接口、配额和计费策略可能变化；执行新的 live 实验前应重新核对上述官方文档。
