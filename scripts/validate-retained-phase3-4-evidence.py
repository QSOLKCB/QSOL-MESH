#!/usr/bin/env python3
"""Validate immutable uploaded CUDA captures; this does not execute CUDA in CI."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'evidence/phase3-4-cuda-host-2026-09-23'
MANIFEST_SHA256 = '902ce9b4d086834e7bf5e2c5923cf398cd153441ae777c5786089778cdef98fd'
SOURCE = '69280c4c5d7553cf0fa17f8ddaae34f07dcceddb'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def oracle(items):
    mask = (1 << 64) - 1
    total = 0
    for i in range(items):
        x = i ^ 0x4d4553485f534d4b
        x = ((x ^ (x >> 30)) * 0xbf58476d1ce4e5b9) & mask
        x = ((x ^ (x >> 27)) * 0x94d049bb133111eb) & mask
        total = (total + (x ^ (x >> 31))) & mask
    return f'{total:016x}'


def validate(directory=EVIDENCE):
    raw = (directory / 'manifest.json').read_bytes()
    require(hashlib.sha256(raw).hexdigest() == MANIFEST_SHA256, 'retained manifest digest mismatch')
    manifest = json.loads(raw)
    require(manifest['source_commit'] == SOURCE, 'source commit mismatch')
    for name, digest in manifest['files'].items():
        require(hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest,
                f'retained evidence changed: {name}')
    required = set(json.loads((ROOT / 'machine/evidence-contract.v1.json').read_text())['receipt_required_sections'])
    for path in directory.rglob('SHA256SUMS'):
        for line in path.read_text().splitlines():
            digest, name = line.split()
            require(hashlib.sha256((path.parent / name).read_bytes()).hexdigest() == digest,
                    f'capture hash mismatch: {path.parent / name}')
    for path in directory.rglob('environment.txt'):
        require(f'source_commit={SOURCE}' in path.read_text(), 'capture source mismatch')
    for path in directory.rglob('*.json'):
        if path.name == 'manifest.json':
            continue
        r = json.loads(path.read_text())
        require(required <= r.keys() and r['verification']['verified'] is True, 'incomplete receipt')
        if 'checksum' in r['verification']:
            require(r['verification']['checksum'] == r['verification']['reference'] == oracle(r['requested_configuration']['items']), 'scalar oracle mismatch')
        if path.name in ('one-chunk.json', 'multi-chunk.json'):
            q, e, m = r['requested_configuration'], r['effective_execution'], r['memory_plan']
            chunk = min(q['items'], q['requested_chunk_items'], (q['host_pinned_limit_bytes'] - 8) // 8, (q['accelerator_limit_bytes'] - 8) // 8)
            count = (q['items'] + chunk - 1) // chunk
            require(r['workload_identity']['workload_id'] == 'mesh-smoke-stream-v1', 'stream workload mismatch')
            require(e['effective_chunk_items'] == chunk and e['chunk_count'] == count and e['event_records'] == 3 * count, 'stream geometry mismatch')
            require(m['physically_materialized'] and m['reuse_across_chunks'], 'physical reuse missing')
            require(m['host_pinned_peak_bytes'] == m['accelerator_peak_bytes'] == chunk * 8 + 8, 'physical peak mismatch')
            require(all(m[k] == 1 for k in ('pinned_staging_allocations', 'pinned_partial_allocations', 'device_pool_allocations', 'device_partial_allocations')), 'allocation count mismatch')
        if path.name == 'timing.json':
            t = r['timing']
            require(t['setup_host_ns'] + t['transfer_host_ns'] + t['teardown_host_ns'] <= t['worker_total_ns'] <= t['launcher_total_ns'], 'timing bounds invalid')
        if path.name == 'calibration.json':
            c, e = r['calibration'], r['effective_execution']
            candidates = {p['id']: p for p in c['candidates']}
            require(len(candidates) == 4 and {o['candidate_id'] for o in c['observations']} == candidates.keys(), 'candidate evidence incomplete')
            for o in c['observations'] + c['full_work_confirmation']:
                require(o['verified'] and o['checksum'] == oracle(o['work_units']), 'calibration oracle mismatch')
                require(o['total_ns'] == sum(o[k] for k in ('service_ns', 'setup_ns', 'transfer_ns')), 'cost arithmetic mismatch')
            winner = min(c['observations'], key=lambda o: (o['total_ns'], o['candidate_id']))
            require(winner['candidate_id'] == e['selected_candidate_id'] == e['canonical_candidate_id'] == 0 and e['canonical_retained'], 'canonical selection mismatch')
            require(len(c['full_work_confirmation']) == 1 and c['full_work_confirmation'][0]['candidate_id'] == 0 and c['full_work_confirmation'][0]['work_units'] == 100000, 'full work confirmation missing')


if __name__ == '__main__':
    validate()
    print('Retained Phase 3 streaming and Phase 4 calibration evidence: valid (two captures)')
