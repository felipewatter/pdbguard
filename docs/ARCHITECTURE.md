# Architecture and invariants

## Components

- `inputs.py` strictly parses a bounded JSON snapshot and imports the three Kubernetes resource lists. It normalizes object names, namespaces, labels, owner kind, health, annotations, generation and status.
- `planner.py` evaluates individual target-node blocks and budget consumption. It computes an exact maximum-cardinality feasible subset of the remaining candidates using depth-first branch-and-bound. No commands are sent to a Kubernetes cluster.
- `report.py` produces canonical JSON, human-readable text and SARIF 2.1 with explanation codes.
- `cli.py` provides an explicit, offline import/plan boundary and stable exit codes.

## Selection invariants

For selected node set `W` and each PodDisruptionBudget `p`:

`sum(healthy eligible Pods selected for eviction under p) <= status.disruptionsAllowed(p)`

For each zone `z`:

`ready_nodes_before(z) - selected_nodes(z) >= min_ready_nodes_per_zone`

Each selected node must pass local conservative checks. The search maximizes `|W|`, breaking equal-sized ties lexicographically for stable CI results. Candidates are capped at 18 because the algorithm explores subsets (worst-case O(2^n * (PDBs+zones))).

## Design trade-offs

- The optimizer does not claim a sequential order or replenish PDB quota between drains; selecting a simultaneous wave is deliberately conservative.
- `maxUnavailable` and `minAvailable` are **not** re-implemented. The tool consumes the API-server-observed `status.disruptionsAllowed`, while rejecting stale observed generation.
- The importer discards unneeded Kubernetes fields and uses no kubeconfig. It **does not anonymize** namespace/node/pod names or labels: snapshots must be handled as internal operational data.
- `safe-to-evict=false` is not a hard rule enforced by `kubectl drain` itself, but is treated as an additional conservative site policy.
- `emptyDir`, unmanaged pods and no-PDB workloads fail closed unless explicitly acknowledged via CLI flags.
- Running non-ready pods are conservatively blocked unless the PDB reports `AlwaysAllow`; server behavior can vary with version/configuration.
- Real Eviction API behavior, scheduler capacity and operator-specific processes are outside scope.

## Data flow

`kubectl read-only JSON exports` → `pdbguard import` → `minimal snapshot` → `strict validation` → `per-Pod selector associations` → `node blockers/PDB demand` → `bounded exact wave search` → `text/JSON/SARIF` → `human change review`.

## Report schema

`schemaVersion` is `pdbguard.report/v1`. Fields: `engineVersion`, `advisoryOnly`, `assumptions`, `summary` (targets, selected, blocked, deferred, complete), `selectedWave` (node names), `nodes` (`name`, `zone`, `status`, `pdbCost`, `findings`). Findings include `code`, `severity`, `message`, and optional `node`/`pod`/`pdb` metadata.
