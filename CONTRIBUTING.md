# Contributing

We welcome security-first bug fixes, tests, docs, reproducible examples and conservative policy improvements.

1. Open an issue with a synthetic reproducer and expected behavior (do **not** upload real cluster snapshots).
2. Work on a topic branch. Keep v0.1 runtime dependency-free and do not add network or write access to clusters.
3. Update tests for every behavioral change; run `python -m unittest discover -s tests -v` and `python -m compileall -q src tests`.
4. Describe assumptions, fail-closed semantics, potential false positives and new limitations in your pull request.
5. Do not claim a `kubectl drain` will succeed without Kubernetes integration and validation evidence.

All contributions are reviewed before merge. A green CI is required for releases.
