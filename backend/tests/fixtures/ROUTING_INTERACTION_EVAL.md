# Interaction routing evaluation corpus

`routing_interaction_eval_v1.jsonl` is the versioned, provider-independent gold
corpus for the interaction decision boundary.

Each line has one input and one expected decision:

```text
id/category
input.text + optional identity-free input.context
    -> status
    -> goal
    -> requirements (asserted subset)
    -> memory_persistence
    -> business_state_change_required
    -> planning
    -> required_operations
    -> must_not_operations
    -> forbidden_operations
```

The operation fields validate the downstream compatibility envelope; they do
not make operations part of `GoalDecision`. In particular:

- `required_operations` must be present in the final `RoutingDecision`.
- `forbidden_operations` must be absent because they would be semantically
  incorrect for the input.
- `must_not_operations` must be absent **and**, when a first-class
  `InteractionDecision` exists, backed by a prohibited abstract capability.

The verifier always enters production through `RoutingFunnel.decide`. It
disables live vector calls so the suite is deterministic and cannot turn into
an integration test for an embedding provider.

Run only the corpus contract checks:

```powershell
.\.venv\Scripts\python.exe scripts\verify_routing_interaction_eval.py --contract-only
```

Print a migration baseline without failing the command:

```powershell
.\.venv\Scripts\python.exe scripts\verify_routing_interaction_eval.py --report-only
```

Run the strict acceptance gate:

```powershell
.\.venv\Scripts\python.exe scripts\verify_routing_interaction_eval.py
```

Strict mode fails on any mismatch or skipped context-follow-up case.
