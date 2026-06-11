# Changelog

## v1.0.0
- Initial release.
- Manifest-driven architecture validation (`repo_guard.py`).
- Forbidden-pattern blocking (secrets, keys, .env) that fails the CI gate.
- Structural drift detection and repair-plan generation (`repo_guard_repair.py`).
- Snapshot & restore safety net with secret-exclusion (`repo_guard_snapshot.py`).
- GitHub Action (composite) for one-line CI integration.
