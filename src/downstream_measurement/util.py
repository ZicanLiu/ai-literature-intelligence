"""Shared IO helpers: hashing, atomic writes, absolute-path guard."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

# Path-fragment patterns are assembled from concatenated pieces so that this
# source file itself never contains a literal personal path sample.
_WINDOWS_DRIVE = re.compile("^[A-Za-z][:][\\\\/]")
_HOME_FRAGMENT = re.compile("|".join([
    "/" + "Users" + "/",
    "\\\\" + "Users" + "\\",
    "/" + "home" + "/",
]))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path):
    raw = Path(path).read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return json.loads(raw.decode("utf-8"))


def canonical_json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def ensure_dir(path: Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Publish via temp file + replace so readers never see partial output."""
    path = Path(path)
    ensure_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, str(path))
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def jsonable(obj):
    """Recursively convert Fractions to exact 'num/den' strings for JSON output."""
    from fractions import Fraction

    if isinstance(obj, Fraction):
        return f"{obj.numerator}/{obj.denominator}" if obj.denominator != 1 else str(obj.numerator)
    if isinstance(obj, dict):
        return {key: jsonable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(value) for value in obj]
    return obj


def atomic_write_json(path: Path, obj) -> None:
    atomic_write_bytes(path, json.dumps(jsonable(obj), ensure_ascii=False, indent=2).encode("utf-8") + b"\n")


def write_csv(path: Path, header, rows) -> None:
    import csv
    import io

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(header), extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        clean = {}
        for key in header:
            value = row.get(key)
            if isinstance(value, (dict, list, tuple, bool)):
                clean[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
            elif value is None:
                clean[key] = ""
            else:
                clean[key] = value
        writer.writerow(clean)
    atomic_write_text(path, buffer.getvalue())


def find_absolute_path_leaks(obj, path="$"):
    """Recursively collect locations of strings that look like absolute user paths."""
    leaks = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            leaks.extend(find_absolute_path_leaks(value, f"{path}.{key}"))
    elif isinstance(obj, (list, tuple)):
        for index, value in enumerate(obj):
            leaks.extend(find_absolute_path_leaks(value, f"{path}[{index}]"))
    elif isinstance(obj, str):
        if _WINDOWS_DRIVE.match(obj) or _HOME_FRAGMENT.search(obj):
            leaks.append({"path": path, "value": obj[:60]})
    return leaks


def assert_no_absolute_paths(obj, label: str) -> None:
    leaks = find_absolute_path_leaks(obj)
    if leaks:
        raise AssertionError(f"absolute user path leaked into persisted artifact {label}: {leaks[:3]}")


def prepare_staging_target(target: Path) -> Path:
    """Atomic bundle publication step 1: refuse existing target, fresh staging.

    The final output directory either does not exist (this run creates a
    sibling `*.staging` directory and only renames it into place after full
    success) or the run fails closed — never mixed writes into stale output.
    """
    import shutil

    target = Path(target).resolve()
    if target.exists():
        raise FileExistsError(f"output target already exists; refusing to mix writes: {target}")
    staging = target.with_name(target.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    return staging


def publish_staging(staging: Path, target: Path) -> None:
    """Atomic bundle publication step 2: rename staging into the final target."""
    staging = Path(staging)
    target = Path(target)
    if not staging.is_dir():
        raise FileNotFoundError(f"staging directory missing: {staging}")
    os.replace(staging, target)


def mark_staging_partial(staging: Path, message: str) -> None:
    """Leave an explicit diagnostic marker on a failed staging directory."""
    staging = Path(staging)
    (staging / "_PARTIAL_FAILED.txt").write_text(message + "\n", encoding="utf-8")


def is_subpath(child: Path, parent: Path) -> bool:
    child = Path(child).resolve()
    parent = Path(parent).resolve()
    return child == parent or parent in child.parents


def safe_output_dir(output_dir: Path, evidence_roots) -> Path:
    """Refuse output directories inside any read-only evidence root."""
    output_dir = Path(output_dir).resolve()
    for root in evidence_roots:
        root = Path(root).resolve()
        if not root.exists():
            continue
        if is_subpath(output_dir, root):
            raise ValueError(f"output directory {output_dir} must not be inside read-only evidence root {root}")
        if is_subpath(root, output_dir):
            raise ValueError(f"evidence root {root} must not be nested inside output directory {output_dir}")
    return output_dir
