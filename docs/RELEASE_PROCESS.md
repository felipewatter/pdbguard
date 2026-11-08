# Release procedure

1. Review changes, threat model, README and synthetic-only examples.
2. Run unit/regression tests and lint/syntax checks locally; merge to `main` with approval.
3. Require green `CI` on the exact `main` commit across all twelve environment combinations.
4. For v0.1.0, the one-time `workflow_run` bootstrap checks that the successful push CI SHA equals the present `main` head, that the version matches, and reruns tests before publication. No release is created on failed CI.
5. For later releases, use the manual release workflow after CI completes. It refuses nonexistent or divergent successful CI and checks tag/commit consistency.
6. Confirm GitHub Release version, attached source ZIP, Python wheel and SHA-256 files; do not rewrite published tags.
7. Publish release notes and compare assets to hashes. Public release artifacts contain only source and synthetic examples.

No release may be described as validated until GitHub Actions passes and the release endpoint shows a real published asset.
