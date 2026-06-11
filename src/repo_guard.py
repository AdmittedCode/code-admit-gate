#!/usr/bin/env python3
"""
Repo Guard — Architecture Validator

Manifest-driven structural validation for repositories.

Repo Guard is opt-in:
- if no manifest is found, it reports DORMANT and does not fail;
- if a manifest is found, it validates expected structure, forbidden paths,
  naming drift, and stray files.

No third-party dependencies. Python 3.8+ stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


MANIFEST_NAMES = [
    "repo-guard.json",
    "stegverse.architecture.json",
    "architecture.json",
    ".architecture.json",
]


@dataclass
class Violation:
    level: str
    category: str
    path: str
    message: str
    suggestion: Optional[str] = None


@dataclass
class ValidationReport:
    repo_path: str
    manifest_path: Optional[str]
    manifest_found: bool
    repo_id: Optional[str] = None
    repo_type: Optional[str] = None
    manifest: Optional[Dict[str, Any]] = None
    violations: List[Violation] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=lambda: {
        "errors": 0,
        "warnings": 0,
        "notices": 0,
        "total": 0,
    })

    def add(self, violation: Violation) -> None:
        self.violations.append(violation)
        key = violation.level + "s"
        self.summary[key] = self.summary.get(key, 0) + 1
        self.summary["total"] = self.summary.get("total", 0) + 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "repo_guard.validation_report.v1",
            "repo_path": self.repo_path,
            "manifest_path": self.manifest_path,
            "manifest_found": self.manifest_found,
            "repo_id": self.repo_id,
            "repo_type": self.repo_type,
            "manifest": self.manifest,
            "summary": self.summary,
            "violations": [asdict(v) for v in self.violations],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


class ArchitectureValidator:
    def __init__(self, repo_path: str, manifest_path: Optional[str] = None):
        self.repo_path = Path(repo_path).resolve()
        self.manifest_path = self._discover_manifest(manifest_path)
        self.manifest: Dict[str, Any] = {}
        self.report: Optional[ValidationReport] = None

    def _discover_manifest(self, explicit_path: Optional[str]) -> Optional[Path]:
        if explicit_path:
            p = Path(explicit_path)
            if not p.is_absolute():
                p = self.repo_path / p
            p = p.resolve()
            return p if p.is_file() else None

        for name in MANIFEST_NAMES:
            p = self.repo_path / name
            if p.is_file():
                return p.resolve()
        return None

    def validate(self) -> ValidationReport:
        self.report = ValidationReport(
            repo_path=str(self.repo_path),
            manifest_path=str(self.manifest_path) if self.manifest_path else None,
            manifest_found=False,
        )

        if not self.manifest_path:
            self.report.add(Violation(
                level="notice",
                category="missing",
                path=str(self.repo_path),
                message="No architecture manifest found. Guard is dormant.",
                suggestion="Create repo-guard.json to activate validation.",
            ))
            return self.report

        if not self._load_manifest():
            return self.report

        self.report.manifest_found = True
        self.report.repo_id = self.manifest.get("repo_id")
        self.report.repo_type = self.manifest.get("repo_type")
        self.report.manifest = self.manifest

        self._validate_structure()
        self._find_stray_files()
        self._check_naming_conventions()
        self._check_forbidden_patterns()

        return self.report

    def _load_manifest(self) -> bool:
        assert self.report is not None
        try:
            self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return True
        except json.JSONDecodeError as e:
            self.report.add(Violation(
                level="error",
                category="syntax",
                path=str(self.manifest_path),
                message=f"Invalid JSON in manifest: {e}",
                suggestion="Fix JSON syntax errors.",
            ))
            return False
        except OSError as e:
            self.report.add(Violation(
                level="error",
                category="manifest",
                path=str(self.manifest_path),
                message=f"Unable to read manifest: {e}",
                suggestion="Verify path and permissions.",
            ))
            return False

    def _validate_structure(self) -> None:
        expected = self.manifest.get("expected_structure", {}) or {}
        for expected_path, rules in expected.items():
            full_path = self.repo_path / expected_path
            required = bool((rules or {}).get("required", False))

            if required and not full_path.exists():
                self.report.add(Violation(
                    level="error",
                    category="missing",
                    path=expected_path,
                    message=f"Required path missing: {expected_path}",
                    suggestion=f"Create {expected_path} or set required: false.",
                ))

            if full_path.exists() and isinstance(rules, dict) and "subdirs" in rules:
                for subdir, subrules in (rules.get("subdirs") or {}).items():
                    sub_path = full_path / subdir
                    if (subrules or {}).get("required", False) and not sub_path.exists():
                        self.report.add(Violation(
                            level="error",
                            category="missing",
                            path=f"{expected_path.rstrip('/')}/{subdir}",
                            message=f"Required subdirectory missing: {expected_path.rstrip('/')}/{subdir}",
                        ))

    def _allowed_prefixes(self) -> set:
        expected = self.manifest.get("expected_structure", {}) or {}
        allowed = set()

        for ep in expected:
            ep = str(ep)
            allowed.add(ep)
            suffix = Path(ep).suffix.lower()
            if not suffix:
                allowed.add(ep.rstrip("/") + "/")

        allowed.update({
            "repo-guard.json",
            "stegverse.architecture.json",
            "architecture.json",
            ".architecture.json",
            "review_needed/",
            "legacy/",
            "__pycache__/",
            ".pytest_cache/",
            ".venv/",
            "venv/",
            "node_modules/",
        })
        return allowed

    def _find_stray_files(self) -> None:
        allowed_prefixes = self._allowed_prefixes()

        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [
                d for d in dirs
                if d not in ("review_needed", "legacy", "__pycache__", "node_modules", ".venv", "venv")
                and not d.startswith(".")
            ]

            rel_root = Path(root).relative_to(self.repo_path)
            for name in files:
                if name.startswith("."):
                    continue

                rel = str(rel_root / name) if str(rel_root) != "." else name
                is_allowed = any(
                    rel == allowed.rstrip("/")
                    or rel.startswith(allowed.rstrip("/") + "/")
                    for allowed in allowed_prefixes
                )

                if not is_allowed:
                    self.report.add(Violation(
                        level="warning",
                        category="stray",
                        path=rel,
                        message=f"File not in expected structure: {rel}",
                        suggestion="Move to proper directory or add to manifest.",
                    ))

    def _check_naming_conventions(self) -> None:
        patterns = self.manifest.get("migration_rules", {}).get("syntax_issue_patterns", []) or []
        compiled = []
        for pattern in patterns:
            try:
                compiled.append(re.compile(pattern))
            except re.error as e:
                self.report.add(Violation(
                    level="error",
                    category="manifest",
                    path="migration_rules.syntax_issue_patterns",
                    message=f"Invalid regex {pattern!r}: {e}",
                    suggestion="Fix or remove the invalid regex.",
                ))

        if not compiled:
            return

        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [
                d for d in dirs
                if d not in ("review_needed", "legacy", "__pycache__", "node_modules", ".venv", "venv")
                and not d.startswith(".")
            ]

            for name in files + dirs:
                if any(pattern.match(name) for pattern in compiled):
                    rel = Path(root).relative_to(self.repo_path) / name
                    self.report.add(Violation(
                        level="warning",
                        category="syntax",
                        path=rel.as_posix(),
                        message=f"Syntax issue in name: {name}",
                        suggestion="Use only a-z, 0-9, _, -, . in file names.",
                    ))

    def _check_forbidden_patterns(self) -> None:
        patterns = self.manifest.get("file_rules", {}).get("forbidden_patterns", []) or []
        compiled = []
        for pattern in patterns:
            try:
                compiled.append(re.compile(pattern, re.IGNORECASE))
            except re.error as e:
                self.report.add(Violation(
                    level="error",
                    category="manifest",
                    path="file_rules.forbidden_patterns",
                    message=f"Invalid regex {pattern!r}: {e}",
                    suggestion="Fix or remove the invalid regex.",
                ))

        if not compiled:
            return

        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            rel_root = Path(root).relative_to(self.repo_path)

            for name in files:
                if any(pattern.match(name) for pattern in compiled):
                    rel = rel_root / name if str(rel_root) != "." else Path(name)
                    self.report.add(Violation(
                        level="error",
                        category="forbidden",
                        path=rel.as_posix(),
                        message=f"Forbidden pattern matched: {name}",
                        suggestion="Remove, rename, or move the file outside committed repo state.",
                    ))


def main() -> int:
    parser = argparse.ArgumentParser(description="Repo Guard — manifest-driven architecture validator")
    parser.add_argument("--repo", default=".", help="Path to repository root")
    parser.add_argument("--manifest", help="Explicit path to manifest; auto-discovered if omitted")
    parser.add_argument("--output", default="repo-guard-report.json", help="Output report file")
    parser.add_argument("--fail-on-drift", action="store_true", help="Exit with error if error-level violations are found")
    parser.add_argument("--format", choices=["json", "pretty"], default="pretty", help="Output format")

    args = parser.parse_args()

    validator = ArchitectureValidator(args.repo, args.manifest)
    report = validator.validate()

    if args.format == "json":
        print(report.to_json())
    else:
        print(f"\n{'=' * 60}")
        print("Repo Guard")
        print(f"{'=' * 60}")
        print(f"Repo: {report.repo_path}")
        print(f"Manifest: {report.manifest_path or 'NOT FOUND'}")
        print(f"Status: {'ACTIVE' if report.manifest_found else 'DORMANT'}")
        if report.repo_id:
            print(f"Repo ID: {report.repo_id} ({report.repo_type})")
        print(
            f"Violations: {report.summary.get('errors', 0)} errors, "
            f"{report.summary.get('warnings', 0)} warnings, "
            f"{report.summary.get('notices', 0)} notices"
        )
        print(f"{'=' * 60}")

        for v in report.violations:
            icon = "ERROR" if v.level == "error" else "WARN" if v.level == "warning" else "INFO"
            print(f"\n[{icon}] {v.category}: {v.path}")
            print(f"  {v.message}")
            if v.suggestion:
                print(f"  Suggestion: {v.suggestion}")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.to_json() + "\n", encoding="utf-8")

    if args.fail_on_drift and report.summary.get("errors", 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
