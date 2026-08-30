# SRTP Pilot v0.2 Selection Infrastructure and Matched Context

## 1. Scope and stop boundary

This stage implements the offline infrastructure between the committed canonical
U80 and future generation:

```text
U80
├─ BM25 Lexical Selection tooling
└─ Dual-Curator human-selection tooling
        ↓
generic Selection Artifact
        ↓
Matched Context Builder
        ↓
validated evidence context
```

It stops before the first real human selection. It does not contain a real
Dual-Curator result, a real BM25 Top-8, a real matched context, an LLM prompt, an
LLM call, calibration output, synthesis evaluation, SCR/citation metrics, or
Hidden evaluation. Tests use only artifacts explicitly marked
`is_fixture=true` and `purpose=plumbing_only`.

The frozen config is
[`configs/pilot/srtp_pilot_v0.2_selection_context_v1.json`](../../configs/pilot/srtp_pilot_v0.2_selection_context_v1.json).
It hash-binds the committed Pilot foundation manifest, U80, canonical selection
view, frozen Topic set, both Research Questions, both selection methods, and the
context policy. No live OpenAlex or LLM access is allowed.

The upstream U80 remains an OpenAlex-query-conditioned, metadata-filtered,
canonicalized, query-balanced, multi-query-support-tilted, deterministic
calibration sample. This stage does not change its membership, order, seed,
algorithm, or files.

## 2. Shared selection contract

Both experimental arms produce the same thin `srtp_pilot_selection` artifact.
The method-independent fields bind:

- Pilot version and artifact identity;
- Topic, Question ID, and frozen Research Question identity;
- U80 artifact ID, semantic identity, and file SHA-256;
- exactly eight unique canonical entity IDs from that Topic's U80;
- method/config identity, timestamp, Git provenance, and fixture status.

BM25 scores/ranks and curator/adjudication provenance live only under
`method_specific_provenance`. The Context Builder validates the whole selection
but renders only the method-independent Topic/U80/selected-ID contract. Method
metadata and input priority cannot affect context ordering or text.

Use the generic validator after a selection exists:

```powershell
python -m app.validate_pilot_selection --selection <selection.json>
```

## 3. Frozen BM25 condition and curator blinding

The Pilot BM25 condition reuses `src.bm25_ranking` and
`src.text_relevance.tokenize_text`; it does not introduce another BM25
implementation.

```text
query                 frozen Topic research_question
paper representation  title + abstract
k1                     1.5
b                      0.75
ranking                score descending, canonical_entity_id ascending tie-break
K                      8
```

The implementation, configuration, deterministic reconstruction validator, and
synthetic determinism tests are frozen now. The real U80 BM25 Top-8 is
intentionally not generated in this stage so that neither curator can encounter
its ranks, scores, or selected set. The formal CLI requires the validated final
non-fixture Dual-Curator selection for the same Topic. The resulting BM25
artifact embeds that exact Human artifact's ID, selection identity, SHA-256,
and frozen timestamp; validation requires the Human artifact again and rejects
any hash or time-order drift:

```powershell
python -m app.run_pilot_bm25_selection `
  --topic-id <topic_id> `
  --human-selection-freeze <final_human_selection.json> `
  --output <new_bm25_selection.json>
```

## 4. Dual-Curator preparation and visibility boundary

The committed preparation package is
`data/research/pilot/v0.2/selection-preparation-v1/`. It is the immutable,
coordinator-side source package: do not fill or edit its committed blank
responses. It contains two Topic tasks for each of `curator_a` and `curator_b`,
private mappings, readable views, and blank templates. It contains no prefilled
selection and records both `human_selection_status=not_started` and deferred
BM25 execution.

Export one fillable bundle per person to directories outside the repository.
For example on Windows PowerShell (choose any suitable external root; these
paths are examples, not artifact fields):

```powershell
$curatorRoot = "D:\pilot_curator_workspaces"
$coordinatorRoot = "D:\pilot_v0_2_coordinator"

python -m app.export_pilot_curator_bundle `
  --curator-slot curator_a `
  --output-dir "$curatorRoot\curator_a"

python -m app.export_pilot_curator_bundle `
  --curator-slot curator_b `
  --output-dir "$curatorRoot\curator_b"
```

An export contains only the instructions, that slot's two task Markdown files,
two blank response JSON files, and non-secret task/package identity metadata.
It contains no coordinator mapping, canonical IDs, BM25 data, query support,
source rank, authors, venue, or information about the other curator. Export to
any path under the repository fails closed. Filling the external response files
there does not change `git status`.

Each curator sees:

- the frozen Research Question;
- scientific object, data modality, target task, method role, scope-in,
  scope-out, and boundary cases;
- 80 candidates containing only opaque candidate ID, title, and abstract.

Each curator must not see BM25 rank/score/Top-8, OpenAlex source rank, query
support, citation count, the other curator's submission, authors, venue, or the
canonical-ID mapping. The `coordinator/` directory is private and must not be
shared with curators.

Each response must select exactly eight unique candidate IDs, give one short
reason per selection, record start/end or elapsed time, keep
`external_lookup=false`, and acknowledge an independent submission. The
validator rejects unknown/duplicate IDs, wrong count, missing reasons/timing,
external lookup, or a missing acknowledgement. If an abstract contains a URL,
leave its scientific text unchanged but do not click it; do not search a DOI,
title, author, or paper page.

Curator A and B receive the same 80 canonical papers and the same title and
abstract snapshots, but each slot has a different deterministic order and a
different opaque-ID namespace. Rebuilding a slot is stable; the slot affects
presentation only and never changes U80.

The package itself is validated by file closure, SHA-256, source binding, task
blindness, and deterministic reconstruction:

```powershell
python -m app.validate_pilot_curator_preparation
```

After completed forms are returned, validate and import each external JSON
against the trusted committed package, not against caller-supplied mappings:

```powershell
python -m app.pilot_curator_workflow validate-response `
  --curator-slot curator_a `
  --response "D:\pilot_curator_workspaces\curator_a\responses\<topic>_response.json"

python -m app.pilot_curator_workflow import-response `
  --curator-slot curator_a `
  --response "D:\pilot_curator_workspaces\curator_a\responses\<topic>_response.json" `
  --output "$coordinatorRoot\curator_a_submission_<topic>.json"
```

Repeat for both Topics and both slots. Import reconstructs the committed
manifest → task → visible roster → private map → U80 → canonical entity →
title/abstract source snapshot chain before decoding submitted opaque IDs. The
workflow then provides `compare`, `build-adjudication-task`,
`import-adjudication`, and `build-final-selection`; human operators edit only
external response JSON and never Python or committed package files. Every
generated submission, comparison, adjudication task/import, and final Human
selection must use an output path under an external coordinator directory such
as `D:\pilot_v0_2_coordinator\`; any output path under the repository fails
closed. Thus normal export-through-finalization operation creates no tracked or
untracked Git changes.

## 5. Overlap and adjudication protocol

Original Curator A and Curator B imports are immutable and remain separately
hash-bound to their tasks, maps, source snapshots, and preparation package. The
comparison artifact hash-binds both full submissions and records both original
selected sets, intersection, symmetric difference, overlap count, and Jaccard.

```text
overlap < 4/8
→ curation_stability_failure
→ fail closed
→ do not automatically replace the Topic

overlap >= 4/8
→ retain the intersection
→ if fewer than 8, a third adjudicator selects only the required additions
  from the symmetric difference
```

The adjudicator task hash-binds the comparison and exposes only a reconstructed
symmetric-difference roster. It does not reopen the full U80 and does not reveal
which curator selected which item. Its imported response binds the task,
comparison, both original submissions, preparation package, and mapping. Final
selection revalidates that complete chain and is exactly the intersection plus
the validated additions. Fixture comparisons can only produce a fixture
generic selection; they cannot masquerade as the formal human arm.

## 6. Frozen context policy

The Matched Context Builder is selection-method agnostic:

```text
validated generic Selection Artifact
+ committed U80 canonical selection snapshots
+ frozen Context Policy
→ exact matched evidence context
```

The policy is:

- `K=8`, one slot per canonical entity;
- representation: exact Title + Abstract only; no PDF, full text,
  summarization, paraphrasing, compression, or generated snippet;
- provider-neutral tokenizer convention: Python Unicode regex
  `[^\W_]+(?:[-'’][^\W_]+)*`, counting only with no text normalization;
- per-paper combined Title+Abstract cap: 256 counting tokens, allocated title
  first and then abstract;
- maximum rendered context: 2400 counting tokens; overflow fails closed;
- no global tail truncation and no padding;
- separator: `\n\n---\n\n` and a frozen field template;
- generator-visible blocks contain only `Title: ...` and `Abstract: ...`;
  canonical IDs, method, condition, rank, and score remain metadata and never
  enter `exact_rendered_context`;
- every paper records its exposed title/abstract, source snapshot SHA-256,
  truncation flags, and actual counting-token count;
- the artifact stores exact rendered UTF-8 text, rendered SHA-256, actual total
  count, selection/config/policy/U80 identities, Git provenance, and fixture
  status.

This tokenizer is a reproducible construction convention, not a promise of
provider-token equality. A future generator must consume the exact rendered
UTF-8 context unchanged and separately record its provider/model token count.
If the future model cannot accept the frozen context, compatibility must be
resolved before generation rather than silently changing this artifact.

Context is evidence input, not an LLM prompt. This stage freezes no system
prompt, answer format, citation instruction, model snapshot, temperature, or
provider.

## 7. Treatment-neutral ordering and pairwise fairness

Selected papers are ordered by ascending:

```text
SHA256(order_seed | question_id | canonical_entity_id)
```

with canonical ID as a defensive deterministic tie-break. Condition/method,
selection rank/priority, score, repeat number, and model do not enter the key.
Therefore the same selected set yields the same rendered order regardless of
whether it came from BM25, human curation, or a fixture.

The generic pairwise helper requires equal Pilot, Topic, Question, U80, K,
config, context policy, tokenizer, representation, ordering algorithm/seed, and
fixture status. The formal Pilot validator additionally requires the method
roster to be exactly one `pilot_bm25_lexical_v1` artifact and one
`pilot_dual_curator_v1` artifact; BM25/BM25, Human/Human, and fixtures fail
closed. The validator uses the Human selection in the pair itself to validate
the BM25 artifact's stored Human-freeze artifact ID, selection identity,
SHA-256, frozen timestamp, Topic, Question, U80, and K. It does not accept a
separate caller-supplied Human freeze that could differ from the Human arm. It
allows only the treatment variable (selected canonical set) and the natural
content consequences (actual token count and per-paper truncation). It records
signed and absolute token deltas and never pads to equality.

```powershell
python -m app.build_pilot_matched_context `
  --selection <validated_selection.json> `
  --output <new_context.json>

python -m app.validate_pilot_matched_context `
  --selection <validated_selection.json> `
  --context <context.json>

python -m app.validate_pilot_matched_context_pair `
  --left-selection <bm25_selection.json> `
  --left-context <bm25_context.json> `
  --right-selection <human_selection.json> `
  --right-context <human_context.json> `
  --report <new_pair_report.json>
```

## 8. HUMAN CHECKPOINT INSTRUCTIONS

1. **People needed:** two independent curators now. A third adjudicator is
   needed later only for a Topic whose overlap is 4–7; overlap below 4 stops the
   Topic workflow.
2. **Three workspace boundaries:** the Git repository is read-only trusted
   source; Curator A/B each receive a separate repository-external bundle; all
   imports, comparisons, adjudication files, and final Human selections go to a
   third repository-external coordinator workspace such as
   `D:\pilot_v0_2_coordinator\`.
3. **Coordinator action:** keep the committed `selection-preparation-v1/`
   package read-only. Run the export command twice, give Curator A only the
   `curator_a` export and Curator B only the `curator_b` export, and never share
   `coordinator/`.
4. **Files each person opens:** their exported `CURATOR_INSTRUCTIONS.md`, both
   Markdown files under `tasks/`, and both blank JSON files under `responses/`.
5. **What each person does:** review all 80 candidates for each Topic,
   independently choose exactly eight, enter the eight opaque candidate IDs and
   one short reason each, record time, and return the completed response JSONs.
6. **What they can see:** frozen Question and Topic guidance plus opaque ID,
   title, and abstract for each candidate.
7. **What they cannot see:** the coordinator mapping, canonical IDs, BM25
   output, source rank/score, query support, citations, authors, venue, or the
   other curator's work. They must not click embedded URLs, search DOI/title, or
   use any other external lookup.
8. **How many to select:** exactly 8 of 80 for each Topic; each person completes
   both Topics.
9. **Work estimate:** plan about 2–3 hours per Topic, or 4–6 hours per curator;
   record actual elapsed time.
10. **Files produced:** initially four completed external response JSONs (two
    people × two Topics). In the external coordinator workspace, the tools then
    preserve four imported submissions and one comparison per Topic; if
    required, they create restricted adjudication task/response/import files
    and then one final Human selection per Topic.
11. **What to return to Codex:** only the four completed response JSONs from the
    two external bundles. Do not return edited task files, the bundle manifest,
    or any coordinator mapping; do not change Python.
12. **What Codex does next:** validate each response against the immutable
    committed package, import and preserve the four originals, calculate
    overlap/Jaccard, stop if overlap is below four, or prepare restricted
    third-person adjudication when needed. Only after final human selections
    are frozen will Codex execute formal BM25, build the two real matched
    contexts per Topic, and stop before LLM generation until that next stage is
    approved. From export through final Human selection, normal operation must
    leave `git status` clean.
