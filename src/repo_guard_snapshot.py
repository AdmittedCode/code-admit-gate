#!/usr/bin/env python3
"""
Repo Guard — Snapshot & Restore

Captures a recoverable checkpoint of a repository BEFORE any mutating operation
(repair, cleanup), so a user can verify or restore if something goes wrong.

Two capture modes:
  - manifest (always): paths + SHA-256 of every non-excluded file. Contains NO
    file contents, so it can never leak a secret. Detects and verifies damage.
  - archive (--archive): a .tar.gz enabling true restore.

Secret safety (non-negotiable): files matching the manifest's forbidden_patterns
are EXCLUDED from the archive and flagged in the manifest as
"excluded_forbidden", never stored. The matching logic is identical to the
validator's, so exclusion never diverges from what the guard blocks.

This protects the END USER. Snapshots live in the user's repo/CI only; nothing
is transmitted anywhere.

Usage:
  python repo_guard_snapshot.py --repo . --out .repo-guard/snap            # manifest only
  python repo_guard_snapshot.py --repo . --out .repo-guard/snap --archive  # + .tar.gz
  python repo_guard_snapshot.py --restore .repo-guard/snap.tar.gz --repo . --verify-only
  python repo_guard_snapshot.py --restore .repo-guard/snap.tar.gz --repo .
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tarfile
import datetime as _dt
from pathlib import Path
from typing import Dict, List, Any, Optional


MANIFEST_NAMES = ["repo-guard.json", "stegverse.architecture.json",
                  "architecture.json", ".architecture.json"]


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def load_forbidden(repo: Path, manifest_path: Optional[str]) -> List[str]:
    """Read forbidden_patterns from the repo's manifest (same source the guard uses)."""
    mpath = None
    if manifest_path:
        mpath = Path(manifest_path)
    else:
        for n in MANIFEST_NAMES:
            cand = repo / n
            if cand.is_file():
                mpath = cand
                break
    if not mpath or not mpath.is_file():
        return []
    try:
        m = json.loads(mpath.read_text(encoding="utf-8"))
    except Exception:
        return []
    return (m.get("file_rules", {}) or {}).get("forbidden_patterns", []) or []


def is_forbidden(name: str, patterns: List[str]) -> bool:
    # Identical matching to repo_guard._check_forbidden_patterns: basename, IGNORECASE.
    return any(re.match(p, name, re.IGNORECASE) for p in patterns)


def iter_files(repo: Path):
    for root, dirs, files in os.walk(repo):
        # Skip dotdirs and the snapshot output dir, matching guard's walk behavior.
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            full = Path(root) / name
            rel = full.relative_to(repo)
            yield rel, full


def build_manifest(repo: Path, forbidden: List[str]) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    excluded: List[str] = []
    for rel, full in iter_files(repo):
        rel_posix = rel.as_posix()  # OS-neutral path
        if is_forbidden(full.name, forbidden):
            excluded.append(rel_posix)
            entries.append({"path": rel_posix, "status": "excluded_forbidden"})
            continue
        try:
            digest = sha256_bytes(full.read_bytes())
        except Exception as e:
            entries.append({"path": rel_posix, "status": f"unreadable:{e.__class__.__name__}"})
            continue
        entries.append({"path": rel_posix, "status": "captured", "sha256": digest,
                        "size": full.stat().st_size})
    entries.sort(key=lambda e: e["path"])  # deterministic ordering
    manifest = {
        "schema": {"name": "repo_guard.snapshot_manifest", "version": "0.1.0"},
        "created_at": now_iso(),
        "repo": str(repo),
        "file_count": sum(1 for e in entries if e.get("status") == "captured"),
        "excluded_forbidden_count": len(excluded),
        "entries": entries,
    }
    return manifest


def write_archive(repo: Path, manifest: Dict[str, Any], archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    captured = {e["path"] for e in manifest["entries"] if e.get("status") == "captured"}
    with tarfile.open(archive_path, "w:gz") as tar:
        for rel, full in iter_files(repo):
            if rel.as_posix() in captured:
                tar.add(str(full), arcname=rel.as_posix())
        # store the manifest inside the archive for self-verification
        import io
        data = json.dumps(manifest, indent=2).encode("utf-8")
        info = tarfile.TarInfo(name="_repo-guard-manifest.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))


def do_snapshot(repo: Path, out: Path, archive: bool, manifest_path: Optional[str]) -> int:
    forbidden = load_forbidden(repo, manifest_path)
    manifest = build_manifest(repo, forbidden)
    out.parent.mkdir(parents=True, exist_ok=True)
    man_file = out.with_suffix(".manifest.json")
    man_file.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[snapshot] manifest: {man_file}  "
          f"({manifest['file_count']} files, {manifest['excluded_forbidden_count']} forbidden excluded)")
    if archive:
        arc = out.with_suffix(".tar.gz")
        write_archive(repo, manifest, arc)
        print(f"[snapshot] archive:  {arc}  (forbidden-pattern files NOT included)")
    return 0


def do_restore(archive_path: Path, repo: Path, verify_only: bool) -> int:
    if not archive_path.is_file():
        print(f"[restore] archive not found: {archive_path}", file=sys.stderr)
        return 1
    with tarfile.open(archive_path, "r:gz") as tar:
        names = tar.getnames()
        manifest = None
        if "_repo-guard-manifest.json" in names:
            manifest = json.loads(tar.extractfile("_repo-guard-manifest.json").read().decode("utf-8"))

        if verify_only:
            mismatched, missing, ok = [], [], 0
            by_path = {e["path"]: e for e in (manifest or {}).get("entries", [])
                       if e.get("status") == "captured"}
            for path, e in by_path.items():
                cur = repo / path
                if not cur.is_file():
                    missing.append(path)
                    continue
                if sha256_bytes(cur.read_bytes()) == e.get("sha256"):
                    ok += 1
                else:
                    mismatched.append(path)
            print(f"[verify] ok={ok} mismatched={len(mismatched)} missing={len(missing)}")
            for p in mismatched[:20]:
                print(f"  ~ changed: {p}")
            for p in missing[:20]:
                print(f"  - missing: {p}")
            return 0 if not mismatched and not missing else 2

        # actual restore: extract everything except the embedded manifest
        members = [m for m in tar.getmembers() if m.name != "_repo-guard-manifest.json"]
        # path-traversal guard
        for m in members:
            target = (repo / m.name).resolve()
            if not str(target).startswith(str(repo.resolve())):
                print(f"[restore] refused unsafe path: {m.name}", file=sys.stderr)
                return 1
        tar.extractall(path=str(repo), members=members)
        print(f"[restore] restored {len(members)} files into {repo}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Repo Guard — snapshot & restore")
    ap.add_argument("--repo", default=".", help="Repository root")
    ap.add_argument("--out", default=".repo-guard/snapshot",
                    help="Output path stem (snapshot mode)")
    ap.add_argument("--archive", action="store_true",
                    help="Also write a .tar.gz (enables true restore; excludes forbidden files)")
    ap.add_argument("--manifest", default="", help="Explicit manifest path (else auto-discover)")
    ap.add_argument("--restore", default="", help="Path to a .tar.gz snapshot to restore")
    ap.add_argument("--verify-only", action="store_true",
                    help="With --restore: report drift vs snapshot, change nothing")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    if args.restore:
        return do_restore(Path(args.restore), repo, args.verify_only)
    return do_snapshot(repo, Path(args.out), args.archive, args.manifest or None)


if __name__ == "__main__":
    raise SystemExit(main())
