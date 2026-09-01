# SRTP Pilot RCP-v0.3.1 External Agent Runner Addendum

Status: `prepared_not_started`. This addendum changes one Primary trust rule in
RCP-v0.3; all other RCP semantics remain frozen.

The versioned machine-readable closure is:

- `configs/pilot/srtp_pilot_v0.3.1_reference_curation_v1.json`;
- `data/research/pilot/v0.3.1/reference-curation-preparation-v1/manifest.json`;
- the new roster template in that preparation package;
- the exact unchanged RCP-v0.3 screening prompt identity
  `srtp-rcp-screening-prompt:sha256:b38f158a1e0c24eedb31c6ff88bf82af8874c64c6c321e0e9438ecc6ef25d616`.

The schema-family `protocol_id` remains `srtp_reference_curation_v0.3` for
backward compatibility. The exact revision is bound by
`protocol_version=RCP-v0.3.1` plus the new config identity and SHA-256. The
historical RCP-v0.3 config and preparation package remain unchanged and valid.

## Sole protocol change

An RCP-v0.3.1 Primary roster supports two honest identity paths.

1. Exact snapshot available: retain the RCP-v0.3 provider, requested model,
   provider-reported/resolved model, snapshot/version, and snapshot-guarantee
   rules unchanged.
2. External agent runner without an immutable/provider-versioned snapshot:
   set `snapshot_guarantee=unavailable`, `snapshot_version=null`, and explicitly
   enable the roster's snapshot-unavailable exception. This path is allowed
   only when the hashed execution config declares `external_agent_runner` and
   contains all required runner provenance.

For the unavailable path, `provider_reported_model_id` and `resolved_model_id`
record the exact displayed underlying-model label, and
`resolved_identity_confirmed=true` confirms that displayed label was observed.
It does not claim an immutable snapshot. A rolling/display alias may remain the
same label only in this explicit unavailable branch; it cannot masquerade as
an exact snapshot.

Required hashed runner execution fields are:

```text
execution_route
runner_name
runner_version (nullable only when unavailable)
displayed_model_label
execution_mode
prompt_identity
protocol_config_identity
external_lookup=false
fulltext_access=false
one_candidate_per_judgement=true
```

Together with the existing judgement-batch contract, this binds the execution
start/end window, frozen prompt and config, Git revision, raw-response hashes,
and external content-addressed retention references. The actual-model duplicate
guard remains provider + resolved/displayed model identity + snapshot/version;
the snapshot component is explicitly unavailable rather than invented.

## Sequential shared runner session

A model × Topic may process its 80 opaque one-candidate tasks in one
`sequential_shared_runner_session`. It does not become a ranking task. Each
candidate must be judged and emitted separately and immediately. The runner
must not compare candidates, revisit earlier candidates, infer a Top-8, or
rescale decisions from prior 0/1/2 counts.

## Unchanged Primary boundaries

RCP-v0.3.1 does not change the 3 Core + 2 Sentinel panel, five distinct
families/independence groups, Title+Abstract-only information boundary,
one-candidate judgement schema, no-web/no-fulltext rules, safe-zero semantics,
Human H1/H2/R3, cutoff/final Reference reconstruction, U80, BM25, or matched
context. No real roster, model judgement, Human review, Reference, BM25,
context, or synthesis is created by this addendum.
