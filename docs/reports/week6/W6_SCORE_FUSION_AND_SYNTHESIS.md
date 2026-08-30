# W6 标准化分数融合与证据约束文献综述原型（Issue #65）

本报告记录 Issue #65 的两个模块：标准化分数融合（Part A）与 evidence-grounded
literature synthesis 原型（Part B）。全部开发与测试只依赖 `tests/fixtures/w6_bootstrap/`
公共 fixture 与已冻结的 W5/W6 contract，不依赖任何未合并的 sibling PR，不读取任何
W6 Dev/Hidden relevance label、annotation、review、adjudication 或 metrics。

## Part A：Standardized Score Fusion

### 动机

W5 已证明 BM25 与 SPECTER2 具有互补的成功/失败模式，RRF 能利用 rank 级互补，但不利用
raw score 的 magnitude；不同方法的 score scale 差异很大（fixture 中 sparse 为 1–9，
dense 为 0.3–0.96），不能直接相加。本模块研究：显式、无标签的 normalization 之后做
score-level 加权融合，能否形成可信、可复现的 fusion baseline。

### Normalization 候选（均为 unsupervised，均不读取 label）

| 策略 | 定义 | zero variance | 特点 |
| --- | --- | --- | --- |
| `z_score` | `(x - mean) / std`（总体标准差，ddof=0） | 全部 0.0 | 保留方向与相对间距，对量级差异稳健 |
| `min_max` | `(x - min) / (max - min)` → [0,1] | 全部 0.5（区间中点） | 输出有界，但对 min/max outlier 敏感 |
| `robust` | `(x - median) / IQR`（Tukey exclusive hinges） | IQR=0 → 全部 0.0 | 抗 outlier，但小样本 topic 下 IQR 不稳定 |

统一约定：

- fit scope：`per_topic`（在 topic 内拟合）或 `global_frozen_pool`（整个冻结池）；
- score direction：所有 W6 artifact 均为 `higher_is_better`（contract 强制），融合前再核对；
- missing / non-finite score：fail closed（contract 已拒绝，模块内再次校验）；
- normalization 参数在生成时一次性冻结，写入 manifest 的 `score_processing.normalization`
  （strategy / parameters / fit_scope / label_access=false）。

### Label-free 对比（fixture denoise topic，等权 0.5/0.5）

在不查看任何 W6 label 的前提下，仅比较三种策略产生的冻结排序：

- `z_score` 与 `min_max` 产生完全一致的 topic 内排序
  （003 > 008 > 001 > 002 > 006 > 005 > 004）；
- `robust` 将 001 提到首位并交换 005/006——小 N（7 篇）下 IQR 对中位邻域敏感，
  排序稳定性较差。

### Primary fusion configuration（已在评价前冻结）

见 `configs/w6/score_fusion_primary.json`：

- input methods：`w6_fixture_sparse_v1` + `w6_fixture_dense_v1`
  （真实 W6 方法的 BM25 + SPECTER2 组合的 fixture 类比；W5 RRF 已有该组合的互补证据，
  因此优先研究二方法组合，不默认"模型越多越好"）；
- normalization：`z_score`，`fit_scope=per_topic`（理由：对 scale 差异稳健、保留方向、
  排序与 min_max 一致且无 outlier 敏感点）；
- weights：0.5 / 0.5（等权；不根据任何指标回调）；
- version：`1.0`；configuration_sha256：
  `0c8410d77532bbb3dcbc1759babcaefee0164975c84b455df1ac4d71cc68cb5a`。

该 config 在任何 W6 Dev/Hidden 评价结果可见之前冻结；后续调整必须新建版本。

注意 hash 语义边界：`configuration_sha256` 是 **semantic configuration hash**，只绑定
`config_id` / `version` / `input_methods` / `normalization` / `weights` 五个核心字段；
它不绑定 `frozen_at`、`output` 等 provenance 字段，不构成对这些字段的完整防篡改证明——
freeze 时间证据由 Git history 提供（`frozen_at` 字段本身做严格 ISO-8601 + 时区校验）。
第二轮审查起 hash 采用 canonical form：`input_methods` 按 method_id 排序后计入
（weights 本身是 method→value mapping，不依赖 list 顺序）；**算法语义 config 未变化**，
旧 hash `81222d22…` 与新 hash `0c8410d7…` 描述的是同一组 input methods / weights /
normalization / fit scope，仅 hash 表达方式 canonicalize。

### 实现与 artifact

- `src/w6_score_fusion.py`：`normalize_scores` / `validate_fusion_input_packages` /
  `fuse_method_rankings`。输入 method 按 method_id 字典序累加（order-independent），
  排序键为写入 CSV 的 float 本身，同分由 pair_id 升序打破，与 contract 复核一致。
- `app/fuse_w6_scores.py`：CLI。逐个用 `validate_w6_method_package` 校验输入并累积
  `known_method_packages`，在临时目录生成 `ranking.csv` + `manifest.json`，
  自校验通过后原子发布；`--config` 直接消费冻结配置。
- 输出是合法 W6-compatible method_ranking artifact：family=`hybrid`，`method_inputs`
  记录每个输入的 method_id / manifest_artifact_id / manifest_sha256 / ranking_sha256 /
  uses_raw_score / uses_rank，`freeze.configuration_sha256` 由
  `compute_method_configuration_hash` 重算，`label_access` 双 false。

### Label-access 声明

fusion generation 的输入只有 frozen method artifacts 与 bundle registry；代码没有任何
读取 labels/annotations/reviews/adjudications/metrics 的路径，contract 层对
`inputs`/`auxiliary_inputs` 中的禁止名（labels、hidden_labels、metrics 等）fail closed。

## Part B：Evidence-Grounded Literature Synthesis 原型

### 流水线

```text
Research Question + Frozen Ranked Papers（已验证 method package 的 top-N selection）
→ Evidence Extraction（`build_evidence_units`）
→ Structured Claims（backend）
→ Claim ↔ Paper ↔ Evidence 闭包（`validate_structured_synthesis`）
→ Human-readable Mini Review（`render_mini_review`，仅是 claims 的 render）
```

实现：`src/w6_synthesis_pipeline.py` + CLI `app/run_w6_synthesis.py`。输入为冻结
ranked-paper selection，不等待 Multi-Retriever / Leader / Canonicalization 等 PR。

### Synthesis backend

- 本仓库只提供 `DeterministicFakeBackend`：完全离线、确定性；每条非 rejected 的
  evidence 生成一条 claim，claim 文本直接取自 evidence 内容，不允许自由发挥；
  `human_verified` evidence → `supported`/`verified`，机器抽取（`extracted`）→
  `partially_supported`/`incomplete`。
- 真实 LLM backend 走 provider-agnostic 的 `SynthesisBackend` Protocol 扩展；核心
  流水线不含任何 LLM client、不读 `.env`、CI 不调真实 LLM、核心依赖不含模型 SDK。

### Evidence policy

- 只使用 title/abstract 短 snippet（≤800 字符，超长确定性截断）与 structured metadata
  （如 `abstract_present=false`）；不提交整篇 PDF 或大段受版权保护正文
  （`copyright_policy = short_public_snippets_or_structured_fields_only`）；
- 每条 evidence 绑定 source record + canonical entity + source_reference + locator +
  extraction provenance（方法/工具/时间/license note）。

### Structured claim contract 与闭包

claim 含 `claim_id / claim_text / supporting_canonical_entity_ids / evidence_refs /
confidence / support_status / citation_status`，由 `validate_structured_synthesis`
强制：Claim → Evidence → Selected Frozen Paper → Frozen Synthesis Input 完整闭包；
未选中论文、其他 topic 论文、dangling citation/evidence、rejected evidence、
input hash drift、unsupported claim 伪装 verified 一律 fail closed。
relevance score 不作为 factual correctness 的依据。

### Demo（fixture，小规模真实跑通）

```powershell
python -m app.run_w6_synthesis --output-dir <outdir>
```

默认使用 fixture fusion package 的 denoising topic top-3 selection
（pool_denoise_003/001/008），输出 5 个文件：`evidence_units.json`、
`synthesis_input.json`、`structured_synthesis.json`、`mini_review.md`、
`unsupported_claim_audit.json`。本次 demo 产出 3 条 claim，全部
`partially_supported`/`incomplete`——evidence 为机器抽取（`extracted`），未经人工
核验，因此没有 claim 被伪装成 fully verified。mini review 顶部带有固定状态统计与
“未经人工核验”提示，示例句：

> Paper rec_003 reports: A neural restoration model is trained on synthetic noisy
> stellar spectra and reports line-equivalent-width preservation. [claim_002; partially_supported/incomplete]

## 测试

- `tests/automated/test_w6_score_fusion.py`（39 tests）：三种 normalization 的数值定义、
  zero variance、negative/non-finite score、2 与 >2 输入、duplicate method/ranking、
  pool/candidate identity mismatch、manifest/ranking hash drift、weights missing/extra/
  非有限/bool、确定性与输入顺序无关、tie-break、fit_scope 差异、label-access 禁令、
  输出包过 W6 contract、CLI（端到端/冻结 config/参数互斥/非空输出目录/坏 weight）。
- `tests/automated/test_w6_synthesis.py`（21 tests）：evidence 构造与截断、alias 绑定、
  缺 abstract→structured metadata、fake backend 确定性与支持级别规则、未选中论文与
  rejected evidence 不产 claim、端到端 fixture 链、unsupported/dangling/越界引用/
  rejected 支撑/input hash drift/render 覆盖性检测、CLI 端到端（回读输出重跑三层
  validator）与 top-N 顺序。

## 已知限制

- fixture 规模小（2 topics / 13 pool items / top-3 selection），融合结论只说明
  机制正确性，不代表真实数据上的效果；真实 W6 方法就绪后应按冻结 config 重新生成。
- 未做 supervised / calibrated fusion（需要独立研究协议，禁止在 label 上调权重）。
- demo 的 evidence 未经人工核验，对应 claim 全部保持 `partially_supported`；
  human verification 流程在后续任务中定义。
- 真实 LLM backend 未实现（仅 Protocol）；接入前需要独立的凭据与安全审查。

## 审查修复记录（PR #70 第五轮）

第五轮为 provenance correctness 收口（1 个 P1 + 1 个 P2），未触动已关闭主体：

1. **P1-1 fixture provenance 正确传播**：新增 `derive_output_is_fixture(context,
   packages)`——base context 5 个 payload 与闭包内全部 method package（含传递
   依赖）的 `is_fixture` 必须全部一致，输出 artifact 从可信输入**派生**该值，
   混合 identity fail closed；fusion manifest 与 synthesis 三个 artifact
   （evidence/input/structured）的 `is_fixture` 不再硬编码/默认值，pipeline
   builder 改为必填关键字参数。回归：fixture 链全部输出 `is_fixture: true`；
   翻转任一输入（自洽 rehash）→ fail closed；fixture fusion 输出再进 synthesis
   链保持 true；real-like 全 False 一致输入 → 派生 False。
2. **P2**：PR body 的测试统计同步为 current head 真实数字。

## 审查修复记录（PR #70 第四轮）

第四轮聚焦复审只剩 No-Leakage semantic boundary 下 2 个 P1（其余 4 个 blocker 已独立确认关闭），修复如下：

1. **P1-1 `parallel_development` 等价 contract validation**：`load_w6_base_context`
   复用公共 `PARALLEL_MODULE_FIXTURE_REQUIREMENTS` 矩阵验证该块——槽位恰好六个、
   entry 只含 `depends_on`/`artifacts`、只依赖 `w6_bootstrap`、declared artifact 集合
   不得偏离公共矩阵，并对该块跑递归 side-channel guard 做纵深防御；注入
   `metrics.ndcg` / `evaluation.relevance_label`（额外槽或槽内额外 key）即拒绝。
2. **P1-2 allowlist 改为 (path, key, value) 语义**：`label_access` 仅允许顶层
   dict 或 `score_processing.normalization.label_access=false`；
   `relevance_labels_read` / `hidden_test_labels_read` 仅允许 `label_access.*` 且
   值必须为 `false`（错位置或 `true` 一律 fail closed）；
   `evaluation_started_at` 仅允许 `freeze.*`；`review_state` / `reviewer` 为字符串形
   合法 provenance。`frozen_configuration.relevance_labels_read=true` 与
   `pool.policy.parameters.hidden_test_labels_read=true` 全链自洽 rehash 后仍
   fail closed，合法 fixture 不误杀。

## 审查修复记录（PR #70 第三轮）

针对 owner 三轮审查的 5 个 P1 与 2 个 P2，修复如下（均有回归测试 + 独立攻击重放）：

1. **P1-1 传递依赖逐级绑定**：`_resolve_method_recursive` 内对每个被解析的
   package（含传递 dependency）执行 `validate_method_against_generation_context`，
   不再只检查 top-level；correct top + role-swapped dependency（全部 hash 自洽
   重算）→ default synthesis 与 fusion(top, dense) 均 fail closed。
2. **P1-2 No-Leakage 语义边界**：bundle manifest 恢复严格结构验证（顶层 exact
   fields、每个 artifact reference exact fields、is_fixture、created_at 时区），
   arbitrary metadata 无法混入；guard 升级为 exact-key + token family（label /
   judgement / annotation / adjudication / review / metric / ndcg / precision /
   recall / evaluation 及其复数与 `_at_k` 别名），allowlist 保护 `label_access` /
   `review_state` / `reviewer` / `evaluation_started_at` / `*_labels_read` 等合法
   provenance。13 个别名逐个自洽 rehash → fail closed。
3. **P1-3 bundle identity 无歧义**：加载时即对全部 artifact_refs 建
   `artifact_id → entry` 唯一索引，duplicate artifact_id（含 method/非 method
   碰撞、same ID 不同 path/SHA）立即 fail closed，两种 JSON 顺序结果一致；
   dependency resolver 使用该索引而非 first-match。
4. **P1-4 external dependency 顺序无关**：两阶段解析——Phase 1 为全部显式
   manifest 建 unique `artifact_id → path` 索引（duplicate/collision fail），
   Phase 2 从「显式索引 + bundle 唯一索引」统一解析 DAG；保留 cycle detection、
   same-ID 锚定、context 绑定、依赖 hash 校验。External A(hybrid)→B 的
   `[A,B]` / `[B,A]` 行为完全一致。
5. **P1-5 z-score silent wrong finite 根除**：anchor + difference-space scaling
   （原空间求差，溢出时回退缩放空间；在 difference space 内求 mean/centered/
   variance，全程 max-abs 缩放防下溢/溢出），数学上与 `(x-mean)/std` 等价。
   `[tiny, nextafter(tiny,+∞)]` → `[-1,1]`、`[prev(1e308),1e308,next(1e308)]` →
   `[-1.2247,0,1.2247]`（修复前分别给出 -1.4142/±0.52 与 ±1.04/1.16 的错误值）；
   全部用例经 Decimal（prec=80）高精度参照验证。
6. **P2-1**：PR body 的 config hash 已更新为 canonicalized `0c8410d7…`，并改述
   hash 绑定范围（semantic configuration，非全文件 provenance 防篡改）。
7. **P2-2**：`load_fusion_config` 要求 `input_methods` ≥2 且无重复。

## 审查修复记录（PR #70 第二轮）

针对 owner 二轮审查的 5 个 P1 与 2 个 P2，修复如下（均有回归测试 + 独立攻击重放）：

1. **P1-A per-task dependency closure**：`src/w6_task_context.py` 重写为
   `load_w6_base_context`（仅 topic/retrieval/records/canonical/pool 五个 base
   artifact）+ `resolve_bundle_method` / `resolve_method_path`（按 manifest 声明的
   method_inputs 从 bundle 声明中**递归**解析传递依赖）。Fusion 不再要求旧 fusion
   package；Synthesis 显式 sparse 不再要求 dense/fusion；默认 fusion 按需加载其
   传递依赖。minimal-closure 回归：无旧 fusion artifact 时 fusion PASS；仅
   base+sparse 时 explicit synthesis PASS；删除真正传递依赖 fail closed。
2. **P1-B 递归 No-Leakage guard**：新模块 `src/w6_no_leakage.py`
   （`GENERATION_FORBIDDEN_KEYS`，exact-key + lowercase、**非 substring**，不误杀
   retrieval/review_state/reviewer/score），对 generation 实际读取的每个 JSON
   payload 递归执行。自洽 rehash 攻击（重算 configuration_sha256 / pool_identity /
   bundle artifact sha）仍 fail closed。
3. **P1-C method → 当前 context 身份绑定**：
   `validate_method_against_generation_context` 要求 `inputs.topic_set` /
   `inputs.candidate_pool` 及声明的每个 auxiliary input 精确等于当前 context 的
   artifact identity；topic/pool role-swap 与 auxiliary swap（自洽重哈希）均 fail。
4. **P1-D z-score 数值可靠性**：均值用 fsum 计算后在**偏差向量**上做
   max-abs 缩放再算方差（近值相减无精度损失，平方不下溢/溢出）；
   `min == max` 才是真 zero variance；非常量输入但偏差/方差数值归零 fail closed。
   `[1e-308,-1e-308]`、`[5e-324,-5e-324]` 输出 `[1,-1]`（Decimal 高精度参照一致），
   不再静默 `[0,0]`；大 offset + 可表示 spread 不再失真。
5. **P1-E frozen path safety**：新共享模块 `src/w6_artifact_safety.py`
   （`check_output_dir_safe`），Fusion/Synthesis 使用完全一致的对称 resolved-path
   策略，protected 覆盖 bundle 目录与相关 method package 目录；
   `bundle_root/generated_fusion` 拒绝，bundle 外新目录放行；junction/symlink 用例
   在权限不足时显式 skip（不伪装 PASS）。
6. **P2-1 canonical config hash**：semantic hash 中 `input_methods` 按 method_id
   排序；primary config 重算 hash（算法语义 config 未变，仅 hash 表达 canonicalize）。
7. **P2-2 canonical render 校验**：`validate_canonical_render` 用 structured claims
   重新调用 deterministic renderer 并要求完全一致；保持 claim IDs 不变但删改/注入
   文本即 fail。

## 审查修复记录（PR #70 第一轮）

针对 owner 一轮审查的 5 个 P1 与 2 个 P2，修复如下（均有回归测试）：

1. **No-Leakage**：新增 `src/w6_task_context.py`（task-scoped、label-free 的
   generation loader），两个 CLI 不再调用完整 bundle validator；文件访问级测试断言
   generation 不打开 annotation/review/split/hidden-label/benchmark 文件；只复制
   声明依赖闭包后 CLI 可独立运行。
2. **Artifact identity**：显式 manifest 的 artifact_id 若已被冻结记录占用，
   manifest/ranking hash 与 method identity 必须精确一致，否则两个 CLI 均 fail closed
   （`check_frozen_method_identity`）。
3. **极端输入 correctness**：singleton robust 定义为 Q1=Q3=median（落入 zero-IQR
   规则）；溢出时自动在 `max(abs(x))` 缩放值上重算（三种策略均 scale-equivariant）；
   normalization 输出与 fused score 均显式检查 finite，杜绝
   `OverflowError`/`StatisticsError`/`nan`。
4. **Semantic reproducibility**：`method_inputs` 统一按 method_id 升序构造，
   `--manifest` 传入顺序不再影响 ranking sha 与 `freeze.configuration_sha256`。
5. **Frozen-path safety**：synthesis 输出目录对 method package 目录与 bundle 目录做
   resolve 后的对称重合检查（默认与显式 manifest 同一路径），三个方向均拒绝。
6. **P2-1**：config hash 语义边界已在本报告与 `configs/w6/README.md` 精确化，
   `frozen_at` 增加严格 ISO-8601 + 时区校验。
7. **P2-2**：mini review 顶部标注 support 状态统计与人工核验提示，每条 claim 附带
   `(support_status/citation_status)`。
