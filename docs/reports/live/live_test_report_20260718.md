# OpenAlex Live 测试报告（2026-07-18）

## 1. 测试概况

- 测试日期：2026-07-18
- 项目版本：v0.2.0
- 实际 Git 分支：`main`
- 检索词 1：`machine learning astronomical spectra`
- 检索词 2：`machine learning stellar spectra`
- 请求数量：每次 10 条
- 数据来源：OpenAlex live 模式
- 测试状态：成功；检测到本地密钥并完成两次小规模请求

本报告不记录、复制或展示任何 API Key。

## 2. 安全检查

- `.gitignore` 已包含 `.env` 和 `.env.*`，同时保留 `.env.example`。
- `git check-ignore -v .env` 确认 `.env` 会被忽略。
- Git 当前未跟踪 `.env`。
- 实际项目根目录中检测到 `.env` 文件，且未被 Git 跟踪。
- `python-dotenv` 已安装并可导入。

## 3. mock 基线

运行命令：

```powershell
python -m app.main --mode mock --keyword "machine learning astronomical spectra" --max-results 20
```

运行结果：

- 返回码：0
- 原始记录：20
- 清洗后记录：20
- 去重后记录：18
- 重复记录：2
- JSON、CSV、SQLite、两张图表和运行摘要均正常生成
- mock 基线已备份到 `outputs/baselines/mock_v0.2.0/`

## 4. OpenAlex 客户端检查

当前 `src/openalex_client.py` 符合本次测试要求：

- Base URL 为 `https://api.openalex.org/works`；
- 检索词通过 `search` 参数传入；
- API Key 从 `.env` 或环境变量读取，并通过 `api_key` 参数传入；
- `per_page` 被限制在 1—100；
- 默认请求超时为 20 秒；
- 缺少 Key、网络错误、HTTP 错误和 JSON 错误均有可读提示；
- 错误信息不会输出可能包含 Key 的完整请求 URL。

## 5. live 测试结果

第一次运行：

```powershell
python -m app.main --mode live --keyword "machine learning astronomical spectra" --max-results 10
```

结果：

- 返回码：0
- OpenAlex 实际返回数量：10
- 清洗后数量：10
- 去重后数量：10
- 重复记录数量：0
- DOI 缺失：0
- 摘要缺失：2
- 来源缺失：0
- 链接缺失：0
- 年份范围：2001—2021
- 引用次数范围：47—1613

第一次结果中只有少数论文直接涉及天文数据或光谱，混入了通用机器学习、材料科学和代谢工程等主题，因此按任务要求补充一次更聚焦的检索。

第二次运行：

```powershell
python -m app.main --mode live --keyword "machine learning stellar spectra" --max-results 10
```

结果：

- 返回码：0
- OpenAlex 实际返回数量：10
- 清洗后数量：10
- 去重后数量：10
- 重复记录数量：0
- DOI 缺失：0
- 摘要缺失：0
- 来源缺失：0
- 链接缺失：0
- 年份范围：2014—2021
- 引用次数范围：6—891
- 两张图表标题均包含 `[OPENALEX LIVE]`

第一次结果保存在 `outputs/live_test_20260718/query_1_astronomical_spectra/`；第二次、更聚焦的最终结果保存在 `outputs/live_test_20260718/` 根目录。

## 6. 字段缺失统计和数值范围

对最终 10 条记录的抽查结果：

- 10 条标题均正常提取；
- 10 条作者字段均已用分号正常拼接；
- 10 条发表年份均可转换为整数，范围为 2014—2021；
- 10 条 DOI 均存在，已转为小写并移除 URL 前缀；
- 10 条原始记录均包含 `abstract_inverted_index`，全部成功还原为非空摘要；
- 10 条 `cited_by_count` 均为数字，范围为 6—891；
- 10 条来源、OpenAlex ID 和落地页链接均存在；
- 10 条记录均写入正确的 `keyword` 和 `retrieved_at`。

没有人工补造任何缺失字段。第一次查询中的两条空摘要对应原始 OpenAlex 记录没有摘要倒排索引，不是还原代码失败。

## 7. 抽查发现的问题

- 第一组搜索词过宽，明显混入多个非天文光谱主题结果。
- 第二组搜索词更聚焦，包含恒星光谱分类、参数估计和合成光谱等直接相关论文，但仍混有空间天气、通用大数据处理和恒星活动论文。
- OpenAlex 的普通 `search` 会寻找相关文本，不保证返回结果都严格属于目标子领域。
- 引用量高的宽泛论文会在 `impact_score` 和引用图中占据明显位置，仍需要人工主题筛选。

## 8. 排序局限

`preliminary_score` 只是一条透明的初步排序规则，不代表真实论文价值评价。本次虽然成功取得了 10 条 live 数据，但如此小的样本不能用于评价整个排序算法，只能验证接口、字段映射和输出闭环。

本次只有每组 10 条数据，不能据此评价整个算法。当前完整词项匹配无法理解短语语义，也无法自动排除“包含关键词但研究主题不属于天文光谱”的论文。

## 9. 下一步建议

1. 后续优先研究更明确的检索词或 OpenAlex 过滤条件，不要立即修改排序权重。
2. 建立少量人工“主题相关/不相关”标记，观察检索结果的实际精度。
3. 保留当前 10 条小样本作为接口与字段映射测试材料，不将其视为算法评测集。
4. 后续运行前继续确认 `.env` 被 Git 忽略，任何报告都不得记录 API Key。

## 10. 结论

本次 mock 基线、OpenAlex 客户端检查和两次 10 条 live 小规模验证均成功。字段映射、摘要还原、CSV、SQLite、图表和运行摘要闭环正常；同时真实结果揭示了普通关键词搜索主题偏宽、引用量可能放大非核心论文排名等局限。
