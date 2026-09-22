// SPDX-License-Identifier: Apache-2.0
//! Deterministic calibrated planning.
//!
//! Candidate generation is topology-derived and bounded. Selection is driven by
//! measured cost evidence only. Hardware names are never performance authority.

use crate::{run_smoke, SMOKE_WORKLOAD_ID};
use std::time::Instant;

pub const CALIBRATED_PLAN_SCHEMA: &str = "qsol.mesh.calibrated-plan.v1";
pub const CALIBRATED_PLAN_RECEIPT_SCHEMA: &str = "qsol.mesh.calibrated-plan-receipt.v1";
pub const CALIBRATED_PLAN_ID: &str = "mesh-calibration-smoke-v1";
pub const CANDIDATE_BUDGET: usize = 4;
pub const DEFAULT_NEAR_TIE_BPS: u32 = 500;
pub const CALIBRATED_PLAN_CLAIM_BOUNDARY: &str =
    "host-specific-measured-planning-not-universal-performance-evidence";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BackendKind {
    Cpu,
    Accelerator,
    HeterogeneousStatic,
}

impl BackendKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Cpu => "cpu",
            Self::Accelerator => "accelerator",
            Self::HeterogeneousStatic => "heterogeneous-static",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TopologyObservation {
    pub available_cpu_workers: usize,
    pub accelerator_observed: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CandidatePlan {
    pub id: u32,
    pub backend: BackendKind,
    pub cpu_workers: usize,
    pub accelerator_share_bps: u32,
    pub canonical: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CostObservation {
    pub candidate_id: u32,
    pub work_units: u64,
    pub effective_cpu_workers: usize,
    pub service_ns: u128,
    pub setup_ns: u128,
    pub transfer_ns: u128,
    pub checksum: u64,
    pub verified: bool,
}

impl CostObservation {
    pub fn total_ns(self) -> Result<u128, &'static str> {
        self.service_ns
            .checked_add(self.setup_ns)
            .and_then(|value| value.checked_add(self.transfer_ns))
            .ok_or("calibration cost arithmetic overflow")
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CalibrationRequest {
    pub calibration_units: u64,
    pub full_work_units: u64,
    pub repeats: usize,
    pub near_tie_bps: u32,
}

impl CalibrationRequest {
    pub const fn new(
        calibration_units: u64,
        full_work_units: u64,
        repeats: usize,
        near_tie_bps: u32,
    ) -> Self {
        Self {
            calibration_units,
            full_work_units,
            repeats,
            near_tie_bps,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CalibratedPlan {
    pub topology: TopologyObservation,
    pub candidates: Vec<CandidatePlan>,
    pub calibration: Vec<CostObservation>,
    pub confirmation: Vec<CostObservation>,
    pub calibration_units: u64,
    pub full_work_units: u64,
    pub repeats: usize,
    pub near_tie_bps: u32,
    pub provisional_candidate_id: u32,
    pub selected_candidate_id: u32,
    pub canonical_candidate_id: u32,
    pub canonical_retained: bool,
    pub selection_reason: &'static str,
}

fn push_candidate(
    candidates: &mut Vec<CandidatePlan>,
    backend: BackendKind,
    cpu_workers: usize,
    accelerator_share_bps: u32,
    canonical: bool,
) -> Result<(), &'static str> {
    if candidates.len() >= CANDIDATE_BUDGET {
        return Err("candidate budget exceeded");
    }
    let id = u32::try_from(candidates.len()).map_err(|_| "candidate ID overflow")?;
    candidates.push(CandidatePlan {
        id,
        backend,
        cpu_workers,
        accelerator_share_bps,
        canonical,
    });
    Ok(())
}

pub fn derive_candidates(
    topology: TopologyObservation,
) -> Result<Vec<CandidatePlan>, &'static str> {
    if topology.available_cpu_workers == 0 {
        return Err("observed CPU worker capacity must be greater than zero");
    }

    let mut candidates = Vec::with_capacity(CANDIDATE_BUDGET);
    push_candidate(&mut candidates, BackendKind::Cpu, 1, 0, true)?;

    if topology.available_cpu_workers > 1 {
        push_candidate(
            &mut candidates,
            BackendKind::Cpu,
            topology.available_cpu_workers,
            0,
            false,
        )?;
    }

    if topology.accelerator_observed {
        push_candidate(&mut candidates, BackendKind::Accelerator, 0, 10_000, false)?;
        push_candidate(
            &mut candidates,
            BackendKind::HeterogeneousStatic,
            topology.available_cpu_workers,
            5_000,
            false,
        )?;
    }

    Ok(candidates)
}

fn canonical_candidate(candidates: &[CandidatePlan]) -> Result<CandidatePlan, &'static str> {
    let mut canonical = candidates
        .iter()
        .copied()
        .filter(|candidate| candidate.canonical);
    let Some(first) = canonical.next() else {
        return Err("candidate set requires one canonical plan");
    };
    if canonical.next().is_some() {
        return Err("candidate set must contain exactly one canonical plan");
    }
    Ok(first)
}

fn candidate_by_id(candidates: &[CandidatePlan], candidate_id: u32) -> Option<CandidatePlan> {
    candidates
        .iter()
        .copied()
        .find(|candidate| candidate.id == candidate_id)
}

fn observation_by_id(
    observations: &[CostObservation],
    candidate_id: u32,
) -> Option<CostObservation> {
    observations
        .iter()
        .copied()
        .find(|observation| observation.candidate_id == candidate_id)
}

fn validate_candidate_set(
    topology: TopologyObservation,
    candidates: &[CandidatePlan],
) -> Result<CandidatePlan, &'static str> {
    if candidates.is_empty() {
        return Err("candidate set must not be empty");
    }
    if candidates.len() > CANDIDATE_BUDGET {
        return Err("candidate budget exceeded");
    }
    for (index, candidate) in candidates.iter().enumerate() {
        if candidate.id != index as u32 {
            return Err("candidate IDs must be contiguous deterministic indices");
        }
        match candidate.backend {
            BackendKind::Cpu => {
                if candidate.cpu_workers == 0
                    || candidate.cpu_workers > topology.available_cpu_workers
                    || candidate.accelerator_share_bps != 0
                {
                    return Err("CPU candidate exceeds observed topology");
                }
            }
            BackendKind::Accelerator => {
                if !topology.accelerator_observed
                    || candidate.cpu_workers != 0
                    || candidate.accelerator_share_bps != 10_000
                {
                    return Err("accelerator candidate lacks observed topology");
                }
            }
            BackendKind::HeterogeneousStatic => {
                if !topology.accelerator_observed
                    || candidate.cpu_workers == 0
                    || candidate.cpu_workers > topology.available_cpu_workers
                    || candidate.accelerator_share_bps == 0
                    || candidate.accelerator_share_bps >= 10_000
                {
                    return Err("heterogeneous candidate exceeds observed topology");
                }
            }
        }
    }
    canonical_candidate(candidates)
}

fn validate_observations(
    candidates: &[CandidatePlan],
    observations: &[CostObservation],
    work_units: u64,
    require_all_candidates: bool,
) -> Result<(), &'static str> {
    if work_units == 0 {
        return Err("calibration work units must be greater than zero");
    }
    for (index, observation) in observations.iter().enumerate() {
        if observations[..index]
            .iter()
            .any(|previous| previous.candidate_id == observation.candidate_id)
        {
            return Err("candidate observation IDs must be unique");
        }
        let Some(candidate) = candidate_by_id(candidates, observation.candidate_id) else {
            return Err("observation references unknown candidate");
        };
        if observation.work_units != work_units {
            return Err("observation work units do not match phase");
        }
        if !observation.verified {
            return Err("unverified cost observation is not admissible");
        }
        match candidate.backend {
            BackendKind::Cpu => {
                if observation.setup_ns != 0 || observation.transfer_ns != 0 {
                    return Err(
                        "CPU smoke observations require zero separate setup and transfer cost",
                    );
                }
                let effective_as_u64 =
                    u64::try_from(observation.effective_cpu_workers).unwrap_or(u64::MAX);
                if observation.effective_cpu_workers == 0
                    || observation.effective_cpu_workers > candidate.cpu_workers
                    || effective_as_u64 > observation.work_units
                {
                    return Err("CPU observation effective workers exceed measured execution");
                }
            }
            BackendKind::Accelerator => {
                if observation.effective_cpu_workers != 0 {
                    return Err("accelerator observation must not report CPU workers");
                }
            }
            BackendKind::HeterogeneousStatic => {
                if observation.effective_cpu_workers == 0
                    || observation.effective_cpu_workers > candidate.cpu_workers
                {
                    return Err("heterogeneous observation CPU workers exceed candidate");
                }
            }
        }
        observation.total_ns()?;
    }

    if require_all_candidates && observations.len() != candidates.len() {
        return Err("calibration requires one observation per candidate");
    }
    if require_all_candidates {
        for candidate in candidates {
            if observation_by_id(observations, candidate.id).is_none() {
                return Err("calibration observation missing candidate");
            }
        }
    }
    Ok(())
}

fn best_observed_candidate(
    candidates: &[CandidatePlan],
    observations: &[CostObservation],
) -> Result<u32, &'static str> {
    let mut best: Option<(u128, u32)> = None;
    for candidate in candidates {
        let observation =
            observation_by_id(observations, candidate.id).ok_or("candidate observation missing")?;
        let total = observation.total_ns()?;
        match best {
            None => best = Some((total, candidate.id)),
            Some((best_total, best_id))
                if total < best_total || (total == best_total && candidate.id < best_id) =>
            {
                best = Some((total, candidate.id));
            }
            _ => {}
        }
    }
    best.map(|(_, id)| id)
        .ok_or("candidate set must not be empty")
}

fn materially_faster(
    candidate_ns: u128,
    canonical_ns: u128,
    near_tie_bps: u32,
) -> Result<bool, &'static str> {
    if near_tie_bps >= 10_000 {
        return Err("near-tie basis points must be less than 10000");
    }
    if candidate_ns >= canonical_ns {
        return Ok(false);
    }
    let improvement = canonical_ns - candidate_ns;
    let lhs = improvement
        .checked_mul(10_000)
        .ok_or("near-tie arithmetic overflow")?;
    let rhs = canonical_ns
        .checked_mul(u128::from(near_tie_bps))
        .ok_or("near-tie arithmetic overflow")?;
    Ok(lhs > rhs)
}

fn checksums_match_canonical(
    canonical_id: u32,
    observations: &[CostObservation],
) -> Result<(), &'static str> {
    let canonical =
        observation_by_id(observations, canonical_id).ok_or("canonical observation missing")?;
    for observation in observations {
        if observation.checksum != canonical.checksum {
            return Err("candidate checksum does not match canonical result");
        }
    }
    Ok(())
}

pub fn select_calibrated_plan(
    topology: TopologyObservation,
    candidates: Vec<CandidatePlan>,
    calibration: Vec<CostObservation>,
    confirmation: Vec<CostObservation>,
    request: CalibrationRequest,
) -> Result<CalibratedPlan, &'static str> {
    if request.repeats == 0 {
        return Err("calibration repeats must be greater than zero");
    }
    if request.full_work_units < request.calibration_units {
        return Err("full-work confirmation must not be smaller than calibration");
    }
    if request.near_tie_bps >= 10_000 {
        return Err("near-tie basis points must be less than 10000");
    }

    let canonical = validate_candidate_set(topology, &candidates)?;
    validate_observations(&candidates, &calibration, request.calibration_units, true)?;
    checksums_match_canonical(canonical.id, &calibration)?;

    let calibration_winner = best_observed_candidate(&candidates, &calibration)?;
    let canonical_calibration =
        observation_by_id(&calibration, canonical.id).ok_or("canonical calibration missing")?;
    let winner_calibration =
        observation_by_id(&calibration, calibration_winner).ok_or("calibration winner missing")?;

    let provisional = if calibration_winner == canonical.id
        || !materially_faster(
            winner_calibration.total_ns()?,
            canonical_calibration.total_ns()?,
            request.near_tie_bps,
        )? {
        canonical.id
    } else {
        calibration_winner
    };

    let required_confirmation_ids: Vec<u32> = if provisional == canonical.id {
        vec![canonical.id]
    } else {
        vec![canonical.id, provisional]
    };
    validate_observations(&candidates, &confirmation, request.full_work_units, false)?;
    if confirmation.len() != required_confirmation_ids.len() {
        return Err("full-work confirmation contains unexpected candidates");
    }
    for candidate_id in &required_confirmation_ids {
        if observation_by_id(&confirmation, *candidate_id).is_none() {
            return Err("full-work confirmation missing required candidate");
        }
    }
    checksums_match_canonical(canonical.id, &confirmation)?;

    let (selected, reason) = if provisional == canonical.id {
        (canonical.id, "canonical-kept-after-calibration-near-tie")
    } else {
        let canonical_full = observation_by_id(&confirmation, canonical.id)
            .ok_or("canonical full-work confirmation missing")?;
        let provisional_full = observation_by_id(&confirmation, provisional)
            .ok_or("provisional full-work confirmation missing")?;
        if materially_faster(
            provisional_full.total_ns()?,
            canonical_full.total_ns()?,
            request.near_tie_bps,
        )? {
            (provisional, "promoted-after-full-work-confirmation")
        } else {
            (canonical.id, "canonical-restored-after-full-work-near-tie")
        }
    };

    Ok(CalibratedPlan {
        topology,
        candidates,
        calibration,
        confirmation,
        calibration_units: request.calibration_units,
        full_work_units: request.full_work_units,
        repeats: request.repeats,
        near_tie_bps: request.near_tie_bps,
        provisional_candidate_id: provisional,
        selected_candidate_id: selected,
        canonical_candidate_id: canonical.id,
        canonical_retained: selected == canonical.id,
        selection_reason: reason,
    })
}

fn median(values: &mut [u128]) -> Result<u128, &'static str> {
    if values.is_empty() {
        return Err("timing sample set must not be empty");
    }
    values.sort_unstable();
    let middle = values.len() / 2;
    if values.len() % 2 == 0 {
        let low = values[middle - 1];
        let high = values[middle];
        Ok(low + (high - low) / 2)
    } else {
        Ok(values[middle])
    }
}

fn measure_cpu_smoke(
    candidate: CandidatePlan,
    items: u64,
    repeats: usize,
) -> Result<CostObservation, &'static str> {
    if candidate.backend != BackendKind::Cpu {
        return Err("CPU smoke probe cannot execute non-CPU candidate");
    }
    if repeats == 0 {
        return Err("calibration repeats must be greater than zero");
    }

    let mut timings = Vec::new();
    timings
        .try_reserve_exact(repeats)
        .map_err(|_| "timing sample allocation failed")?;
    let mut checksum = None;
    let mut effective_cpu_workers = None;
    for _ in 0..repeats {
        let started = Instant::now();
        let run = run_smoke(items, candidate.cpu_workers)?;
        let elapsed = started.elapsed().as_nanos();
        if let Some(expected) = checksum {
            if run.checksum != expected {
                return Err("CPU calibration checksum changed between repeats");
            }
        } else {
            checksum = Some(run.checksum);
        }
        if let Some(expected) = effective_cpu_workers {
            if run.effective_workers != expected {
                return Err("CPU effective worker count changed between repeats");
            }
        } else {
            effective_cpu_workers = Some(run.effective_workers);
        }
        timings.push(elapsed);
    }

    Ok(CostObservation {
        candidate_id: candidate.id,
        work_units: items,
        effective_cpu_workers: effective_cpu_workers
            .ok_or("missing CPU effective worker observation")?,
        service_ns: median(&mut timings)?,
        setup_ns: 0,
        transfer_ns: 0,
        checksum: checksum.ok_or("missing CPU calibration checksum")?,
        verified: true,
    })
}

pub fn calibrate_cpu_smoke_host(
    available_cpu_workers: usize,
    calibration_items: u64,
    full_work_items: u64,
    repeats: usize,
    near_tie_bps: u32,
) -> Result<CalibratedPlan, &'static str> {
    let topology = TopologyObservation {
        available_cpu_workers,
        accelerator_observed: false,
    };
    let candidates = derive_candidates(topology)?;

    let mut calibration = Vec::new();
    calibration
        .try_reserve_exact(candidates.len())
        .map_err(|_| "calibration observation allocation failed")?;
    for candidate in &candidates {
        calibration.push(measure_cpu_smoke(*candidate, calibration_items, repeats)?);
    }

    let canonical = canonical_candidate(&candidates)?;
    let calibration_winner = best_observed_candidate(&candidates, &calibration)?;
    let canonical_observation =
        observation_by_id(&calibration, canonical.id).ok_or("canonical calibration missing")?;
    let winner_observation =
        observation_by_id(&calibration, calibration_winner).ok_or("calibration winner missing")?;
    let provisional = if calibration_winner == canonical.id
        || !materially_faster(
            winner_observation.total_ns()?,
            canonical_observation.total_ns()?,
            near_tie_bps,
        )? {
        canonical.id
    } else {
        calibration_winner
    };

    let mut confirmation = vec![measure_cpu_smoke(canonical, full_work_items, repeats)?];
    if provisional != canonical.id {
        let candidate =
            candidate_by_id(&candidates, provisional).ok_or("provisional candidate missing")?;
        confirmation.push(measure_cpu_smoke(candidate, full_work_items, repeats)?);
    }

    select_calibrated_plan(
        topology,
        candidates,
        calibration,
        confirmation,
        CalibrationRequest::new(calibration_items, full_work_items, repeats, near_tie_bps),
    )
}

fn candidate_json(candidate: CandidatePlan) -> String {
    format!(
        "{{\"id\":{},\"backend\":\"{}\",\"cpu_workers\":{},\"accelerator_share_bps\":{},\"canonical\":{}}}",
        candidate.id,
        candidate.backend.as_str(),
        candidate.cpu_workers,
        candidate.accelerator_share_bps,
        candidate.canonical
    )
}

fn observation_json(observation: CostObservation) -> Result<String, &'static str> {
    Ok(format!(
        "{{\"candidate_id\":{},\"work_units\":{},\"effective_cpu_workers\":{},\"service_ns\":{},\"setup_ns\":{},\"transfer_ns\":{},\"total_ns\":{},\"checksum\":\"{:016x}\",\"verified\":{}}}",
        observation.candidate_id,
        observation.work_units,
        observation.effective_cpu_workers,
        observation.service_ns,
        observation.setup_ns,
        observation.transfer_ns,
        observation.total_ns()?,
        observation.checksum,
        observation.verified
    ))
}

pub fn validate_calibrated_plan(plan: &CalibratedPlan) -> Result<(), &'static str> {
    let rebuilt = select_calibrated_plan(
        plan.topology,
        plan.candidates.clone(),
        plan.calibration.clone(),
        plan.confirmation.clone(),
        CalibrationRequest::new(
            plan.calibration_units,
            plan.full_work_units,
            plan.repeats,
            plan.near_tie_bps,
        ),
    )?;
    if &rebuilt != plan {
        return Err("calibrated plan derived state mismatch");
    }
    Ok(())
}

pub fn calibrated_plan_receipt_json(plan: &CalibratedPlan) -> Result<String, &'static str> {
    validate_calibrated_plan(plan)?;
    let selected_candidate = candidate_by_id(&plan.candidates, plan.selected_candidate_id)
        .ok_or("selected candidate missing")?;
    let selected_confirmation = observation_by_id(&plan.confirmation, plan.selected_candidate_id)
        .ok_or("selected full-work confirmation missing")?;
    let candidates = plan
        .candidates
        .iter()
        .copied()
        .map(candidate_json)
        .collect::<Vec<_>>()
        .join(",");
    let calibration = plan
        .calibration
        .iter()
        .copied()
        .map(observation_json)
        .collect::<Result<Vec<_>, _>>()?
        .join(",");
    let confirmation = plan
        .confirmation
        .iter()
        .copied()
        .map(observation_json)
        .collect::<Result<Vec<_>, _>>()?
        .join(",");

    Ok(format!(
        "{{\"schema\":\"{CALIBRATED_PLAN_RECEIPT_SCHEMA}\",\"source_identity\":{{\"runtime\":\"qsol-mesh-cli\",\"plan_schema\":\"{CALIBRATED_PLAN_SCHEMA}\",\"plan_version\":\"1.0.0\",\"plan_identity\":\"{CALIBRATED_PLAN_ID}\"}},\"workload_identity\":{{\"workload_id\":\"{SMOKE_WORKLOAD_ID}\",\"workload_contract_version\":\"1.0.0\"}},\"requested_configuration\":{{\"calibration_items\":{},\"full_work_items\":{},\"repeats\":{},\"near_tie_bps\":{}}},\"observed_topology\":{{\"available_cpu_workers\":{},\"accelerator_observed\":{}}},\"effective_execution\":{{\"kind\":\"calibration-and-planning\",\"selected_candidate_id\":{},\"canonical_candidate_id\":{},\"canonical_retained\":{},\"selection_reason\":\"{}\",\"selected_requested_cpu_workers\":{},\"selected_effective_cpu_workers\":{}}},\"memory_plan\":{{\"kind\":\"not-applicable-to-smoke-calibration\",\"physical_memory_claim\":false}},\"calibration\":{{\"candidate_budget\":{CANDIDATE_BUDGET},\"candidate_count\":{},\"provisional_candidate_id\":{},\"candidates\":[{}],\"observations\":[{}],\"full_work_confirmation\":[{}]}},\"verification\":{{\"kind\":\"canonical-checksum-equality-plus-full-work-confirmation\",\"verified\":true}},\"claim_boundary\":\"{CALIBRATED_PLAN_CLAIM_BOUNDARY}\"}}",
        plan.calibration_units,
        plan.full_work_units,
        plan.repeats,
        plan.near_tie_bps,
        plan.topology.available_cpu_workers,
        plan.topology.accelerator_observed,
        plan.selected_candidate_id,
        plan.canonical_candidate_id,
        plan.canonical_retained,
        plan.selection_reason,
        selected_candidate.cpu_workers,
        selected_confirmation.effective_cpu_workers,
        plan.candidates.len(),
        plan.provisional_candidate_id,
        candidates,
        calibration,
        confirmation
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cpu_candidates() -> Vec<CandidatePlan> {
        derive_candidates(TopologyObservation {
            available_cpu_workers: 8,
            accelerator_observed: false,
        })
        .unwrap()
    }

    fn observation(candidate_id: u32, units: u64, total_ns: u128) -> CostObservation {
        CostObservation {
            candidate_id,
            work_units: units,
            effective_cpu_workers: if candidate_id == 0 { 1 } else { 8 },
            service_ns: total_ns,
            setup_ns: 0,
            transfer_ns: 0,
            checksum: 0x1234,
            verified: true,
        }
    }

    #[test]
    fn topology_candidate_set_is_bounded_and_deterministic() {
        let cpu = cpu_candidates();
        assert_eq!(
            cpu,
            vec![
                CandidatePlan {
                    id: 0,
                    backend: BackendKind::Cpu,
                    cpu_workers: 1,
                    accelerator_share_bps: 0,
                    canonical: true,
                },
                CandidatePlan {
                    id: 1,
                    backend: BackendKind::Cpu,
                    cpu_workers: 8,
                    accelerator_share_bps: 0,
                    canonical: false,
                },
            ]
        );

        let accelerated = derive_candidates(TopologyObservation {
            available_cpu_workers: 8,
            accelerator_observed: true,
        })
        .unwrap();
        assert_eq!(accelerated.len(), CANDIDATE_BUDGET);
        assert_eq!(accelerated[2].backend, BackendKind::Accelerator);
        assert_eq!(accelerated[3].backend, BackendKind::HeterogeneousStatic);
    }

    #[test]
    fn canonical_is_kept_on_calibration_near_tie() {
        let candidates = cpu_candidates();
        let plan = select_calibrated_plan(
            TopologyObservation {
                available_cpu_workers: 8,
                accelerator_observed: false,
            },
            candidates,
            vec![observation(0, 100, 1_000), observation(1, 100, 960)],
            vec![observation(0, 1_000, 10_000)],
            CalibrationRequest::new(100, 1_000, 1, 500),
        )
        .unwrap();
        assert_eq!(plan.selected_candidate_id, 0);
        assert!(plan.canonical_retained);
        assert_eq!(
            plan.selection_reason,
            "canonical-kept-after-calibration-near-tie"
        );
    }

    #[test]
    fn clear_calibration_and_full_work_win_promotes_candidate() {
        let candidates = cpu_candidates();
        let plan = select_calibrated_plan(
            TopologyObservation {
                available_cpu_workers: 8,
                accelerator_observed: false,
            },
            candidates,
            vec![observation(0, 100, 1_000), observation(1, 100, 700)],
            vec![observation(0, 1_000, 10_000), observation(1, 1_000, 7_000)],
            CalibrationRequest::new(100, 1_000, 1, 500),
        )
        .unwrap();
        assert_eq!(plan.provisional_candidate_id, 1);
        assert_eq!(plan.selected_candidate_id, 1);
        assert!(!plan.canonical_retained);
        assert_eq!(
            plan.selection_reason,
            "promoted-after-full-work-confirmation"
        );
    }

    #[test]
    fn full_work_near_tie_restores_canonical() {
        let candidates = cpu_candidates();
        let plan = select_calibrated_plan(
            TopologyObservation {
                available_cpu_workers: 8,
                accelerator_observed: false,
            },
            candidates,
            vec![observation(0, 100, 1_000), observation(1, 100, 700)],
            vec![observation(0, 1_000, 10_000), observation(1, 1_000, 9_700)],
            CalibrationRequest::new(100, 1_000, 1, 500),
        )
        .unwrap();
        assert_eq!(plan.provisional_candidate_id, 1);
        assert_eq!(plan.selected_candidate_id, 0);
        assert!(plan.canonical_retained);
        assert_eq!(
            plan.selection_reason,
            "canonical-restored-after-full-work-near-tie"
        );
    }

    #[test]
    fn unobserved_accelerator_candidate_fails_closed() {
        let topology = TopologyObservation {
            available_cpu_workers: 8,
            accelerator_observed: false,
        };
        let mut candidates = cpu_candidates();
        candidates.push(CandidatePlan {
            id: 2,
            backend: BackendKind::Accelerator,
            cpu_workers: 0,
            accelerator_share_bps: 10_000,
            canonical: false,
        });
        assert_eq!(
            validate_candidate_set(topology, &candidates),
            Err("accelerator candidate lacks observed topology")
        );
    }

    #[test]
    fn mismatched_or_unverified_measurements_fail_closed() {
        let candidates = cpu_candidates();
        let mut bad_checksum = observation(1, 100, 700);
        bad_checksum.checksum ^= 1;
        assert_eq!(
            select_calibrated_plan(
                TopologyObservation {
                    available_cpu_workers: 8,
                    accelerator_observed: false,
                },
                candidates.clone(),
                vec![observation(0, 100, 1_000), bad_checksum],
                vec![observation(0, 1_000, 10_000)],
                CalibrationRequest::new(100, 1_000, 1, 500),
            ),
            Err("candidate checksum does not match canonical result")
        );

        let mut unverified = observation(1, 100, 700);
        unverified.verified = false;
        assert_eq!(
            select_calibrated_plan(
                TopologyObservation {
                    available_cpu_workers: 8,
                    accelerator_observed: false,
                },
                candidates,
                vec![observation(0, 100, 1_000), unverified],
                vec![observation(0, 1_000, 10_000)],
                CalibrationRequest::new(100, 1_000, 1, 500),
            ),
            Err("unverified cost observation is not admissible")
        );
    }

    #[test]
    fn confirmation_rejects_unexpected_or_divergent_recorded_evidence() {
        let candidates = cpu_candidates();
        let mut extra = observation(1, 1_000, 9_600);
        extra.checksum ^= 1;
        assert_eq!(
            select_calibrated_plan(
                TopologyObservation {
                    available_cpu_workers: 8,
                    accelerator_observed: false,
                },
                candidates,
                vec![observation(0, 100, 1_000), observation(1, 100, 960)],
                vec![observation(0, 1_000, 10_000), extra],
                CalibrationRequest::new(100, 1_000, 1, 500),
            ),
            Err("full-work confirmation contains unexpected candidates")
        );
    }

    #[test]
    fn cpu_smoke_cost_field_constraints_fail_closed() {
        let candidates = cpu_candidates();
        let mut invalid = observation(1, 100, 700);
        invalid.setup_ns = 1;
        invalid.transfer_ns = 1;
        assert_eq!(
            select_calibrated_plan(
                TopologyObservation {
                    available_cpu_workers: 8,
                    accelerator_observed: false,
                },
                candidates,
                vec![observation(0, 100, 1_000), invalid],
                vec![observation(0, 1_000, 10_000)],
                CalibrationRequest::new(100, 1_000, 1, 500),
            ),
            Err("CPU smoke observations require zero separate setup and transfer cost")
        );
    }

    #[test]
    fn serializer_revalidates_public_plan_before_claiming_verified() {
        let mut plan = calibrate_cpu_smoke_host(2, 256, 512, 1, 500).unwrap();
        plan.confirmation[0].verified = false;
        assert_eq!(
            calibrated_plan_receipt_json(&plan),
            Err("unverified cost observation is not admissible")
        );
    }

    #[test]
    fn effective_workers_and_repeats_are_preserved_as_evidence() {
        let plan = calibrate_cpu_smoke_host(8, 1, 1, 2, 500).unwrap();
        let wide = observation_by_id(&plan.calibration, 1).unwrap();
        assert_eq!(wide.effective_cpu_workers, 1);
        assert_eq!(plan.repeats, 2);
        let receipt = calibrated_plan_receipt_json(&plan).unwrap();
        assert!(receipt.contains("\"repeats\":2"));
        assert!(receipt.contains("\"effective_cpu_workers\":1"));
        assert!(receipt.contains("\"workload_id\":\"mesh-smoke-v1\""));
        assert!(receipt.contains("\"plan_identity\":\"mesh-calibration-smoke-v1\""));
    }

    #[test]
    fn host_probe_runs_real_cpu_candidates_and_emits_receipt() {
        let plan = calibrate_cpu_smoke_host(2, 256, 512, 1, 500).unwrap();
        assert!(plan.candidates.len() <= CANDIDATE_BUDGET);
        assert!(!plan.topology.accelerator_observed);
        let receipt = calibrated_plan_receipt_json(&plan).unwrap();
        assert!(receipt.contains("\"schema\":\"qsol.mesh.calibrated-plan-receipt.v1\""));
        assert!(receipt.contains("\"verified\":true"));
        assert!(receipt.contains(
            "\"claim_boundary\":\"host-specific-measured-planning-not-universal-performance-evidence\""
        ));
    }
}
