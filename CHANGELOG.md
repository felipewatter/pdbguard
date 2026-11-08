# Changelog

## [0.1.0] — 2026-11-08

- New offline import of Kubernetes Nodes, Pods and PodDisruptionBudgets JSON lists.
- Fail-closed preflight checks for stale/overlapping PDBs, unmanaged Pods, unsafe local storage and missing labels/budgets.
- Deterministic exact maximum-cardinality selection of simultaneous candidate node drains (up to 18 targets).
- Ready-node zone floor, node/PDB cost accounting and explicit blocked/deferred reasons.
- Human-readable, JSON and SARIF 2.1 reports.
- Bounded, strict JSON parser and untrusted-input regression suite.
- CI matrix for Python 3.10–3.13 on Linux, Windows and macOS; CI-gated release automation.
