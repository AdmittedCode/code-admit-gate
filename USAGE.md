# Code Admit Gate Usage Guide

**Project:** AdmittedCode / code-admit-gate  
**Role:** front-door governance gate  
**Purpose:** validate declared code actions before they enter coherency scanning, admissibility receipt generation, provider governance, replayability, and governed execution.

---

## 1. What This Repo Does

Code Admit Gate is the entry point of the AdmittedCode governance pipeline.

It asks:

```text
Is the repo action declared?
Is the action scope bounded?
Are required files present?
Are forbidden files excluded?
Is the action ready to be routed into coherency scanning?
Can the action produce downstream evidence?
```

It does not decide final policy.

It does not replace StegCore.

It does not emit the final admissibility receipt.

It decides whether a declared code action is structurally ready to enter the governed path.

---

## 2. Pipeline Position

```text
Code Admit Gate
↓
Coherency Scanner
↓
Admissibility Receipts
↓
Provider Harness
↓
Replayability
↓
governed execution
```

Canonical distinction:

```text
Code Admit Gate asks:
Can this declared code action enter the governed pipeline?

Coherency Scanner asks:
Is the repo’s governance posture coherent?

Admissibility Receipts prove:
What decision was made and what evidence was bound?

Provider Harness demonstrates:
External AI capability use under consent, budget, and receipt governance.
```

---

## 3. Quick Start

Install from repo root:

```bash
python -m pip install -e .
```

Run tests:

```bash
python -m pytest
```

Run a basic admission check:

```bash
code-admit-gate check \
  --repo . \
  --manifest examples/action-manifest.json \
  --out reports/admission-report.json
```

Expected result:

```text
status: PASS or FAIL_CLOSED
action_declared: true
forbidden_paths_detected: false
ready_for_coherency_scan: true
```

---

## 4. Example Action Manifest

```json
{
  "schema": "admittedcode.action_manifest.v1",
  "action_id": "demo-readme-update",
  "repo_role": "provider-harness",
  "declared_action": "update_readme_usage_section",
  "scope": {
    "allowed_paths": [
      "README.md",
      "docs/**",
      "examples/**",
      ".github/workflows/provider-harness-ci.yml"
    ],
    "forbidden_paths": [
      ".env",
      "secrets/**",
      "*.pem",
      "*.key",
      "__pycache__/**",
      "*.pyc"
    ]
  },
  "requires": {
    "coherency_scan": true,
    "admissibility_receipt": true,
    "provider_harness": false
  },
  "outputs": {
    "report": "reports/admission-report.json"
  }
}
```

Displayed without the leading dot:

```text
github/workflows/provider-harness-ci.yml
```

Actual path:

```text
.github/workflows/provider-harness-ci.yml
```

---

## 5. Denial Examples

Code Admit Gate should fail closed when:

```text
manifest missing
declared_action missing
allowed paths missing
forbidden path matched
compiled bytecode committed
secret-like file included
repo role unknown
downstream evidence path undeclared
```

Example forbidden artifact:

```text
src/provider_harness/__pycache__/core.cpython-312.pyc
```

Expected result:

```text
status: FAIL_CLOSED
ready_for_coherency_scan: false
reason: forbidden path matched
```

---

## 6. CI Usage

Suggested workflow path:

```text
.github/workflows/code-admit-gate-ci.yml
```

Displayed without the leading dot:

```text
github/workflows/code-admit-gate-ci.yml
```

CI should:

```text
install package
run tests
run admission check against examples/action-manifest.json
upload admission report
fail on forbidden files
```

---

## 7. What Success Looks Like

A useful public demo should show:

```text
1. Valid declared action passes.
2. Missing manifest fails closed.
3. Forbidden secret path fails closed.
4. Compiled Python bytecode fails closed.
5. Report is emitted.
6. Report can be consumed by Coherency Scanner.
```

---

## 8. Canonical Usage Claim

```text
Code Admit Gate prevents undeclared or structurally unsafe code actions from entering the AdmittedCode governance pipeline.
```

Final doctrine:

```text
Code is not merely committed.
Code is admitted.
