// SPDX-License-Identifier: Apache-2.0
//! Experimental NVIDIA CUDA executor boundary.
//!
//! The Rust runtime does not pretend that a requested accelerator exists.
//! Effective CUDA execution is accepted only after an external CUDA worker
//! process reports observed CUDA runtime/device data and its checksum passes the
//! workload's scalar oracle.

use crate::{smoke_reference, smoke_reference_range, SMOKE_WORKLOAD_ID};
use std::{
    ffi::OsStr,
    path::{Path, PathBuf},
    process::Command as ProcessCommand,
    time::Instant,
};

pub const CUDA_WORKER_PROTOCOL: &str = "qsol.mesh.cuda-smoke-worker.v1";
pub const CUDA_TIMING_WORKER_PROTOCOL: &str = "qsol.mesh.cuda-smoke-worker.v2";
pub const CUDA_RANGE_WORKER_PROTOCOL: &str = "qsol.mesh.cuda-smoke-range-worker.v1";
pub const CUDA_EXECUTOR_ID: &str = "qsol-mesh-cuda-smoke-v1";
pub const CUDA_SMOKE_RECEIPT_SCHEMA: &str = "qsol.mesh.cuda-smoke-receipt.v1";
pub const CUDA_TIMING_RECEIPT_SCHEMA: &str = "qsol.mesh.cuda-smoke-receipt.v2";
pub const CANONICAL_CUDA_HELPER_FILENAME: &str = "mesh-cuda-smoke";
pub const CUDA_SMOKE_CLAIM_BOUNDARY: &str =
    "experimental-nvidia-cuda-smoke-single-device-helper-reported-topology-not-performance-evidence";
pub const CUDA_TIMING_CLAIM_BOUNDARY: &str =
    "experimental-nvidia-cuda-smoke-separated-timing-evidence-not-placement-not-performance-evidence";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CudaWorkerObservation {
    pub items: u64,
    pub checksum: u64,
    pub blocks: u32,
    pub threads_per_block: u32,
    pub device_ordinal: u32,
    pub compute_major: u32,
    pub compute_minor: u32,
    pub cuda_runtime_version: u32,
    pub cuda_driver_version: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CudaTimingWorkerObservation {
    pub items: u64,
    pub checksum: u64,
    pub blocks: u32,
    pub threads_per_block: u32,
    pub device_ordinal: u32,
    pub compute_major: u32,
    pub compute_minor: u32,
    pub cuda_runtime_version: u32,
    pub cuda_driver_version: u32,
    pub setup_host_ns: u64,
    pub kernel_device_ns: u64,
    pub transfer_host_ns: u64,
    pub teardown_host_ns: u64,
    pub worker_total_ns: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CudaRangeWorkerObservation {
    pub start: u64,
    pub items: u64,
    pub checksum: u64,
    pub blocks: u32,
    pub threads_per_block: u32,
    pub device_ordinal: u32,
    pub compute_major: u32,
    pub compute_minor: u32,
    pub cuda_runtime_version: u32,
    pub cuda_driver_version: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CudaSmokeRangeRun {
    observation: CudaRangeWorkerObservation,
    reference: u64,
    helper_path: PathBuf,
}

impl CudaSmokeRangeRun {
    pub const fn observation(&self) -> CudaRangeWorkerObservation {
        self.observation
    }

    pub const fn reference(&self) -> u64 {
        self.reference
    }

    pub fn helper_path(&self) -> &Path {
        &self.helper_path
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CudaSmokeRun {
    observation: CudaWorkerObservation,
    reference: u64,
    helper_path: PathBuf,
}

impl CudaSmokeRun {
    pub const fn observation(&self) -> CudaWorkerObservation {
        self.observation
    }

    pub const fn reference(&self) -> u64 {
        self.reference
    }

    pub fn helper_path(&self) -> &Path {
        &self.helper_path
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CudaSmokeTimingRun {
    observation: CudaTimingWorkerObservation,
    reference: u64,
    helper_path: PathBuf,
    launcher_total_ns: u64,
    verification_ns: u64,
}

impl CudaSmokeTimingRun {
    pub const fn observation(&self) -> CudaTimingWorkerObservation {
        self.observation
    }

    pub const fn reference(&self) -> u64 {
        self.reference
    }

    pub fn helper_path(&self) -> &Path {
        &self.helper_path
    }

    pub const fn launcher_total_ns(&self) -> u64 {
        self.launcher_total_ns
    }

    pub const fn verification_ns(&self) -> u64 {
        self.verification_ns
    }
}

fn parse_prefixed_u64(field: &str, prefix: &str) -> Result<u64, &'static str> {
    field
        .strip_prefix(prefix)
        .ok_or("CUDA worker field prefix mismatch")?
        .parse::<u64>()
        .map_err(|_| "CUDA worker decimal field is invalid")
}

fn parse_prefixed_u32(field: &str, prefix: &str) -> Result<u32, &'static str> {
    field
        .strip_prefix(prefix)
        .ok_or("CUDA worker field prefix mismatch")?
        .parse::<u32>()
        .map_err(|_| "CUDA worker decimal field is invalid")
}

fn parse_prefixed_hex_u64(field: &str, prefix: &str) -> Result<u64, &'static str> {
    let value = field
        .strip_prefix(prefix)
        .ok_or("CUDA worker field prefix mismatch")?;
    if value.len() != 16 || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("CUDA worker checksum must be exactly 16 hexadecimal digits");
    }
    u64::from_str_radix(value, 16).map_err(|_| "CUDA worker checksum is invalid")
}

pub fn parse_cuda_worker_line(line: &str) -> Result<CudaWorkerObservation, &'static str> {
    let protocol_line = if let Some(stripped) = line.strip_suffix("\r\n") {
        stripped
    } else if let Some(stripped) = line.strip_suffix('\n') {
        stripped
    } else {
        line
    };
    if protocol_line.contains('\n') || protocol_line.contains('\r') {
        return Err("CUDA worker output must contain exactly one protocol line");
    }

    let fields: Vec<&str> = protocol_line.split('\t').collect();
    if fields.len() != 10 || fields[0] != CUDA_WORKER_PROTOCOL {
        return Err("CUDA worker protocol shape mismatch");
    }

    Ok(CudaWorkerObservation {
        items: parse_prefixed_u64(fields[1], "items=")?,
        checksum: parse_prefixed_hex_u64(fields[2], "checksum=")?,
        blocks: parse_prefixed_u32(fields[3], "blocks=")?,
        threads_per_block: parse_prefixed_u32(fields[4], "threads_per_block=")?,
        device_ordinal: parse_prefixed_u32(fields[5], "device=")?,
        compute_major: parse_prefixed_u32(fields[6], "compute_major=")?,
        compute_minor: parse_prefixed_u32(fields[7], "compute_minor=")?,
        cuda_runtime_version: parse_prefixed_u32(fields[8], "cuda_runtime=")?,
        cuda_driver_version: parse_prefixed_u32(fields[9], "cuda_driver=")?,
    })
}

pub fn parse_cuda_timing_worker_line(
    line: &str,
) -> Result<CudaTimingWorkerObservation, &'static str> {
    let protocol_line = if let Some(stripped) = line.strip_suffix("\r\n") {
        stripped
    } else if let Some(stripped) = line.strip_suffix('\n') {
        stripped
    } else {
        line
    };
    if protocol_line.contains('\n') || protocol_line.contains('\r') {
        return Err("CUDA timing worker output must contain exactly one protocol line");
    }

    let fields: Vec<&str> = protocol_line.split('\t').collect();
    if fields.len() != 15 || fields[0] != CUDA_TIMING_WORKER_PROTOCOL {
        return Err("CUDA timing worker protocol shape mismatch");
    }

    Ok(CudaTimingWorkerObservation {
        items: parse_prefixed_u64(fields[1], "items=")?,
        checksum: parse_prefixed_hex_u64(fields[2], "checksum=")?,
        blocks: parse_prefixed_u32(fields[3], "blocks=")?,
        threads_per_block: parse_prefixed_u32(fields[4], "threads_per_block=")?,
        device_ordinal: parse_prefixed_u32(fields[5], "device=")?,
        compute_major: parse_prefixed_u32(fields[6], "compute_major=")?,
        compute_minor: parse_prefixed_u32(fields[7], "compute_minor=")?,
        cuda_runtime_version: parse_prefixed_u32(fields[8], "cuda_runtime=")?,
        cuda_driver_version: parse_prefixed_u32(fields[9], "cuda_driver=")?,
        setup_host_ns: parse_prefixed_u64(fields[10], "setup_host_ns=")?,
        kernel_device_ns: parse_prefixed_u64(fields[11], "kernel_device_ns=")?,
        transfer_host_ns: parse_prefixed_u64(fields[12], "transfer_host_ns=")?,
        teardown_host_ns: parse_prefixed_u64(fields[13], "teardown_host_ns=")?,
        worker_total_ns: parse_prefixed_u64(fields[14], "worker_total_ns=")?,
    })
}

pub fn parse_cuda_range_worker_line(
    line: &str,
) -> Result<CudaRangeWorkerObservation, &'static str> {
    let protocol_line = if let Some(stripped) = line.strip_suffix("\r\n") {
        stripped
    } else if let Some(stripped) = line.strip_suffix('\n') {
        stripped
    } else {
        line
    };
    if protocol_line.contains('\n') || protocol_line.contains('\r') {
        return Err("CUDA range worker output must contain exactly one protocol line");
    }

    let fields: Vec<&str> = protocol_line.split('\t').collect();
    if fields.len() != 11 || fields[0] != CUDA_RANGE_WORKER_PROTOCOL {
        return Err("CUDA range worker protocol shape mismatch");
    }

    Ok(CudaRangeWorkerObservation {
        start: parse_prefixed_u64(fields[1], "start=")?,
        items: parse_prefixed_u64(fields[2], "items=")?,
        checksum: parse_prefixed_hex_u64(fields[3], "checksum=")?,
        blocks: parse_prefixed_u32(fields[4], "blocks=")?,
        threads_per_block: parse_prefixed_u32(fields[5], "threads_per_block=")?,
        device_ordinal: parse_prefixed_u32(fields[6], "device=")?,
        compute_major: parse_prefixed_u32(fields[7], "compute_major=")?,
        compute_minor: parse_prefixed_u32(fields[8], "compute_minor=")?,
        cuda_runtime_version: parse_prefixed_u32(fields[9], "cuda_runtime=")?,
        cuda_driver_version: parse_prefixed_u32(fields[10], "cuda_driver=")?,
    })
}

fn validate_cuda_worker_observation(
    requested_items: u64,
    requested_device: u32,
    observation: CudaWorkerObservation,
) -> Result<u64, &'static str> {
    if requested_items == 0 {
        return Err("items must be greater than zero");
    }
    if observation.items != requested_items {
        return Err("CUDA worker items do not match requested workload");
    }
    if observation.device_ordinal != requested_device {
        return Err("CUDA worker device does not match requested device");
    }
    if observation.blocks == 0 || observation.threads_per_block == 0 {
        return Err("CUDA worker launch geometry must be nonzero");
    }
    if observation.compute_major == 0 {
        return Err("CUDA worker did not report a CUDA compute capability");
    }
    if observation.cuda_runtime_version == 0 || observation.cuda_driver_version == 0 {
        return Err("CUDA worker did not report CUDA runtime and driver versions");
    }

    let reference = smoke_reference(requested_items)?;
    if observation.checksum != reference {
        return Err("CUDA checksum does not match scalar smoke oracle");
    }

    Ok(reference)
}

fn validate_cuda_timing_worker_observation_shape(
    requested_items: u64,
    requested_device: u32,
    observation: CudaTimingWorkerObservation,
) -> Result<(), &'static str> {
    if requested_items == 0 {
        return Err("items must be greater than zero");
    }
    if observation.items != requested_items {
        return Err("CUDA timing worker items do not match requested workload");
    }
    if observation.device_ordinal != requested_device {
        return Err("CUDA timing worker device does not match requested device");
    }
    if observation.blocks == 0 || observation.threads_per_block == 0 {
        return Err("CUDA timing worker launch geometry must be nonzero");
    }
    if observation.compute_major == 0 {
        return Err("CUDA timing worker did not report a CUDA compute capability");
    }
    if observation.cuda_runtime_version == 0 || observation.cuda_driver_version == 0 {
        return Err("CUDA timing worker did not report CUDA runtime and driver versions");
    }
    if observation.worker_total_ns == 0 {
        return Err("CUDA timing worker total must be greater than zero");
    }

    let host_accounted_ns = observation
        .setup_host_ns
        .checked_add(observation.transfer_host_ns)
        .and_then(|value| value.checked_add(observation.teardown_host_ns))
        .ok_or("CUDA timing host component sum overflows u64")?;
    if host_accounted_ns > observation.worker_total_ns {
        return Err("CUDA timing host components exceed worker total");
    }
    Ok(())
}

fn validate_cuda_range_worker_observation(
    requested_start: u64,
    requested_items: u64,
    requested_device: u32,
    observation: CudaRangeWorkerObservation,
) -> Result<u64, &'static str> {
    if requested_items == 0 {
        return Err("items must be greater than zero");
    }
    requested_start
        .checked_add(requested_items)
        .ok_or("CUDA requested logical range overflows u64")?;
    if observation.start != requested_start {
        return Err("CUDA range worker start does not match requested workload");
    }
    if observation.items != requested_items {
        return Err("CUDA range worker items do not match requested workload");
    }
    if observation.device_ordinal != requested_device {
        return Err("CUDA range worker device does not match requested device");
    }
    if observation.blocks == 0 || observation.threads_per_block == 0 {
        return Err("CUDA range worker launch geometry must be nonzero");
    }
    if observation.compute_major == 0 {
        return Err("CUDA range worker did not report a CUDA compute capability");
    }
    if observation.cuda_runtime_version == 0 || observation.cuda_driver_version == 0 {
        return Err("CUDA range worker did not report CUDA runtime and driver versions");
    }

    let reference = smoke_reference_range(requested_start, requested_items)?;
    if observation.checksum != reference {
        return Err("CUDA range checksum does not match scalar smoke oracle");
    }

    Ok(reference)
}

fn run_cuda_smoke_with_helper(
    helper_path: &Path,
    items: u64,
    device_ordinal: u32,
) -> Result<CudaSmokeRun, String> {
    if items == 0 {
        return Err("items must be greater than zero".into());
    }

    let output = ProcessCommand::new(helper_path)
        .arg("--items")
        .arg(items.to_string())
        .arg("--device")
        .arg(device_ordinal.to_string())
        .output()
        .map_err(|error| format!("CUDA helper launch failed: {error}"))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let detail = stderr.trim();
        return if detail.is_empty() {
            Err(format!(
                "CUDA helper exited unsuccessfully with status {}",
                output.status
            ))
        } else {
            Err(format!("CUDA helper failed: {detail}"))
        };
    }

    let stdout = std::str::from_utf8(&output.stdout)
        .map_err(|_| "CUDA helper stdout is not UTF-8".to_owned())?;
    let observation = parse_cuda_worker_line(stdout).map_err(str::to_owned)?;
    let reference = validate_cuda_worker_observation(items, device_ordinal, observation)
        .map_err(str::to_owned)?;
    Ok(CudaSmokeRun {
        observation,
        reference,
        helper_path: helper_path.to_path_buf(),
    })
}

fn elapsed_nanos_u64(start: Instant, overflow_error: &'static str) -> Result<u64, String> {
    u64::try_from(start.elapsed().as_nanos()).map_err(|_| overflow_error.to_owned())
}

fn run_cuda_smoke_timed_with_helper(
    helper_path: &Path,
    items: u64,
    device_ordinal: u32,
) -> Result<CudaSmokeTimingRun, String> {
    if items == 0 {
        return Err("items must be greater than zero".into());
    }

    let launcher_started = Instant::now();
    let output = ProcessCommand::new(helper_path)
        .arg("--items")
        .arg(items.to_string())
        .arg("--device")
        .arg(device_ordinal.to_string())
        .arg("--timing-v2")
        .output()
        .map_err(|error| format!("CUDA timing helper launch failed: {error}"))?;
    let launcher_total_ns = elapsed_nanos_u64(
        launcher_started,
        "CUDA launcher timing overflows u64 nanoseconds",
    )?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let detail = stderr.trim();
        return if detail.is_empty() {
            Err(format!(
                "CUDA timing helper exited unsuccessfully with status {}",
                output.status
            ))
        } else {
            Err(format!("CUDA timing helper failed: {detail}"))
        };
    }

    let stdout = std::str::from_utf8(&output.stdout)
        .map_err(|_| "CUDA timing helper stdout is not UTF-8".to_owned())?;
    let observation = parse_cuda_timing_worker_line(stdout).map_err(str::to_owned)?;
    validate_cuda_timing_worker_observation_shape(items, device_ordinal, observation)
        .map_err(str::to_owned)?;

    let verification_started = Instant::now();
    let reference = smoke_reference(items).map_err(str::to_owned)?;
    let verification_ns = elapsed_nanos_u64(
        verification_started,
        "CUDA scalar verification timing overflows u64 nanoseconds",
    )?;
    if observation.checksum != reference {
        return Err("CUDA timing checksum does not match scalar smoke oracle".into());
    }
    if launcher_total_ns < observation.worker_total_ns {
        return Err("CUDA launcher total is shorter than worker total".into());
    }

    Ok(CudaSmokeTimingRun {
        observation,
        reference,
        helper_path: helper_path.to_path_buf(),
        launcher_total_ns,
        verification_ns,
    })
}

fn canonical_cuda_helper_path() -> Result<PathBuf, String> {
    let executable = std::env::current_exe()
        .map_err(|error| format!("cannot resolve running mesh executable: {error}"))?;
    let executable = std::fs::canonicalize(&executable)
        .map_err(|error| format!("cannot canonicalize running mesh executable: {error}"))?;
    let target_dir = executable
        .ancestors()
        .find(|path| path.file_name() == Some(OsStr::new("target")))
        .ok_or_else(|| {
            "running mesh executable is outside the supported application target tree".to_owned()
        })?;
    Ok(target_dir.join(CANONICAL_CUDA_HELPER_FILENAME))
}

pub fn run_cuda_smoke(items: u64, device_ordinal: u32) -> Result<CudaSmokeRun, String> {
    let helper_path = canonical_cuda_helper_path()?;
    run_cuda_smoke_with_helper(&helper_path, items, device_ordinal)
}

pub fn run_cuda_smoke_timed(items: u64, device_ordinal: u32) -> Result<CudaSmokeTimingRun, String> {
    let helper_path = canonical_cuda_helper_path()?;
    run_cuda_smoke_timed_with_helper(&helper_path, items, device_ordinal)
}

fn run_cuda_smoke_range_with_helper(
    helper_path: &Path,
    start: u64,
    items: u64,
    device_ordinal: u32,
) -> Result<CudaSmokeRangeRun, String> {
    if items == 0 {
        return Err("items must be greater than zero".into());
    }
    start
        .checked_add(items)
        .ok_or_else(|| "CUDA requested logical range overflows u64".to_owned())?;

    let output = ProcessCommand::new(helper_path)
        .arg("--start")
        .arg(start.to_string())
        .arg("--items")
        .arg(items.to_string())
        .arg("--device")
        .arg(device_ordinal.to_string())
        .output()
        .map_err(|error| format!("CUDA range helper launch failed: {error}"))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let detail = stderr.trim();
        return if detail.is_empty() {
            Err(format!(
                "CUDA range helper exited unsuccessfully with status {}",
                output.status
            ))
        } else {
            Err(format!("CUDA range helper failed: {detail}"))
        };
    }

    let stdout = std::str::from_utf8(&output.stdout)
        .map_err(|_| "CUDA range helper stdout is not UTF-8".to_owned())?;
    let observation = parse_cuda_range_worker_line(stdout).map_err(str::to_owned)?;
    let reference =
        validate_cuda_range_worker_observation(start, items, device_ordinal, observation)
            .map_err(str::to_owned)?;

    Ok(CudaSmokeRangeRun {
        observation,
        reference,
        helper_path: helper_path.to_path_buf(),
    })
}

pub fn run_cuda_smoke_range(
    start: u64,
    items: u64,
    device_ordinal: u32,
) -> Result<CudaSmokeRangeRun, String> {
    let helper_path = canonical_cuda_helper_path()?;
    run_cuda_smoke_range_with_helper(&helper_path, start, items, device_ordinal)
}

pub(crate) fn validate_cuda_smoke_range_run(run: &CudaSmokeRangeRun) -> Result<(), &'static str> {
    let reference = validate_cuda_range_worker_observation(
        run.observation.start,
        run.observation.items,
        run.observation.device_ordinal,
        run.observation,
    )?;
    if reference != run.reference {
        return Err("CUDA smoke range run derived state mismatch");
    }

    let canonical_helper =
        canonical_cuda_helper_path().map_err(|_| "cannot resolve canonical CUDA worker path")?;
    if run.helper_path != canonical_helper {
        return Err("CUDA smoke range run was not produced by the canonical worker path");
    }
    Ok(())
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

pub fn cuda_smoke_receipt_json(command: &str, run: CudaSmokeRun) -> Result<String, &'static str> {
    if command != "run" && command != "verify" {
        return Err("CUDA smoke receipt command must be run or verify");
    }

    let reference = validate_cuda_worker_observation(
        run.observation.items,
        run.observation.device_ordinal,
        run.observation,
    )?;
    if reference != run.reference {
        return Err("CUDA smoke run derived state mismatch");
    }

    let canonical_helper =
        canonical_cuda_helper_path().map_err(|_| "cannot resolve canonical CUDA worker path")?;
    if run.helper_path != canonical_helper {
        return Err("CUDA smoke run was not produced by the canonical worker path");
    }

    let helper = json_escape(&run.helper_path.to_string_lossy());
    let observation = run.observation();

    Ok(format!(
        "{{\"schema\":\"{CUDA_SMOKE_RECEIPT_SCHEMA}\",\"source_identity\":{{\"runtime\":\"qsol-mesh-cli\",\"executor_id\":\"{CUDA_EXECUTOR_ID}\",\"worker_protocol\":\"{CUDA_WORKER_PROTOCOL}\"}},\"workload_identity\":{{\"workload_id\":\"{SMOKE_WORKLOAD_ID}\",\"workload_contract_version\":\"1.0.0\"}},\"requested_configuration\":{{\"command\":\"{command}\",\"items\":{},\"device_ordinal\":{},\"helper_path\":\"{}\"}},\"observed_topology\":{{\"accelerator_observed\":true,\"backend\":\"nvidia-cuda\",\"device_ordinal\":{},\"compute_major\":{},\"compute_minor\":{},\"cuda_runtime_version\":{},\"cuda_driver_version\":{},\"evidence_source\":\"cuda-helper-process\"}},\"effective_execution\":{{\"backend\":\"nvidia-cuda\",\"device_ordinal\":{},\"blocks\":{},\"threads_per_block\":{},\"reduction\":\"device-strided-local-sums-plus-atomicAdd-u64\"}},\"memory_plan\":{{\"domains\":[\"accelerator-local\",\"host-pageable\"],\"accelerator_checksum_buffer_bytes\":8,\"per_item_materialization\":false}},\"calibration\":{{\"performed\":false}},\"verification\":{{\"kind\":\"scalar-reference-equality\",\"checksum\":\"{:016x}\",\"reference\":\"{:016x}\",\"verified\":true}},\"claim_boundary\":\"{CUDA_SMOKE_CLAIM_BOUNDARY}\"}}",
        observation.items,
        observation.device_ordinal,
        helper,
        observation.device_ordinal,
        observation.compute_major,
        observation.compute_minor,
        observation.cuda_runtime_version,
        observation.cuda_driver_version,
        observation.device_ordinal,
        observation.blocks,
        observation.threads_per_block,
        observation.checksum,
        run.reference()
    ))
}

pub fn cuda_smoke_timing_receipt_json(
    command: &str,
    run: CudaSmokeTimingRun,
) -> Result<String, &'static str> {
    if command != "run" && command != "verify" {
        return Err("CUDA timing receipt command must be run or verify");
    }

    validate_cuda_timing_worker_observation_shape(
        run.observation.items,
        run.observation.device_ordinal,
        run.observation,
    )?;
    let reference = smoke_reference(run.observation.items)?;
    if run.observation.checksum != reference || run.reference != reference {
        return Err("CUDA timing run derived state mismatch");
    }
    if run.launcher_total_ns < run.observation.worker_total_ns {
        return Err("CUDA launcher total is shorter than worker total");
    }

    let canonical_helper =
        canonical_cuda_helper_path().map_err(|_| "cannot resolve canonical CUDA worker path")?;
    if run.helper_path != canonical_helper {
        return Err("CUDA timing run was not produced by the canonical worker path");
    }

    let helper = json_escape(&run.helper_path.to_string_lossy());
    let observation = run.observation();

    Ok(format!(
        "{{\"schema\":\"{CUDA_TIMING_RECEIPT_SCHEMA}\",\"source_identity\":{{\"runtime\":\"qsol-mesh-cli\",\"executor_id\":\"{CUDA_EXECUTOR_ID}\",\"worker_protocol\":\"{CUDA_TIMING_WORKER_PROTOCOL}\",\"base_executor_contract\":\"qsol.mesh.nvidia-executor-contract.v1\"}},\"workload_identity\":{{\"workload_id\":\"{SMOKE_WORKLOAD_ID}\",\"workload_contract_version\":\"1.0.0\"}},\"requested_configuration\":{{\"command\":\"{command}\",\"items\":{},\"device_ordinal\":{},\"helper_path\":\"{}\",\"timing\":true}},\"observed_topology\":{{\"accelerator_observed\":true,\"backend\":\"nvidia-cuda\",\"device_ordinal\":{},\"compute_major\":{},\"compute_minor\":{},\"cuda_runtime_version\":{},\"cuda_driver_version\":{},\"evidence_source\":\"cuda-helper-process\"}},\"effective_execution\":{{\"backend\":\"nvidia-cuda\",\"device_ordinal\":{},\"blocks\":{},\"threads_per_block\":{},\"reduction\":\"device-strided-local-sums-plus-atomicAdd-u64\"}},\"memory_plan\":{{\"domains\":[\"accelerator-local\",\"host-pageable\"],\"accelerator_checksum_buffer_bytes\":8,\"device_to_host_result_bytes\":8,\"per_item_materialization\":false}},\"timing\":{{\"launcher_total_ns\":{},\"worker_total_ns\":{},\"setup_host_ns\":{},\"kernel_device_ns\":{},\"transfer_host_ns\":{},\"teardown_host_ns\":{},\"verification_ns\":{},\"clock_sources\":{{\"launcher_total_ns\":\"rust-std-instant-monotonic\",\"worker_total_ns\":\"cxx-std-steady-clock-monotonic\",\"setup_host_ns\":\"cxx-std-steady-clock-monotonic\",\"kernel_device_ns\":\"cuda-event-default-stream\",\"transfer_host_ns\":\"cxx-std-steady-clock-monotonic\",\"teardown_host_ns\":\"cxx-std-steady-clock-monotonic\",\"verification_ns\":\"rust-std-instant-monotonic\"}},\"synchronization\":{{\"kernel\":\"cuda-event-start-kernel-event-stop-device-synchronize\",\"transfer\":\"synchronous-cudaMemcpy-device-to-host-after-device-synchronize\",\"host_destination\":\"pageable-stack-u64\"}},\"cross_clock_additive_total\":false}},\"calibration\":{{\"performed\":false,\"placement_decision_influenced\":false}},\"verification\":{{\"kind\":\"scalar-reference-equality\",\"checksum\":\"{:016x}\",\"reference\":\"{:016x}\",\"verified\":true}},\"claim_boundary\":\"{CUDA_TIMING_CLAIM_BOUNDARY}\"}}",
        observation.items,
        observation.device_ordinal,
        helper,
        observation.device_ordinal,
        observation.compute_major,
        observation.compute_minor,
        observation.cuda_runtime_version,
        observation.cuda_driver_version,
        observation.device_ordinal,
        observation.blocks,
        observation.threads_per_block,
        run.launcher_total_ns(),
        observation.worker_total_ns,
        observation.setup_host_ns,
        observation.kernel_device_ns,
        observation.transfer_host_ns,
        observation.teardown_host_ns,
        run.verification_ns(),
        observation.checksum,
        run.reference()
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn valid_line() -> String {
        format!(
            "{CUDA_WORKER_PROTOCOL}\titems=1000\tchecksum=d3886842145b489c\tblocks=16\tthreads_per_block=256\tdevice=0\tcompute_major=12\tcompute_minor=0\tcuda_runtime=13020\tcuda_driver=13020"
        )
    }

    fn valid_timing_line() -> String {
        format!(
            "{CUDA_TIMING_WORKER_PROTOCOL}\titems=1000\tchecksum=d3886842145b489c\tblocks=16\tthreads_per_block=256\tdevice=0\tcompute_major=12\tcompute_minor=0\tcuda_runtime=13020\tcuda_driver=13020\tsetup_host_ns=100\tkernel_device_ns=40\ttransfer_host_ns=20\tteardown_host_ns=10\tworker_total_ns=200"
        )
    }

    fn valid_range_line() -> String {
        format!(
            "{CUDA_RANGE_WORKER_PROTOCOL}\tstart=400\titems=600\tchecksum=66eba516d94fe913\tblocks=8\tthreads_per_block=256\tdevice=0\tcompute_major=12\tcompute_minor=0\tcuda_runtime=13020\tcuda_driver=13020"
        )
    }

    #[test]
    fn parses_exact_worker_protocol() {
        assert_eq!(
            parse_cuda_worker_line(&valid_line()),
            Ok(CudaWorkerObservation {
                items: 1_000,
                checksum: 0xd388_6842_145b_489c,
                blocks: 16,
                threads_per_block: 256,
                device_ordinal: 0,
                compute_major: 12,
                compute_minor: 0,
                cuda_runtime_version: 13_020,
                cuda_driver_version: 13_020,
            })
        );
    }

    #[test]
    fn parses_exact_timing_worker_protocol() {
        assert_eq!(
            parse_cuda_timing_worker_line(&valid_timing_line()),
            Ok(CudaTimingWorkerObservation {
                items: 1_000,
                checksum: 0xd388_6842_145b_489c,
                blocks: 16,
                threads_per_block: 256,
                device_ordinal: 0,
                compute_major: 12,
                compute_minor: 0,
                cuda_runtime_version: 13_020,
                cuda_driver_version: 13_020,
                setup_host_ns: 100,
                kernel_device_ns: 40,
                transfer_host_ns: 20,
                teardown_host_ns: 10,
                worker_total_ns: 200,
            })
        );
    }

    #[test]
    fn timing_protocol_fails_closed_on_bad_or_inconsistent_fields() {
        assert!(parse_cuda_timing_worker_line(
            &valid_timing_line().replace("\tsetup_host_ns=100", "")
        )
        .is_err());
        assert!(parse_cuda_timing_worker_line(
            &valid_timing_line().replace("kernel_device_ns=40", "setup_host_ns=40")
        )
        .is_err());
        assert!(parse_cuda_timing_worker_line(
            &valid_timing_line().replace("setup_host_ns=100", "setup_host_ns=-1")
        )
        .is_err());
        assert!(parse_cuda_timing_worker_line(&valid_timing_line().replace(
            "worker_total_ns=200",
            "worker_total_ns=18446744073709551616"
        ))
        .is_err());

        let inconsistent = parse_cuda_timing_worker_line(
            &valid_timing_line().replace("worker_total_ns=200", "worker_total_ns=120"),
        )
        .unwrap();
        assert_eq!(
            validate_cuda_timing_worker_observation_shape(1_000, 0, inconsistent),
            Err("CUDA timing host components exceed worker total")
        );
    }

    #[test]
    fn parses_exact_range_worker_protocol() {
        assert_eq!(
            parse_cuda_range_worker_line(&valid_range_line()),
            Ok(CudaRangeWorkerObservation {
                start: 400,
                items: 600,
                checksum: 0x66eb_a516_d94f_e913,
                blocks: 8,
                threads_per_block: 256,
                device_ordinal: 0,
                compute_major: 12,
                compute_minor: 0,
                cuda_runtime_version: 13_020,
                cuda_driver_version: 13_020,
            })
        );
    }

    #[test]
    fn malformed_range_worker_protocol_fails_closed() {
        assert!(parse_cuda_range_worker_line("not-the-range-protocol").is_err());
        assert!(parse_cuda_range_worker_line(&(valid_range_line() + "\n\n")).is_err());
        assert!(parse_cuda_range_worker_line(
            &valid_range_line().replace("checksum=66eba516d94fe913", "checksum=0000000000000000")
        )
        .is_ok());
    }

    #[test]
    fn malformed_worker_protocol_fails_closed() {
        assert!(parse_cuda_worker_line("not-the-protocol").is_err());
        assert!(parse_cuda_worker_line(&(valid_line() + "\textra=1")).is_err());
        assert!(parse_cuda_worker_line(&(valid_line() + "\n\n")).is_err());
        assert!(parse_cuda_worker_line(&(valid_line() + "\r\n\r\n")).is_err());
        assert!(parse_cuda_worker_line(&(valid_line() + "\r")).is_err());
        assert!(parse_cuda_worker_line(
            &valid_line().replace("checksum=d3886842145b489c", "checksum=1234")
        )
        .is_err());
    }

    #[test]
    fn worker_observation_must_match_request_and_oracle() {
        let observation = parse_cuda_worker_line(&valid_line()).unwrap();
        let reference = validate_cuda_worker_observation(1_000, 0, observation).unwrap();
        assert_eq!(reference, 0xd388_6842_145b_489c);

        assert_eq!(
            validate_cuda_worker_observation(999, 0, observation),
            Err("CUDA worker items do not match requested workload")
        );
        assert_eq!(
            validate_cuda_worker_observation(1_000, 1, observation),
            Err("CUDA worker device does not match requested device")
        );

        let mut wrong = observation;
        wrong.checksum ^= 1;
        assert_eq!(
            validate_cuda_worker_observation(1_000, 0, wrong),
            Err("CUDA checksum does not match scalar smoke oracle")
        );
    }

    #[test]
    fn range_worker_observation_must_match_request_and_oracle() {
        let observation = parse_cuda_range_worker_line(&valid_range_line()).unwrap();
        let reference = validate_cuda_range_worker_observation(400, 600, 0, observation).unwrap();
        assert_eq!(reference, 0x66eb_a516_d94f_e913);

        assert_eq!(
            validate_cuda_range_worker_observation(401, 600, 0, observation),
            Err("CUDA range worker start does not match requested workload")
        );
        assert_eq!(
            validate_cuda_range_worker_observation(400, 599, 0, observation),
            Err("CUDA range worker items do not match requested workload")
        );
        let mut wrong = observation;
        wrong.checksum ^= 1;
        assert_eq!(
            validate_cuda_range_worker_observation(400, 600, 0, wrong),
            Err("CUDA range checksum does not match scalar smoke oracle")
        );
        assert_eq!(
            validate_cuda_range_worker_observation(u64::MAX, 1, 0, observation),
            Err("CUDA requested logical range overflows u64")
        );
    }

    #[test]
    fn canonical_helper_path_is_independent_of_current_working_directory() {
        let resolved = canonical_cuda_helper_path().unwrap();
        assert!(resolved.is_absolute());
        assert_eq!(
            resolved.file_name(),
            Some(OsStr::new(CANONICAL_CUDA_HELPER_FILENAME))
        );
        assert_ne!(resolved, PathBuf::from(CANONICAL_CUDA_HELPER_FILENAME));
    }

    #[test]
    fn receipt_rejects_noncanonical_launcher_path() {
        let observation = parse_cuda_worker_line(&valid_line()).unwrap();
        let reference = validate_cuda_worker_observation(1_000, 0, observation).unwrap();
        let run = CudaSmokeRun {
            observation,
            reference,
            helper_path: PathBuf::from("/tmp/forged/mesh-cuda-smoke"),
        };
        assert_eq!(
            cuda_smoke_receipt_json("run", run),
            Err("CUDA smoke run was not produced by the canonical worker path")
        );
    }

    #[test]
    fn missing_helper_fails_closed_independently_of_canonical_worker_state() {
        let root = std::env::temp_dir().join(format!(
            "qsol-mesh-missing-cuda-helper-{}",
            std::process::id()
        ));
        let helper = root.join(CANONICAL_CUDA_HELPER_FILENAME);
        let _ = std::fs::remove_file(&helper);
        let _ = std::fs::remove_dir_all(&root);

        let result = run_cuda_smoke_with_helper(&helper, 1_000, 0);
        assert!(result.is_err());
        assert!(!helper.exists());
    }

    #[test]
    fn timing_receipt_requires_revalidated_cuda_execution() {
        let observation = parse_cuda_timing_worker_line(&valid_timing_line()).unwrap();
        validate_cuda_timing_worker_observation_shape(1_000, 0, observation).unwrap();
        let reference = smoke_reference(1_000).unwrap();
        let helper_path = canonical_cuda_helper_path().unwrap();
        let run = CudaSmokeTimingRun {
            observation,
            reference,
            helper_path: helper_path.clone(),
            launcher_total_ns: 300,
            verification_ns: 12,
        };
        let receipt = cuda_smoke_timing_receipt_json("verify", run).unwrap();
        assert!(receipt.contains("\"schema\":\"qsol.mesh.cuda-smoke-receipt.v2\""));
        assert!(receipt.contains("\"worker_protocol\":\"qsol.mesh.cuda-smoke-worker.v2\""));
        assert!(receipt.contains("\"kernel_device_ns\":40"));
        assert!(receipt.contains("\"cross_clock_additive_total\":false"));
        assert!(receipt.contains("\"placement_decision_influenced\":false"));
    }

    #[test]
    fn receipt_requires_revalidated_cuda_execution() {
        let observation = parse_cuda_worker_line(&valid_line()).unwrap();
        let reference = validate_cuda_worker_observation(1_000, 0, observation).unwrap();
        let helper_path = canonical_cuda_helper_path().unwrap();
        let run = CudaSmokeRun {
            observation,
            reference,
            helper_path: helper_path.clone(),
        };
        let receipt = cuda_smoke_receipt_json("run", run).unwrap();
        for section in [
            "\"source_identity\"",
            "\"workload_identity\"",
            "\"requested_configuration\"",
            "\"observed_topology\"",
            "\"effective_execution\"",
            "\"memory_plan\"",
            "\"calibration\"",
            "\"verification\"",
            "\"claim_boundary\"",
        ] {
            assert!(receipt.contains(section));
        }
        assert!(receipt.contains("\"backend\":\"nvidia-cuda\""));
        assert!(receipt.contains(&format!(
            "\"helper_path\":\"{}\"",
            json_escape(&helper_path.to_string_lossy())
        )));
        assert!(receipt.contains("\"verified\":true"));
        assert!(receipt.contains("\"checksum\":\"d3886842145b489c\""));
    }
}
