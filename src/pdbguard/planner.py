"""Conservative and deterministic PDB-aware node maintenance wave planning.

Never executes kubectl or touches Kubernetes. The result is advisory, not a safety proof.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .inputs import InputError, matches, validate_snapshot

MAX_EXACT_CANDIDATES = 18


def _finding(code: str, level: str, message: str, node: str | None = None,
             pod: str | None = None, pdb: str | None = None) -> dict[str, Any]:
    result = {"code": code, "severity": level, "message": message}
    for key, val in (("node", node), ("pod", pod), ("pdb", pdb)):
        if val is not None:
            result[key] = val
    return result


def plan(snapshot: dict[str, Any], targets: list[str], *, require_pdb: bool = True,
         allow_emptydir: bool = False, allow_unmanaged: bool = False,
         min_nodes_per_zone: int = 1) -> dict[str, Any]:
    """Select largest *simultaneous* drain candidate set under snapshot PDB quotas.

    No rescheduling, replacement readiness, or PDB replenishment assumed. The selected
    wave uses the current disruption allowance once; it is not an execution approval.
    """
    validate_snapshot(snapshot)
    if type(min_nodes_per_zone) is not int or min_nodes_per_zone < 0:
        raise InputError("min_nodes_per_zone must be nonnegative integer")
    if not targets or len(targets) > MAX_EXACT_CANDIDATES or len(set(targets)) != len(targets):
        raise InputError(f"choose between 1 and {MAX_EXACT_CANDIDATES} unique target nodes")
    all_nodes = {n["name"]: n for n in snapshot["nodes"]}
    if any(t not in all_nodes for t in targets):
        raise InputError("target node is absent from snapshot")
    if any(not all_nodes[t]["ready"] for t in targets):
        raise InputError("target nodes must be Ready; non-Ready drains require manual investigation")
    zone_available = Counter(n["zone"] for n in snapshot["nodes"] if n["ready"])
    pods_by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pod in snapshot["pods"]:
        pods_by_node[pod["node"]].append(pod)
    pdbs = {(p["namespace"], p["name"]): p for p in snapshot["pdbs"]}
    matching: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for pod in snapshot["pods"]:
        key = (pod["namespace"], pod["name"])
        matching[key] = [k for k, pdb in sorted(pdbs.items()) if pdb["namespace"] == pod["namespace"]
                         and matches(pdb["selector"], pod["labels"])]
    node_findings: dict[str, list[dict[str, Any]]] = {n: [] for n in targets}
    node_cost: dict[str, Counter[tuple[str, str]]] = {}
    for name in targets:
        findings = node_findings[name]
        costs: Counter[tuple[str, str]] = Counter()
        if zone_available[all_nodes[name]["zone"]] <= min_nodes_per_zone:
            findings.append(_finding("ZONE_FLOOR", "error", "Node removal would violate zone Ready-node floor", node=name))
        for pod in sorted(pods_by_node[name], key=lambda p: (p["namespace"], p["name"])):
            ident = f"{pod['namespace']}/{pod['name']}"
            if pod["phase"] in ("Succeeded", "Failed") or pod["terminating"]:
                findings.append(_finding("TERMINAL_POD", "info", "Terminal/terminating Pod excluded from eviction simulation", node=name, pod=ident))
                continue
            if pod["mirror"]:
                findings.append(_finding("MIRROR_POD", "info", "Static mirror Pod ignored; kubelet ownership remains", node=name, pod=ident))
                continue
            if pod["ownerKind"] == "DaemonSet":
                findings.append(_finding("DAEMONSET", "info", "DaemonSet Pod is ignored by kubectl drain with --ignore-daemonsets", node=name, pod=ident))
                continue
            if pod["phase"] != "Running":
                findings.append(_finding("NONRUNNING", "error", "Nonterminal Pod is not Running; cannot model eviction", node=name, pod=ident))
                continue
            if not pod["safeToEvict"]:
                findings.append(_finding("DO_NOT_EVICT", "error", "Pod explicitly annotated safe-to-evict=false (conservative policy)", node=name, pod=ident))
            if pod["emptyDir"]:
                findings.append(_finding("EMPTYDIR", "warning" if allow_emptydir else "error", "Pod has emptyDir: local data can be lost on eviction", node=name, pod=ident))
            if pod["ownerKind"] == "Unmanaged":
                findings.append(_finding("UNMANAGED", "warning" if allow_unmanaged else "error", "Bare Pod lacks a controlling workload", node=name, pod=ident))
            budget_ids = matching[(pod["namespace"], pod["name"])]
            if len(budget_ids) > 1:
                findings.append(_finding("OVERLAPPING_PDB", "error", "Pod matches multiple PDBs; Kubernetes eviction is ambiguous", node=name, pod=ident))
                continue
            if not budget_ids:
                findings.append(_finding("MISSING_PDB", "error" if require_pdb else "warning", "No PDB protects workload Pod", node=name, pod=ident))
                continue
            budget_id = budget_ids[0]
            budget = pdbs[budget_id]
            fq_pdb = f"{budget_id[0]}/{budget_id[1]}"
            if budget["observedGeneration"] < budget["generation"]:
                findings.append(_finding("STALE_PDB", "error", "PDB status is older than spec generation", node=name, pod=ident, pdb=fq_pdb))
                continue
            if not pod["ready"] and budget["unhealthyPolicy"] != "AlwaysAllow":
                findings.append(_finding("UNHEALTHY_EVICTION", "error", "Non-ready Pod has no AlwaysAllow eviction policy; manually verify PDB", node=name, pod=ident, pdb=fq_pdb))
                continue
            if pod["ready"]:
                costs[budget_id] += 1
            else:
                findings.append(_finding("UNHEALTHY_ALWAYS_ALLOW", "warning", "Unhealthy Pod excluded from PDB quota under AlwaysAllow; verify current API behavior", node=name, pod=ident, pdb=fq_pdb))
        for budget_id, amount in sorted(costs.items()):
            allowed = pdbs[budget_id]["allowed"]
            if amount > allowed:
                findings.append(_finding("PDB_EXHAUSTED", "error", f"Node needs {amount} PDB evictions; status allows {allowed}", node=name, pdb="/".join(budget_id)))
        node_cost[name] = costs

    candidates = sorted(n for n in targets if not any(f["severity"] == "error" for f in node_findings[n]))
    # Exact subset enumeration, bounded at 18 candidates for predictable runtime.
    # Ties broken deterministically by node-name tuple, independent of input order.
    best: tuple[str, ...] = ()
    def dfs(index: int, selected: tuple[str, ...], consumed: Counter[tuple[str, str]], removed: Counter[str]) -> None:
        nonlocal best
        if len(selected) + len(candidates) - index < len(best):
            return
        if index == len(candidates):
            if len(selected) > len(best) or (len(selected) == len(best) and selected < best):
                best = selected
            return
        name = candidates[index]
        zone = all_nodes[name]["zone"]
        budget_ok = all(consumed[k] + value <= pdbs[k]["allowed"] for k, value in node_cost[name].items())
        zone_ok = zone_available[zone] - removed[zone] - 1 >= min_nodes_per_zone
        if budget_ok and zone_ok:
            updated_consumed = consumed.copy()
            updated_consumed.update(node_cost[name])
            updated_removed = removed.copy()
            updated_removed[zone] += 1
            dfs(index + 1, (*selected, name), updated_consumed, updated_removed)
        dfs(index + 1, selected, consumed, removed)
    dfs(0, (), Counter(), Counter())
    selected = set(best)
    status = {}
    for node in targets:
        status[node] = "blocked" if node not in candidates else ("selected" if node in selected else "deferred")
        if status[node] == "deferred":
            node_findings[node].append(_finding("WAVE_CONTENTION", "warning", "Individually eligible, but PDB/zone capacity conflicts with selected maintenance wave", node=node))
    summary = {"targets": len(targets), "selected": len(best),
               "blocked": sum(s == "blocked" for s in status.values()),
               "deferred": sum(s == "deferred" for s in status.values()),
               "complete": len(best) == len(targets)}
    return {"schemaVersion": "pdbguard.report/v1", "engineVersion": "0.1.0",
            "advisoryOnly": True,
            "assumptions": ["Point-in-time snapshot, not an API-server eviction dry run",
                            "No workload rescheduling or PDB replenishment during simultaneous wave",
                            "PDB status.disruptionsAllowed is used; scheduling/affinity/capacity not simulated",
                            "DaemonSet and mirror Pods excluded, with operational caveats"],
            "summary": summary, "selectedWave": list(best),
            "nodes": [{"name": n, "zone": all_nodes[n]["zone"], "status": status[n],
                       "pdbCost": {"/".join(key): value for key, value in sorted(node_cost[n].items())},
                       "findings": node_findings[n]} for n in sorted(targets)]}
