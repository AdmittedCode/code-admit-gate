# Changelog

## v1.0.0
- Initial release.
- Manifest-driven architecture validation (`code_admit_gate.py`).
- Forbidden-pattern blocking (secrets, keys, .env) that fails the CI gate.
- Structural drift detection and repair-plan generation (`code_admit_gate_repair.py`).
- Snapshot & restore safety net with secret-exclusion (`code_admit_gate_snapshot.py`).
- GitHub Action (composite) for one-line CI integration.
