# Revenue OS Architecture Overview

## Runtime Layers
1. Acquisition Layer (Qianfan + Creator)
2. Normalization / Registry Layer
3. Decision Layer (`anomaly_gate_result`, `current_state`, `mission_plan`)
4. Execution Layer (`execution_package`, experiments)
5. Learning & Governance Layer (`pattern_object`, `promotion_decision`)
6. Eval & Release Layer (`planner_eval_record`, `active_runtime_manifest`)

## Contract-First Design
- All primary artifacts are schema-validated JSON contracts.
- Main chain writes immutable runtime artifacts to `runtime/revenue_os`.
- Release gate controls promotion to active runtime.

## Integration Boundary
- Revenue OS exposes stable read interfaces to knowledge skill.
- Knowledge skill does not write back into Revenue OS main runtime artifacts.
