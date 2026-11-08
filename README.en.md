# PDBGuard — English Overview

**Offline Kubernetes disruption-budget and maintenance-wave planning, for security-minded SRE and infrastructure teams.**

PDBGuard imports three `kubectl get ... -o json` resource lists (Nodes, Pods, PDBs) and produces a minimized offline snapshot. It conservatively evaluates PodDisruptionBudget status, label selectors, Pod lifecycle/ownership, ephemeral storage risks, zone availability floors, and PDB contention between candidate nodes. An exact, deterministic subset optimizer chooses the largest simultaneous maintenance wave among up to 18 target nodes.

**Important:** This is a snapshot advisory, **not** an API-server eviction dry run or a guarantee that `kubectl drain` is safe or will succeed. It performs no cluster mutations or networking. It does not simulate scheduling, node capacity, topology spread, workload recovery, or persistent storage.

## Quick start

```bash
python -m pip install .
pdbguard plan examples/snapshot.json --nodes worker-a worker-b worker-d
```

For real authorized clusters:

```bash
kubectl get nodes -o json > nodes.json
kubectl get pods -A -o json > pods.json
kubectl get pdb -A -o json > pdbs.json
pdbguard import --nodes nodes.json --pods pods.json --pdbs pdbs.json --out snapshot.json
pdbguard plan snapshot.json --nodes my-node-1 my-node-2 --format sarif --out assessment.sarif
```

Exit codes: `0` = all requested nodes selected by the offline model; `1` = blocked or deferred; `2` = invalid data or I/O error. Exit code 0 is **never** an operational drain approval.

Read [README.md](README.md) for complete Brazilian Portuguese documentation, [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for algorithm internals, [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) for defensive scope, and [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

MIT License · Author: Felipe Watter.
