# RCP-v0.3.1 preparation package

This package versions only the Primary model-identity rule needed for external
agent runners. It reuses the exact frozen RCP-v0.3 screening prompt identity,
U80, judgement schema, routing, Human workflow, and final Reference rules.

For an external agent runner that cannot expose an immutable or
provider-versioned snapshot, the roster must say `snapshot_guarantee=unavailable`
and `snapshot_version=null`. The hashed execution config must identify the
runner, displayed model label, execution mode, prompt/config identities, and
the no-web/no-fulltext/one-candidate constraints. A model × Topic may use one
`sequential_shared_runner_session`; each candidate remains a separate judgement
and must be emitted without comparison, ranking, or label-count rescaling.

Status is `prepared_not_started`. This package contains no real roster, model
judgement, Human review, Reference Top-8, BM25 result, context, or synthesis.
The historical RCP-v0.3 package remains unchanged.
