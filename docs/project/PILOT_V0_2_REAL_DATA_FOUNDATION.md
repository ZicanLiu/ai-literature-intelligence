# SRTP Pilot v0.2 Real-Data Foundation

## 1. Scope

This package builds the shared upstream data foundation for the first SRTP Pilot comparison. It is limited to:

```text
committed OpenAlex audit package
→ explicit aq query registry
→ W6-compatible retrieval/source artifacts
→ arm-neutral metadata gate
→ W6 Candidate Pool Builder
→ W6 canonicalization
→ canonical selection view
→ deterministic U80 per Dev Topic
```

It does not run OpenAlex live acquisition, BM25, curator selection, labels, Hidden evaluation, an LLM, synthesis, or factual evaluation. `U80` means an OpenAlex-query-conditioned calibration universe, not a complete or representative scientific corpus and not a gold or retrieval benchmark.

The frozen Pilot config is [`configs/pilot/srtp_pilot_v0.2_real_data_foundation_v1.json`](../../configs/pilot/srtp_pilot_v0.2_real_data_foundation_v1.json). It fixes the two Dev Topics, all 12 acquisition runs, metadata policy, full-roster pooling policy, canonical selection policy, sampling algorithm, seed, and `N=80` before generating U80.

## 2. Frozen inputs and immutability

The build validates and reads, but never modifies:

- `data/research/w6/v0.2-alpha/topics.json`;
- `data/research/w6/v0.2-alpha/split_manifest.json`;
- `configs/w6/openalex_topic_query_audit_v1.json`;
- `data/research/w6/v0.2-alpha/openalex-audit-v1/`.

Only these frozen Dev Topics enter derived artifacts:

```text
w6_topic_21cm_foreground_removal
w6_topic_spectral_anomaly_detection
```

The build validates the full split solely to prove both selected Topics are Dev. No Hidden Topic, Hidden label, judgement, ranking, metric, or downstream output enters the adapter, canonical view, or sampler.

## 3. Query identity resolution

The frozen W6 Topic artifact contains historical `qv1/qv2`, while the real acquisition package contains `aq01–aq06`. The Pilot uses a new versioned `query_registry.json` and a derived two-Topic W6 adapter view:

- every AQ keeps its real `acquisition_query_id` and source `query_run_id`;
- every entry binds exact query text, acquisition config identity/file hash, and source package identity/manifest hash;
- `aq01` and `aq02` record a historical lineage only when Topic and exact query text match `qv1` or `qv2`;
- `aq03–aq06` have no historical qv lineage and are not renamed;
- the derived `topic_adapter.json` exposes the six AQ identities to the existing W6 retrieval validator without changing the frozen W6 Topic artifact.

## 4. OpenAlex → W6 bridge and metadata gate

The bridge first runs the existing committed OpenAlex package validator. It then projects the selected 12 runs into existing `w6_retrieval_provenance` and `w6_source_records` contracts.

The source package uses identities such as `openalex:W123`, which are not legal lowercase W6 machine IDs. The bridge deterministically maps them to `pilot_openalex_w123` while retaining the real `W123` in both `openalex_id` and `record_provenance.source_record_id`. Source query-run and hit IDs are retained unchanged.

W6 requires non-empty title, publication year, authors, venue, and landing page. A source Work missing any of these fields is excluded before pooling, with its source Work/hit/query/run identity and reason codes preserved in `eligibility_report.json`. Abstract and DOI remain truthful nullable fields under the existing W6 partial-metadata semantics. There is no placeholder, metadata fabrication, relevance filtering, or network enrichment.

After canonicalization, a canonical entity is selection-eligible only when its deterministic W6 preferred record has both a non-empty title and abstract. These later exclusions are recorded separately from source representability exclusions.

### Source Git provenance limitation

The committed OpenAlex package did not capture the exact acquisition execution HEAD. The adapter therefore does not use the current Pilot HEAD as a substitute. The required W6 run `git_revision` field is bound to `4a98c33cba3131de581a540584331e67f66dd07f`, the source package introduction commit's nearest pre-acquisition parent/repository anchor. Config, registry, run configuration, and manifest explicitly state that this is not a claim that the exact execution HEAD was captured. The source config freeze commit and package/file hashes remain the stronger available provenance boundaries.

## 5. Pooling, canonicalization, and selection view

The build reuses `src.w6_candidate_pool_builder` with all 12 query runs and depth 80, exactly matching the committed per-query capture cap. Thus every representable committed hit is admitted; target size does not truncate the pool and random fill is disabled.

It then reuses `src.w6_canonicalization`:

- confirmed high-confidence aliases share one canonical entity and one selection slot;
- suspected duplicates remain separate entities and retain explicit relationship IDs/status;
- preferred-record choice and record/provenance union use the existing deterministic W6 v1 behavior;
- source-record pool items remain available in pre/post-canonical artifacts, while later arms consume only `canonical_selection_view.json`.

## 6. U80 algorithm

For each Topic, the sampler:

1. builds six canonical-entity rosters from the eligible canonical view;
2. orders each roster by SHA-256 of the fixed seed, Topic ID, AQ ID, and canonical entity ID;
3. orders the six AQ iterators themselves by a separate seeded hash;
4. round-robins across queries and admits only previously unseen canonical entities;
5. stops at exactly 80 or fails closed if fewer than 80 eligible entities exist;
6. retains each selected entity's complete query support, aliases, preferred record, and canonical selection reference;
7. reports both first-admission contribution and total U80 support for every AQ.

Sampling never reads source rank, citation count, BM25, labels, human preference, or synthesis output. Reordering source rows, canonical-view rows, or registry rows does not change the semantic result.

## 7. Reproduction and validation

Generation requires a clean Git worktree and refuses to overwrite a non-empty output directory:

```powershell
python -m app.build_pilot_real_data_foundation `
  --config configs/pilot/srtp_pilot_v0.2_real_data_foundation_v1.json `
  --output-dir data/research/pilot/v0.2/real-data-foundation-v1
```

Independent offline validation rechecks source package closure, every input/output hash, W6 contracts, metadata exclusions, pool/canonical closure, canonical view, U80 sampling, identities, counts, and manifest:

```powershell
python -m app.validate_pilot_real_data_foundation `
  --config configs/pilot/srtp_pilot_v0.2_real_data_foundation_v1.json `
  --package-dir data/research/pilot/v0.2/real-data-foundation-v1
```

The output package contains:

```text
query_registry.json
topic_adapter.json
retrieval_provenance.json
source_records.json
pooling_policy.json
pool_statistics.json
precanonical_candidate_pool.json
canonical_entities.json
postcanonical_candidate_pool.json
canonical_selection_view.json
eligibility_report.json
u80_calibration_universe.json
manifest.json
```

All JSON is generated atomically and deterministically for the same frozen config, inputs, timestamp, and generation revision.
