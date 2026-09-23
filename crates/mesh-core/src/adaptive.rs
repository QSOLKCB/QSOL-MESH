// SPDX-License-Identifier: Apache-2.0
//! Bounded phase-boundary replanning over independent smoke instances.
use crate::{
    accelerator::run_cuda_smoke,
    planner::{
        calibrate_cpu_smoke_host, calibrate_cuda_smoke_host, calibrated_plan_receipt_json,
        cuda_calibrated_plan_receipt_json, validate_calibrated_plan, BackendKind, CalibratedPlan,
        CandidatePlan, CudaCalibratedRun,
    },
    run_smoke, smoke_reference,
    static_split::{run_static_smoke_partition, StaticSplitRequest},
};
use std::time::Instant;

pub const MAX_PHASES: usize = 64;
pub const MAX_REPEATS: usize = 31;
pub const WORKLOAD_ID: &str = "mesh-smoke-phases-v1";

#[derive(Clone, Debug)]
pub struct PhaseRequest {
    pub phase_items: Vec<u64>,
    pub calibration_items: u64,
    pub repeats: usize,
    pub near_tie_bps: u32,
    pub cuda: bool,
    pub device: u32,
}

impl PhaseRequest {
    pub fn validate(&self) -> Result<(), &'static str> {
        let minimum = if self.cuda { 2 } else { 1 };
        if self.phase_items.is_empty() || self.phase_items.len() > MAX_PHASES {
            return Err("phase count must be between 1 and 64");
        }
        if self.calibration_items < minimum || self.phase_items.iter().any(|n| *n < minimum) {
            return Err("phase and calibration items must be positive; CUDA requires at least two");
        }
        if self.repeats == 0 || self.repeats > MAX_REPEATS || self.near_tie_bps >= 10_000 {
            return Err("repeats must be 1..=31 and near-tie-bps must be below 10000");
        }
        if !self.cuda && self.device != 0 {
            return Err("device requires CUDA activation");
        }
        self.phase_items.iter().try_fold(0_u64, |sum, n| {
            sum.checked_add(*n).ok_or("total phase items overflow u64")
        })?;
        Ok(())
    }
}

enum Calibration {
    Cpu(CalibratedPlan),
    Cuda(CudaCalibratedRun),
}

impl Calibration {
    fn plan(&self) -> &CalibratedPlan {
        match self {
            Self::Cpu(plan) => plan,
            Self::Cuda(run) => run.plan(),
        }
    }

    fn receipt(&self) -> Result<String, &'static str> {
        match self {
            Self::Cpu(plan) => calibrated_plan_receipt_json(plan),
            Self::Cuda(run) => cuda_calibrated_plan_receipt_json(run),
        }
    }
}

struct Execution {
    checksum: u64,
    effective_cpu_workers: usize,
}

struct Phase {
    calibration: Calibration,
    execution: Execution,
    calibration_host_ns: u128,
    execution_host_ns: u128,
}

/// Only a complete, verified execution can construct this receipt authority.
pub struct PhaseRun {
    request: PhaseRequest,
    available_workers: usize,
    phases: Vec<Phase>,
    checksum: u64,
}

fn selected(plan: &CalibratedPlan) -> Result<CandidatePlan, &'static str> {
    plan.candidates
        .iter()
        .copied()
        .find(|candidate| candidate.id == plan.selected_candidate_id)
        .ok_or("selected phase candidate missing")
}

fn execute(calibration: &Calibration, items: u64, device: u32) -> Result<Execution, String> {
    let candidate = selected(calibration.plan())?;
    match candidate.backend {
        BackendKind::Cpu => {
            let run = run_smoke(items, candidate.cpu_workers)?;
            Ok(Execution {
                checksum: run.checksum,
                effective_cpu_workers: run.effective_workers,
            })
        }
        BackendKind::Accelerator | BackendKind::HeterogeneousStatic => {
            let Calibration::Cuda(calibrated) = calibration else {
                return Err("accelerator execution requires CUDA calibration".into());
            };
            if candidate.backend == BackendKind::Accelerator {
                let run = run_cuda_smoke(items, device)?;
                if !calibrated.accepts_execution_identity(run.observation(), run.helper_path()) {
                    return Err("CUDA identity changed between calibration and execution".into());
                }
                Ok(Execution {
                    checksum: run.observation().checksum,
                    effective_cpu_workers: 0,
                })
            } else {
                let run = run_static_smoke_partition(StaticSplitRequest {
                    items,
                    cpu_items: items / 2,
                    cpu_workers: candidate.cpu_workers,
                    device_ordinal: device,
                })?;
                if !calibrated.accepts_range_execution_identity(
                    run.cuda().observation(),
                    run.cuda().helper_path(),
                ) {
                    return Err("CUDA identity changed between calibration and execution".into());
                }
                Ok(Execution {
                    checksum: run.checksum(),
                    effective_cpu_workers: run.cpu().effective_workers,
                })
            }
        }
    }
}

pub fn run_phases(request: &PhaseRequest, available_workers: usize) -> Result<PhaseRun, String> {
    run_with(
        request,
        available_workers,
        |items| {
            let calibration_items = request.calibration_items.min(items);
            if request.cuda {
                Ok(Calibration::Cuda(calibrate_cuda_smoke_host(
                    available_workers,
                    calibration_items,
                    items,
                    request.repeats,
                    request.near_tie_bps,
                    request.device,
                )?))
            } else {
                Ok(Calibration::Cpu(calibrate_cpu_smoke_host(
                    available_workers,
                    calibration_items,
                    items,
                    request.repeats,
                    request.near_tie_bps,
                )?))
            }
        },
        |calibration, items| execute(calibration, items, request.device),
    )
}

fn run_with(
    request: &PhaseRequest,
    available_workers: usize,
    mut calibrate: impl FnMut(u64) -> Result<Calibration, String>,
    mut execute: impl FnMut(&Calibration, u64) -> Result<Execution, String>,
) -> Result<PhaseRun, String> {
    request.validate()?;
    if available_workers == 0 {
        return Err("observed CPU worker capacity must be positive".into());
    }
    let mut phases: Vec<Phase> = Vec::with_capacity(request.phase_items.len());
    let mut checksum = 0_u64;
    for &items in &request.phase_items {
        let started = Instant::now();
        let calibration = calibrate(items)?;
        let plan = calibration.plan();
        validate_calibrated_plan(plan)?;
        if plan.full_work_units != items
            || plan.calibration_units != request.calibration_items.min(items)
            || plan.repeats != request.repeats
            || plan.near_tie_bps != request.near_tie_bps
            || plan.topology.available_cpu_workers != available_workers
            || plan.topology.accelerator_observed != request.cuda
            || matches!(calibration, Calibration::Cuda(_)) != request.cuda
        {
            return Err("phase calibration does not match request".into());
        }
        if let (Some(previous), Calibration::Cuda(current)) = (phases.last(), &calibration) {
            if let Calibration::Cuda(previous) = &previous.calibration {
                if !previous.same_identity(current) {
                    return Err("CUDA identity changed across phase boundaries".into());
                }
            }
        }
        let calibration_host_ns = started.elapsed().as_nanos();
        let started = Instant::now();
        let execution = execute(&calibration, items)?;
        if execution.checksum != smoke_reference(items)? {
            return Err("phase execution checksum does not match scalar oracle".into());
        }
        let candidate = selected(plan)?;
        let cpu_items = match candidate.backend {
            BackendKind::Cpu => items,
            BackendKind::Accelerator => 0,
            BackendKind::HeterogeneousStatic => items / 2,
        };
        let expected_workers = candidate
            .cpu_workers
            .min(usize::try_from(cpu_items).unwrap_or(usize::MAX));
        if execution.effective_cpu_workers != expected_workers {
            return Err("phase effective workers do not match selected execution".into());
        }
        let execution_host_ns = started.elapsed().as_nanos();
        checksum = checksum.wrapping_add(execution.checksum);
        phases.push(Phase {
            calibration,
            execution,
            calibration_host_ns,
            execution_host_ns,
        });
    }
    Ok(PhaseRun {
        request: request.clone(),
        available_workers,
        phases,
        checksum,
    })
}

pub fn phase_receipt_json(command: &str, run: &PhaseRun) -> Result<String, &'static str> {
    if command != "run" && command != "verify" {
        return Err("phase runtime is admitted only by run or verify");
    }
    let mut entries = Vec::with_capacity(run.phases.len());
    let mut reference = 0_u64;
    let mut previous = None;
    let mut changes = 0;
    for (index, phase) in run.phases.iter().enumerate() {
        let items = run.request.phase_items[index];
        let candidate = selected(phase.calibration.plan())?;
        let oracle = smoke_reference(items)?;
        if phase.execution.checksum != oracle {
            return Err("phase receipt checksum does not match scalar oracle");
        }
        reference = reference.wrapping_add(oracle);
        let changed = previous.is_some_and(|previous| previous != candidate);
        changes += usize::from(changed);
        previous = Some(candidate);
        entries.push(format!(
            "{{\"phase_index\":{index},\"items\":{items},\"plan_changed\":{changed},\"calibration_receipt\":{},\"execution\":{{\"backend\":\"{}\",\"requested_cpu_workers\":{},\"effective_cpu_workers\":{},\"cpu_items\":{},\"cuda_items\":{},\"checksum\":\"{:016x}\",\"reference\":\"{oracle:016x}\",\"verified\":true}},\"calibration_host_ns\":{},\"execution_host_ns\":{}}}",
            phase.calibration.receipt()?, candidate.backend.as_str(), candidate.cpu_workers,
            phase.execution.effective_cpu_workers,
            match candidate.backend { BackendKind::Cpu => items, BackendKind::Accelerator => 0, BackendKind::HeterogeneousStatic => items / 2 },
            match candidate.backend { BackendKind::Cpu => 0, BackendKind::Accelerator => items, BackendKind::HeterogeneousStatic => items - items / 2 },
            phase.execution.checksum, phase.calibration_host_ns, phase.execution_host_ns,
        ));
    }
    if run.checksum != reference {
        return Err("phase reduction does not match scalar oracle");
    }
    let items = run
        .request
        .phase_items
        .iter()
        .map(u64::to_string)
        .collect::<Vec<_>>()
        .join(",");
    Ok(format!(
        "{{\"schema\":\"qsol.mesh.phase-runtime-receipt.v1\",\"source_identity\":{{\"runtime\":\"qsol-mesh-cli\",\"contract\":\"qsol.mesh.phase-runtime-contract.v1\"}},\"workload_identity\":{{\"workload_id\":\"{WORKLOAD_ID}\",\"workload_contract_version\":\"1.0.0\"}},\"requested_configuration\":{{\"command\":\"{command}\",\"phase_items\":[{items}],\"calibration_items\":{},\"repeats\":{},\"near_tie_bps\":{},\"cuda\":{},\"device_ordinal\":{}}},\"observed_topology\":{{\"available_cpu_workers\":{},\"accelerator_observed\":{},\"details\":\"per-phase-calibration-receipts\"}},\"effective_execution\":{{\"kind\":\"phase-boundary-replanning-and-execution\",\"completed_phases\":{},\"plan_changes\":{changes},\"within_phase_replanning\":false,\"phases\":[{}]}},\"memory_plan\":{{\"per_item_materialization\":false,\"phase_state_bound\":64,\"persistent_cuda_context\":false}},\"calibration\":{{\"performed_before_every_phase\":true,\"candidate_budget_per_phase\":4,\"cached\":false,\"calibration_host_scope\":\"calibrator-call-plus-plan-validation\",\"execution_host_scope\":\"selected-executor-call-plus-phase-oracle-validation\"}},\"verification\":{{\"kind\":\"per-phase-scalar-oracle-and-phase-order-wrapping-u64\",\"checksum\":\"{:016x}\",\"reference\":\"{reference:016x}\",\"verified\":true}},\"claim_boundary\":\"bounded-phase-boundary-replanning-only-not-work-stealing-kernel-overlap-or-universal-speedup\"}}",
        run.request.calibration_items, run.request.repeats, run.request.near_tie_bps,
        run.request.cuda, run.request.device, run.available_workers, run.request.cuda,
        run.phases.len(), entries.join(","), run.checksum,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::planner::{
        derive_candidates, select_calibrated_plan, CalibrationRequest, CostObservation,
        TopologyObservation,
    };
    use std::cell::RefCell;

    fn request() -> PhaseRequest {
        PhaseRequest {
            phase_items: vec![100, 200, 100],
            calibration_items: 10,
            repeats: 1,
            near_tie_bps: 500,
            cuda: false,
            device: 0,
        }
    }

    // Synthetic cost fixtures force an actual policy change independently of host timing.
    fn calibration(items: u64) -> Calibration {
        let topology = TopologyObservation {
            available_cpu_workers: 2,
            accelerator_observed: false,
        };
        let observation = |id, units, ns| CostObservation {
            candidate_id: id,
            work_units: units,
            effective_cpu_workers: if id == 0 { 1 } else { 2 },
            service_ns: ns,
            setup_ns: 0,
            transfer_ns: 0,
            checksum: smoke_reference(units).unwrap(),
            verified: true,
        };
        let winner_ns = if items == 200 { 50 } else { 200 };
        let mut confirmation = vec![observation(0, items, 100)];
        if winner_ns < 100 {
            confirmation.push(observation(1, items, winner_ns));
        }
        Calibration::Cpu(
            select_calibrated_plan(
                topology,
                derive_candidates(topology).unwrap(),
                vec![observation(0, 10, 100), observation(1, 10, winner_ns)],
                confirmation,
                CalibrationRequest::new(10, items, 1, 500),
            )
            .unwrap(),
        )
    }

    #[test]
    fn replans_only_after_verified_phase_execution_and_preserves_order() {
        let events = RefCell::new(Vec::new());
        let run = run_with(
            &request(),
            2,
            |items| {
                events.borrow_mut().push(("calibrate", items));
                Ok(calibration(items))
            },
            |plan, items| {
                events.borrow_mut().push(("execute", items));
                execute(plan, items, 0)
            },
        )
        .unwrap();
        assert_eq!(
            *events.borrow(),
            vec![
                ("calibrate", 100),
                ("execute", 100),
                ("calibrate", 200),
                ("execute", 200),
                ("calibrate", 100),
                ("execute", 100)
            ]
        );
        assert_eq!(
            run.phases
                .iter()
                .map(|p| p.execution.effective_cpu_workers)
                .collect::<Vec<_>>(),
            vec![1, 2, 1]
        );
        let receipt = phase_receipt_json("run", &run).unwrap();
        assert!(receipt.contains("\"plan_changes\":2"));
        assert_eq!(
            run.checksum,
            smoke_reference(100)
                .unwrap()
                .wrapping_mul(2)
                .wrapping_add(smoke_reference(200).unwrap())
        );
        assert!(phase_receipt_json("calibrate", &run).is_err());
    }

    #[test]
    fn mismatch_and_executor_error_stop_before_later_phases_without_fallback() {
        for mismatch in [false, true] {
            let count = RefCell::new(0);
            let result = run_with(
                &request(),
                2,
                |items| {
                    *count.borrow_mut() += 1;
                    Ok(calibration(items))
                },
                |_, _| {
                    if mismatch {
                        Ok(Execution {
                            checksum: 0,
                            effective_cpu_workers: 1,
                        })
                    } else {
                        Err("executor failed".into())
                    }
                },
            );
            assert!(result.is_err());
            assert_eq!(*count.borrow(), 1);
        }
    }

    #[test]
    fn request_limits_fail_before_calibration() {
        let mut cases = Vec::new();
        let mut r = request();
        r.phase_items.clear();
        cases.push(r);
        let mut r = request();
        r.phase_items = vec![1; 65];
        cases.push(r);
        let mut r = request();
        r.phase_items = vec![u64::MAX, 1];
        cases.push(r);
        let mut r = request();
        r.repeats = 32;
        cases.push(r);
        let mut r = request();
        r.cuda = true;
        r.phase_items = vec![1];
        cases.push(r);
        for r in cases {
            assert!(run_with(
                &r,
                2,
                |_| panic!("must not calibrate"),
                |_, _| panic!("must not execute")
            )
            .is_err());
        }
    }

    #[test]
    fn recalibration_is_bound_to_each_phase_request() {
        let result = run_with(
            &request(),
            2,
            |_| Ok(calibration(200)),
            |_, _| panic!("must not execute"),
        );
        assert!(result.err().unwrap().contains("does not match request"));
    }
}
