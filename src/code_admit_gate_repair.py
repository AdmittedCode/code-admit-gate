#!/usr/bin/env python3
"""
Code Admit Gate — Repair Planner

Generates approval-gated repair plans from Code Admit Gate validation reports.

Default posture:
- plan-only is safe and non-mutating;
- no step runs unless it is explicitly approved in a plan or --approve-all is used;
- destinations are constrained to remain inside the repository.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ArchitectureRepair:
    def __init__(self, report_path: str, repo_path: str, dry_run: bool = True):
        self.report_path = Path(report_path).resolve()
        self.report = json.loads(self.report_path.read_text(encoding="utf-8"))
        self.repo_path = Path(repo_path).resolve()
        self.dry_run = dry_run
        self.plan: List[Dict[str, Any]] = []

    def _migration_rules(self) -> Dict[str, Any]:
        manifest = self.report.get("manifest") or {}
        return manifest.get("migration_rules", {}) or {}

    def generate_plan(self) -> List[Dict[str, Any]]:
        migration = self._migration_rules()
        review_dir = migration.get("review_needed_path", "review_needed/")
        legacy_dir = migration.get("legacy_path", "legacy/")

        for violation in self.report.get("violations", []):
            category = violation.get("category")
            path = violation.get("path", "")
            level = violation.get("level", "")
            message = violation.get("message", "")

            if category == "stray":
                self.plan.append({
                    "action": "move",
                    "source": path,
                    "destination": str(Path(review_dir) / Path(path).name),
                    "reason": message,
                    "approved": False,
                })
            elif category == "syntax":
                self.plan.append({
                    "action": "move",
                    "source": path,
                    "destination": str(Path(review_dir) / Path(path).name),
                    "reason": message,
                    "approved": False,
                })
            elif category == "forbidden":
                self.plan.append({
                    "action": "move",
                    "source": path,
                    "destination": str(Path(legacy_dir) / Path(path).name),
                    "reason": message,
                    "approved": False,
                    "requires_human_review": True,
                })
            elif category == "missing" and level == "error":
                suffix = Path(path).suffix.lower()
                if not suffix:
                    self.plan.append({
                        "action": "create",
                        "source": None,
                        "destination": path,
                        "reason": message,
                        "approved": False,
                    })

        return self.plan

    def _resolve_inside_repo(self, rel_path: str) -> Path:
        target = (self.repo_path / rel_path).resolve()
        try:
            target.relative_to(self.repo_path)
        except ValueError as exc:
            raise ValueError(f"path escapes repo: {rel_path}") from exc
        return target

    def _avoid_collision(self, dst: Path) -> Path:
        if not dst.exists():
            return dst
        stem = dst.stem
        suffix = dst.suffix
        parent = dst.parent
        index = 1
        while True:
            candidate = parent / f"{stem}.{index}{suffix}"
            if not candidate.exists():
                return candidate
            index += 1

    def execute(self) -> None:
        for step in self.plan:
            action = step.get("action")
            source = step.get("source")
            destination = step.get("destination")

            if not step.get("approved"):
                print(f"SKIPPED (not approved): {action} {source or ''} -> {destination}")
                continue

            dst = self._resolve_inside_repo(destination)
            src = self._resolve_inside_repo(source) if source else None

            if self.dry_run:
                print(f"DRY RUN: {action} {source or ''} -> {destination}")
                continue

            dst.parent.mkdir(parents=True, exist_ok=True)

            if action == "move":
                if src is None or not src.exists():
                    print(f"SKIPPED missing source: {source}")
                    continue
                final_dst = self._avoid_collision(dst)
                shutil.move(str(src), str(final_dst))
                print(f"MOVED: {src} -> {final_dst}")
            elif action == "create":
                dst.mkdir(parents=True, exist_ok=True)
                print(f"CREATED: {dst}")
            else:
                print(f"SKIPPED unknown action: {action}")

    def save_plan(self, path: str) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({
            "schema": "code_admit_gate.repair_plan.v1",
            "created_at": now_iso(),
            "repo": str(self.repo_path),
            "source_report": str(self.report_path),
            "dry_run": self.dry_run,
            "steps": self.plan,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Code Admit Gate — repair planner")
    parser.add_argument("--report", required=True, help="Path to repo-guard report JSON")
    parser.add_argument("--repo", default=".", help="Path to repo root")
    parser.add_argument("--plan-only", action="store_true", help="Generate plan only; do not execute")
    parser.add_argument("--approve-all", action="store_true", help="Approve all generated steps")
    parser.add_argument("--output", default="repair-plan.json", help="Output plan file")

    args = parser.parse_args()

    repair = ArchitectureRepair(args.report, args.repo, dry_run=args.plan_only)
    plan = repair.generate_plan()

    if args.approve_all:
        for step in plan:
            step["approved"] = True

    repair.save_plan(args.output)
    print(f"Repair plan saved to: {args.output}")
    print(f"Steps: {len(plan)}")

    if not args.plan_only:
        repair.execute()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
