"""Offline fixtures; tests never access or mutate a Kubernetes cluster."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from pdbguard.cli import main
from pdbguard.inputs import InputError, import_kubernetes, load_json, matches, validate_snapshot
from pdbguard.planner import plan
from pdbguard.report import to_json, to_sarif, to_text


def fixture():
    return {"apiVersion": "pdbguard.io/v1",
            "nodes": [{"name": "n1", "zone": "az-a", "ready": True},
                      {"name": "n2", "zone": "az-a", "ready": True},
                      {"name": "n3", "zone": "az-b", "ready": True},
                      {"name": "n4", "zone": "az-b", "ready": True}],
            "pods": [{"name": f"web-{i}", "namespace": "prod", "node": node,
                      "ownerKind": "ReplicaSet", "phase": "Running", "ready": True,
                      "labels": {"app": "web", "tier": "frontend"}, "mirror": False,
                      "emptyDir": False, "safeToEvict": True, "terminating": False}
                     for i, node in enumerate(("n1", "n2", "n3"), 1)],
            "pdbs": [{"name": "web", "namespace": "prod", "selector": {"matchLabels": {"app": "web"}},
                      "allowed": 1, "generation": 1, "observedGeneration": 1,
                      "unhealthyPolicy": "IfHealthyBudget"}]}


class PlannerTests(unittest.TestCase):
    def test_valid_snapshot(self):
        self.assertEqual(validate_snapshot(fixture())["apiVersion"], "pdbguard.io/v1")

    def test_select_two_independent_nodes(self):
        r = plan(fixture(), ["n1", "n4"])
        self.assertEqual(r["selectedWave"], ["n1", "n4"])
        self.assertTrue(r["summary"]["complete"])

    def test_budget_contention_deferred(self):
        r = plan(fixture(), ["n1", "n2", "n4"])
        self.assertEqual(r["selectedWave"], ["n1", "n4"])
        self.assertEqual(r["summary"]["deferred"], 1)

    def test_deterministic_order(self):
        a = plan(fixture(), ["n4", "n2", "n1"])
        b = plan(fixture(), ["n1", "n2", "n4"])
        self.assertEqual(a, b)

    def test_missing_pdb_blocks(self):
        x = fixture(); x["pdbs"] = []
        self.assertEqual(plan(x, ["n1"])["summary"]["blocked"], 1)

    def test_missing_pdb_override(self):
        x = fixture(); x["pdbs"] = []
        self.assertTrue(plan(x, ["n1"], require_pdb=False)["summary"]["complete"])

    def test_zero_budget_blocks(self):
        x = fixture(); x["pdbs"][0]["allowed"] = 0
        self.assertEqual(plan(x, ["n1"])["summary"]["blocked"], 1)

    def test_stale_generation_blocks(self):
        x = fixture(); x["pdbs"][0]["generation"] = 2
        self.assertIn("STALE_PDB", [f["code"] for f in plan(x, ["n1"])["nodes"][0]["findings"]])

    def test_overlapping_pdb_blocks(self):
        x = fixture(); b = copy.deepcopy(x["pdbs"][0]); b["name"] = "web-2"; x["pdbs"].append(b)
        self.assertIn("OVERLAPPING_PDB", [f["code"] for f in plan(x, ["n1"])["nodes"][0]["findings"]])

    def test_emptydir_blocks(self):
        x = fixture(); x["pods"][0]["emptyDir"] = True
        self.assertEqual(plan(x, ["n1"])["summary"]["blocked"], 1)

    def test_emptydir_acknowledgement(self):
        x = fixture(); x["pods"][0]["emptyDir"] = True
        self.assertTrue(plan(x, ["n1"], allow_emptydir=True)["summary"]["complete"])

    def test_unmanaged_blocks(self):
        x = fixture(); x["pods"][0]["ownerKind"] = "Unmanaged"
        self.assertEqual(plan(x, ["n1"])["summary"]["blocked"], 1)

    def test_unmanaged_acknowledgement(self):
        x = fixture(); x["pods"][0]["ownerKind"] = "Unmanaged"
        self.assertTrue(plan(x, ["n1"], allow_unmanaged=True)["summary"]["complete"])

    def test_do_not_evict_blocks_even_with_overrides(self):
        x = fixture(); x["pods"][0]["safeToEvict"] = False
        self.assertEqual(plan(x, ["n1"], allow_unmanaged=True, allow_emptydir=True, require_pdb=False)["summary"]["blocked"], 1)

    def test_mirror_ignored(self):
        x = fixture(); x["pods"][0]["mirror"] = True
        self.assertTrue(plan(x, ["n1"])["summary"]["complete"])

    def test_daemonset_ignored(self):
        x = fixture(); x["pods"][0]["ownerKind"] = "DaemonSet"
        self.assertTrue(plan(x, ["n1"])["summary"]["complete"])

    def test_terminal_pod_ignored(self):
        x = fixture(); x["pods"][0]["phase"] = "Succeeded"
        self.assertTrue(plan(x, ["n1"])["summary"]["complete"])

    def test_unhealthy_pod_blocks_without_always_allow(self):
        x = fixture(); x["pods"][0]["ready"] = False
        self.assertEqual(plan(x, ["n1"])["summary"]["blocked"], 1)

    def test_unhealthy_pod_allowed_with_always_allow(self):
        x = fixture(); x["pods"][0]["ready"] = False; x["pdbs"][0]["unhealthyPolicy"] = "AlwaysAllow"; x["pdbs"][0]["allowed"] = 0
        self.assertTrue(plan(x, ["n1"])["summary"]["complete"])

    def test_zone_floor_blocks(self):
        x = fixture(); x["nodes"][1]["zone"] = "another"
        self.assertEqual(plan(x, ["n1"])["summary"]["blocked"], 1)

    def test_zone_floor_override(self):
        x = fixture(); x["nodes"][1]["zone"] = "another"
        self.assertTrue(plan(x, ["n1"], min_nodes_per_zone=0)["summary"]["complete"])

    def test_budget_multiple_pods_on_node(self):
        x = fixture(); pod = copy.deepcopy(x["pods"][0]); pod["name"] = "web-4"; x["pods"].append(pod)
        self.assertEqual(plan(x, ["n1"])["summary"]["blocked"], 1)
        x["pdbs"][0]["allowed"] = 2
        self.assertTrue(plan(x, ["n1"])["summary"]["complete"])

    def test_backtracking_maximizes_wave(self):
        x = fixture(); x["pods"][2]["node"] = "n4"
        # n1+n4 consume 2; n2 only 1: cannot take both under quota 1
        r = plan(x, ["n1", "n2", "n3", "n4"])
        self.assertEqual(r["summary"]["selected"], 2)

    def test_nonrunning_pod_blocks(self):
        x = fixture(); x["pods"][0]["phase"] = "Pending"
        self.assertEqual(plan(x, ["n1"])["summary"]["blocked"], 1)

    def test_unknown_target_rejected(self):
        with self.assertRaises(InputError): plan(fixture(), ["ghost"])

    def test_non_ready_node_rejected(self):
        x = fixture(); x["nodes"][0]["ready"] = False
        with self.assertRaises(InputError): plan(x, ["n1"])

    def test_duplicate_targets_rejected(self):
        with self.assertRaises(InputError): plan(fixture(), ["n1", "n1"])

    def test_empty_targets_rejected(self):
        with self.assertRaises(InputError): plan(fixture(), [])

    def test_too_many_targets_rejected(self):
        with self.assertRaises(InputError): plan(fixture(), ["n1"] * 19)

    def test_negative_zone_floor_rejected(self):
        with self.assertRaises(InputError): plan(fixture(), ["n1"], min_nodes_per_zone=-1)


class InputTests(unittest.TestCase):
    def test_duplicate_nodes(self):
        x = fixture(); x["nodes"].append(x["nodes"][0]); self.assertRaises(InputError, validate_snapshot, x)

    def test_duplicate_pods(self):
        x = fixture(); x["pods"].append(x["pods"][0]); self.assertRaises(InputError, validate_snapshot, x)

    def test_duplicate_pdbs(self):
        x = fixture(); x["pdbs"].append(x["pdbs"][0]); self.assertRaises(InputError, validate_snapshot, x)

    def test_unknown_node_reference(self):
        x = fixture(); x["pods"][0]["node"] = "ghost"; self.assertRaises(InputError, validate_snapshot, x)

    def test_negative_allowed(self):
        x = fixture(); x["pdbs"][0]["allowed"] = -1; self.assertRaises(InputError, validate_snapshot, x)

    def test_boolean_as_allowed_rejected(self):
        x = fixture(); x["pdbs"][0]["allowed"] = True; self.assertRaises(InputError, validate_snapshot, x)

    def test_unsupported_schema(self):
        x = fixture(); x["apiVersion"] = "x"; self.assertRaises(InputError, validate_snapshot, x)

    def test_missing_selector(self):
        x = fixture(); x["pdbs"][0]["selector"] = None; self.assertRaises(InputError, validate_snapshot, x)

    def test_invalid_selector_operator(self):
        x = fixture(); x["pdbs"][0]["selector"] = {"matchExpressions": [{"key": "app", "operator": "exec", "values": ["web"]}]}
        self.assertRaises(InputError, validate_snapshot, x)

    def test_generation_is_int(self):
        x = fixture(); x["pdbs"][0]["generation"] = True; self.assertRaises(InputError, validate_snapshot, x)

    def test_labels_must_be_strings(self):
        x = fixture(); x["pods"][0]["labels"] = {"x": 4}; self.assertRaises(InputError, validate_snapshot, x)

    def test_selector_in(self):
        self.assertTrue(matches({"matchExpressions": [{"key":"env","operator":"In","values":["prod"]}]}, {"env":"prod"}))

    def test_selector_not_in_absent_key_fails(self):
        self.assertFalse(matches({"matchExpressions": [{"key":"env","operator":"NotIn","values":["dev"]}]}, {}))

    def test_selector_exists(self):
        self.assertTrue(matches({"matchExpressions": [{"key":"env","operator":"Exists"}]}, {"env":""}))

    def test_selector_does_not_exist(self):
        self.assertTrue(matches({"matchExpressions": [{"key":"env","operator":"DoesNotExist"}]}, {}))

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/"dup.json"; path.write_text('{"a":1,"a":2}')
            self.assertRaises(InputError, load_json, path)

    def test_nan_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/"nan.json"; path.write_text('{"a":NaN}')
            self.assertRaises(InputError, load_json, path)

    def test_large_file_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/"huge.json"
            with path.open("wb") as stream: stream.truncate(8 * 1024 * 1024 + 1)
            self.assertRaises(InputError, load_json, path)

    def test_import_kubernetes_lists(self):
        nodes = {"items":[{"kind":"Node","metadata":{"name":"n1","labels":{"topology.kubernetes.io/zone":"a"}},"status":{"conditions":[{"type":"Ready","status":"True"}]}}]}
        pods = {"items":[{"kind":"Pod","metadata":{"name":"app-1","namespace":"prod","labels":{"app":"a"},"ownerReferences":[{"kind":"ReplicaSet","controller":True}]},"spec":{"nodeName":"n1"},"status":{"phase":"Running","conditions":[{"type":"Ready","status":"True"}]}}]}
        pdbs = {"items":[{"kind":"PodDisruptionBudget","metadata":{"name":"pdb-a","namespace":"prod","generation":1},"spec":{"selector":{"matchLabels":{"app":"a"}}},"status":{"observedGeneration":1,"disruptionsAllowed":1}}]}
        x = import_kubernetes(nodes,pods,pdbs)
        self.assertTrue(x["nodes"][0]["ready"])
        self.assertEqual(x["pods"][0]["ownerKind"], "ReplicaSet")
        self.assertEqual(plan(x,["n1"],min_nodes_per_zone=0)["summary"]["selected"],1)

    def test_import_ignores_unscheduled_pods(self):
        nodes = {"items":[{"metadata":{"name":"n1"},"status":{"conditions":[]}}]}
        pods = {"items":[{"metadata":{"name":"queued"},"spec":{},"status":{}}]}
        x = import_kubernetes(nodes,pods,{"items":[]})
        self.assertEqual(x["pods"],[])

    def test_import_rejects_beta_pdb_selector_semantics(self):
        nodes = {"items": []}
        pods = {"items": []}
        pdbs = {"apiVersion": "policy/v1beta1", "kind": "PodDisruptionBudgetList", "items": []}
        self.assertRaises(InputError, import_kubernetes, nodes, pods, pdbs)

    def test_import_rejects_incorrect_top_level_kind(self):
        nodes = {"kind": "PodList", "items": []}
        self.assertRaises(InputError, import_kubernetes, nodes, {"items": []}, {"items": []})

    def test_import_rejects_non_list_items(self):
        self.assertRaises(InputError, import_kubernetes, {"items": {}}, {"items": []}, {"items": []})

    def test_import_rejects_malformed_volumes(self):
        nodes = {"items": [{"metadata": {"name": "a"}}]}
        pods = {"items": [{"metadata": {"name": "p"}, "spec": {"nodeName": "a", "volumes": "bad"}}]}
        self.assertRaises(InputError, import_kubernetes, nodes, pods, {"items": []})

    def test_import_rejects_overlimit_node_list(self):
        self.assertRaises(InputError, import_kubernetes, {"items": [{}]*2001}, {"items": []}, {"items": []})

    def test_import_rejects_wrong_kind(self):
        self.assertRaises(InputError, import_kubernetes,{"items":[{"kind":"Secret"}]},{"items":[]},{"items":[]})


class ReportTests(unittest.TestCase):
    def test_json_report(self):
        r = json.loads(to_json(plan(fixture(), ["n1", "n2"])))
        self.assertEqual(r["schemaVersion"], "pdbguard.report/v1")

    def test_sarif_report(self):
        r = json.loads(to_sarif(plan(fixture(), ["n1", "n2"])))
        self.assertEqual(r["version"], "2.1.0")
        self.assertTrue(r["runs"][0]["results"])

    def test_text_report(self):
        self.assertIn("OFFLINE ADVISORY", to_text(plan(fixture(), ["n1"])))

    def test_cli_success(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"snap.json";p.write_text(json.dumps(fixture()))
            result=Path(td)/"result.json"
            self.assertEqual(main(["plan",str(p),"--nodes","n1","--format","json","--out",str(result)]),0)
            self.assertEqual(json.loads(result.read_text())["summary"]["selected"],1)

    def test_cli_policy_block_exit_code(self):
        with tempfile.TemporaryDirectory() as td:
            x=fixture();x["pdbs"][0]["allowed"]=0
            p=Path(td)/"snap.json";p.write_text(json.dumps(x))
            self.assertEqual(main(["plan",str(p),"--nodes","n1","--out",str(Path(td)/"result")]),1)

    def test_cli_malformed_exit_code(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"bad.json";p.write_text("not json")
            self.assertEqual(main(["plan",str(p),"--nodes","n1"]),2)

    def test_cli_refuses_symlink_output(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"snap.json";p.write_text(json.dumps(fixture()))
            link=Path(td)/"out";link.symlink_to(p)
            self.assertEqual(main(["plan",str(p),"--nodes","n1","--out",str(link)]),2)


class ExactOptimizerPropertyTests(unittest.TestCase):
    def test_against_independent_bruteforce_random_cases(self):
        import itertools
        import random
        rng = random.Random(20261108)
        for case in range(100):
            nodes = [f"n{i}" for i in range(6)]
            data = {"apiVersion": "pdbguard.io/v1",
                    "nodes": [{"name": n, "zone": "a" if i < 3 else "b", "ready": True} for i, n in enumerate(nodes)],
                    "pods": [], "pdbs": []}
            group = [rng.randrange(3) for _ in nodes]
            allowances = [rng.randrange(4) for _ in range(3)]
            for i, n in enumerate(nodes):
                data["pods"].append({"name": f"pod-{n}", "namespace": "team", "node": n,
                                     "labels": {"app": str(group[i])}, "ownerKind": "ReplicaSet",
                                     "phase": "Running", "ready": True, "terminating": False,
                                     "mirror": False, "emptyDir": False, "safeToEvict": True})
            for i in range(3):
                data["pdbs"].append({"namespace": "team", "name": f"budget-{i}",
                                     "selector": {"matchLabels": {"app": str(i)}},
                                     "allowed": allowances[i], "generation": 1,
                                     "observedGeneration": 1, "unhealthyPolicy": "IfHealthyBudget"})
            report = plan(data, nodes)
            best = ()
            for k in range(7):
                for chosen in itertools.combinations(nodes, k):
                    remaining = [3 - sum(nodes.index(n) < 3 for n in chosen),
                                 3 - sum(nodes.index(n) >= 3 for n in chosen)]
                    demand = [sum(group[nodes.index(n)] == i for n in chosen) for i in range(3)]
                    if min(remaining) < 1 or any(demand[i] > allowances[i] for i in range(3)):
                        continue
                    if k > len(best) or (k == len(best) and chosen < best):
                        best = chosen
            self.assertEqual(report["selectedWave"], list(best), f"seed case {case}")

    def test_sarif_escapes_untrusted_node_name_as_uri(self):
        x = fixture()
        x["nodes"][0]["name"] = "n/../?1"
        x["pods"][0]["node"] = "n/../?1"
        x["pods"][0]["emptyDir"] = True
        r = json.loads(to_sarif(plan(x, ["n/../?1"])))
        uri = r["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        self.assertEqual(uri, "k8s-node/n%2F..%2F%3F1")


if __name__ == "__main__":
    unittest.main()
