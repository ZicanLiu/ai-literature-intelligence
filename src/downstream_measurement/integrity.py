"""Phase B: independent SHA256 recomputation of evidence packages.

Verification levels:
- VERIFIED_BYTES: expected hash from a manifest/binding recomputed over the
  actual source bytes and matching.
- HASH_REFERENCE_ONLY: an expected hash is recorded somewhere but the source
  bytes were not read/verified in this run.
- MISSING_SOURCE_BYTES: referenced file does not exist.
- REPORT_ASSERTION_ONLY: a report claims a status without a usable hash entry.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from .inventory import resolve_package_directory
from .util import atomic_write_json, load_json, sha256_bytes, sha256_file, write_csv

HASH_REFERENCE_ONLY = "HASH_REFERENCE_ONLY"
MISSING_SOURCE_BYTES = "MISSING_SOURCE_BYTES"
REPORT_ASSERTION_ONLY = "REPORT_ASSERTION_ONLY"
VERIFIED_BYTES = "VERIFIED_BYTES"
SELF_HASHED_UNANCHORED = "SELF_HASHED_UNANCHORED"

# Known members of the meeting supplement (zip listing 2026-09-19). When the
# supplement is consumed as an extracted directory, only these files belong to
# the supplement package; other files in the same directory are NOT evidence.
# Known members of the meeting supplement (zip listing 2026-09-19). When the
# supplement is consumed as an extracted directory, only these files belong to
# the supplement package; other files in the same directory are NOT evidence.
SUPPLEMENT_MEMBER_NAMES = (
    "PRO_FULL_BLIND_AUDIT_144.json",
    "PRO_FULL_BLIND_AUDIT_REPORT.md",
    "README.md",
    "SRTP_Measurement_Validity_Audit_20260918.md",
    "SRTP_Measurement_Validity_Audit_20260918.html",
    "component_decomposition_all_grains.csv",
    "metric_contrasts_all_grains.csv",
    "high_leverage_case_atlas.csv",
    "SRTP_Novelty_Closest_Work_Matrix_20260918.csv",
    "SRTP_Novelty_Closest_Work_Matrix_20260918.xlsx",
    "SRTP_Novelty_Search_and_Input_Audit_20260918.md",
    "synthetic_stress_blueprint_40.csv",
)
MISSING_UNANCHORED_SUPPLEMENT_MEMBER = "MISSING_UNANCHORED_SUPPLEMENT_MEMBER"
DUPLICATE_MEMBER_BASENAME = "DUPLICATE_MEMBER_BASENAME"


class IntegrityError(AssertionError):
    """Raised when a formal-chain byte verification fails (fail closed)."""


def parse_sha_manifest(path: Path) -> dict[str, str]:
    text = Path(path).read_bytes().decode("utf-8-sig")
    entries = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, rel = line.split(None, 1)
        entries[rel.strip().replace("\\", "/")] = digest
    return entries


# Byte mismatches that the project itself has already discovered, classified
# and independently verified. Each exception is re-verified here against the
# cited in-project check files before it may soften the fail-closed rule; the
# row keeps an honest BYTES_MISMATCH-based level either way.
DOCUMENTED_EXCEPTIONS = [
    {
        "package": "mca_human_aggregation",
        "file": "adjudication/reviewer_R3/submission_template.csv",
        "classification": "PREEXISTING_UNUSED_BLANK_TEMPLATE_LINE_ENDINGS_ONLY",
        "evidence_files": [
            "MCA_V1_FINAL_20260906/checks/upstream_integrity_report.json",
            "MCA_V1_FINAL_20260906/checks/independent_final_verification.json",
        ],
    },
]


def _is_blank_template(package_dir: Path, rel: str) -> bool:
    """A blank CSV template: header plus rows whose non-ID fields are all empty."""
    target = package_dir / rel
    if not target.is_file():
        return False
    try:
        text = target.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return False
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    return all(line.count(",") >= 5 and line.split(",", 1)[1].strip(",") == "" for line in lines[1:])


def verify_documented_exception(evidence_root: Path, exception: dict, mismatch_row: dict) -> dict | None:
    """Confirm a documented exception against the project's own check files."""
    final_dir = resolve_package_directory(evidence_root, "mca_final")
    final_report = final_dir / "checks" / "upstream_integrity_report.json"
    verification = final_dir / "checks" / "independent_final_verification.json"
    if not final_report.is_file() or not verification.is_file():
        return None
    report = load_json(final_report)
    verified_doc = load_json(verification)
    candidates = []
    reports = report if isinstance(report, list) else [report]
    for package_report in reports:
        if isinstance(package_report, dict):
            candidates.extend(package_report.get("exceptions", []))
            candidates.extend(package_report.get("mismatches", []))
    classified = None
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("path") == exception["file"]:
            classified = candidate
            break
    if classified is None or classified.get("classification") != exception["classification"]:
        return None
    if not verified_doc.get("upstream_blank_template_line_ending_exception_verified", False):
        return None
    if not _is_blank_template(resolve_package_directory(evidence_root, "mca_human_aggregation"), exception["file"]):
        return None
    return {
        "classification": exception["classification"],
        "evidence_files": exception["evidence_files"],
        "expected_sha256": mismatch_row["expected_sha256"],
        "actual_sha256": mismatch_row["actual_sha256"],
        "cells_unchanged_per_upstream_report": bool(classified.get("cells_unchanged", False)),
        "blank_template_reverified_here": True,
    }


def verify_package(package_dir: Path, package_id: str) -> dict:
    """Recompute every manifest entry of one package."""
    package_dir = Path(package_dir)
    manifest_path = package_dir / "SHA256_manifest.txt"
    if not manifest_path.exists():
        return {
            "package_id": package_id,
            "has_manifest": False,
            "rows": [],
            "summary": {"verified": 0, "mismatched": 0, "missing": 0, "total": 0},
            "manifest_sha256": None,
        }
    manifest = parse_sha_manifest(manifest_path)
    rows = []
    counts = {"verified": 0, "mismatched": 0, "missing": 0}
    for rel in sorted(manifest):
        expected = manifest[rel]
        target = package_dir / rel
        if not target.is_file():
            level = MISSING_SOURCE_BYTES
            actual = None
            counts["missing"] += 1
        else:
            actual = sha256_file(target)
            if actual == expected:
                level = VERIFIED_BYTES
                counts["verified"] += 1
            else:
                level = "BYTES_MISMATCH"
                counts["mismatched"] += 1
        rows.append(
            {
                "package": package_id,
                "file": rel,
                "expected_sha256": expected,
                "actual_sha256": actual or "",
                "match": actual == expected if actual else False,
                "source_of_expected_hash": "package SHA256_manifest.txt",
                "verification_level": level,
            }
        )
    return {
        "package_id": package_id,
        "has_manifest": True,
        "rows": rows,
        "summary": {**counts, "total": len(manifest)},
        "manifest_sha256": sha256_file(manifest_path),
    }


def verify_zip_package(supplement_path: Path, package_id: str) -> dict:
    """Digest supplement payloads against the EXPECTED member roster.

    - present member: SELF_HASHED_UNANCHORED (bytes read + identity hash; no
      previously frozen expected digest exists to match).
    - expected member absent: MISSING_UNANCHORED_SUPPLEMENT_MEMBER (visible in
      the integrity report; supplement is sensitivity-only so this does not
      block the primary chain, but it is never hidden).
    - duplicate expected basename inside a zip: DUPLICATE_MEMBER_BASENAME
      (never silently pick one).
    Package identity: no SHA256 manifest exists, so manifest_sha256 is null
    and package_identity_sha256 records the self-computed digest.
    """
    supplement_path = Path(supplement_path)
    rows = []
    present: dict[str, bytes] = {}
    identity_kind = None
    if supplement_path.is_dir():
        identity_kind = "SELF_HASHED_MEMBER_SET"
        for name in SUPPLEMENT_MEMBER_NAMES:
            target = supplement_path / name
            if target.is_file():
                present[name] = target.read_bytes()
        composite = "|".join(
            hashlib.sha256(present[name]).hexdigest() for name in SUPPLEMENT_MEMBER_NAMES if name in present
        ).encode("ascii")
        package_identity = sha256_bytes(composite) if present else None
    else:
        identity_kind = "SELF_HASHED_ZIP"
        with zipfile.ZipFile(supplement_path) as archive:
            by_basename: dict[str, list[str]] = {}
            for info in archive.infolist():
                if not info.is_dir():
                    by_basename.setdefault(Path(info.filename).name, []).append(info.filename)
            for name in SUPPLEMENT_MEMBER_NAMES:
                members = by_basename.get(name, [])
                if len(members) > 1:
                    rows.append({
                        "package": package_id, "file": name,
                        "expected_sha256": "", "actual_sha256": "", "match": False,
                        "source_of_expected_hash": f"expected member roster; {len(members)} zip entries share this basename",
                        "verification_level": DUPLICATE_MEMBER_BASENAME,
                    })
                elif len(members) == 1:
                    present[name] = archive.read(members[0])
        package_identity = sha256_file(supplement_path)
    counts = {"verified": 0, "mismatched": 0, "missing": 0,
              "self_hashed_unanchored": 0,
              "missing_unanchored_supplement_members": 0,
              "duplicate_member_basenames": 0}
    for name in SUPPLEMENT_MEMBER_NAMES:
        if name in present:
            rows.append({
                "package": package_id, "file": name,
                "expected_sha256": "", "actual_sha256": sha256_bytes(present[name]),
                "match": "", "source_of_expected_hash": "member roster; self-computed digest, no upstream anchor",
                "verification_level": SELF_HASHED_UNANCHORED,
            })
            counts["self_hashed_unanchored"] += 1
        elif not any(row["file"] == name and row["verification_level"] == DUPLICATE_MEMBER_BASENAME for row in rows):
            rows.append({
                "package": package_id, "file": name,
                "expected_sha256": "", "actual_sha256": "", "match": False,
                "source_of_expected_hash": "expected member roster (2026-09-19 supplement zip listing)",
                "verification_level": MISSING_UNANCHORED_SUPPLEMENT_MEMBER,
            })
            counts["missing_unanchored_supplement_members"] += 1
    counts["duplicate_member_basenames"] = sum(
        1 for row in rows if row["verification_level"] == DUPLICATE_MEMBER_BASENAME)
    summary = {"verified": 0, "mismatched": 0, "missing": 0, "total": len(SUPPLEMENT_MEMBER_NAMES), **counts}
    return {
        "package_id": package_id,
        "has_manifest": False,
        "identity_kind": identity_kind,
        "manifest_sha256": None,
        "package_identity_sha256": package_identity,
        "rows": rows,
        "summary": summary,
    }


def verify_binding_references(root: Path, bindings: list[dict]) -> list[dict]:
    """Verify selected cross-package hash references (expected from binding files).

    Each binding: {package_id, file(relative to evidence root), expected_sha256}.
    Missing file -> MISSING_SOURCE_BYTES; hash mismatch -> BYTES_MISMATCH.
    """
    rows = []
    for binding in bindings:
        target = Path(root) / binding["file"]
        expected = binding["expected_sha256"]
        if not target.is_file():
            actual, level, match = "", MISSING_SOURCE_BYTES, False
        else:
            actual = sha256_file(target)
            match = actual == expected
            level = VERIFIED_BYTES if match else "BYTES_MISMATCH"
        rows.append(
            {
                "package": binding["package_id"],
                "file": binding["file"],
                "expected_sha256": expected,
                "actual_sha256": actual,
                "match": match,
                "source_of_expected_hash": binding["source"],
                "verification_level": level,
            }
        )
    return rows


def build_integrity(evidence_root: Path, package_dirs: dict[str, str], supplement_zip: Path | None,
                    formal_chain_ids: set[str]) -> dict:
    results = {}
    for package_id, dir_name in sorted(package_dirs.items()):
        results[package_id] = verify_package(Path(evidence_root) / dir_name, package_id)
    if supplement_zip and Path(supplement_zip).exists():
        results["meeting_supplement_pro_full"] = verify_zip_package(Path(supplement_zip), "meeting_supplement_pro_full")
    all_rows = []
    mismatches = []
    missing = []
    for package_id, result in sorted(results.items()):
        all_rows.extend(result["rows"])
        for row in result["rows"]:
            if row["verification_level"] == "BYTES_MISMATCH":
                mismatches.append(row)
            elif row["verification_level"] == MISSING_SOURCE_BYTES:
                missing.append(row)
    documented = []
    for exception in DOCUMENTED_EXCEPTIONS:
        for row in mismatches:
            if row["package"] == exception["package"] and row["file"] == exception["file"]:
                confirmed = verify_documented_exception(evidence_root, exception, row)
                if confirmed is not None:
                    row["verification_level"] = "BYTES_MISMATCH_DOCUMENTED_EXCEPTION"
                    row["documented_exception"] = confirmed
                    documented.append({
                        "package": row["package"], "file": row["file"], **confirmed,
                    })
    formal_mismatches = [r for r in mismatches
                         if r["package"] in formal_chain_ids
                         and r["verification_level"] == "BYTES_MISMATCH"]
    formal_missing = [r for r in missing if r["package"] in formal_chain_ids]
    return {
        "schema_version": "1.0",
        "packages": {pid: {
            "identity_kind": (r.get("identity_kind")
                              or ("SHA256_MANIFEST" if r["has_manifest"] else "NONE")),
            "manifest_sha256": r["manifest_sha256"],
            "package_identity_sha256": r.get("package_identity_sha256"),
            "summary": r["summary"],
        } for pid, r in results.items()},
        "rows": all_rows,
        "counts": {
            "packages_verified": len(results),
            "files_verified": sum(1 for r in all_rows if r["verification_level"] == VERIFIED_BYTES),
            "self_hashed_unanchored": sum(1 for r in all_rows if r["verification_level"] == SELF_HASHED_UNANCHORED),
            "bytes_mismatch": len(mismatches),
            "missing_source_bytes": len(missing),
            "missing_unanchored_supplement_members": sum(
                1 for r in all_rows if r["verification_level"] == MISSING_UNANCHORED_SUPPLEMENT_MEMBER),
            "duplicate_member_basenames": sum(
                1 for r in all_rows if r["verification_level"] == DUPLICATE_MEMBER_BASENAME),
            "formal_chain_mismatch": len(formal_mismatches),
            "formal_chain_missing": len(formal_missing),
            "documented_exceptions_confirmed": len(documented),
        },
        "documented_exceptions": documented,
        "fail_closed": bool(formal_mismatches or formal_missing),
    }


def collect_missing_source_rows(integrity_rows: list[dict]) -> list[dict]:
    """Real missing-byte rows for manifest.known_missing_source_bytes (never hardcoded)."""
    return [
        {"package": row["package"], "file": row["file"], "verification_level": row["verification_level"]}
        for row in integrity_rows
        if row["verification_level"] in (MISSING_SOURCE_BYTES, MISSING_UNANCHORED_SUPPLEMENT_MEMBER)
    ]


def persist_integrity(integrity: dict, output_dir: Path) -> None:
    output_dir = Path(output_dir)
    (output_dir / "integrity").mkdir(parents=True, exist_ok=True)
    header = ["package", "file", "expected_sha256", "actual_sha256", "match",
              "source_of_expected_hash", "verification_level"]
    write_csv(output_dir / "integrity" / "evidence_integrity.csv", header, integrity["rows"])
    summary = {
        "schema_version": "1.1",
        "packages": {pid: info for pid, info in integrity["packages"].items()},
        "counts": integrity["counts"],
        "documented_exceptions": integrity.get("documented_exceptions", []),
        "fail_closed": integrity["fail_closed"],
    }
    atomic_write_json(output_dir / "integrity" / "integrity_summary.json", summary)


def load_integrity_summary(path: Path) -> dict:
    """Load an integrity summary written by persist_integrity (or legacy flat shape)."""
    data = json.loads(Path(path).read_bytes().decode("utf-8"))
    if "packages" in data and isinstance(data["packages"], dict):
        return data
    legacy_packages = {k: v for k, v in data.items() if k not in ("counts", "documented_exceptions", "fail_closed")}
    return {
        "schema_version": "legacy-flat",
        "packages": legacy_packages,
        "counts": data.get("counts", {}),
        "documented_exceptions": data.get("documented_exceptions", []),
        "fail_closed": data.get("fail_closed", False),
    }
