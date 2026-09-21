## Contract impact

- Exact base/head SHA:
- Machine contract files changed:
- Existing invariant IDs affected:
- New invariant IDs:
- Workload semantic change: yes/no
- Memory-domain change: yes/no
- Evidence-schema change: yes/no

## Validation

- [ ] `python3 scripts/validate-contracts.py`
- [ ] `cargo fmt --all --check`
- [ ] `cargo test --workspace --locked`
- [ ] `cargo clippy --workspace --all-targets --locked -- -D warnings`

## AI review instruction

Review this exact SHA against the existing contract. Report only actionable correctness defects, with a minimal reproduction, expected versus actual behavior, and affected lines. State whether each reproduction was executed or statically inferred. Don’t repeat fixed findings without a new failing case. Keep architectural suggestions separate and non-blocking.

Normative policy: `machine/agent-review-policy.v1.json`.
