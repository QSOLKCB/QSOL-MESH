#!/usr/bin/env python3
"""Validate this immutable Phase 5 capture, not arbitrary receipts or live CUDA."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'evidence/phase5-cuda-host-2026-09-23'
MANIFEST_SHA256 = '1395b39691e5cd5325bc609888f57c57fceadbae5df2532882415fbc94f9bac9'
SOURCE = '4ea2225658e8e2eba0a7ea91cba59b230637b200'
CAPTURED = '2026-09-23T22:37:27Z'
REQUEST = {
    'command': 'verify', 'phase_items': [1000, 100000, 10000],
    'calibration_items': 10000, 'repeats': 3, 'near_tie_bps': 500,
    'cuda': True, 'device_ordinal': 0,
}
TOPOLOGY = {
    'available_cpu_workers': 32, 'device_ordinal': 0,
    'accelerator_observed': True, 'cuda_compute_major': 12,
    'cuda_compute_minor': 0, 'cuda_runtime_version': 12040,
    'cuda_driver_version': 13020, 'cuda_topology_source': 'canonical-helper-reported',
}
CANDIDATES = [
    {'id': 0, 'backend': 'cpu', 'cpu_workers': 1, 'accelerator_share_bps': 0, 'canonical': True},
    {'id': 1, 'backend': 'cpu', 'cpu_workers': 32, 'accelerator_share_bps': 0, 'canonical': False},
    {'id': 2, 'backend': 'accelerator', 'cpu_workers': 0, 'accelerator_share_bps': 10000, 'canonical': False},
    {'id': 3, 'backend': 'heterogeneous-static', 'cpu_workers': 32, 'accelerator_share_bps': 5000, 'canonical': False},
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


@lru_cache(maxsize=3)
def oracle(items):
    """Independent scalar calculation; called only with bound capture work sizes."""
    mask = (1 << 64) - 1
    total = 0
    for i in range(items):
        x = i ^ 0x4d4553485f534d4b
        x = ((x ^ (x >> 30)) * 0xbf58476d1ce4e5b9) & mask
        x = ((x ^ (x >> 27)) * 0x94d049bb133111eb) & mask
        total = (total + (x ^ (x >> 31))) & mask
    return f'{total:016x}'


def validate_receipt(r):
    """Semantic checks for this capture, separate from immutable byte checks."""
    required = set(json.loads((ROOT / 'machine/evidence-contract.v1.json').read_text())['receipt_required_sections'])
    require(required <= r.keys(), 'missing common evidence section')
    require(r['schema'] == 'qsol.mesh.phase-runtime-receipt.v1', 'phase receipt schema')
    require(r['source_identity'] == {'runtime': 'qsol-mesh-cli', 'contract': 'qsol.mesh.phase-runtime-contract.v1'}, 'runtime identity')
    require(r['workload_identity'] == {'workload_id': 'mesh-smoke-phases-v1', 'workload_contract_version': '1.0.0'}, 'phase workload identity')
    require(r['requested_configuration'] == REQUEST, 'capture request mismatch')
    require(r['observed_topology'] == {'available_cpu_workers': 32, 'accelerator_observed': True, 'details': 'per-phase-calibration-receipts'}, 'phase topology')
    require(r['memory_plan'] == {'per_item_materialization': False, 'phase_state_bound': 64, 'persistent_cuda_context': False}, 'phase memory scope')
    require(r['calibration'] == {
        'performed_before_every_phase': True, 'candidate_budget_per_phase': 4, 'cached': False,
        'calibration_host_scope': 'calibrator-call-plus-plan-validation',
        'execution_host_scope': 'selected-executor-call-plus-phase-oracle-validation',
    }, 'phase calibration scope')
    e = r['effective_execution']
    require(e['kind'] == 'phase-boundary-replanning-and-execution' and e['within_phase_replanning'] is False, 'execution scope')
    phases = e['phases']
    require(len(phases) == e['completed_phases'] == len(REQUEST['phase_items']), 'phase count')
    total, changes, previous = 0, 0, None
    for index, (phase, items) in enumerate(zip(phases, REQUEST['phase_items'])):
        require(phase['phase_index'] == index and phase['items'] == items, 'phase order or size')
        c = phase['calibration_receipt']
        require(required <= c.keys(), 'missing calibration evidence section')
        require(c['schema'] == 'qsol.mesh.calibrated-plan-receipt.v2', 'calibration schema')
        require(c['source_identity'] == {'runtime': 'qsol-mesh-cli', 'plan_identity': 'mesh-calibration-smoke-v1', 'plan_version': '2.0.0'}, 'calibration identity')
        require(c['workload_identity'] == {'workload_id': 'mesh-smoke-v1'}, 'calibration workload')
        calibration_items = min(REQUEST['calibration_items'], items)
        require(c['requested_configuration'] == {
            'calibration_items': calibration_items, 'full_work_items': items,
            'repeats': REQUEST['repeats'], 'near_tie_bps': REQUEST['near_tie_bps'],
            'device_ordinal': REQUEST['device_ordinal'],
        }, 'calibration request binding')
        require(c['observed_topology'] == TOPOLOGY, 'CUDA topology continuity')
        require(c['memory_plan'] == {'physical_memory_claim': False}, 'calibration memory scope')
        cal = c['calibration']
        require(cal['candidate_budget'] == 4 and cal['candidates'] == CANDIDATES, 'candidate set')
        require(cal['cost_scopes'] == {
            'cpu': 'run_smoke-end-to-end',
            'accelerator': 'median-sample-launcher-plus-verification-host-wall-partitioned-by-nested-setup-and-D2H',
            'heterogeneous-static': 'full-static-call-end-to-end',
        } and cal['cross_clock_kernel_timing_added'] is False, 'calibration clock scopes')
        observations, confirmation = cal['observations'], cal['full_work_confirmation']
        require(len(observations) == 4 and {o['candidate_id'] for o in observations} == {0, 1, 2, 3}, 'candidate observation coverage')
        require(len(confirmation) == 1 and confirmation[0]['candidate_id'] == 0, 'full-work confirmation coverage')
        for batch, work in ((observations, calibration_items), (confirmation, items)):
            for o in batch:
                require(o['work_units'] == work, 'measurement work binding')
                require(o['verified'] is True and o['checksum'] == oracle(work), 'measurement scalar oracle')
                require(o['effective_cpu_workers'] == CANDIDATES[o['candidate_id']]['cpu_workers'], 'measurement workers')
                require(all(type(o[k]) is int and o[k] >= 0 for k in ('service_ns', 'setup_ns', 'transfer_ns', 'total_ns')), 'measurement timing domain')
                require(o['total_ns'] == o['service_ns'] + o['setup_ns'] + o['transfer_ns'], 'cost arithmetic')
        winner = min(observations, key=lambda o: (o['total_ns'], o['candidate_id']))
        require(winner['candidate_id'] == 0, 'captured canonical is not lowest cost')
        require(c['effective_execution'] == {
            'kind': 'calibration-and-planning', 'provisional_candidate_id': 0,
            'selected_candidate_id': 0, 'canonical_candidate_id': 0,
            'canonical_retained': True,
            'selection_reason': 'canonical-kept-after-calibration-near-tie',
            'selected_requested_cpu_workers': 1, 'selected_effective_cpu_workers': 1,
        }, 'canonical selection')
        require(c['verification'] == {'kind': 'scalar-oracle-plus-full-work-confirmation', 'verified': True}, 'calibration verification')
        require(c['claim_boundary'] == 'host-specific-helper-reported-CUDA-calibration-not-universal-performance-or-kernel-overlap-evidence', 'calibration claim boundary')
        selected = CANDIDATES[c['effective_execution']['selected_candidate_id']]
        changed = previous is not None and previous != selected
        require(phase['plan_changed'] is changed, 'phase change flag')
        changes += changed
        previous = selected
        checksum = oracle(items)
        require(phase['execution'] == {
            'backend': selected['backend'], 'requested_cpu_workers': selected['cpu_workers'],
            'effective_cpu_workers': 1, 'cpu_items': items, 'cuda_items': 0,
            'checksum': checksum, 'reference': checksum, 'verified': True,
        }, 'selected phase execution or scalar oracle')
        require(all(type(phase[k]) is int and phase[k] > 0 for k in ('calibration_host_ns', 'execution_host_ns')), 'phase timing domain')
        total = (total + int(checksum, 16)) & ((1 << 64) - 1)
    require(e['plan_changes'] == changes == 0, 'plan change count')
    require(r['verification'] == {
        'kind': 'per-phase-scalar-oracle-and-phase-order-wrapping-u64',
        'checksum': f'{total:016x}', 'reference': f'{total:016x}', 'verified': True,
    }, 'aggregate oracle')
    require(r['claim_boundary'] == 'bounded-phase-boundary-replanning-only-not-work-stealing-kernel-overlap-or-universal-speedup', 'phase claim boundary')


def validate(directory=EVIDENCE):
    raw = (directory / 'manifest.json').read_bytes()
    require(hashlib.sha256(raw).hexdigest() == MANIFEST_SHA256, 'retained manifest digest mismatch')
    manifest = json.loads(raw)
    require(manifest['schema'] == 'qsol.mesh.retained-phase5-evidence.v1' and manifest['source_commit'] == SOURCE and manifest['captured_utc'] == CAPTURED, 'manifest provenance')
    require(set(manifest['files']) == {'adaptive.json', 'environment.txt', 'SHA256SUMS'}, 'capture file set')
    for name, digest in manifest['files'].items():
        require(hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest, f'retained evidence changed: {name}')
    sums = [line.split() for line in (directory / 'SHA256SUMS').read_text().splitlines()]
    require(sums == [[manifest['files'][name], name] for name in ('adaptive.json', 'environment.txt')], 'capture hash manifest')
    environment = (directory / 'environment.txt').read_text().splitlines()
    require(f'source_commit={SOURCE}' in environment and f'captured_utc={CAPTURED}' in environment and 'nvcc_path=/usr/bin/nvcc' in environment, 'capture environment provenance')
    validate_receipt(json.loads((directory / 'adaptive.json').read_text()))
    boundary = json.loads((ROOT / 'machine/phase-runtime-contract.v1.json').read_text())['evidence_boundary']
    require(boundary['cuda_host_evidence_status'] == 'retained-capture-at-4ea2225'
            and boundary['retained_evidence_manifest'] == str(EVIDENCE.relative_to(ROOT) / 'manifest.json')
            and boundary['selected_cuda_phase_execution_observed'] is False
            and boundary['plan_changes_observed'] == 0, 'contract evidence status mismatch')


if __name__ == '__main__':
    validate()
    print('Retained Phase 5 CUDA-host evidence: valid (three CPU-selected phases, zero plan changes)')
