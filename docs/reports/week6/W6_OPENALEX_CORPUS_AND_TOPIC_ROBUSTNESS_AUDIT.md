# W6 OpenAlex 多查询语料扩展与 Topic Robustness Audit

## 1. 状态与研究边界

本报告记录 PR #71 在 Issue #64 Topic freeze **之后**开展的 Leader research expansion。
它不是 Issue #64 Topic discovery/freeze 的重做，也不属于正式 retrieval experiment、ranking
evaluation 或 label-aware method selection。

截至 `2026-08-26T15:50:21+08:00`：

- 原 9 个 frozen Topics 保持不变；
- 原 topic-level Dev 5 / Hidden 4 split 保持不变且 `reveal_state=sealed`；
- 已先冻结独立的 54-query audit config；
- live acquisition 尚未执行，因为当前 Codex 进程、Windows User 与 Machine 环境均未暴露
  `OPENALEX_API_KEY`；遵守仓库规则，没有读取 `.env`、没有从聊天明文重建 key，也没有用匿名
  请求替代正式 evidence；
- 用户提供的 OpenAlex Usage 页面截图显示 Free Plan 当时 `$1.000` daily budget remaining
  (`100%`)；这只作为预算可用性背景，不是 API 查询结果或 scientific evidence；
- `potential_topic_amendments` 为空，Topic Set 与 split 没有修改。

## 2. 冻结 Acquisition Design

独立配置：
[`openalex_topic_query_audit_v1.json`](../../../configs/w6/openalex_topic_query_audit_v1.json)

- artifact ID：`w6_openalex_topic_query_audit_v1`；
- config identity：
  `w6-openalex-query-audit-config:sha256:9f312e242f3b9bed2d65da651a85620d38ece58b2ffa9e8fe7425a66f11926a4`；
- Topic Set hash：
  `6e2f6e6b8fea56cef6e245dcf37fa97a46ba5efc6703fb47e9863840e3a06ca4`；
- split identity：
  `w6-topic-split:sha256:8391d14987a15982b5afa2ae3760f029824909353f51056360d79fe9b85202bc`；
- split file hash：
  `bb57448288f122406d195cbec09dde80f76f78a7a0a1d0ef9bc85c052aea69ad`；
- freeze time：`2026-08-26T15:50:21+08:00`；
- 9 Topics × 6 query variants = 54 个固定 query；
- OpenAlex Works `search`，年份 `2000–2026`；
- 每 query 最多 80 条，因此单 Topic 理论上限为 480，目标约 200–400 unique works，
  soft cap 为 500；
- query 文本、variant ID、coverage facets 与 rationale 全部在 live acquisition 前冻结；
- 禁止看结果后改 query，禁止读取 relevance labels、judgements、ranking metrics 或 annotations。

这 54 个 variants 独立于原 Topic contract 中的 `acquisition_query_variants`。原
[`topics.json`](../../../data/research/w6/v0.2-alpha/topics.json) 没有被修改或重冻。

### 2.1 Query coverage roster

| Frozen Topic | Audit query IDs | 主要设计覆盖 |
|---|---|---|
| `w6_topic_galaxy_activity_spectra` | `galaxy_activity_aq01..06` | integrated spectra、activity classes、emission lines、AGN/LINER、ML classification |
| `w6_topic_supernova_spectral_typing` | `supernova_typing_aq01..06` | transient spectra、type、low signal、phase variation、ML classification |
| `w6_topic_exoplanet_atmospheric_retrieval` | `exoplanet_retrieval_aq01..06` | transmission/emission、retrieval、abundance、learned inverse model |
| `w6_topic_stellar_radial_velocity` | `stellar_rv_aq01..06` | spectra、RV、high resolution、time series、spectral variability |
| `w6_topic_spectral_anomaly_detection` | `spectral_anomaly_aq01..06` | spectra、survey、novelty、unsupervised、rare-object discovery |
| `w6_topic_stellar_spectral_denoising` | `stellar_denoising_aq01..06` | low S/N、learned denoising、artifact restoration、line preservation |
| `w6_topic_stellar_spectral_emulation` | `stellar_emulation_aq01..06` | synthetic spectra、parameters、forward surrogate、interpolation、synthesis |
| `w6_topic_solar_spectropolarimetric_inversion` | `solar_inversion_aq01..06` | solar spectra、Stokes、spectropolarimetry、magnetic field、inversion |
| `w6_topic_21cm_foreground_removal` | `21cm_foreground_aq01..06` | 21-cm、foreground removal、component separation、EoR、intensity mapping |

## 3. Acquisition 与 artifact contract

实现入口：

```powershell
python -m app.run_w6_openalex_audit validate-config
python -m app.run_w6_openalex_audit acquire --output-dir data/research/w6/v0.2-alpha/openalex-audit-v1
python -m app.run_w6_openalex_audit validate-package --package-dir data/research/w6/v0.2-alpha/openalex-audit-v1
```

live command 只读取 process / Windows User / Windows Machine 环境中明确命名的
`OPENALEX_API_KEY`，不枚举其他变量、不读取 `.env`。manifest 只记录来源类型，不记录值。它复用
`src.openalex_client_v2.fetch_openalex_papers_v2` 的 cursor pagination、有限 retry/backoff、
年份 filter 与安全统计；key 不进入参数日志、源码、config、fixture、report 或输出 artifact。

完整 package 原子写入全新目录，拒绝覆盖现有 evidence，且通过 resolved path guard 防止输出目录
与 frozen Topic/config/split 输入发生父子或同路径重合。计划输出：

- `works.jsonl`：compact public work metadata，全局仅按 normalized OpenAlex Work ID exact dedup；
- `query_hits.jsonl`：每个 query-work hit、topic、variant 与 source rank，全部保留；
- `query_runs.json`：固定 query、API hit count、retrieved count、请求/分页/retry 统计；
- `topic_audit.json` / `topic_audit.md`：label-free descriptive audit；
- `manifest.json`：config/Topic/split 绑定、file hashes 与 acquisition identity。

不会做 DOI/title canonicalization、Multi-Retriever、enrichment、QA、fusion、synthesis 或新增 ranking
算法。相同标题但不同 OpenAlex Work ID 的记录必须分别保留。

## 4. 预注册 Audit 指标与解释边界

每个 query 记录 API hit count、retrieved count、对 Topic union 的 unique contribution，并计算 query
pair 的 intersection、union 与 Jaccard。每个 Topic 记录 union、multi-query support distribution、逐年
分布、title/abstract/DOI/authors/year/source/landing-page completeness、query-facet coverage 与代表性公开
论文 identity。跨 Topic 记录 exact Work-ID intersection 与 Jaccard。

代表论文只按 `query support → cited_by_count → year → OpenAlex ID` 的预注册描述顺序选择，用于人工
理解检索边界，不是 relevance judgement。hit count、overlap、metadata completeness 与 query-facet
coverage 都不等于 scientific relevance 或 ranking quality。

若后续 evidence 显示 fundamental scientific problem，只在本报告和 artifact 中新增
`potential_topic_amendment` 记录；不得直接修改 frozen Topic Set 或 Dev/Hidden split。

## 5. Offline verification（采集前）

新增纯离线 fixture 和 13 项定向测试，覆盖：

- 9 Topic / 54 query / config identity / Topic 与 split hashes；
- label-free、non-adaptive 和 exact-ID-only policy drift；
- 全 query-hit provenance、同标题不同 ID 不合并、Topic 内/跨 Topic overlap；
- API count、year、metadata completeness、representative identity 与 risk signal；
- API key、个人绝对路径不落盘，且 live path 不导入 dotenv 或 label-aware W6 模块；
- process → Windows User → Windows Machine 的限定 key-source 解析，不枚举其他环境 secret；
- missing key、frozen input/output path overlap、file hash tampering；
- 相同 fixture 的 acquisition identity 可复现。

执行结果：

```text
python -m unittest tests.automated.test_w6_openalex_audit -v
Ran 13 tests ... OK
```

OpenAlex v2 的多页 cursor、429/5xx/timeout retry/backoff、无效响应和 safe-error 行为继续由既有
`tests/automated/test_openalex_client_v2.py` 离线测试覆盖。

采集前全量回归为 548 tests 全部通过（含 2 个既有 Windows symlink 条件性 skip）；Basic Gate
扫描 370 files，0 error / 0 warning；Full Gate 扫描 370 files，0 error / 3 个既有历史 warning，
均 PASSED。live artifact 进入仓库后必须再次执行完整验证，不能直接沿用本次采集前结果。

## 6. Live evidence（待执行）

本节必须在环境变量实际可见并完成 bounded live acquisition 后，以真实 package identity、逐 Topic
数量、query overlap、年份、metadata、代表论文、cross-topic overlap 与明确风险更新。当前不得把
fixture 数字、预算截图或失败/未执行请求表述为 live scientific evidence。
