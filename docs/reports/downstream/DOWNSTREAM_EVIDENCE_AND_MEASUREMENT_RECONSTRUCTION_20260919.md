# Downstream Evidence and Measurement Reconstruction — 2026-09-19

> 工具：`zcode-downstream-measurement/1.0.0`（worktree 分支
> `research/zcode-downstream-measurement-workbench-20260919`，基线 `34bbd9c`）。
> Derived 输出：证据根同级的 `MVP_zcode_derived/downstream_measurement_20260919`
> 目录（36 个工件已入 manifest）。原始证据只读，未做任何修改。
> 本文严格区分 FACT（机器复算）/ DIAGNOSTIC（事后测量分析）/
> INTERPRETATION（科学解释）/ FUTURE（下一实验建议）。

## 1. FACT — 证据链字节核验

- 29 个外部目录 + supplement 全量 inventory；25 个带 SHA256 manifest 的包
  **独立重算得 9,307 个 VERIFIED_BYTES**（对既有 manifest 锚的字节级验证）、
  **12 个 SELF_HASHED_UNANCHORED**（supplement 成员：本轮读取并计算了
  identity hash，但不存在此前冻结的 expected digest，不计入 verified）、
  0 缺失；1 mismatch = `MCA_V1_HUMAN_AUDIT_AGGREGATION/adjudication/reviewer_R3/submission_template.csv`
  ——下游 `MCA_V1_FINAL/checks` 已分类
  `PREEXISTING_UNUSED_BLANK_TEMPLATE_LINE_ENDINGS_ONLY` 并独立核验；本次重验
  该文件确为空白模板（全部裁决字段为空），登记为文档化例外，未静默 PASS。
- 证据 DAG：21 条边，12 VERIFIED_EDGE / 9 QUALIFIED / 0 UNVERIFIED。
  VERIFIED 要求具体 binding 字段/逐 case 条目/snapshot 键匹配**特定上游文件**
  的已验证字节哈希（或显式 identity 字段锚定上游包 manifest）；DeepSeek/GLM
  的 judge 边因 source_binding schema 不同记 QUALIFIED——其逐 case 身份由
  canonical loader 的 judgement input_sha256 四元组核验补足。
- Supplement（Full Pro 144-claim 盲评）原 zip 在审计期间被解压删除；
  本轮从解压目录载入，12 个期望成员以 SELF_HASHED_UNANCHORED 入册
  （当前 12/12 在场，期望 roster 缺失即显式报告）。**这是单副本风险的现实例证。**
- Full Pro 按期望 roster 锁定：24/24 output、output_id/evaluation_id 唯一、
  无 missing/unexpected；逐 claim 文本对齐与事件结构验证与 primary 同规。
- Canonical registry：**24 outputs（2×2×2×3 lattice 完整）、144 claims、
  72 primary evaluations、432 primary claim-judge units、144 Full Pro
  sensitivity units**；全部 72 个 judgement 通过独立结构验证
  （input_sha256 四元组、claim 对齐、事件互链重算一致）。

## 2. FACT — First-look 独立复现

不引用原分析代码，从 raw judgement 重新实现 U/E/聚合（精确有理数）：

| evaluator | 角色 | ΔU | ΔE | U 方向 | E 方向 |
| --- | --- | ---: | ---: | --- | --- |
| GPT | PRIMARY_JUDGE | +7/12 ≈ +0.5833 | −7/12 | MCA_HIGHER | MCA_LOWER |
| DeepSeek | PRIMARY_JUDGE | +1/12 ≈ +0.0833 | −1/12 | MCA_HIGHER | MCA_LOWER |
| GLM | PRIMARY_JUDGE | 0 | 0 | EQUAL | EQUAL |
| Full Pro | SENSITIVITY_EVALUATOR | −7/12 ≈ −0.5833 | −8/12 ≈ −0.6667 | MCA_LOWER | MCA_LOWER |

与冻结表 `JUDGE_PRIMARY_MACRO_RESULTS.csv` 的 **28 项字段对比全部一致**（3 judge × 8
语义字段 + 3 × n_cells 结构字段 + judge roster 锁定；数值按冻结工件 double
精度 |diff|≤1e-12；比较不硬编码预期值）。
Full Pro 的 ΔU 与 ΔU_without_atomicity(+0.6667) 亦与 9/19 诊断材料 S16 一致。

## 3. DIAGNOSTIC — 测量构造分解

- 分解恒等式 `U_original + B + E_f = 6`（B = S∧C∧N 通过但 atomic 失败；
  E_f = 失败 S∧C∧N）对全部 96 个 output-evaluator 成立——这是**首六单元
  划分的 DATA-SPECIFIC IDENTITY（分区恒等式），不是度量定义的一般定理**。
- 首六失败成分（按 evaluator × arm，A/S/C/N）：

| evaluator\arm | BM25 | MCA |
| --- | --- | --- |
| GPT | A=7, C=8 | A=4, C=1 |
| DeepSeek | C=1 | （无失败） |
| GLM | （无失败） | （无失败） |
| Full Pro | A=1, C=11 | A=17, C=3 |

- atomic-only 失败（B）：Full Pro BM25=1 / MCA=16（与 9/19 材料记录一致）；
  GPT 两臂各 4。GPT 的首六失败同时落在 atomic 与 scope 两成分；
  Full Pro 的负 ΔU 与其 MCA 臂 atomicity 拒绝在诊断层面相伴出现。
- 支持度与冗余度成分在四个 evaluator 间 raw agreement = **1.000**（全部
  SUPPORTED / NONREDUNDANT）；分歧几乎完全来自 atomicity（0.854–1.000）
  与 scope（0.896–0.993）。

## 4. DIAGNOSTIC — Evaluator 敏感性与一致性

joint-U-eligibility 一致性（n=144/对）：

| pair | raw agreement | κ | κ 状态 |
| --- | ---: | ---: | --- |
| DeepSeek\|GLM | 0.9931 | — | GLM 退化（144/144 PASS），不计算 κ |
| GLM\|GPT | 0.8819 | — | 同上 |
| FullPro\|GLM | 0.7847 | — | 同上 |
| DeepSeek\|GPT | 0.8889 | 0.099 | 高 raw 低 κ：患病率效应 |
| FullPro\|GPT | 0.8056 | 0.312 | |
| DeepSeek\|FullPro | 0.7778 | −0.014 | |

864 个两两单元比较中 125 个不一致。标签分布：GLM 144 PASS / DeepSeek
143 PASS / GPT 127 PASS / Full Pro 113 PASS——pass 患病率极高，κ 的解释力
有限，必须与列联表、患病率同报（本报告如此执行）。

## 5. DIAGNOSTIC — λ 反事实敏感性与影响集中度

- 固定 λ 网格 {0, ¼, ½, ¾, 1}（`U_λ = S∧C∧N∧[A+λ(1−A)]`，不搜索最优 λ）：
  GPT、DeepSeek、GLM 的 ΔU 方向全程不变；**Full Pro 从 −0.583(λ=0) 单调
  变号为 +0.667(λ=1)**。去 atomicity 变体下 Full Pro 方向翻转、GPT/DeepSeek
  不变——度量对 atomicity 处理方式敏感，且该敏感性是 evaluator 依赖的。
- Leave-one-output-out（**等权重 cell estimand**：被删 output 所属 cell-arm
  用剩余 2 reps 均值，四 cell 权重保持各 1/4；完整数据下与冻结 macro 精确相等）：
  GPT ∈ [+0.417, +0.708]、DeepSeek ∈ [0.00, +0.125]、GLM 恒 0、
  Full Pro ∈ [−0.667, −0.500]——**各 evaluator 的方向在剔除任一 output 后均
  不翻转**。最大单一影响 output：GPT 为 `output_9882d5ee…`（21cm|A|MCA，
  贡献 +0.167）；Full Pro 为 `output_2e67d962…`（spectral|A|BM25，−0.083）。
- Leave-one-cell-out（剩余 3 cell 等权）：GPT 正向集中于 21cm|TaskB（剔除后
  ΔU 由 +0.583 降至 +0.222）；Full Pro 负向相伴于 21cm|TaskA（剔除后升至
  −0.111；而剔除 21cm|TaskB 使其降至 −1.111）。
- 槽位：Full Pro 在 MCA 臂 slot3 的合格率骤降至 0.583；boundary 事件命中
  集中于 BM25 臂 slot5/slot6。
- Claim 文本重复（**计数单位 = generator claim，每 claim 只计一次**）：
  144 个提交 claim 中 132 个文本唯一，**11 个文本跨 output 逐字重复**
  （最高 3 次）；lexical 模板（前 12 规范化词）127 组、16 组重复。这是
  字符串级诊断，**不是**语义聚类。

## 6. DIAGNOSTIC — 错误事件审计（软件 gap 核验）

- 事件词表：`task_boundary_misuse`(24) + `wrong_method_role`(12)、
  `wrong_target_task`(8)、`wrong_scientific_object`(2)、`wrong_data_modality`(1)。
- **subtype 从不脱离 generic 标签单独出现**（subtype-without-generic = 0）：
  V1 的 generic 计数在事件层面**没有漏检**；真实 gap 是**报告粒度**——
  边界失败的四种子类型未被分开统计。据此为 v2 计数器补了 subtype 分布
  输出与回归测试；**原 first-look 未受影响（CURRENT FIRST-LOOK UNAFFECTED）**，
  其计数定义自洽。
- 事件分布：GPT 9（BM25 8 / MCA 1）、DeepSeek 1（BM25）、Full Pro 14
  （BM25 11 / MCA 3）、GLM 0。

## 7. INTERPRETATION（允许的科学表述）

- 原三 Judge 的 ΔU 方向为正/小正/零，**无一反转**；E 同向为负/小负/零。
  在冻结协议内，这是"evaluator 依赖的测量差异"，**不是** MCA 被证明更好。
- Full Pro（post-hoc、无冻结 schema 的敏感性评审）在原度量下方向相反；
  诊断反事实度量下去掉 atomicity 足以使其 ΔU 翻转（λ 敏感性 + B=1/16
  不平衡）。**这不能把 atomicity 识别为 evaluator 分歧的唯一因果来源**，
  也不构成对任何 arm 的有利证据。
- 观察到的 evaluator 分歧**集中于 atomicity 与 scope 标签**；support 与
  redundancy 标签在本 pilot 完全一致。分歧来源是规则解释、内容理解还是
  二者交互，**仍需 human reason audit 才能判定**，当前数据不足以区分。
- 2 topics / 3 repetitions、claims 为嵌套标注、evaluator 非独立真值确认：
  任何总体优越性、显著性或"减少 hallucination"的表述都不成立。

## 8. NOT ALLOWED（本轮明确禁止的结论）

- "MCA proved better / significantly better"；
- 把 Full Pro 当第四 Judge、多数票当真值、或以其反转宣布 BM25 更好；
- 用 λ 或任何变体挑出新 endpoint 宣布方向；
- 把 144 claims 当独立样本做检验或 p-value fishing；
- 依据上述任何数字回调 V1 权重或重打分 first-look。

## 9. FUTURE

1. 按独立人评流程完成 Gate 1 前提（双人工独立评审 + 盲裁决），当前仍
   NOT_EVALUABLE；
2. 采用 Rubric V2 草案（分构造报告 + 边界子类型 + evaluator 校准集）设计
   下一次**预注册**实验；
3. 立即执行证据保存方案 E（独立 evidence repo + hash registry + 异地备份）
   ——supplement zip 在本轮审计期间被解压删除，单副本风险已现实发生；
4. 对 21cm|TaskA/TaskB 两 cell 与修正后 LOO 的最大影响 output
   （GPT：`output_9882d5ee…`，21cm|A|MCA；Full Pro：`output_2e67d962…`，
   spectral|A|BM25）做人工理由审计，区分规则解释差异与事实判断差异。

## 附：验证与工件

- 测试：synthetic 44/44 PASS（含 16 项 second-layer review 回归）；真实证据
  回归 10/10 PASS（env-gated）；worktree 全量套件结果见本轮 Final Report——
  唯一预期内 failure 是既有测试 `test_real_cli_sequence_stays_external_and_
  git_clean` 断言工作树零未跟踪文件，由本任务**尚未 commit 的新增代码文件**
  触发（等待人工复核的预期状态），非行为缺陷；4 skips 为 Windows symlink
  权限（既有模式）。
- Derived 工件（证据根同级 `MVP_zcode_derived/downstream_measurement_20260919/`）：
  inventory / integrity / evidence_dag.{json,md} / canonical 5 表 /
  first_look 复现与对比 / decomposition / sensitivity / influence /
  counterfactual / error_audit / figures 1–7 / manifest.json。
- 图：fig1 各 evaluator ΔU/ΔE（primary 实心、sensitivity 描边）；
  fig2 成分失败；fig3 cell 对比；fig4 一致性；fig5 λ 曲线；
  fig6 leave-one-out 影响；fig7 证据链字节核验。
