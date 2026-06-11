# Repo Guard

Manifest-driven architecture validation for any repository. Declare what your
repo's structure *should* be in one file; Repo Guard enforces it in CI — blocking
forbidden files (secrets, keys, env files), catching structural drift, and
generating repair plans. No dependencies, no service, no telemetry. Python 3.8+
stdlib only.

## Why

Repos rot. Files land in the wrong place, secrets get committed, structure
drifts from what the team agreed on, and nobody notices until it's a problem.
Most linters check *code*. Repo Guard checks *structure* — the layer above the
code that no existing tool governs well, especially across many repos.

## How it works

1. Add a `repo-guard.json` manifest to your repo root (see `examples/`).
2. Add the GitHub Action (or run the CLI in any CI).
3. On every push/PR, Repo Guard validates structure and **fails the build** if
   error-level violations are found (e.g. a committed secret).

If no manifest exists, the guard is **dormant** — it does nothing. Governance is
opt-in, per repo.

## Quick start (GitHub Action)

```yaml
- uses: your-org/repo-guard@v1
  with:
    fail-on-drift: true
```

## Quick start (CLI, any platform)

```bash
python src/repo_guard.py --repo . --fail-on-drift
```

## What it checks

| Check | Severity | Blocks build? |
|-------|----------|---------------|
| Required directories/files missing | error | yes |
| Forbidden patterns (secrets, keys, .env) | error | yes |
| Stray files outside declared structure | warning | no |
| Naming-convention drift | warning | no |

Error-level violations fail the build under `--fail-on-drift`. Warnings are
reported but don't block — they flag files a human should classify.

## Repair plans

When violations are found, generate a structured, approval-gated repair plan
(it never moves files without an approved plan):

```bash
python src/repo_guard.py --repo . --output report.json
python src/repo_guard_repair.py --report report.json --plan-only
```

## Manifest

See `examples/repo-guard.json` for a complete starter. The manifest declares
`expected_structure`, `file_rules.forbidden_patterns`, and optional
`migration_rules`. Legacy manifest names (`architecture.json`) are also
recognized for drop-in compatibility.

## Snapshot & restore (safety net)

Before any repair or cleanup, capture a recoverable checkpoint:

```bash
# manifest only (paths + hashes; contains no file contents)
python src/repo_guard_snapshot.py --repo . --out .repo-guard/snap

# manifest + restorable archive
python src/repo_guard_snapshot.py --repo . --out .repo-guard/snap --archive
```

Verify or restore later:

```bash
python src/repo_guard_snapshot.py --restore .repo-guard/snap.tar.gz --repo . --verify-only
python src/repo_guard_snapshot.py --restore .repo-guard/snap.tar.gz --repo .
```

**Secret safety:** files matching `forbidden_patterns` (secrets, keys, .env) are
**never** written to the archive — they're recorded in the manifest as
`excluded_forbidden` and nothing more. The snapshot can neither leak a secret
nor be misused to back one up.

**Scope (important):** restore brings back the non-secret files it captured. It
does **not** recreate excluded secret files, and is not a bit-for-bit full repo
reset. It's a safety net for accidental deletion or corruption of tracked
project files, not a backup system.

This protects you, the user. Snapshots stay in your repo/CI; nothing is
transmitted anywhere.

## What it is not

- Not a code linter (use ruff/eslint for that — Repo Guard governs structure).
- Not a secret *scanner* of file contents (it blocks secret-shaped *paths*;
  pair it with a content scanner for defense in depth).
- Not a hosted service. Everything runs in your CI; nothing leaves your repo.

## License

[Choose: MIT for the core to drive adoption; commercial license for the org
dashboard tier.]
