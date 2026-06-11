#!/usr/bin/env python3
"""
Repo Guard — Snapshot & Restore

Captures a recoverable checkpoint before a repair or cleanup operation.

Two capture modes:
- manifest: paths + SHA-256 for non-excluded files; no file contents.
- archive: restorable tar.gz containing only non-forbidden regular files.

Secret safety:
Files matching manifest forbidden_patterns are never archived. They are recorded
only as excluded_forbidden entries.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import io
import json
import os
import re
import sys
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Optional


MANIFEST_NAMES = [
    "repo-guard.json",
    "stegverse.architecture.json",
    "architecture.json",
    ".architecture.json",
]


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def load_forbidden(repo: Path, manifest_path: Optional[str]) -> List[str]:
    manifest_file: Optional[Path] = None
    if manifest_path:
        manifest_file = Path(manifest_path)
        if not manifest_file.is_absolute():
            manifest_file = repo / manifest_file
    else:
        for name in MANIFEST_NAMES:
            candidate = repo / name
            if candidate.is_file():
                manifest_file = candidate
                break

    if not manifest_file or not manifest_file.is_file():
        return []

    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except Exception:
        return []

    return (manifest.get("file_rules", {}) or {}).get("forbidden_patterns", []) or []


def is_forbidden(name: str, patterns: List[str]) -> bool:
    return any(re.match(pattern, name, re.IGNORECASE) for pattern in patterns)


def iter_files(repo: Path):
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            full = Path(root) / name
            if not full.is_file():
                continue
            rel = full.relative_to(repo)
            yield rel, full


def build_manifest(repo: Path, forbidden: List[str]) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    excluded: List[str] = []

    for rel, full in iter_files(repo):
        rel_posix = rel.as_posix()
        if is_forbidden(full.name, forbidden):
            excluded.append(rel_posix)
            entries.append({"path": rel_posix, "status": "excluded_forbidden"})
            continue

        try:
            data = full.read_bytes()
            entries.append({
                "path": rel_posix,
                "status": "captured",
                "sha256": sha256_bytes(data),
                "size": len(data),
            })
        except Exception as e:
            entries.append({"path": rel_posix, "status": f"unreadable:{e.__class__.__name__}"})

    entries.sort(key=lambda entry: entry["path"])
    return {
        "schema": "repo_guard.snapshot_manifest.v1",
        "created_at": now_iso(),
        "repo": str(repo),
        "file_count": sum(1 for entry in entries if entry.get("status") == "captured"),
        "excluded_forbidden_count": len(excluded),
        "entries": entries,
    }


def write_archive(repo: Path, manifest: Dict[str, Any], archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    captured = {entry["path"] for entry in manifest["entries"] if entry.get("status") == "captured"}

    with tarfile.open(archive_path, "w:gz") as tar:
        for rel, full in iter_files(repo):
            rel_posix = rel.as_posix()
            if rel_posix in captured:
                tar.add(str(full), arcname=rel_posix, recursive=False)

        data = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
        info = tarfile.TarInfo(name="_repo-guard-manifest.json")
        info.size = len(data)
        info.mtime = 0
        tar.addfile(info, io.BytesIO(data))


def is_safe_member(repo: Path, member: tarfile.TarInfo) -> bool:
    if member.name == "_repo-guard-manifest.json":
        return False
    if member.islnk() or member.issym() or member.isdev():
        return False
    target = (repo / member.name).resolve()
    try:
        target.relative_to(repo.resolve())
    except ValueError:
        return False
    return member.isfile() or member.isdir()


def do_snapshot(repo: Path, out: Path, archive: bool, manifest_path: Optional[str]) -> int:
    forbidden = load_forbidden(repo, manifest_path)
    manifest = build_manifest(repo, forbidden)
    out.parent.mkdir(parents=True, exist_ok=True)

    manifest_file = out.with_suffix(".manifest.json")
    manifest_file.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"[snapshot] manifest: {manifest_file} "
        f"({manifest['file_count']} files, {manifest['excluded_forbidden_count']} forbidden excluded)"
    )

    if archive:
        archive_file = out.with_suffix(".tar.gz")
        write_archive(repo, manifest, archive_file)
        print(f"[snapshot] archive: {archive_file} (forbidden-pattern files NOT included)")

    return 0


def do_restore(archive_path: Path, repo: Path, verify_only: bool) -> int:
    if not archive_path.is_file():
        print(f"[restore] archive not found: {archive_path}", file=sys.stderr)
        return 1

    repo = repo.resolve()
    with tarfile.open(archive_path, "r:gz") as tar:
        names = tar.getnames()
        manifest = None
        if "_repo-guard-manifest.json" in names:
            manifest_member = tar.extractfile("_repo-guard-manifest.json")
            if manifest_member:
                manifest = json.loads(manifest_member.read().decode("utf-8"))

        if verify_only:
            by_path = {
                entry["path"]: entry
                for entry in (manifest or {}).get("entries", [])
                if entry.get("status") == "captured"
            }
            mismatched, missing, ok = [], [], 0
            for path, entry in by_path.items():
                current = repo / path
                if not current.is_file():
                    missing.append(path)
                    continue
                if sha256_bytes(current.read_bytes()) == entry.get("sha256"):
                    ok += 1
                else:
                    mismatched.append(path)

            print(f"[verify] ok={ok} mismatched={len(mismatched)} missing={len(missing)}")
            for path in mismatched[:20]:
                print(f"  ~ changed: {path}")
            for path in missing[:20]:
                print(f"  - missing: {path}")
            return 0 if not mismatched and not missing else 2

        members = [member for member in tar.getmembers() if is_safe_member(repo, member)]
        unsafe_count = len(tar.getmembers()) - len(members) - (1 if "_repo-guard-manifest.json" in names else 0)
        if unsafe_count:
            print(f"[restore] refused {unsafe_count} unsafe archive members", file=sys.stderr)
            return 1

        tar.extractall(path=str(repo), members=members)
        print(f"[restore] restored {len(members)} files into {repo}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Repo Guard — snapshot and restore")
    parser.add_argument("--repo", default=".", help="Repository root")
    parser.add_argument("--out", default=".repo-guard/snapshot", help="Output path stem for snapshot mode")
    parser.add_argument("--archive", action="store_true", help="Also write a tar.gz archive; forbidden files are excluded")
    parser.add_argument("--manifest", default="", help="Explicit manifest path; auto-discovered if omitted")
    parser.add_argument("--restore", default="", help="Path to a snapshot tar.gz to restore")
    parser.add_argument("--verify-only", action="store_true", help="With --restore: verify drift and change nothing")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if args.restore:
        return do_restore(Path(args.restore), repo, args.verify_only)
    return do_snapshot(repo, Path(args.out), args.archive, args.manifest or None)


if __name__ == "__main__":
    raise SystemExit(main())
