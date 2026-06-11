#!/usr/bin/env python3
"""
Repo Guard — Architecture Validator
Validates any repository's structure against a declared manifest (repo-guard.json).
Manifest-driven structural linting, forbidden-pattern blocking, and drift detection.
Vendor-neutral; no external dependencies (Python 3.8+ stdlib only).
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
import argparse


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
    manifest_path: str
    manifest_found: bool
    repo_id: Optional[str] = None
    repo_type: Optional[str] = None
    violations: List[Violation] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=lambda: {
        "errors": 0, "warnings": 0, "notices": 0, "total": 0
    })
    
    def add(self, violation: Violation):
        self.violations.append(violation)
        self.summary[violation.level + "s"] += 1
        self.summary["total"] += 1
    
    def to_json(self) -> str:
        return json.dumps({
            "repo_path": self.repo_path,
            "manifest_path": self.manifest_path,
            "manifest_found": self.manifest_found,
            "repo_id": self.repo_id,
            "repo_type": self.repo_type,
            "summary": self.summary,
            "violations": [asdict(v) for v in self.violations]
        }, indent=2)


class ArchitectureValidator:
    MANIFEST_NAMES = [
        "repo-guard.json",
        "stegverse.architecture.json",
        "architecture.json",
        ".architecture.json"
    ]
    
    def __init__(self, repo_path: str, manifest_path: Optional[str] = None):
        self.repo_path = Path(repo_path).resolve()
        self.manifest_path = self._discover_manifest(manifest_path)
        self.manifest: Dict[str, Any] = {}
        self.report: Optional[ValidationReport] = None
    
    def _discover_manifest(self, explicit_path: Optional[str]) -> Optional[Path]:
        if explicit_path:
            p = Path(explicit_path).resolve()
            return p if p.exists() else None
        
        for name in self.MANIFEST_NAMES:
            p = self.repo_path / name
            if p.exists():
                return p
        return None
    
    def validate(self) -> ValidationReport:
        self.report = ValidationReport(
            repo_path=str(self.repo_path),
            manifest_path=str(self.manifest_path) if self.manifest_path else None,
            manifest_found=False
        )
        
        if not self.manifest_path:
            self.report.add(Violation(
                level="notice",
                category="missing",
                path=str(self.repo_path),
                message="No architecture manifest found. Guard is dormant.",
                suggestion="Create repo-guard.json to activate validation."
            ))
            return self.report
        
        if not self._load_manifest():
            return self.report
        
        self.report.manifest_found = True
        self.report.repo_id = self.manifest.get("repo_id")
        self.report.repo_type = self.manifest.get("repo_type")
        
        self._validate_structure()
        self._find_stray_files()
        self._check_naming_conventions()
        self._check_forbidden_patterns()
        
        return self.report
    
    def _load_manifest(self) -> bool:
        try:
            with open(self.manifest_path, 'r') as f:
                self.manifest = json.load(f)
            return True
        except json.JSONDecodeError as e:
            self.report.add(Violation(
                level="error",
                category="syntax",
                path=str(self.manifest_path),
                message=f"Invalid JSON in manifest: {e}",
                suggestion="Fix JSON syntax errors."
            ))
            return False
    
    def _validate_structure(self):
        expected = self.manifest.get("expected_structure", {})
        for expected_path, rules in expected.items():
            full_path = self.repo_path / expected_path
            required = rules.get("required", False)
            
            if required and not full_path.exists():
                self.report.add(Violation(
                    level="error",
                    category="missing",
                    path=expected_path,
                    message=f"Required path missing: {expected_path}",
                    suggestion=f"Create {expected_path} or set required: false."
                ))
            
            if full_path.exists() and "subdirs" in rules:
                for subdir, subrules in rules["subdirs"].items():
                    sub_path = full_path / subdir
                    if subrules.get("required", False) and not sub_path.exists():
                        self.report.add(Violation(
                            level="error",
                            category="missing",
                            path=f"{expected_path}/{subdir}",
                            message=f"Required subdirectory missing: {expected_path}/{subdir}"
                        ))
    
    def _find_stray_files(self):
        expected = self.manifest.get("expected_structure", {})
        expected_paths = set(expected.keys())
        
        # Build allowed prefixes
        allowed_prefixes = set()
        for ep in expected_paths:
            allowed_prefixes.add(ep)
            if not any(ep.endswith(ext) for ext in ['.py', '.md', '.json', '.txt', '.toml', '.yml', '.yaml']):
                allowed_prefixes.add(ep.rstrip('/') + '/')
        
        # Always allow these
        allowed_prefixes.update([
            '.git/', '.github/', 'review_needed/', 'legacy/',
            '__pycache__/', '.pytest_cache/', '.venv/', 'venv/',
            'repo-guard.json', 'stegverse.architecture.json', 'architecture.json'
        ])
        
        for root, dirs, files in os.walk(self.repo_path):
            rel_root = Path(root).relative_to(self.repo_path)
            
            # Skip hidden and system dirs
            dirs[:] = [d for d in dirs if not d.startswith('.') 
                       and d not in ('review_needed', 'legacy', '__pycache__', 
                                     'node_modules', '.venv', 'venv')]
            
            for file in files:
                if file.startswith('.'):
                    continue
                
                file_rel = str(rel_root / file) if str(rel_root) != '.' else file
                
                is_allowed = any(
                    file_rel == allowed or file_rel.startswith(allowed.rstrip('/') + '/')
                    for allowed in allowed_prefixes
                )
                
                if not is_allowed:
                    self.report.add(Violation(
                        level="warning",
                        category="stray",
                        path=file_rel,
                        message=f"File not in expected structure: {file_rel}",
                        suggestion="Move to proper directory or add to manifest."
                    ))
    
    def _check_naming_conventions(self):
        syntax_patterns = self.manifest.get("migration_rules", {}).get("syntax_issue_patterns", [])
        
        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') 
                       and d not in ('review_needed', 'legacy', '__pycache__')]
            
            for name in files + dirs:
                for pattern in syntax_patterns:
                    if re.match(pattern, name):
                        rel_path = str(Path(root).relative_to(self.repo_path) / name)
                        self.report.add(Violation(
                            level="warning",
                            category="syntax",
                            path=rel_path,
                            message=f"Syntax issue in name: {name}",
                            suggestion="Use only a-z, 0-9, _, -, . in file names."
                        ))
    
    def _check_forbidden_patterns(self):
        forbidden = self.manifest.get("file_rules", {}).get("forbidden_patterns", [])
        
        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            for name in files:
                for pattern in forbidden:
                    if re.match(pattern, name, re.IGNORECASE):
                        rel_path = str(Path(root).relative_to(self.repo_path) / name)
                        self.report.add(Violation(
                            level="error",
                            category="forbidden",
                            path=rel_path,
                            message=f"Forbidden pattern matched: {name}",
                            suggestion="Rename file to remove forbidden pattern."
                        ))


def main():
    parser = argparse.ArgumentParser(description="Repo Guard — manifest-driven architecture validator")
    parser.add_argument("--repo", default=".", help="Path to repository root")
    parser.add_argument("--manifest", help="Explicit path to manifest (auto-discovered if omitted)")
    parser.add_argument("--output", default="architecture-report.json", help="Output report file")
    parser.add_argument("--fail-on-drift", action="store_true", help="Exit error if violations found")
    parser.add_argument("--format", choices=["json", "pretty"], default="pretty", help="Output format")
    
    args = parser.parse_args()
    
    validator = ArchitectureValidator(args.repo, args.manifest)
    report = validator.validate()
    
    # Output
    if args.format == "json":
        print(report.to_json())
    else:
        print(f"\n{'='*60}")
        print(f"Repo Guard")
        print(f"{'='*60}")
        print(f"Repo: {report.repo_path}")
        print(f"Manifest: {report.manifest_path or 'NOT FOUND'}")
        print(f"Status: {'ACTIVE' if report.manifest_found else 'DORMANT'}")
        if report.repo_id:
            print(f"Repo ID: {report.repo_id} ({report.repo_type})")
        print(f"Violations: {report.summary['errors']} errors, "
              f"{report.summary['warnings']} warnings, "
              f"{report.summary['notices']} notices")
        print(f"{'='*60}")
        
        if report.violations:
            for v in report.violations:
                icon = "🔴" if v.level == "error" else "🟡" if v.level == "warning" else "🔵"
                print(f"\n{icon} [{v.level.upper()}] {v.category}: {v.path}")
                print(f"   {v.message}")
                if v.suggestion:
                    print(f"   💡 {v.suggestion}")
    
    # Write report
    with open(args.output, 'w') as f:
        f.write(report.to_json())
    
    if args.fail_on_drift and report.summary["errors"] > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
