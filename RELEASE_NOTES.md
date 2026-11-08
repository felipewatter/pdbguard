# PDBGuard v0.1.0

Initial public release of an offline, conservative Kubernetes PodDisruptionBudget (PDB) maintenance-wave advisor.

**Features:** import `kubectl get nodes/pods/pdb -o json`, validate snapshot integrity and PDB status, analyze risky evictions, find the largest concurrent target-node set under PDB and zone constraints, export JSON/SARIF and human-readable review reports.

**Not an operational safety guarantee:** no cluster access, no scheduler/affinity/storage simulation, no actual API-server eviction; human approval is mandatory.

Tested through Python unittest and GitHub Actions on Linux/Windows/macOS (Python 3.10–3.13) prior to release.
