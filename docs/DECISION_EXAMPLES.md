# Decision examples — synthetic cases

All fixtures here are fictional. Never upload production cluster snapshots to a public issue or pull request.

| Situation | Outcome | Reason |
|---|---|---|
| Two nodes each host one healthy Pod protected by the same PDB, `disruptionsAllowed=1` | At most one selected in concurrent wave | Combined removal exceeds observed quota |
| Node has two healthy Pods protected by the same PDB, `disruptionsAllowed=1` | Blocked | Eviction cost on one node exceeds budget |
| Pod matches two overlapping PDBs | Blocked | Kubernetes eviction resolution is not modeled safely |
| PDB `generation=4`, `observedGeneration=3` | Blocked | Controller has not acknowledged latest spec generation |
| Unmanaged Pod on node | Blocked by default | No verified workload controller to recreate Pod |
| `emptyDir` storage | Blocked by default | Local data may be lost; `--ack-emptydir-loss` is explicit risk acknowledgment only |
| Node is only remaining Ready node in its zone | Blocked with default zone floor 1 | Loss of zone-level node continuity |
| Pod with `unhealthyPodEvictionPolicy=AlwaysAllow`, not Ready | Warning, does not consume PDB quota | Snapshot advisory still requires validation against Kubernetes behavior |
| DaemonSet Pod | Skipped with informational finding | `kubectl drain --ignore-daemonsets` cannot evict DaemonSet-managed Pod |
| Non-running nonterminal Pod | Blocked | No supported phase/readiness handling assumption |
| No PDB for managed Pod | Blocked by default | `--allow-missing-pdb` can lower severity to warning, but provides no new protection |

**Example:** in `examples/snapshot.json`, `worker-a` and `worker-b` each have a healthy replica of the same `web` service. `web` has `allowed=1`, and `worker-d` has no workloads. Asking for `worker-a worker-b worker-d` yields `worker-a, worker-d` selected, with `worker-b` deferred as a simultaneous-wave conflict.

These are **risk findings, not execution commands**. A change manager should verify PDBs, runtime topology, service SLOs, scheduler capacity, storage and rollback procedures immediately before maintenance.
