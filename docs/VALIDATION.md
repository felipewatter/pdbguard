# Validation log — PDBGuard 0.1.0

## Local checks — 2026-11-08

| Check | Result | Method |
|---|---|---|
| Unit and adversarial regression suite | PASS — 65 tests | `PYTHONPATH=src python -m unittest discover -s tests -q` |
| Independent Pytest execution | PASS — 65 tests | `PYTHONPATH=src python -m pytest -q tests` |
| Exact subset optimizer | PASS — 100 reproducible synthetic configurations | Compared to an independent brute-force subset enumerator in tests |
| Python syntax | PASS | `python -m compileall -q src tests` |
| Python wheel packaging | PASS | `python -m pip wheel --no-deps --no-build-isolation .` |
| Isolated wheel install and smoke | PASS | `pip install --target ...` followed by `python -m pdbguard --version` and `plan` |
| Kubernetes sample JSON import | PASS | `pdbguard import ...` and subsequent plan |
| SARIF export | PASS | `plan --format sarif`, JSON validation and selected node count |
| Workflow YAML | PASS | Parsed `.github/workflows/*.yml` with PyYAML local validator |
| Workflow Bash syntax | PASS | `bash -n` for embedded `run` steps |
| Remote GitHub Actions | NOT RUN YET | Requires a created GitHub repository and first push |
| GitHub Release | NOT PUBLISHED YET | Must follow successful remote CI on the release SHA |

Local validation does **not** establish correctness on all Kubernetes versions, real cluster integrations or all GitHub Action runner OS versions. The CI matrix must be observed after publication; never mark it passed on the basis of this document.

## Release rules

1. The code committed to public `main` must match the reviewed distribution files.
2. GitHub CI must succeed across its 12 OS/Python combinations for that commit.
3. Only then may the CI-triggered bootstrap workflow publish `v0.1.0` with ZIP, wheel and `SHA256SUMS` assets.
4. Independently confirm release tag SHA, files and checksums on GitHub.
