"""Machine-readable outputs for automation and security review."""
from __future__ import annotations

import json
from urllib.parse import quote
from typing import Any


def to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def to_sarif(report: dict[str, Any]) -> str:
    findings = [(n, f) for n in report["nodes"] for f in n["findings"]]
    rules = sorted({f["code"] for _, f in findings})
    results = []
    for node, finding in findings:
        results.append({"ruleId": finding["code"],
                        "level": {"error": "error", "warning": "warning", "info": "note"}[finding["severity"]],
                        "message": {"text": finding["message"]},
                        "locations": [{"physicalLocation": {"artifactLocation": {"uri": "k8s-node/" + quote(node["name"], safe="")}}}],
                        "properties": {"node": node["name"], "pod": finding.get("pod"), "pdb": finding.get("pdb")}})
    obj = {"$schema": "https://json.schemastore.org/sarif-2.1.0.json", "version": "2.1.0",
           "runs": [{"tool": {"driver": {"name": "PDBGuard", "version": report["engineVersion"],
                                          "rules": [{"id": rule, "shortDescription": {"text": rule}} for rule in rules]}},
                     "results": results, "properties": {"summary": report["summary"], "advisoryOnly": True}}]}
    return to_json(obj)


def to_text(report: dict[str, Any]) -> str:
    s = report["summary"]
    out = ["PDBGuard | OFFLINE ADVISORY (NOT A KUBERNETES SAFETY GUARANTEE)",
           f"Selected: {s['selected']}/{s['targets']} | Blocked: {s['blocked']} | Deferred: {s['deferred']}",
           "Proposed simultaneous maintenance wave: " + (", ".join(report["selectedWave"]) or "(none)")]
    for node in report["nodes"]:
        out.append(f"  [{node['status'].upper()}] {node['name']} (zone {node['zone']})")
        out.extend(f"    {f['severity'].upper()} {f['code']}: {f['message']}" for f in node["findings"])
    return "\n".join(out) + "\n"
