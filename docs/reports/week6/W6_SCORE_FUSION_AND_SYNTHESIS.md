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
  `81222d2240190bf9eb7530cd9d338a48087843b361abf3f6702e76dc35c69b68`。

该 config 在任何 W6 Dev/Hidden 评价结果可见之前冻结；后续调整必须新建版本。

注意 hash 语义边界：`configuration_sha256` 是 **semantic configuration hash**，只绑定
`config_id` / `version` / `input_methods` / `normalization` / `weights` 五个核心字段；
它不绑定 `frozen_at`、`output` 等 provenance 字段，不构成对这些字段的完整防篡改证明——
freeze 时间证据由 Git history 提供（`frozen_at` 字段本身做严格 ISO-8601 + 时区校验）。

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

## 审查修复记录（PR #70 第一轮）

针对 owner 审查的 5 个 P1 与 2 个 P2，修复如下（均有回归测试）：

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
