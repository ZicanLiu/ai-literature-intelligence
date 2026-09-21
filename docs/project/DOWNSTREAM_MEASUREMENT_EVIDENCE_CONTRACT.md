# Downstream Measurement Evidence Contract（证据与测量契约）

> 版本：1.1（2026-09-21，路径迁移兼容与正式复现验证；度量语义不变）
> 状态：工程契约文档。描述 `src/downstream_measurement/` 与两个 CLI 的输入、
> 身份、验证与禁止事项。本文不改变任何冻结研究结果。

## 1. 目的

把 2026-09-04～2026-09-19 散落在 Git 仓库之外的 downstream 研究证据
（RCP screening → MCA → 生成器冻结 → 24 formal outputs → 三 Judge 盲评 →
pre-unblinding closure/authorization → first-look 解盲 → Full Pro 敏感性审计）
建立为**不篡改原始证据、可独立重算、可审计**的分析基础设施。

## 2. 输入与只读边界

- 证据根（evidence root）只读：不 rename / 不 normalize / 不重生成 manifest /
  不删除 / 不移动 / 不覆盖。
- Supplement（Full Pro 144-claim 盲评）来自仓库外 zip 或其解压目录，同样只读。
- 当前逻辑 root 是 `MVP/evidence_pilot_202609`，不能再将整个 MVP 作为 evidence root。
  已授权的本地维护只移动 package 顶层目录并转为 lowercase；内部文件名/相对路径/字节不变。
  CLI 自身仍只读。`PACKAGE_ROLE_TABLE` 以 lowercase 为 canonical，并保留显式 legacy aliases；
  `package_id` 和 formal chain 身份不随目录拼写变化。两份 aliases 同时存在时 fail closed。
- Derived 输出目录必须位于证据根之外（`safe_output_dir` 强制拒绝）。
- 禁止：读取 `.env`/secrets、live API、LLM inference、新增 judgement。

## 3. 身份链与 fail-closed 规则

canonical registry 构建按以下顺序独立重验身份（任何一步失败即终止）：

1. protocol `source_files` 哈希绑定 execution plan；
2. condition mapping（4 conditions，opaque id 唯一）；
3. plan runs lattice = topics × tasks × arms × {1,2,3} 完全因子；
4. formal manifest `status=COMPLETE`、输出数 = plan 数、protocol 哈希一致；
5. formal `source_freeze_binding` 快照绑定 mapping + plan 当前字节；
6. 每个 output：input/generator_output 字节哈希 == formal SHA256 manifest；
   evidence_context SHA256 == condition `context_sha256`；task instruction 逐字一致；
7. 每个 judgement：output_id、`input_sha256` 四元组（context / generator_output /
   task（GPT 用 RQ+task 规范化 JSON 哈希，其余用 task instruction UTF-8 哈希）/
   rubric）、claim 对齐（数量、appearance_index=1..n、slot_id、redundancy
   先行一致性）、事件结构（唯一 error_id、affected 回链互斥、覆盖规则）；
8. Full Pro：仅作为 `SENSITIVITY_EVALUATOR` 载入，绑定哈希逐一核对，不进入
   任何 primary 聚合。

Byte integrity（Phase B）独立重算每个包 SHA256 manifest：
`VERIFIED_BYTES / BYTES_MISMATCH / MISSING_SOURCE_BYTES / SELF_HASHED_UNANCHORED`，
正式依赖链出现 mismatch/missing 时 CLI 以非零码终止。Supplement（无上游
trust anchor 的字节）只记 `SELF_HASHED_UNANCHORED`——当前字节已被读取并
计算 identity hash，但没有任何此前冻结的 expected digest 与之匹配，
**不得计入 VERIFIED_BYTES**。唯一豁免类别是**文档化例外**：
byte mismatch 同时满足（a）下游包自己的 integrity report 已分类、
（b）独立 final verification 已确认、（c）本工具重验文件确为空白模板时，
记为 `BYTES_MISMATCH_DOCUMENTED_EXCEPTION` 并单独计数，绝不静默 PASS。

## 4. 度量语义（独立复现，不 import 原分析代码）

- `U`（useful information slots）= 前 6 个提交单元中
  `atomic AND SUPPORTED AND IN_SCOPE AND NONREDUNDANT` 的数量；
  PARTIALLY_SUPPORTED 计零。
- `E` = substantive error event 记录数（distinct event 基数，无 6 上限）。
- 差值方向恒为 `MCA − BM25`；cell 均值 = 3 repetition 均值；
  macro = 4 个 Topic×Task 对比等权均值；全部用精确有理数（Fraction）计算。
- 与冻结 first-look 的比较：冻结表以十进制 double 序列化，因此等值判定在
  冻结工件自身精度上进行（|diff| ≤ 1e-12），不硬编码任何预期数值。
- 正式复现加 `--formal-verification`：恰好 3 Judge × (8 endpoint fields + `n_cells`)
  + exact Judge roster = 28 项，必须完整且全 MATCH。缺少冻结 CSV、字段/roster 不完整、
  重复字段/Judge 或任一 mismatch 都返回非零，并在 staging 留下 `_PARTIAL_FAILED.txt`，
  不发布成功 bundle。默认 diagnostic 模式允许继续，comparison JSON 和 manifest 的
  `analysis_config` 明确记录 mode/status；它不能被当作正式复现通过。
- CSV 必须语法完整、每行与 header 等宽、header 无空名/重复名、必需字段非空，数值必须有限。
  多余单元格、短行、未闭合引号和 NaN/Infinity 均记 `INCOMPLETE`。冻结表中的辅助列
  `n_expected_per_arm`、`n_observed_per_arm`、`E_status` 不增加这 28 项；完整 lattice 在 canonical
  重建时独立验证，整个 CSV 的原始字节仍须匹配冻结 hash。
- 每次 audit 重新核对实际读取的 frozen CSV hash、当前 package manifest 和 registry 保存的
  manifest hash。缺锚为 `UNVERIFIED_SOURCE`，字节或 manifest 漂移为 `SOURCE_MISMATCH`，
  不可读/非法编码为 `INVALID_SOURCE`；均不能正式发布。`source_verification` 保留实际及预期
  digest，`value_comparison_status` 单独记录数值/结构比较结果，避免将数值 MATCH 当作字节验证。
  Diagnostic 模式可继续处理可读的未验证来源，并在 manifest 中保存 source verification 状态。

## 5. 角色与标签纪律

- GPT / DeepSeek / GLM = `PRIMARY_JUDGE`（frozen three-judge first-look）。
- Full Pro = `SENSITIVITY_EVALUATOR`（post-hoc、无冻结 schema、永不进入
  primary 聚合、永不被表述为第四 Judge 或 gold）。
- decomposition / sensitivity / influence / counterfactual / error audit 产物
  一律标 `DIAGNOSTIC`；唯一 `primary` 标签是 first-look 复现本身。
- κ 仅在两个 rater 边缘分布均非退化时计算；否则报告 raw agreement、
  列联表与 prevalence，不输出误导性 κ。
- λ 网格固定 {0, ¼, ½, ¾, 1}，不搜索"最优 λ"；变体是 metric sensitivity，
  不是新 endpoint，不构成对 first-look 的重评分。

## 6. 持久化纪律

- 所有持久化产物不得包含用户绝对路径（构建后 `assert_no_absolute_paths`）；
  source locator 形如 `package_id:relative/path#/json/pointer`。
- 原子写（temp + replace）；确定性排序；manifest 记录 tool 版本、Git
  revision/clean、Python/平台、源包身份、canonical 表哈希、输出哈希、
  primary/diagnostic 标签、missing bytes 与 limitation flags。

## 7. 测试

- `tests/automated/test_downstream_measurement.py`：合成 mini evidence root
  （temp 目录、真实目录布局），覆盖 lattice/唯一性/hash drift fail-closed/
  duplicate id/missing evaluator/Full-Pro 角色隔离/绝对路径泄漏/输出目录
  防护/聚合精确性/κ 退化/λ 公式/分解恒等式/事件计数。
- `tests/automated/test_downstream_measurement_evidence.py`：真实证据回归
  （24/144/72/432 身份格 + 冻结 first-look 复现），由环境变量
  `SRTP_DOWNSTREAM_EVIDENCE_ROOT`（与可选 `SRTP_DOWNSTREAM_SUPPLEMENT_ZIP`）
  门控，CI 无证据时静默 skip。
- `test_downstream_measurement_closeout.py`：真实 synthetic 文件迁移后的 identity/bytes 等价、
  legacy restore、alias 冲突、frozen legacy DAG anchor，以及 formal MATCH/failure/partial
  publication 和 diagnostic 行为。

## 8. 当前本地执行入口

在正式 Git 仓库运行（这里只使用逻辑相对位置，不要求特定个人绝对路径）：

```powershell
$pilotEvidence = '..\evidence_pilot_202609'
$pilotSupplement = Join-Path $pilotEvidence 'srtp_meeting_latest_supplement_20260919\SRTP_MEETING_LATEST_SUPPLEMENT_20260919.zip'
python -m app.build_downstream_evidence_registry --evidence-root $pilotEvidence `
  --supplement-zip $pilotSupplement --output-dir '..\derived_analysis\registry_new_run'
python -m app.run_downstream_measurement_audit --evidence-root $pilotEvidence `
  --supplement-zip $pilotSupplement --registry-dir '..\derived_analysis\registry_new_run' `
  --output-dir '..\derived_analysis\audit_new_run' --formal-verification
```

每次使用新的 derived output 目录；已有目录会被拒绝，避免混入旧产物。恢复旧 uppercase
快照后，只需指定恢复位置与 supplement，科学身份无需重新生成。
同名 `*.staging` 目录也会被拒绝，不删除之前的失败现场；重试应换用新输出名称。
