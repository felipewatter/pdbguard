"""Strict, bounded input handling and Kubernetes resource normalization."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_NODES, MAX_PODS, MAX_PDBS = 2000, 50000, 4000


class InputError(ValueError):
    """Untrusted snapshot input is invalid or unsupported."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, val in pairs:
        if key in obj:
            raise InputError(f"duplicate JSON object key: {key[:64]}")
        obj[key] = val
    return obj


def _reject_constant(value: str) -> None:
    raise InputError(f"non-JSON constant: {value}")


def load_json(path: str | Path) -> Any:
    p = Path(path)
    if not p.is_file() or p.stat().st_size > MAX_INPUT_BYTES:
        raise InputError(f"file missing or above {MAX_INPUT_BYTES} byte limit: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs,
                          parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise InputError(f"invalid UTF-8 JSON: {p}: {exc}") from exc


def _obj(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError(f"{where} must be a JSON object")
    return value


def _items(doc: Any, kind: str) -> list[dict[str, Any]]:
    data = _obj(doc, f"{kind} input")
    expected_api = "policy/v1" if kind == "PodDisruptionBudget" else "v1"
    if data.get("apiVersion") not in (None, expected_api):
        raise InputError(f"unsupported {kind} list apiVersion; expected {expected_api}")
    if data.get("kind") not in (None, kind + "List"):
        raise InputError(f"unsupported {kind} list kind")
    values = data.get("items")
    if not isinstance(values, list):
        raise InputError(f"{kind} input must have items[] from kubectl get -o json")
    for item in values:
        _obj(item, kind)
        if item.get("kind") not in (None, kind):
            raise InputError(f"unexpected resource kind in {kind} list")
    if len(values) > {"Node": MAX_NODES, "Pod": MAX_PODS, "PodDisruptionBudget": MAX_PDBS}[kind]:
        raise InputError(f"{kind} list exceeds maximum supported size")
    return values


def _metadata(item: dict[str, Any], what: str) -> dict[str, Any]:
    m = _obj(item.get("metadata"), f"{what}.metadata")
    if not isinstance(m.get("name"), str) or not m["name"]:
        raise InputError(f"{what} requires metadata.name")
    return m


def _as_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise InputError(f"{field} must be an array")
    return value


def _dictstr(value: Any, field: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                          for k, v in value.items()):
        raise InputError(f"{field} must contain string keys and values")
    return value


def import_kubernetes(nodes: Any, pods: Any, pdbs: Any) -> dict[str, Any]:
    """Convert three kubectl JSON lists to a portable, minimal snapshot."""
    nitems, pitems, bitems = _items(nodes, "Node"), _items(pods, "Pod"), _items(pdbs, "PodDisruptionBudget")
    result: dict[str, Any] = {"apiVersion": "pdbguard.io/v1", "nodes": [], "pods": [], "pdbs": []}
    for n in nitems:
        m = _metadata(n, "Node")
        labels = _dictstr(m.get("labels"), "Node.labels")
        status = _obj(n.get("status") or {}, "Node.status")
        conds = _as_list(status.get("conditions") or [], "Node.status.conditions")
        for c in conds: _obj(c, "Node condition")
        ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in conds)
        result["nodes"].append({"name": m["name"], "zone": labels.get("topology.kubernetes.io/zone", "unknown"), "ready": ready})
    for p in pitems:
        m = _metadata(p, "Pod")
        spec = _obj(p.get("spec") or {}, "Pod.spec")
        node = spec.get("nodeName")
        if not node:  # unscheduled pods cannot be part of a node eviction
            continue
        owners = _as_list(m.get("ownerReferences") or [], "Pod.ownerReferences")
        for owner in owners: _obj(owner, "Pod owner")
        if len([o for o in owners if o.get("controller") is True]) > 1:
            raise InputError(f"Pod {m['name']} has multiple controlling owners")
        controllers = [o for o in owners if o.get("controller") is True]
        kind = controllers[0].get("kind") if controllers else "Unmanaged"
        status = _obj(p.get("status") or {}, "Pod.status")
        conditions = _as_list(status.get("conditions") or [], "Pod.status.conditions")
        for c in conditions: _obj(c, "Pod condition")
        ready = status.get("phase") == "Running" and any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions)
        annotations = _dictstr(m.get("annotations"), "Pod.annotations")
        volumes = _as_list(spec.get("volumes") or [], "Pod.spec.volumes")
        for volume in volumes: _obj(volume, "Pod volume")
        result["pods"].append({
            "namespace": m.get("namespace", "default"), "name": m["name"], "node": node,
            "labels": _dictstr(m.get("labels"), "Pod.labels"), "ownerKind": kind,
            "ready": ready, "phase": status.get("phase", "Unknown"),
            "terminating": m.get("deletionTimestamp") is not None,
            "mirror": "kubernetes.io/config.mirror" in annotations,
            "emptyDir": any(isinstance(v, dict) and "emptyDir" in v for v in volumes),
            "safeToEvict": annotations.get("cluster-autoscaler.kubernetes.io/safe-to-evict") != "false",
        })
    for b in bitems:
        m = _metadata(b, "PodDisruptionBudget")
        spec = _obj(b.get("spec"), "PodDisruptionBudget.spec")
        status = _obj(b.get("status", {}), "PodDisruptionBudget.status")
        result["pdbs"].append({"namespace": m.get("namespace", "default"), "name": m["name"],
                               "selector": spec.get("selector"),
                               "allowed": status.get("disruptionsAllowed"),
                               "observedGeneration": status.get("observedGeneration"),
                               "generation": m.get("generation"),
                               "unhealthyPolicy": spec.get("unhealthyPodEvictionPolicy", "IfHealthyBudget")})
    validate_snapshot(result)
    return result


def validate_snapshot(doc: Any) -> dict[str, Any]:
    root = _obj(doc, "snapshot")
    if root.get("apiVersion") != "pdbguard.io/v1":
        raise InputError("unsupported apiVersion; expected pdbguard.io/v1")
    for name, max_items in (("nodes", MAX_NODES), ("pods", MAX_PODS), ("pdbs", MAX_PDBS)):
        collection = root.get(name)
        if not isinstance(collection, list) or len(collection) > max_items:
            raise InputError(f"{name} must be an array of no more than {max_items} items")
        for item in collection:
            _obj(item, name)
    seen = set()
    for node in root["nodes"]:
        if not isinstance(node.get("name"), str) or not node["name"]:
            raise InputError("node name must be nonempty string")
        if not isinstance(node.get("ready"), bool) or not isinstance(node.get("zone"), str):
            raise InputError("node ready must be boolean and zone must be string")
        if node["name"] in seen:
            raise InputError("duplicate node name")
        seen.add(node["name"])
    podnames = set()
    for pod in root["pods"]:
        for field in ("name", "namespace", "node", "ownerKind", "phase"):
            if not isinstance(pod.get(field), str) or not pod[field]:
                raise InputError(f"pod {field} must be nonempty string")
        for field in ("ready", "terminating", "mirror", "emptyDir", "safeToEvict"):
            if not isinstance(pod.get(field), bool):
                raise InputError(f"pod {field} must be boolean")
        _dictstr(pod.get("labels"), "pod.labels")
        key = (pod["namespace"], pod["name"])
        if key in podnames:
            raise InputError("duplicate pod identity")
        podnames.add(key)
        if pod["node"] not in seen:
            raise InputError(f"pod references missing node: {pod['node']}")
    budgetnames = set()
    for pdb in root["pdbs"]:
        for field in ("name", "namespace"):
            if not isinstance(pdb.get(field), str) or not pdb[field]:
                raise InputError(f"PDB {field} must be nonempty string")
        key = (pdb["namespace"], pdb["name"])
        if key in budgetnames:
            raise InputError("duplicate PDB identity")
        budgetnames.add(key)
        if type(pdb.get("allowed")) is not int or pdb["allowed"] < 0:
            raise InputError(f"PDB {key} requires nonnegative status.disruptionsAllowed")
        generation, observed = pdb.get("generation"), pdb.get("observedGeneration")
        if type(generation) is not int or type(observed) is not int or generation < 0 or observed < 0:
            raise InputError(f"PDB {key} requires integer generations")
        if pdb.get("unhealthyPolicy") not in ("AlwaysAllow", "IfHealthyBudget"):
            raise InputError("unsupported unhealthyPodEvictionPolicy")
        selector = pdb.get("selector")
        if not isinstance(selector, dict):
            raise InputError(f"PDB {key} requires selector object")
        _validate_selector(selector)
    return root


def _validate_selector(selector: dict[str, Any]) -> None:
    if any(x not in ("matchLabels", "matchExpressions") for x in selector):
        raise InputError("unsupported PDB selector field")
    _dictstr(selector.get("matchLabels"), "selector.matchLabels")
    expressions = selector.get("matchExpressions", [])
    if not isinstance(expressions, list):
        raise InputError("selector.matchExpressions must be array")
    for e in expressions:
        _obj(e, "selector expression")
        op, key, values = e.get("operator"), e.get("key"), e.get("values", [])
        if op not in ("In", "NotIn", "Exists", "DoesNotExist") or not isinstance(key, str) or not key:
            raise InputError("unsupported label selector operator/key")
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
            raise InputError("invalid label selector values")
        if (op in ("In", "NotIn") and not values) or (op in ("Exists", "DoesNotExist") and values):
            raise InputError("invalid label selector expression values")


def matches(selector: dict[str, Any], labels: dict[str, str]) -> bool:
    if any(labels.get(k) != v for k, v in selector.get("matchLabels", {}).items()):
        return False
    for e in selector.get("matchExpressions", []):
        op, key, values = e["operator"], e["key"], e.get("values", [])
        if op == "In" and labels.get(key) not in values:
            return False
        if op == "NotIn" and (key not in labels or labels[key] in values):
            return False
        if op == "Exists" and key not in labels:
            return False
        if op == "DoesNotExist" and key in labels:
            return False
    return True
