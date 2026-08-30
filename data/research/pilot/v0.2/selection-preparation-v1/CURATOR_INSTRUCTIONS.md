# SRTP Pilot v0.2 · Independent Curator Instructions

The committed preparation package is immutable and read-only. Curators work only
inside a repository-external exported bundle; this package contains no human
selection result.

## Coordinator

1. Assign `curator_a` and `curator_b` to two different people.
2. Use `python -m app.export_pilot_curator_bundle` to create one repository-
   external bundle for each slot. Give each person only their own exported
   bundle.
3. Never share the `coordinator/` directory with a curator.
4. Do not show either curator BM25 output, the other curator's response, OpenAlex
   source rank, query support, citation counts, authors, or venue.

## Each curator

For each of the two Topic Markdown files:

1. Read the frozen Research Question and Topic guidance.
2. Review all 80 opaque candidates using only title and abstract.
   If an abstract contains a URL, do not click or open it. Do not search a DOI,
   title, author, or paper page. Use only the Question, Topic guidance, Title,
   and Abstract text already present in the exported bundle.
3. Independently select exactly 8 candidates.
4. In the matching response JSON, set `status` to `completed`, fill a stable
   `curator_id`, enter the 8 candidate IDs and one short reason for each, and
   record either start/end times or elapsed minutes.
5. Keep `external_lookup` false, set
   `independent_submission_acknowledged` true, and record `submitted_at` with a
   timezone.
6. Return only the two completed response JSON files from the external bundle to
   the coordinator.

Do not edit the committed preparation package, Python, task Markdown, bundle
manifest, or coordinator mappings. A planning estimate is 2–3 hours per Topic
(4–6 hours per curator); actual elapsed time must be recorded.
