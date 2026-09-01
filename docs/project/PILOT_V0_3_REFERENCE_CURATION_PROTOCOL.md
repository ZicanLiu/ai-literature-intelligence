# SRTP Pilot RCP-v0.3 Reference Curation Protocol

> Historical frozen version. New Primary execution through an external agent
> runner follows the narrowly versioned
> [`RCP-v0.3.1 addendum`](PILOT_V0_3_1_REFERENCE_CURATION_PROTOCOL.md).

## 1. Status and scope

RCP-v0.3 is the provider-neutral infrastructure for an AI-assisted, selectively
human-reviewed internal Reference selection over the two committed Pilot U80
Topics:

```text
Frozen canonical U80
→ one-candidate Title+Abstract tasks
→ 3 cross-family Core + 2 cross-family Sentinel judgements
→ strict safe-zero / human routing
→ blind H1, anonymized-evidence H2, and triggered R3
→ human-supported internal Reference Top-8
→ generic Selection Artifact
→ BM25 only after the Reference Selection is frozen
```

The committed preparation state is `prepared_not_started`. No real model roster,
real model judgement, real human review, formal Reference Top-8, formal BM25
Top-8, matched experimental context, synthesis, or Hidden evaluation is part of
this package. Offline tests use only `is_fixture=true`, `purpose=plumbing_only`
data.

The allowed claim is **auditable internal reference selection**. It is not an
astronomy-expert gold set, ground truth, an optimal corpus, or evidence that one
model family is scientifically superior.

## 2. Versioned preparation artifacts

The machine-readable protocol is frozen by:

- `configs/pilot/srtp_pilot_v0.3_reference_curation_v1.json`;
- `data/research/pilot/v0.3/reference-curation-preparation-v1/manifest.json`;
- the versioned screening prompt in the same package;
- the blank 3-Core + 2-Sentinel roster template in the same package.

Validate the committed state with:

```powershell
python -m app.validate_pilot_reference_curation
```

The validator hash-binds the existing Pilot selection/context config, frozen U80,
prompt, roster template, package closure, and historical Dual-Curator preparation
manifest. It also proves every real-execution state remains `not_started`.

RCP-v0.3 does not change U80 membership, order, seed, identity, canonicalization,
OpenAlex inputs, the BM25 scoring core, or matched-context rendering. Primary
information remains the frozen Research Question and Topic boundary plus opaque
candidate ID, exact Title, and exact Abstract. Full text and external lookup are
forbidden in Primary.

## 3. Why the primary Reference protocol changed

Pilot v0.2 prepared two independent non-expert students to screen all 160 Topic
candidate abstracts. That workflow remains valid as a historical prepared
artifact and optional Dual-Human baseline, but it is no longer the primary
Reference protocol. RCP-v0.3 uses independent model judgements to identify the
easy provisional exclusions and concentrates limited human attention on
disagreements, uncertainty, boundary cases, and a statistically defined audit.

This is not pure multi-LLM voting. Models cannot automatically include a paper
in Top-8. Sentinels do not vote or rank. Every final Top-8 paper must have human
review/support.

## 4. Frozen model roster contract

The protocol structure is frozen; the five real model instances are deliberately
not chosen yet. A formal roster must contain exactly:

```text
3 Core
2 Sentinel
5 distinct model_family values
5 distinct independence_group values
```

Each entry freezes:

- role, provider, model family, and independence group;
- requested model ID and whether it was an exact version or rolling alias;
- provider-reported ID and the confirmed resolved exact ID;
- snapshot/version and snapshot guarantee;
- complete execution config and its SHA-256;
- frozen status.

The validator rejects a missing or extra slot, family/group reuse, multiple
versions presented as independent voters, unresolved identity, mismatch between
provider-reported and resolved identity, an unexpanded rolling alias, an
unfrozen entry, or a forged snapshot. Primary currently fails closed when an
immutable/provider-versioned snapshot cannot be established; a snapshot-
unavailable exception is not silently accepted.

`downstream_generator_family` remains unset until the future generator is
frozen. Once set, any Reference-panel family overlap fails. A sensitivity-only
exception must be explicitly enabled by a future versioned config; the current
Primary config does not enable one.

## 5. AI task and judgement contract

`python -m app.pilot_reference_curation export-ai-tasks` builds one run-specific
opaque namespace per model × Topic and exports 80 independent tasks outside the
repository. Each task contains one candidate only. The public task package does
not contain canonical/OpenAlex IDs, provider/model identity, Core/Sentinel role,
authors, venue, year, citations, source rank, query support, BM25 fields, another
model or human judgement, or downstream results. The canonical mapping is a
separate private coordinator file.

Every response binds protocol, run, Topic, opaque candidate, task identity, and
input SHA-256. Its structured judgement contains:

- `relevance`: `0`, `1`, `2`, or `null` with `abstain=true`;
- four boundary values: `match`, `mismatch`, `unclear`, or `not_stated`;
- evidence sufficiency and stable uncertainty/boundary codes;
- 1–2 exact Title/Abstract spans with offsets, text, and content SHA-256;
- a short auditable reason of at most 240 Unicode characters;
- `external_lookup=false`.

Relevance semantics are:

- `2`: all four necessary dimensions directly match and AI/ML has a substantive
  role in the target task;
- `1`: genuine target-domain relevance with partial/auxiliary match or a
  non-fatal boundary limitation;
- `0`: at least one directly evidenced hard mismatch, with the corresponding
  mismatch code and exact span;
- `abstain`: Title+Abstract is insufficient; relevance must be null.

Uncertainty is not coerced into relevance 1. Numeric self-confidence is absent
and cannot affect aggregation. Private chain-of-thought is neither requested nor
retained.

One schema-only repair is allowed. It may only transform the existing response
into the frozen schema and records that no rejudgement occurred. A second
failure becomes an explicit invalid/abstain outcome and routes to human review.

## 6. Model batches, raw responses, and deterministic aggregation

A formal model × Topic batch is valid only with exact 80/80 coverage: no missing,
extra, duplicate, unknown opaque, wrong-snapshot, wrong-input, or wrong-U80 case.
The batch binds the roster entry, requested/resolved model identity, prompt and
execution config hashes, Topic/Question/U80, task package and private map hashes,
timestamps, Git revision, validation status, and 80 raw response hashes.

Provider raw responses stay in a repository-external, content-addressed run
workspace. They may include service metadata or other material unsuitable for
Git. The repository-safe imported batch stores the validated short structured
response, raw SHA-256, and external retention reference; it must never store
secrets or private reasoning. Logs are not the provenance source.

The final execution manifest requires exactly ten validated batches:

```text
5 frozen models × 2 frozen Topics = 10 batches = 800 judgements
```

Aggregation is deterministic and input-order invariant. Core labels and
Sentinel labels remain separate. Secondary `n_core_label_2` and
`n_core_label_ge_1` diagnostics cannot replace final human relevance or
automatically include a paper.

## 7. Strict safe-zero and routing

A candidate is strict safe-zero only if all five valid judgements satisfy every
condition below:

```text
3 Core relevance = 0
2 Sentinel relevance = 0
no abstain
no unclear or not_stated boundary
sufficient evidence and valid exact spans
at least one shared hard-mismatch boundary dimension across all five
```

Safe-zero is only a provisional exclusion eligible for reduced human workload;
it is not a scientific gold label. Every other candidate routes to human review,
including any Core 1/2, Sentinel challenge to Core unanimous zero, abstain,
unclear/not-stated boundary, insufficient evidence, boundary conflict, invalid
span, or schema failure. Sentinels never enter majority/mean score or Top-8
ranking.

## 8. Selective blind human review

H1 assigns every non-safe-zero case plus the safe-zero audit sample to R1 and R2.
Both receive actor-specific opaque IDs and see only the frozen Question/boundary,
Title, and Abstract. They cannot see model names/families, votes/labels, routing
reasons, safe-zero state, BM25, source signals, rank, score, or the other
reviewer. Completed imports retain the trusted task/map snapshots and rebuild
canonical labels from those snapshots plus the raw response; self-reported
canonical labels are not accepted. R1/R2/R3 reviewer IDs must be distinct for
the same Topic.

H2 is built only from protocol-derived triggers: R1/R2 label difference, defer,
essential match-vs-mismatch conflict, two-level human-consensus/Core gap, or an
explicit disputed cutoff frontier. The packet hash-binds the two H1 submissions.
It contains deterministic-order, deduplicated exact spans, boundary criteria,
and short verifiable claims; it excludes model identity/family, vote count,
majority, confidence, candidate rank, and full model reasons.

R3 is created only for the protocol trigger roster. `r3_h2` cannot be exported
unless an immutable blind `r3_h1` submission for the exact same candidate roster
is supplied and hash-bound. Final numeric relevance uses R1/R2 agreement, or the
median of three numeric R1/R2/R3 labels. An unresolved/deferred case makes the
Reference non-freezable rather than silently assigning a value.

All human bundles and private mappings export outside the repository. The
visible reviewer directory contains instructions, task package, and blank
response; the canonical map is written to a non-nested private coordinator
directory.

## 9. Safe-zero audit

For safe-zero population `N`, the planner sets `m = ceil(0.10 × N)` and chooses
the smallest `n` satisfying:

```text
C(N-m, n) / C(N, n) <= 0.05
```

Sampling uses the frozen SHA-256 protocol/Topic/candidate/seed convention and is
deterministic. Discrepancies are derived from validated final Human labels for
the sampled cases; callers do not supply a discrepancy list. Any non-zero audit
label escalates every remaining safe-zero case to blind human review. The plan
and outcome are both content-addressed and deterministically reconstructed.

## 10. Final Reference and exact cutoff ties

Human relevance 0 is excluded; only 1/2 is eligible. Fewer than eight eligible
candidates fails with `insufficient_eligible_candidates`; relevance 0 is never
used to pad K. Primary ordering is:

```text
final_human_relevance DESC
n_core_label_2 DESC
n_core_label_ge_1 DESC
```

Sentinel output is not a rank signal. Every selected ID must be in the selective
human-label artifact. The formal validator recomputes the ranking and cutoff
result from the validated Human labels and requires exact stored Top-8 IDs.

For an exact rank-8 tie group, the coordinator exports actor-specific blind
cutoff tasks. R1/R2 each select exactly the required `s`; their intersection has
priority. If it is short, R3 independently partitions the complete tie group
into ordered priority groups. SHA-256 resolves only a residual within-group tie
and is recorded as a mechanical last resort, not scientific superiority. The
decision binds all imported blind cutoff submissions.

The Primary finalization records the 8/9/10 frontier only. RCP-v0.3 marks
one-swap generation as `deferred_not_primary_rcp_v0.3` and stores no one-swap
sets; any future sensitivity design requires a separate, explicit scope.

## 11. Generic Selection, BM25, and matched context

The generic Selection contract accepts exactly one new method ID:
`pilot_ai_assisted_reference_abstract_v1`. Its dedicated provenance validator is
separate from the historical `pilot_dual_curator_v1` and BM25 validators. A
fixture Reference can only be `plumbing_only`; formal selection rejects fixture
ancestry.

The new formal sequence is:

```text
finalized non-fixture Reference Selection freeze
→ unchanged BM25 query/tokenizer/k1=1.5/b=0.75/tie-break/K=8
→ formal BM25 Selection bound to that exact Reference ID/identity/SHA/time
→ configured BM25-vs-Reference pair validation
```

The old BM25-after-Dual-Curator path remains backward compatible. The new pair
validator reads exact BM25 and Reference method IDs from the frozen comparison
config rather than guessing families, and verifies equal Pilot, Topic, Question,
Research Question identity, U80, K, and context policy. It proves the Reference
arm in the pair is the exact artifact frozen inside the BM25 provenance.

Matched-context rendering is unchanged: Title+Abstract, K=8, 256 counting tokens
per paper, maximum rendered context 2400, treatment-neutral deterministic order,
no padding, and no global tail truncation. Reference/model/human metadata cannot
enter the rendered text or ordering.

## 12. Stability/quality report

The report schema records Core unanimity and pairwise agreement, boundary
agreement, abstain/invalid rates, Sentinel unique challenges, H1 R1/R2 agreement,
H1→H2 changes, R3 workload/rate, safe-zero audit workload, and cutoff
disagreement/hash-last-resort use when available. These are stability and
workflow diagnostics, not astronomy-correctness metrics.

## 13. REAL MODEL EXECUTION OPTIONS

Three provider-neutral execution routes are supported because the repository
exports tasks and imports strict structured files rather than calling a specific
SDK:

| Route | Identity/snapshot | Automation/cost | Raw retention | Formal suitability |
| --- | --- | --- | --- | --- |
| Official API | Often exposes exact returned model ID and request metadata; snapshot availability is provider-specific | Best automation and auditable 800-case coverage; direct usage cost | Save each raw response externally by SHA-256 | Preferred when the provider exposes a confirmable exact/versioned identity and stable structured output |
| Web/chat manual | UI may expose only a rolling product name; sessions and UI behavior are harder to reproduce | High manual workload and copy risk; subscription rather than per-call accounting | Export/copy every response and UI identity evidence externally | Acceptable only when exact resolved identity and complete response provenance can be confirmed; otherwise not Primary |
| External agent/tool runner | Depends on the runner and underlying provider; wrappers must not hide the returned identity | Can batch safely, but adds another software/config layer | Retain provider raw response plus runner version/config/hash | Suitable if it preserves exact one-task independence, model identity, prompt bytes, raw hashes, and no hidden retrieval |

For formal research, use an official API when it supplies the required exact
identity/version evidence and reproducible execution metadata. If it does not,
the API route does not become acceptable merely because it is automated. A web
workflow can be used for exploratory or sensitivity work, but a rolling UI label
must not be presented as an immutable snapshot.

Operationally, the coordinator freezes a real roster outside Git, validates it,
exports ten model × Topic bundles to separate external workspaces, executes each
of the 80 tasks independently, retains raw responses by hash, constructs one
schema-validated envelope per task, imports exact 80-case batches, then builds
the ten-batch execution manifest and per-Topic aggregation. The coordinator
must never give one model another run's judgements or the private canonical map.

## 14. REAL MODEL ROSTER + EXECUTION CHECKPOINT

Before any of the 800 real judgements starts, the group lead must:

1. choose exactly five real cross-family model instances and assign 3 Core + 2
   Sentinel roles;
2. obtain provider, family, independence group, requested ID, provider-returned
   ID, resolved exact ID, snapshot/version guarantee, and execution config for
   each;
3. freeze the roster and validate all five entries;
4. decide the external raw-response retention root and access policy;
5. ensure the future downstream generator family is unset or non-overlapping;
6. freeze the exact prompt/config/package hashes and a clean Git revision;
7. choose API, web/manual, or external runner per model without changing task
   content or the judgement schema;
8. perform a non-scientific plumbing check only, then start all formal batches
   under the frozen roster.

Do **not** start formal screening when any model is missing, family/group
independence is duplicated, identity cannot be confirmed, a rolling alias is
unresolved, snapshot status is misstated, execution config is incomplete,
downstream-family overlap violates config, the prompt/U80 hash drifts, the task
bundle leaks forbidden fields, raw retention is undefined, or external lookup/
full text/another judgement would be available to a model.

The current repository stops here. The remaining sequence is: freeze the real
roster → run 800 real judgements → selective human review → freeze Reference →
run formal BM25 → build matched contexts → downstream LLM experiment.

## 15. Coordinator CLI map (prepared; do not execute yet)

All generated roster/run/review outputs belong under a repository-external
coordinator root. The commands below are a map, not authorization to start real
screening:

```powershell
$rcpRoot = "D:\srtp_rcp_v0_3_workspace"

# After the group lead fills a five-entry roster input outside Git:
python -m app.pilot_reference_curation freeze-roster `
  --roster-input "$rcpRoot\roster_input.json" `
  --frozen-at <ISO-8601> `
  --output "$rcpRoot\frozen_model_roster.json"

python -m app.pilot_reference_curation validate-roster `
  --roster "$rcpRoot\frozen_model_roster.json"

# Repeat for each frozen roster entry × each frozen Topic (10 exports):
python -m app.pilot_reference_curation export-ai-tasks `
  --roster "$rcpRoot\frozen_model_roster.json" `
  --roster-entry-id <entry_id> `
  --topic-id <topic_id> `
  --created-at <ISO-8601> `
  --model-output-dir "$rcpRoot\runs\<entry_id>\<topic_id>\model" `
  --coordinator-map-output "$rcpRoot\maps\<entry_id>_<topic_id>.json"

# After external execution produces 80 import records and raw hashes:
python -m app.pilot_reference_curation import-model-batch `
  --roster "$rcpRoot\frozen_model_roster.json" `
  --task-package <task_package.json> `
  --mapping <private_map.json> `
  --responses <records_or_legacy_envelopes.json> `
  --started-at <ISO-8601> `
  --completed-at <ISO-8601> `
  --output <new_external_batch.json>
```

`responses` should normally contain a `records` array. A valid record contains
the structured response, raw-response SHA-256, external retention reference,
and whether the one permitted schema-only repair was used. An
`invalid_after_schema_repair` record contains the candidate ID, original and
repaired hashes, retention reference, and validation errors. The importer builds
and validates the immutable envelopes; exact 80 coverage is enforced by batch
construction.

Later coordinator subcommands cover aggregation, execution manifest, audit,
H1/H2/R3 exports/imports, blind cutoff tasks/imports, human-label finalization,
Reference finalization, quality report, Reference-bound BM25, and the formal
matched-context pair. `--help` on each subcommand is the executable source of
truth. Formal Reference finalization requires the exact ten-batch run descriptor;
it cannot validate from self-reported summary hashes alone.
