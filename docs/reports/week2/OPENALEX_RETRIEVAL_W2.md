# 第二周 OpenAlex v2 分页检索报告

- 方向：OpenAlex v2 分页、筛选、有限重试与请求统计
- 报告日期：2026-08-01
- 原任务截止：2026-07-31 18:00（报告日期已晚于原截止，PR 创建时间须按实际记录）
- 实现入口：`src/openalex_client_v2.py`
- 独立验证入口：`app/openalex_fetch_v2.py`
- 正式入口接入状态：未接入，等待组长决定
- 自动测试结果：**通过：v2 定向 21/21，全量 28/28**
- live 验证结果：**成功：目标 120 条，实际 120 条，2 页，无重复 ID**
- Pull Request：**[PR #30](https://github.com/ZicanLiu/ai-literature-intelligence/pull/30)（Draft，未合并）**

本文把代码设计与执行结果分开记录。测试数量、live 统计和执行时间均来自 2026-08-01
实际运行；原截止时间已经过去，本报告不倒填日期。

## 1. 任务目标与范围

旧版 OpenAlex live 客户端把 `max_results` 限制在单页 100 条以内，不能稳定验证 120、
150 条等多页场景。本任务新增独立 v2 客户端，在不修改 `app/main.py`、
`src/processor.py` 和旧版正式入口的前提下完成：

- cursor 多页获取，并在达到 `max_results` 后停止；
- 按非空 OpenAlex ID 跨页去重，不复制记录凑数；
- 网络超时、临时服务器错误、限流和无效 JSON 的有限重试；
- 参数或认证类错误直接失败，不盲目重试；
- 起始年份和结束年份筛选；
- 完整、脱敏的请求统计；
- 不联网的 mock 自动测试；
- 一次 120 条 live 查询及一行式 CSV 摘要。

本任务没有修改共享正式入口。v2 是否进入正式流程、如何与现有 run context 和存储模块
衔接，留给组长在集成阶段决定。

## 2. 交付内容

| 文件或目录 | 用途 | 当前记录 |
| --- | --- | --- |
| `src/openalex_client_v2.py` | 分页、筛选、重试、去重和统计 | 已实现并通过定向/回归测试 |
| `app/openalex_fetch_v2.py` | 独立 live CLI 和摘要 CSV | 已完成 live 验证 |
| `tests/automated/test_openalex_client_v2.py` | v2 不联网自动测试 | 21 项通过 |
| `tests/fixtures/openalex/` | mock OpenAlex 响应 | 已核对，不含凭据或个人路径 |
| `data/samples/w2/openalex_client/live_pagination_summary.csv` | 整理后的 live 摘要 | 已生成并按数据契约核对 |
| `docs/project/OPENALEX_RETRIEVAL_GUIDE.md` | 使用与可靠性说明 | 已编写 |
| `docs/reports/week2/OPENALEX_RETRIEVAL_W2.md` | 本报告 | 已回填实测结果 |

## 3. 实现方案

### 3.1 REST 请求与响应校验

客户端对 `https://api.openalex.org/works` 发送只读 `GET` 请求。关键词、筛选、分页、字段
选择和认证均作为查询参数发送；每次请求显式设置超时。处理顺序为：

1. 本地校验关键词、数量、年份、超时和退避参数；
2. 判断 HTTP 状态码；
3. 解析 JSON；
4. 校验顶层对象、`results` 列表、`meta` 对象和 Work 记录类型；
5. 合并本页结果并更新统计。

这样可以区分“请求失败”“响应不是 JSON”和“JSON 结构与契约不符”，不会仅凭 2xx 就
把响应当成可用数据。

### 3.2 Cursor 分页和去重

第一次请求使用 `cursor=*`，之后原样传递服务端 `meta.next_cursor`。单页大小为：

```text
min(100, max_results - 当前已收集的唯一结果数)
```

没有重复且结果充足时，20 和 100 条各需一页，120 条通常为 100+20，150 条通常为
100+50。若跨页重复被跳过，客户端会在存在下一 cursor 时继续请求，因此实际页数可能
增加。遇到空结果、空 cursor、达到上限或重复 cursor 时停止，不会复制记录补足数量。

去重集合只记录非空 OpenAlex ID。空 ID 没有可靠的稳定标识，当前选择保留而不是猜测。
统计另外记录跳过的重复记录数，并在输出后再次计算非空 ID 的重复数量。

### 3.3 年份筛选

客户端实现两个可选筛选条件：

- `from_year` → `from_publication_date:<年份>-01-01`；
- `to_year` → `to_publication_date:<年份>-12-31`。

二者均为包含端点。未指定时不发送 `filter`。年份越界或起始年份晚于结束年份会在本地
失败，不产生 HTTP 请求。

### 3.4 有限重试和指数退避

每页 `max_retries=3` 表示首次请求之外最多重试 3 次，即单页最多 4 次 HTTP 尝试。
适合重试的情况为：

- 网络超时、临时连接失败和响应分块中断；
- HTTP 408、429 和 5xx；
- 2xx 响应中的无效 JSON。

HTTP 400、401、403、404、其他非 2xx、结构错误和未分类的请求异常不盲目重试。
默认等待序列为 1、2、4 秒，且单次不超过 30 秒。若响应含可解析的数值
`Retry-After`，优先使用该值，但同样受 30 秒上限约束。

该策略符合“暂时性错误给恢复机会、永久性错误先修正原因”的原则。所有次数都有上限，
避免网络任务无限挂起或反复消耗 API 额度。

### 3.5 统计与停止原因

必需统计全部由一次调用产生：

| 字段 | 记录内容 |
| --- | --- |
| `requested_max_results` | 请求目标数量 |
| `actual_result_count` | 实际聚合并返回的结果数 |
| `page_count` | 解析并校验成功的页面数 |
| `request_count` | 包含失败尝试和重试在内的 HTTP 请求数 |
| `retry_count` | 实际执行的重试数 |
| `applied_filters` | 实际使用的起止年份字典 |
| `elapsed_seconds` | 包括等待在内的单调时钟耗时，保留三位小数 |
| `stopped_reason` | 达到上限、耗尽、cursor 结束或错误原因 |
| `status` | `success` 或 `failed` |

扩展字段 `duplicate_records_skipped` 和 `output_duplicate_id_count` 用于解释跨页去重。
请求统计不能保证未来再次取得完全相同的 OpenAlex 数据，但能重建请求规模、分页过程、
重试情况和终止原因，从而判断结果差异来自外部索引变化还是客户端提前停止。

### 3.6 安全错误摘要

Key 只从本地 `.env` 或环境变量取得，并由调用方传入客户端。CLI 不输出请求参数、完整
URL或底层异常对象；已知失败只输出固定摘要和统计，未预期异常输出通用提示。摘要 CSV
不含 Key、Token、`.env` 内容或个人绝对路径。

API Key 类似密码。日志、Git 历史和 CI 产物通常会长期保存；一旦记录完整 Key，即使从
最新文件删除，也不能视为已经撤销泄露。因此本任务不能以“方便调试”为由输出完整请求
URL，发现泄露后必须轮换 Key。

## 4. 自动测试设计

自动测试通过注入 `request_get`、`sleep_fn` 和 `monotonic_fn` 模拟 HTTP、等待和耗时，
不得访问真实 OpenAlex，也不得依赖本地 Key。

| 验收场景 | 应验证的事实 | 执行结果 |
| --- | --- | --- |
| 单页成功 | 一页结果被转换，统计为一页一次请求 | 通过 |
| 多页拼接 | 使用 `next_cursor` 继续并合并结果 | 通过；同时断言第二页 cursor 传递 |
| 达到 `max_results` | 精确停止，不多返回记录 | 通过 |
| 最后一页不足 | 如实返回实际数量，不复制补齐 | 通过 |
| 跨页重复 ID | 重复被跳过，输出非空 ID 唯一 | 通过 |
| 临时错误后成功 | 重试、等待和请求计数正确 | 通过；覆盖超时、503、429 |
| 超过重试上限 | 有限结束并给出脱敏失败摘要 | 通过 |
| 非法筛选 | 本地失败且请求数为 0 | 通过 |
| 请求统计 | 九个必需字段和值一致 | 通过 |
| Key 脱敏 | 标准输出、异常和统计均不包含测试 Key | 通过 |
| 20 条兼容 | 默认或显式 20 条仍返回旧键及旧论文输出字段 | 通过 |
| 原有回归 | 现有自动测试继续通过 | 通过；原有 7 项无回归 |

### 4.1 实际执行命令与结果

v2 定向测试：

```bash
python3 -m unittest discover -s tests/automated -p "test_openalex_client_v2.py" -v
```

- 执行时间：**2026-08-01 00:41+08:00（Asia/Shanghai）**
- 测试总数：**21**
- 通过/失败/错误/跳过：**21/0/0/0**
- 命令退出码：**0**

完整自动测试：

```bash
python3 -m unittest discover -s tests/automated -p "test_*.py" -v
```

- 执行时间：**2026-08-01 00:41+08:00（Asia/Shanghai）**
- 测试总数：**28**
- 通过/失败/错误/跳过：**28/0/0/0**
- 命令退出码：**0**

若测试失败，不得把本节改写为“全部通过”；应记录失败用例、原因、修复和复测结果。

## 5. Live 验证

### 5.1 实际命令

确认仓库根目录的 `.env` 已在本地配置且被 Git 忽略后，执行：

```bash
python3 -m app.openalex_fetch_v2 \
  --keyword "machine learning stellar spectra" \
  --max-results 120 \
  --from-year 2000 \
  --summary-output data/samples/w2/openalex_client/live_pagination_summary.csv
```

命令中不能直接写 Key，终端输出和截图也不能出现 Key。若运行失败，应保留安全错误摘要，
修正原因后重新执行；不能把 mock 结果当作 live 结果。

### 5.2 实际结果

| 项目 | 实际值 |
| --- | --- |
| 执行时间与时区 | **2026-08-01 00:40:03+08:00（CSV 记录为 UTC）** |
| `run_id` | **`openalex-v2-live-20260731T164003Z-c614ab58`** |
| `query_id` | **`openalex-v2-fda348a72056`** |
| `keyword` | **`machine learning stellar spectra`** |
| `requested_max_results` | **120** |
| `actual_result_count` | **120** |
| `page_count` | **2** |
| `request_count` | **2** |
| `retry_count` | **0** |
| `applied_filters` | **`{"from_year":2000}`** |
| `elapsed_seconds` | **4.714** |
| `stopped_reason` | **`max_results_reached`** |
| `status` | **`success`** |
| `duplicate_ids_present` | **`false`** |
| 命令退出码 | **0** |

若实际数量少于 120，应保留真实数值并根据 `stopped_reason` 解释，不能复制记录补到 120。
若 `duplicate_ids_present=true`，则尚未满足验收标准，应先定位去重问题，不能把该次摘要
作为成功证据。

### 5.3 CSV 产物核对

目标文件：`data/samples/w2/openalex_client/live_pagination_summary.csv`

| 检查项 | 结果 |
| --- | --- |
| 文件只含唯一非空表头和一行整理后的 live 摘要 | 通过 |
| 编码为 UTF-8 with BOM，使用 LF，JSON 字段符合约定 | 通过 |
| `keyword`、数量、页数、请求数、重试数和筛选与终端统计一致 | 通过 |
| `retrieved_at` 为 ISO 8601 UTC 时间 | 通过：`2026-07-31T16:40:03+00:00` |
| 不含 API Key、Token、`.env` 内容或个人绝对路径 | 通过 |
| 统计可以从本次运行输出交叉核对 | 通过 |

该 CSV 只记录一次运行摘要，不包含完整论文结果。它复用了
`docs/project/W2_DATA_CONTRACTS.md` 的 `query_id`、`keyword`、编码、时间、相对路径和安全
约定，`applied_filters` 使用紧凑 JSON 对象序列化。当前 summary-only CLI 的 `run_id` 是
唯一逻辑运行标识，但没有创建对应的同名实验目录；正式接入时应复用项目 run context，
使它与数据契约中的实验目录编号一致。

## 6. 安全与边界检查

提交前需要执行并回填：

```bash
git status --short
git check-ignore -v .env
git diff --check
```

| 检查项 | 结果 |
| --- | --- |
| `.env` 被 Git 忽略且未暂存 | **通过：`git check-ignore -v .env` 命中忽略规则** |
| 交付文件中没有实际 Key、Token 或个人绝对路径 | **通过：按本地 Key 精确比对为 0 次，路径扫描无命中** |
| 未修改 `app/main.py`、`src/processor.py`、`README.md`、`docs/CURRENT_STATUS.md`、`.gitignore` | **通过：限定路径状态为空** |
| 只暂存本任务边界内的文件 | **通过：精确暂存 10 个交付文件，`git diff --cached --name-status` 无越界路径** |
| 无尾随空格或补丁格式错误 | **通过：逐文件检查及 `git diff --cached --check` 均无报错** |

若安全扫描意外发现真实凭据，不要把命中内容复制到 Issue、PR 或本报告；应先轮换凭据，
再清理工作区和必要的历史记录。

## 7. 验收状态

| 验收标准 | 代码依据 | 最终状态 |
| --- | --- | --- |
| 支持获取超过 100 条 | cursor 循环和每页最多 100 | 通过：120/150 离线测试，120 条 live |
| 分页后 OpenAlex ID 不重复 | `seen_openalex_ids` 跨页集合 | 通过：跨页重复 fixture 与 live 均为 0 个输出重复 ID |
| 有限重试正确 | 每页重试上限、指数退避和错误分类 | 通过：离线覆盖超时、429、5xx、无效 JSON 与 400 |
| 至少一个筛选条件 | 起始年份和结束年份 | 通过：单测覆盖起止年份，live 使用 `from_year=2000` |
| 请求统计完整 | 九个必需字段和两个去重扩展字段 | 通过：定向断言并与 live CSV 交叉核对 |
| 自动测试不联网 | HTTP、sleep 和时钟注入 | 通过：v2 的 21 项测试均使用替身或 patch |
| live 验证实际执行 | 独立 CLI 和摘要输出 | 通过：2026-08-01 实际请求成功 |
| 未暴露 API Key | 固定摘要、隐藏底层异常、不记录请求 URL | 通过：实际 Key 精确扫描为 0 次命中 |
| 所有测试通过 | 定向测试和完整回归命令 | 通过：21/21、28/28，退出码均为 0 |
| 创建 PR 且不自行合并 | 精确暂存并创建草稿 PR | 通过：PR #30 为 Draft，未执行合并 |

P1 缓存、更多筛选、失败请求明细和 250 条 live 验证不在本次 P0 结果中。在 P0 全部验证
并创建 PR 前，不扩展这些功能。

## 8. 知识说明

### REST 与 HTTP 状态码

REST 客户端通过 HTTP 方法、资源 URL和参数表达请求，服务器用状态码、响应头和 JSON
响应体说明结果。2xx 表示 HTTP 层成功，仍需校验 JSON；400 通常应修正参数，401/403
应检查认证或访问条件，408/429 和 5xx 才可能适合有限重试。

### 网络超时、限流和指数退避

没有超时的网络调用可能无限等待。限流用于保护服务和额度，常见信号为 429，并可能携带
`Retry-After`。指数退避让连续失败后的等待逐步增加，减少服务器恢复期间的额外压力；
它只缓解暂时性故障，不能修复非法参数或无效 Key。

### 为什么记录请求统计

OpenAlex 索引会更新，网络状态也会变化。只看最终 CSV 无法判断少了记录是结果确实耗尽、
分页提前结束，还是请求失败。目标数、实际数、页面数、请求数、重试数、筛选、耗时、停止
原因和状态共同构成一次检索的过程证据，便于复查和解释不同运行之间的差异。

## 9. 已知限制

- 只按非空 OpenAlex ID 去重，不处理 DOI、标题或作者相似重复；
- 未加入随机抖动，只解析数值秒数形式的 `Retry-After`；
- 403 不重试；如果 OpenAlex 用 403 表示额度限制，本次调用会直接失败；
- 没有缓存、断点续传、并发、状态码计数或累计等待时间；
- 只提供年份筛选，没有类型和“要求摘要”筛选；
- CLI 只保存摘要 CSV，不保存论文样例或完整结果；
- 独立 CLI 的 `run_id` 尚未对应项目实验目录，正式接入时需复用 run context；
- 返回值的 `raw_response` 是多页聚合结构，不是服务器原始单页响应；
- 摘要未记录逐页返回量、状态码次数、累计等待、代码版本或产物校验值；
- DOI 沿用旧转换逻辑，未标准化为去 URL 前缀的小写形式；
- 外部索引和 API 策略会变化，本次统计支持解释过程，但不能保证未来结果逐条相同。

## 10. 参考资料

- [OpenAlex：List works](https://developers.openalex.org/api-reference/works/list-works)
- [OpenAlex：Page through Results](https://developers.openalex.org/guides/page-through-results)
- [OpenAlex：Filter](https://developers.openalex.org/guides/filtering)
- [OpenAlex：Error Handling](https://developers.openalex.org/api-reference/errors)
- [OpenAlex：Authentication & Pricing](https://developers.openalex.org/api-reference/authentication)
- [OpenAlex v2 检索与可靠性指南](../../project/OPENALEX_RETRIEVAL_GUIDE.md)
- [第二周数据接口约定](../../project/W2_DATA_CONTRACTS.md)
