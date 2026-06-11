#!/usr/bin/env python3
"""
StegDB Architecture Repair
Generates repair plans from validation reports.
Repos can call this to auto-fix or suggest fixes for structural violations.
"""

import json
import shutil
from pathlib import Path
from typing import List, Dict
import argparse


class ArchitectureRepair:
    def __init__(self, report_path: str, repo_path: str, dry_run: bool = True):
        self.report = json.load(open(report_path))
        self.repo_path = Path(repo_path).resolve()
        self.dry_run = dry_run
        self.plan: List[Dict] = []
    
    def generate_plan(self) -> List[Dict]:
        migration = self.report.get("manifest", {}).get("migration_rules", {})
        review_dir = migration.get("review_needed_path", "review_needed/")
        legacy_dir = migration.get("legacy_path", "legacy/")
        
        for v in self.report.get("violations", []):
            if v["category"] == "stray":
                self.plan.append({
                    "action": "move",
                    "source": v["path"],
                    "destination": review_dir + Path(v["path"]).name,
                    "reason": v["message"],
                    "approved": False
                })
            elif v["category"] == "syntax":
                self.plan.append({
                    "action": "rename",
                    "source": v["path"],
                    "destination": review_dir + Path(v["path"]).name,
                    "reason": v["message"],
                    "approved": False
                })
            elif v["category"] == "missing" and v["level"] == "error":
                # Suggest creating missing directories
                if not v["path"].endswith(('.py', '.md', '.json')):
                    self.plan.append({
                        "action": "create",
                        "source": None,
                        "destination": v["path"],
                        "reason": v["message"],
                        "approved": False
                    })
        
        return self.plan
    
    def execute(self):
        for step in self.plan:
            if not step.get("approved"):
                print(f"⏭️  SKIPPED (not approved): {step['action']} {step.get('source', '')} → {step['destination']}")
                continue
            
            src = self.repo_path / step["source"] if step.get("source") else None
            dst = self.repo_path / step["destination"]
            
            if self.dry_run:
                print(f"🔍 DRY RUN: {step['action']} {step.get('source', '')} → {step['destination']}")
                continue
            
            dst.parent.mkdir(parents=True, exist_ok=True)
            
            if step["action"] == "move" and src.exists():
                shutil.move(str(src), str(dst))
                print(f"✅ MOVED: {src} → {dst}")
            elif step["action"] == "create":
                dst.mkdir(parents=True, exist_ok=True)
                print(f"✅ CREATED: {dst}")
    
    def save_plan(self, path: str):
        with open(path, 'w') as f:
            json.dump({
                "repo": str(self.repo_path),
                "dry_run": self.dry_run,
                "steps": self.plan
            }, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="StegDB Architecture Repair")
    parser.add_argument("--report", required=True, help="Path to architecture-report.json")
    parser.add_argument("--repo", default=".", help="Path to repo root")
    parser.add_argument("--plan-only", action="store_true", help="Generate plan only, don't execute")
    parser.add_argument("--approve-all", action="store_true", help="Auto-approve all steps")
    parser.add_argument("--output", default="repair-plan.json", help="Output plan file")
    
    args = parser.parse_args()
    
    repair = ArchitectureRepair(args.report, args.repo, dry_run=args.plan_only)
    plan = repair.generate_plan()
    
    if args.approve_all:
        for step in plan:
            step["approved"] = True
    
    repair.save_plan(args.output)
    print(f"📋 Repair plan saved to: {args.output}")
    print(f"   Steps: {len(plan)}")
    
    if not args.plan_only:
        repair.execute()


if __name__ == "__main__":
    main()
