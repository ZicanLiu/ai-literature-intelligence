"""Downstream evidence registry and measurement audit infrastructure.

Independent reconstruction of the 2026-09-04 ~ 2026-09-19 downstream pilot
evidence chain: inventory -> byte integrity -> evidence DAG -> canonical
registry -> first-look reproduction -> measurement decomposition.

Design rules:
- external evidence roots are strictly read-only;
- persisted artifacts never contain absolute user paths;
- every derived row carries a source locator and hash provenance;
- hash drift or missing chain bytes fail closed instead of silently passing.
"""

TOOL_ID = "zcode-downstream-measurement"
TOOL_VERSION = "1.0.0"
