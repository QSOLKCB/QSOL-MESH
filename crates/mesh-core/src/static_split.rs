// SPDX-License-Identifier: Apache-2.0
//! Static CPU/CUDA partition execution for the deterministic smoke workload.
//!
//! This is deliberately not an adaptive or concurrent scheduler. The caller
//! fixes one contiguous CPU prefix and one contiguous CUDA suffix. MESH executes
//! them sequentially, validates each partial against the workload oracle, then
//! reduces the two partials in partition order.

use crate::{
    accelerator::{
        run_cuda_smoke_range, validate_cuda_smoke_range_run, CudaSmokeRangeRun, CUDA_EXECUTOR_ID,
        CUDA_RANGE_WORKER_PROTOCOL,
    },
    available_workers, run_smoke_range, smoke_reference, smoke_reference_range, SmokeRangeRun,
    SMOKE_WORKLOAD_ID,
};

pub const STATIC_SPLIT_SCHEMA: &str = "qsol.mesh.static-split.v1";
pub const STATIC_SPLIT_RECEIPT_SCHEMA: &str = "qsol.mesh.static-split-receipt.v1";
pub const STATIC_SPLIT_ID: &str = "mesh-smoke-static-cpu-cuda-v1";
pub const STATIC_SPLIT_CLAIM_BOUNDARY: &str =
    "runtime-bring-up-static-cpu-cuda-sequential-not-concurrent-not-performance-evidence";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct StaticSplitRequest {
    pub items: u64,
    pub cpu_items: u64,
    pub cpu_workers: usize,
    pub device_ordinal: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StaticSplitRun {
    request: StaticSplitRequest,
    available_cpu_workers: usize,
    cpu: SmokeRangeRun,
    cuda: CudaSmokeRangeRun,
    checksum: u64,
    reference: u64,
}

impl StaticSplitRun {
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

pub fn validate_static_split_request(request: StaticSplitRequest) -> Result<(), &'static str> {
    if request.items < 2 {
        return Err("static CPU/CUDA split requires at least two items");
    }
    if request.cpu_items == 0 || request.cpu_items >= request.items {
        return Err("static CPU/CUDA split requires two nonempty partitions");
    }
    if request.cpu_workers == 0 {
        return Err("CPU workers must be greater than zero");
    }
    Ok(())
}

fn validate_partition_checksums(
    request: StaticSplitRequest,
    cpu_checksum: u64,
    cuda_checksum: u64,
) -> Result<(u64, u64), &'static str> {
    validate_static_split_request(request)?;

    let cpu_reference = smoke_reference_range(0, request.cpu_items)?;
    if cpu_checksum != cpu_reference {
        return Err("CPU static-split checksum does not match assigned range oracle");
    }

    let cuda_items = request.items - request.cpu_items;
    let cuda_reference = smoke_reference_range(request.cpu_items, cuda_items)?;
    if cuda_checksum != cuda_reference {
        return Err("CUDA static-split checksum does not match assigned range oracle");
    }

    let checksum = cpu_checksum.wrapping_add(cuda_checksum);
    let reference = smoke_reference(request.items)?;
    if checksum != reference {
        return Err("static CPU/CUDA reduction does not match full smoke oracle");
    }
    Ok((checksum, reference))
}

fn validate_static_split_run(run: &StaticSplitRun) -> Result<(), &'static str> {
    validate_static_split_request(run.request)?;

    if run.available_cpu_workers == 0 {
        return Err("static split must record observed CPU capacity");
    }

    if run.cpu.start != 0
        || run.cpu.items != run.request.cpu_items
        || run.cpu.requested_workers != run.request.cpu_workers
        || run.cpu.effective_workers == 0
        || run.cpu.effective_workers > run.cpu.requested_workers
        || run.cpu.effective_workers > usize::try_from(run.cpu.items).unwrap_or(usize::MAX)
    {
        return Err("CPU static-split effective execution does not match request");
    }
    let cpu_reference = smoke_reference_range(run.cpu.start, run.cpu.items)?;
    if run.cpu.reference != cpu_reference || run.cpu.checksum != cpu_reference {
        return Err("CPU static-split evidence does not pass its range oracle");
    }

    validate_cuda_smoke_range_run(&run.cuda)?;
    let cuda_observation = run.cuda.observation();
    let cuda_items = run.request.items - run.request.cpu_items;
    if cuda_observation.start != run.request.cpu_items
        || cuda_observation.items != cuda_items
        || cuda_observation.device_ordinal != run.request.device_ordinal
    {
        return Err("CUDA static-split effective execution does not match request");
    }
    let cuda_reference = smoke_reference_range(cuda_observation.start, cuda_observation.items)?;
    if run.cuda.reference() != cuda_reference || cuda_observation.checksum != cuda_reference {
        return Err("CUDA static-split evidence does not pass its range oracle");
    }

    let (checksum, reference) =
        validate_partition_checksums(run.request, run.cpu.checksum, cuda_observation.checksum)?;
    if checksum != run.checksum || reference != run.reference {
        return Err("static CPU/CUDA run derived state mismatch");
    }

    Ok(())
}

pub fn run_static_smoke_partition(request: StaticSplitRequest) -> Result<StaticSplitRun, String> {
    validate_static_split_request(request).map_err(str::to_owned)?;

    let available_cpu_workers = available_workers();

    // Deliberately sequential. Concurrent execution is the next roadmap rung.
    let cpu = run_smoke_range(0, request.cpu_items, request.cpu_workers).map_err(str::to_owned)?;

    let cuda_items = request.items - request.cpu_items;
    let cuda = run_cuda_smoke_range(request.cpu_items, cuda_items, request.device_ordinal)?;

    let (checksum, reference) =
        validate_partition_checksums(request, cpu.checksum, cuda.observation().checksum)
            .map_err(str::to_owned)?;

    let run = StaticSplitRun {
        request,
        available_cpu_workers,
        cpu,
        cuda,
        checksum,
        reference,
    };
    validate_static_split_run(&run).map_err(str::to_owned)?;
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

pub fn static_split_receipt_json(
    command: &str,
    run: &StaticSplitRun,
) -> Result<String, &'static str> {
    if command != "run" && command != "verify" {
        return Err("static split receipt command must be run or verify");
    }
    validate_static_split_run(run)?;

    let request = run.request;
    let cpu = run.cpu;
    let cuda = run.cuda.observation();
    let cpu_end = request.cpu_items;
    let cuda_end = request.items;
    let helper = json_escape(&run.cuda.helper_path().to_string_lossy());

    Ok(format!(
        "{{\"schema\":\"{STATIC_SPLIT_RECEIPT_SCHEMA}\",\"source_identity\":{{\"runtime\":\"qsol-mesh-cli\",\"split_id\":\"{STATIC_SPLIT_ID}\",\"split_schema\":\"{STATIC_SPLIT_SCHEMA}\",\"cuda_executor_id\":\"{CUDA_EXECUTOR_ID}\",\"cuda_worker_protocol\":\"{CUDA_RANGE_WORKER_PROTOCOL}\"}},\"workload_identity\":{{\"workload_id\":\"{SMOKE_WORKLOAD_ID}\",\"workload_contract_version\":\"1.0.0\"}},\"requested_configuration\":{{\"command\":\"{command}\",\"items\":{},\"cpu_items\":{},\"cpu_workers\":{},\"device_ordinal\":{}}},\"observed_topology\":{{\"available_cpu_workers\":{},\"accelerator_observed\":true,\"cuda_device_ordinal\":{},\"cuda_compute_major\":{},\"cuda_compute_minor\":{},\"cuda_runtime_version\":{},\"cuda_driver_version\":{},\"cuda_helper_path\":\"{}\",\"cuda_evidence_source\":\"cuda-helper-process\"}},\"effective_execution\":{{\"kind\":\"static-cpu-cuda-partition-v1\",\"concurrent\":false,\"adaptive\":false,\"execution_order\":[\"cpu\",\"nvidia-cuda\"],\"cpu\":{{\"range_start\":0,\"range_end\":{},\"requested_workers\":{},\"effective_workers\":{},\"checksum\":\"{:016x}\"}},\"cuda\":{{\"range_start\":{},\"range_end\":{},\"device_ordinal\":{},\"blocks\":{},\"threads_per_block\":{},\"checksum\":\"{:016x}\"}},\"reduction\":\"partition-order-wrapping-u64\"}},\"memory_plan\":{{\"domains\":[\"host-pageable\",\"accelerator-local\"],\"per_item_materialization\":false,\"cpu_temporary_state\":\"O(cpu-workers)\",\"accelerator_checksum_buffer_bytes\":8,\"device_to_host_result_bytes\":8}},\"calibration\":{{\"performed\":false}},\"verification\":{{\"kind\":\"partition-range-oracles-plus-full-scalar-reference\",\"cpu_reference\":\"{:016x}\",\"cuda_reference\":\"{:016x}\",\"checksum\":\"{:016x}\",\"reference\":\"{:016x}\",\"verified\":true}},\"claim_boundary\":\"{STATIC_SPLIT_CLAIM_BOUNDARY}\"}}",
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
        cpu_end,
        cpu.requested_workers,
        cpu.effective_workers,
        cpu.checksum,
        request.cpu_items,
        cuda_end,
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

    fn request() -> StaticSplitRequest {
        StaticSplitRequest {
            items: 1_000,
            cpu_items: 400,
            cpu_workers: 4,
            device_ordinal: 0,
        }
    }

    #[test]
    fn static_split_requires_two_nonempty_fixed_partitions() {
        assert_eq!(validate_static_split_request(request()), Ok(()));

        let mut invalid = request();
        invalid.items = 1;
        assert_eq!(
            validate_static_split_request(invalid),
            Err("static CPU/CUDA split requires at least two items")
        );

        let mut invalid = request();
        invalid.cpu_items = 0;
        assert_eq!(
            validate_static_split_request(invalid),
            Err("static CPU/CUDA split requires two nonempty partitions")
        );

        let mut invalid = request();
        invalid.cpu_items = invalid.items;
        assert_eq!(
            validate_static_split_request(invalid),
            Err("static CPU/CUDA split requires two nonempty partitions")
        );

        let mut invalid = request();
        invalid.cpu_workers = 0;
        assert_eq!(
            validate_static_split_request(invalid),
            Err("CPU workers must be greater than zero")
        );
    }

    #[test]
    fn known_static_partials_reduce_to_full_oracle() {
        let (checksum, reference) =
            validate_partition_checksums(request(), 0x6c9c_c32b_3b0b_5f89, 0x66eb_a516_d94f_e913)
                .unwrap();
        assert_eq!(checksum, 0xd388_6842_145b_489c);
        assert_eq!(checksum, reference);
    }

    #[test]
    fn wrong_partition_partial_fails_closed() {
        assert_eq!(
            validate_partition_checksums(request(), 0x6c9c_c32b_3b0b_5f89, 0x66eb_a516_d94f_e912,),
            Err("CUDA static-split checksum does not match assigned range oracle")
        );
    }
}
