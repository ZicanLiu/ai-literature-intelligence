# W4 Pilot Query Relevance Benchmark 收口协议

状态：协议有效；当前 judged-set artifact 为 `proposed/draft`，尚未 approved。

## 1. 名称、目标与边界

本基准统一称为 **W4 Pilot Adjudicated Judged Set** 或 **Pilot Adjudicated
Judged Set**。不得称为 expert gold、gold standard、ground truth 或专家真值。

它只评价 query-paper pair 的 **Query Relevance**，不评价论文绝对科学价值、创新性、
Value Profile 或 Reading Priority。标签使用 graded relevance：

- `2`：核心对象、光谱输入、机器学习方法角色和主要任务与 Research Query 直接对应；
- `1`：存在真实且重要的交集，但范围或核心任务只部分对应；
- `0`：对象、数据模态、方法角色或主要输出不对应。

个人 annotation 阶段允许的 `?` 只表示待讨论。approved benchmark 不允许 `?`、空值或
其他标签。

## 2. 原始 annotation 与 judgement 形成

六人的原始 annotation CSV 是不可改写的判断历史。judged set 通过 provenance 引用这些
文件及其 SHA-256，不把合并结果反写到成员 CSV。

当前 W4 v0.1 的 60 个 pair 按以下规则形成 judgement：

1. 30 个只有 primary 的 pair 保留 primary judgement，并标为 `single_annotation`；
2. 30 个双标 pair 中，双方标签一致时直接采用共同标签，标为 `agreement`；
3. 双方标签不一致时不得投票、平均或按算法分数选择，必须标为 `disagreement` 并进入独立
   adjudication；
4. adjudication 完成前 `final_label` 为空。AI 可写 `proposed_label`，但状态必须是
   `pending_human_review`；
5. 独立人工 reviewer 可 `approve` proposal 或 `modify` label，必须记录 reviewer、最终标签、
   带时区的 ISO-8601 时间和说明；之后才能标为 `adjudicated`。分歧 pair 不允许用 `ready`
   绕过 adjudication；proposal 仍为 `pending_human_review` 时不能进入 approved benchmark。

后续版本可继续为当前 `single_annotation` pair 增加独立复标；这会产生新 benchmark 版本，
不得覆盖 v0.1 的 provenance。

## 3. 独立 adjudication 协议

Reviewer 只使用 Research Question、论文 title/abstract、两位 annotator 的原始理由，以及
必要时升级查询的可靠论文页面。不得利用 `preliminary_score`、TF-IDF、Stage 1/2 分数、
baseline/two-stage rank、引用量或 selection bucket 决定标签。

建议 reviewer 不是该 pair 的两位原 annotator。若现实安排无法满足，必须在 review note 中
说明并由另一名成员复核。Title + Abstract 不足时，可按标注指南升级到 OpenAlex landing
page、ADS/SciX、arXiv、出版社、DOI 页面或全文关键位置，并记录 URL。

AI proposal 只能作为辅助建议。Artifact 必须同时保留：

- 两位原 annotator、原 label 和原 reason；
- AI proposed label、理由、证据来源、confidence；
- `proposal_status=pending_human_review`；
- reviewer 的 approve/modify 决定和最终 label。

## 4. AI assistance provenance

个人 annotation 的 `none/translation/explanation/label_suggestion` 原样进入 judgement
provenance；adjudication 中 AI 明确建议标签时记录 `label_suggestion`。使用 AI 不使 judgement
失效，但禁止把 AI-assisted judgement 表述为纯人工或专家 ground truth。

陈星妤的 15 条 annotation 已由本人实际审核确认；本次只修正其 review provenance，不改变
任何标签。贾馥诚的标签是人工判断并带逐行 AI 辅助记录；仓库中没有可据以声称“本人在
GitHub 再确认”的记录，因此 approved 前保留一项 provenance confirmation checklist，不能
补造记录。

## 5. Versioning 与 hash 规则

Benchmark 使用 `vMAJOR.MINOR.PATCH[-draft.N]`：

- `draft.N`：同一拟发布版本的复核轮次；每轮建立新目录，不覆盖旧 draft；
- `PATCH`：不改变 pair/query 范围的 judgement 或 provenance 修订；
- `MINOR`：新增 Research Query 或 candidate，同时保持标签语义和 record unit；
- `MAJOR`：改变标签语义、评价目标、record unit 或不兼容的数据契约。

每个版本的 manifest 必须记录 benchmark version/status、Git revision、reference year，以及
candidate pool、assignment、research query config、来源样例、pool manifest、六人原始
annotation、judgements 和 adjudication proposals 的路径与 SHA-256。任一冻结输入或 judgement
发生变化，都必须生成新版本和新 hash。approved 版本不可原地修改。

Package 自报 hash 不是信任根。Strict validator 还会使用 package 之外、经代码审查固定的 W4
v0.1 trust anchors 验证 `pool_manifest_v0.1.json` 本身，并解析该 pool manifest，交叉核对其中的
candidate pool、assignments、research query config 和 source sample 原始路径/hash；六份原始
annotation 也绑定到独立可信 hash。所有冻结输入和六份 annotation 共同形成
`input_set_identity`。

Approved manifest 必须通过 `parent_package` 记录实际被审核 draft manifest 的路径、SHA-256、
版本和 `input_set_identity`。Validator 会重新验证 parent draft，并确认 approved package 只增加
人工 review/final label 等允许变化，没有改写 proposal 证据、原 annotation provenance 或输入集。
因此同时修改输入文件和 approved manifest 的自报 hash 也不能形成有效 package。

当前 artifact：

`data/benchmarks/w4_query_relevance/v0.1.0-draft.1/`

其状态为 `proposed`，只可用于协议和结构复核。正式实验必须使用不含 `draft` 后缀且
`status=approved` 的新版本。

## 6. Record-level entity policy

W4 v0.1 是 **record-level Pilot Benchmark**：每个冻结的
`research_query_id + openalex_id` 都是独立评价记录，不静默删除或合并。当前保留两对高置信
same-paper alias：

- RQ02：`w4_rq02_002` / `w4_rq02_011`；
- RQ03：`w4_rq03_004` / `w4_rq03_011`。

因此 v0.1 的 60 pair 对应 57 个 OpenAlex records，canonicalize 后约 55 个论文实体。
后续可建立 sensitivity/canonicalized v0.2：新增稳定 canonical entity mapping、保留全部 alias
和 provenance，并同时报告 record-level 与 canonicalized 指标；本次不修改冻结池或 dedup。

## 7. Draft 与 strict 验证

复核当前 draft 的结构、pair identity 和 hash：

```powershell
python -m app.validate_w4_benchmark --allow-draft
```

默认 validator 是 strict，会拒绝当前 draft：

```powershell
python -m app.validate_w4_benchmark --manifest <approved-manifest.json>
```

Strict 至少要求：60/60、三个 RQ 各 20/20、pair 全量且唯一、无未知 pair、所有
`final_label` 都是 `0/1/2`、无 pending review、status 为 approved、版本不含 draft，并且冻结
candidate/query/source 等 hash 全部匹配。对三个 disagreement，它还要求 proposal 与 judgement
同时是已人工复核状态，decision/final label/reviewer/带时区时间/note 完整一致；并把 proposal
中的 annotator、原 label、原 reason 重新同 assignments 和六份原始 annotation 交叉验证。
Package-level `approval.checklist` 必须全部完成，不能只修改 `judgement_status`。

正式评价命令必须显式使用 strict package：

```powershell
python -m app.evaluate_w4_benchmark --strict `
  --benchmark-manifest <approved-manifest.json> `
  --output-dir <experiment-output-dir>
```

正式运行会在产生任何输出前采集 Git 状态并拒绝 dirty/无法确认 clean 的工作树；程序随后写入
自身输出不会反过来污染该快照。Strict 的 reference year 必须继承 approved benchmark，显式 CLI
参数不一致时直接拒绝。`experiment_manifest.json` 记录 Git revision/clean state、Python 与必要
依赖/平台信息、benchmark version/hash/input-set/parent-draft hash、candidate/query/source hash、
reference year、两种方法的实际固定配置、运行时间和输出文件 hash。未使用 `--strict` 的旧
`--labels` 入口只保留 smoke/partial evaluation 能力，不得作为正式 W5 实验。

## 8. Approved 前最小 checklist

1. 三个 disagreement 均由独立人类 reviewer approve 或 modify；
2. proposal 与 judgement 同时记录 final label、decision、reviewer、reviewed_at 和 note；
3. 核对贾馥诚的人工判断 + AI assistance provenance，不伪造 GitHub 确认记录；
4. 复制为新的无 draft 版本目录，更新 version、status 和全部 artifact hash；approved manifest
   绑定本 draft 的 manifest hash 与 `input_set_identity`；
5. 填完 package-level approval metadata/checklist，并确认不可变 proposal/provenance 未改写；
6. 默认 strict validator 通过；
7. 在 clean Git 工作树中运行正式 evaluator；
8. 人工审查完整 diff 后，才允许将该版本用于正式算法实验。
