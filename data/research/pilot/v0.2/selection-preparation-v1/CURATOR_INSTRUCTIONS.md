# SRTP Pilot v0.2 · Independent Curator Instructions

This package prepares, but does not contain, a human selection result.

## Coordinator

1. Assign `curator_a` and `curator_b` to two different people.
2. Give each person only their matching `curator_tasks/<slot>/` and
   `responses/<slot>/` files plus this instruction file.
3. Never share the `coordinator/` directory with a curator.
4. Do not show either curator BM25 output, the other curator's response, OpenAlex
   source rank, query support, citation counts, authors, or venue.

## Each curator

For each of the two Topic Markdown files:

1. Read the frozen Research Question and Topic guidance.
2. Review all 80 opaque candidates using only title and abstract.
3. Independently select exactly 8 candidates.
4. In the matching response JSON, set `status` to `completed`, fill a stable
   `curator_id`, enter the 8 candidate IDs and one short reason for each, and
   record either start/end times or elapsed minutes.
5. Keep `external_lookup` false, set
   `independent_submission_acknowledged` true, and record `submitted_at` with a
   timezone.
6. Return only the two completed response JSON files to the coordinator.

Do not edit Python, task JSON, task Markdown, or coordinator mappings. A planning
estimate is 2–3 hours per Topic (4–6 hours per curator); actual elapsed time must
be recorded.
