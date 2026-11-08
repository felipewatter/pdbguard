# Security Policy

Supported releases: `v0.1.x` (best-effort maintenance).

**Responsible disclosure:** Please report vulnerabilities privately through the GitHub repository's security-advisory workflow (Security → Advisories → Report a vulnerability), if available. Do not publish exploit details, active cluster credentials, kubeconfigs, client certificates, real production snapshots or sensitive labels in public issues or pull requests. If private reporting is not enabled, open an issue requesting a confidential contact channel **without disclosing the vulnerability itself**.

Scope: untrusted JSON parsing, algorithmic correctness, unsafe output handling, package supply chain, accidental disclosure and misleading safety claims. This tool never issues cluster-changing commands. Please use synthetic data in reproductions.

No warranty is made that maintenance is safe: actual API-server Eviction behavior, scheduler, capacity and current cluster state remain authoritative.
