// SPDX-License-Identifier: Apache-2.0
//! Concurrent CPU/CUDA execution for the fixed deterministic smoke partition.
//!
//! The partition geometry is unchanged from the static split. CPU and CUDA
//! executor calls are dispatched concurrently, but result reduction remains
//! deterministic in partition order. No adaptive scheduling is introduced.

use crate::{
    accelerator::{
        run_cuda_smoke_range, validate_cuda_smoke_range_run, CudaSmokeRangeRun,
        CUDA_EXECUTOR_ID, CUDA_RANGE_WORKER_PROTOCOL,
    },
    available_workers, run_smoke_range,
    static_split::{validate_partition_checksums, validate_static_split_request, StaticSplitRequest},
    SmokeRangeRun, SMOKE_WORKLOAD_ID,
};

pub const CONCURRENT_SPLIT_SCHEMA: &str = "qsol.mesh.concurrent-split.v1";
pub const CONCURRENT_SPLIT_RECEIPT_SCHEMA: &str = "qsol.mesh.concurrent-split-receipt.v1";
pub const CONCURRENT_SPLIT_ID: &str = "mesh-smoke-concurrent-cpu-cuda-v1";
pub const CONCURRENT_SPLIT_CLAIM_BOUNDARY: &str =
    "runtime-bring-up-concurrent-dispatch-fixed-split-not-kernel-overlap-measurement-not-performance-evidence";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ConcurrentSplitRun {
    request: StaticSplitRequest,
    available_cpu_workers: usize,
    cpu: SmokeRangeRun,
    cuda: CudaSmokeRangeRun,
    checksum: u64,
    reference: u64,
}

impl ConcurrentSplitRun {
    pub const fn request(&self) -> StaticSplitRequest {
        self.request
    }

    pub const fn available_cpu_workers(&self) -> usize {
        self.available_cpu_workers
    }

    pub const fn cpu(&self) -> SmokeRangeRun {
        self.cpu
    }

    pub fn cuda(&self) -> &CudaSmokeRangeRun {
        &self.cuda
    }

    pub const fn checksum(&self) -> u64 {
        self.checksum
    }

    pub const fn reference(&self) -> u64 {
        self.reference
    }
}

fn run_concurrent_pair<C, D, F, G>(
    cpu_fn: F,
    cuda_fn: G,
) -> Result<(C, D), String>
where
    C: Send,
    F: FnOnce() -> Result<C, String> + Send,
    G: FnOnce() -> Result<D, String>,
{
    std::thread::scope(|scope| {
        let cpu_handle = scope.spawn(cpu_fn);

        // CUDA is dispatched before joining the CPU task. This is the exact
        // concurrency claim made by this stage.
        let cuda_result = cuda_fn();

        let cpu_result = cpu_handle
            .join()
            .map_err(|_| "concurrent CPU executor thread panicked".to_owned())?;

        let cpu = cpu_result?;
        let cuda = cuda_result?;
        Ok((cpu, cuda))
    })
}

fn validate_concurrent_split_run(run: &ConcurrentSplitRun) -> Result<(), &'static str> {
    validate_static_split_request(run.request)?;

    if run.available_cpu_workers == 0 {
        return Err("concurrent split must record observed CPU capacity");
    }

    if run.cpu.start != 0
        || run.cpu.items != run.request.cpu_items
        || run.cpu.requested_workers != run.request.cpu_workers
        || run.cpu.effective_workers == 0
        || run.cpu.effective_workers > run.cpu.requested_workers
        || run.cpu.effective_workers > usize::try_from(run.cpu.items).unwrap_or(usize::MAX)
    {
        return Err("CPU concurrent-split effective execution does not match request");
    }

    validate_cuda_smoke_range_run(&run.cuda)?;
    let cuda = run.cuda.observation();
    let cuda_items = run.request.items - run.request.cpu_items;
    if cuda.start != run.request.cpu_items
        || cuda.items != cuda_items
        || cuda.device_ordinal != run.request.device_ordinal
    {
        return Err("CUDA concurrent-split effective execution does not match request");
    }

    let (checksum, reference) =
        validate_partition_checksums(run.request, run.cpu.checksum, cuda.checksum)?;
    if checksum != run.checksum || reference != run.reference {
        return Err("concurrent CPU/CUDA run derived state mismatch");
    }

    Ok(())
}

pub fn run_concurrent_smoke_partition(
    request: StaticSplitRequest,
) -> Result<ConcurrentSplitRun, String> {
    validate_static_split_request(request).map_err(str::to_owned)?;
    let available_cpu_workers = available_workers();
    let cuda_items = request.items - request.cpu_items;

    let (cpu, cuda) = run_concurrent_pair(
        || {
            run_smoke_range(0, request.cpu_items, request.cpu_workers)
                .map_err(str::to_owned)
        },
        || run_cuda_smoke_range(request.cpu_items, cuda_items, request.device_ordinal),
    )?;

    let (checksum, reference) =
        validate_partition_checksums(request, cpu.checksum, cuda.observation().checksum)
            .map_err(str::to_owned)?;

    let run = ConcurrentSplitRun {
        request,
        available_cpu_workers,
        cpu,
        cuda,
        checksum,
        reference,
    };
    validate_concurrent_split_run(&run).map_err(str::to_owned)?;
    Ok(run)
}

fn json_escape(value: &str) -> String {
    let mut escaped = String::with_capacity(value.len());
    for character in value.chars() {
        match character {
            '"' => escaped.push_str("\\\""),
            '\\' => escaped.push_str("\\\\"),
            '\n' => escaped.push_str("\\n"),
            '\r' => escaped.push_str("\\r"),
            '\t' => escaped.push_str("\\t"),
            character if character.is_control() => {
                use std::fmt::Write;
                let _ = write!(escaped, "\\u{:04x}", character as u32);
            }
            character => escaped.push(character),
        }
    }
    escaped
}

pub fn concurrent_split_receipt_json(
    command: &str,
    run: &ConcurrentSplitRun,
) -> Result<String, &'static str> {
    if command != "run" && command != "verify" {
        return Err("concurrent split receipt command must be run or verify");
    }
    validate_concurrent_split_run(run)?;

    let request = run.request;
    let cpu = run.cpu;
    let cuda = run.cuda.observation();
    let helper = json_escape(&run.cuda.helper_path().to_string_lossy());

    Ok(format!(
        "{{\"schema\":\"{CONCURRENT_SPLIT_RECEIPT_SCHEMA}\",\"source_identity\":{{\"runtime\":\"qsol-mesh-cli\",\"split_id\":\"{CONCURRENT_SPLIT_ID}\",\"split_schema\":\"{CONCURRENT_SPLIT_SCHEMA}\",\"cuda_executor_id\":\"{CUDA_EXECUTOR_ID}\",\"cuda_worker_protocol\":\"{CUDA_RANGE_WORKER_PROTOCOL}\"}},\"workload_identity\":{{\"workload_id\":\"{SMOKE_WORKLOAD_ID}\",\"workload_contract_version\":\"1.0.0\"}},\"requested_configuration\":{{\"command\":\"{command}\",\"items\":{},\"cpu_items\":{},\"cpu_workers\":{},\"device_ordinal\":{}}},\"observed_topology\":{{\"available_cpu_workers\":{},\"accelerator_observed\":true,\"cuda_device_ordinal\":{},\"cuda_compute_major\":{},\"cuda_compute_minor\":{},\"cuda_runtime_version\":{},\"cuda_driver_version\":{},\"cuda_helper_path\":\"{}\",\"cuda_evidence_source\":\"cuda-helper-process\"}},\"effective_execution\":{{\"kind\":\"concurrent-cpu-cuda-partition-v1\",\"concurrent_dispatch\":true,\"adaptive\":false,\"dispatch_contract\":{{\"cpu_task_spawned_before_cuda_call\":true,\"cpu_joined_after_cuda_call_return\":true,\"kernel_overlap_measured\":false}},\"cpu\":{{\"range_start\":0,\"range_end\":{},\"requested_workers\":{},\"effective_workers\":{},\"checksum\":\"{:016x}\"}},\"cuda\":{{\"range_start\":{},\"range_end\":{},\"device_ordinal\":{},\"blocks\":{},\"threads_per_block\":{},\"checksum\":\"{:016x}\"}},\"reduction\":\"partition-order-wrapping-u64\",\"reduction_order\":[\"cpu\",\"nvidia-cuda\"]}},\"memory_plan\":{{\"domains\":[\"host-pageable\",\"accelerator-local\"],\"per_item_materialization\":false,\"cpu_temporary_state\":\"O(cpu-workers)\",\"accelerator_checksum_buffer_bytes\":8,\"device_to_host_result_bytes\":8}},\"calibration\":{{\"performed\":false}},\"verification\":{{\"kind\":\"partition-range-oracles-plus-full-scalar-reference\",\"cpu_reference\":\"{:016x}\",\"cuda_reference\":\"{:016x}\",\"checksum\":\"{:016x}\",\"reference\":\"{:016x}\",\"verified\":true}},\"claim_boundary\":\"{CONCURRENT_SPLIT_CLAIM_BOUNDARY}\"}}",
        request.items,
        request.cpu_items,
        request.cpu_workers,
        request.device_ordinal,
        run.available_cpu_workers,
        cuda.device_ordinal,
        cuda.compute_major,
        cuda.compute_minor,
        cuda.cuda_runtime_version,
        cuda.cuda_driver_version,
        helper,
        request.cpu_items,
        cpu.requested_workers,
        cpu.effective_workers,
        cpu.checksum,
        request.cpu_items,
        request.items,
        cuda.device_ordinal,
        cuda.blocks,
        cuda.threads_per_block,
        cuda.checksum,
        cpu.reference,
        run.cuda.reference(),
        run.checksum,
        run.reference
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        sync::mpsc,
        time::Duration,
    };

    #[test]
    fn concurrent_pair_dispatches_cuda_before_cpu_join() {
        let (tx, rx) = mpsc::channel::<()>();

        let (cpu, cuda) = run_concurrent_pair(
            || {
                rx.recv_timeout(Duration::from_secs(1))
                    .map_err(|_| "CUDA closure was not dispatched while CPU task was live".to_owned())?;
                Ok::<_, String>(11_u32)
            },
            || {
                tx.send(())
                    .map_err(|_| "CPU task was not live during CUDA dispatch".to_owned())?;
                Ok::<_, String>(22_u32)
            },
        )
        .unwrap();

        assert_eq!((cpu, cuda), (11, 22));
    }

    #[test]
    fn concurrent_pair_propagates_cuda_failure_without_cpu_fallback() {
        let result = run_concurrent_pair(
            || Ok::<_, String>(11_u32),
            || Err::<u32, _>("cuda-failed".to_owned()),
        );
        assert_eq!(result, Err("cuda-failed".to_owned()));
    }

    #[test]
    fn fixed_split_reduction_remains_deterministic() {
        let request = StaticSplitRequest {
            items: 1_000,
            cpu_items: 400,
            cpu_workers: 4,
            device_ordinal: 0,
        };
        let (checksum, reference) = validate_partition_checksums(
            request,
            0x6c9c_c32b_3b0b_5f89,
            0x66eb_a516_d94f_e913,
        )
        .unwrap();
        assert_eq!(checksum, 0xd388_6842_145b_489c);
        assert_eq!(checksum, reference);
    }
}
