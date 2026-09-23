// SPDX-License-Identifier: Apache-2.0
//! Physical bounded CUDA streaming for the MESH-owned smoke workload.
//! The CUDA worker owns the allocations; the Rust launcher verifies its output
//! against an independent scalar oracle before issuing an execution receipt.

use crate::{accelerator::canonical_cuda_worker_path, smoke_reference, SMOKE_WORKLOAD_ID};
use std::{path::PathBuf, process::Command};

pub const STREAM_WORKER_PROTOCOL: &str = "qsol.mesh.cuda-stream-worker.v1";
pub const STREAM_RECEIPT_SCHEMA: &str = "qsol.mesh.cuda-stream-receipt.v1";
pub const STREAM_HELPER: &str = "mesh-cuda-stream";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct StreamRequest {
    pub items: u64,
    pub requested_chunk_items: u64,
    pub pinned_limit_bytes: u64,
    pub accelerator_limit_bytes: u64,
    pub device: u32,
}

impl StreamRequest {
    pub fn geometry(self) -> Result<(u64, u64, u64), &'static str> {
        if self.items == 0 || self.requested_chunk_items == 0 {
            return Err("stream items and chunk items must be positive");
        }
        if self.pinned_limit_bytes < 16 || self.accelerator_limit_bytes < 16 {
            return Err("stream memory budgets must fit one item and a compact partial");
        }
        let chunk = self
            .items
            .min(self.requested_chunk_items)
            .min((self.pinned_limit_bytes - 8) / 8)
            .min((self.accelerator_limit_bytes - 8) / 8)
            .min((usize::MAX / 8) as u64);
        if chunk == 0 {
            return Err("stream chunk capacity is zero");
        }
        let chunks = (self.items - 1) / chunk + 1;
        let events = chunks
            .checked_mul(3)
            .ok_or("stream event count overflows u64")?;
        Ok((chunk, chunks, events))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct StreamObservation {
    pub items: u64,
    pub chunk_items: u64,
    pub chunks: u64,
    pub checksum: u64,
    pub device: u32,
    pub compute_major: u32,
    pub compute_minor: u32,
    pub cuda_runtime: u32,
    pub cuda_driver: u32,
    pub host_pinned_peak_bytes: u64,
    pub accelerator_peak_bytes: u64,
    pub event_records: u64,
}

fn decimal(value: &str, key: &str) -> Result<u64, &'static str> {
    let value = value
        .strip_prefix(key)
        .ok_or("stream worker field mismatch")?;
    if value.is_empty() || !value.bytes().all(|c| c.is_ascii_digit()) {
        return Err("stream worker decimal field invalid");
    }
    value.parse().map_err(|_| "stream worker decimal overflow")
}

pub fn parse_stream_line(line: &str) -> Result<StreamObservation, &'static str> {
    let line = line
        .strip_suffix("\r\n")
        .or_else(|| line.strip_suffix('\n'))
        .unwrap_or(line);
    let fields: Vec<_> = line.split('\t').collect();
    if fields.len() != 18 || fields[0] != STREAM_WORKER_PROTOCOL {
        return Err("stream worker protocol mismatch");
    }
    let checksum = fields[4]
        .strip_prefix("checksum=")
        .ok_or("stream checksum field missing")?;
    if checksum.len() != 16
        || !checksum
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
    {
        return Err("stream checksum must be 16 lowercase hex digits");
    }
    for (index, name) in [
        (12, "pinned_staging_allocations="),
        (13, "pinned_partial_allocations="),
        (14, "device_pool_allocations="),
        (15, "device_partial_allocations="),
    ] {
        if decimal(fields[index], name)? != 1 {
            return Err("stream worker did not reuse its allocations");
        }
    }
    if decimal(fields[17], "partial_bytes=")? != 8 {
        return Err("stream partial must be one u64");
    }
    let small = |index, key| -> Result<u32, &'static str> {
        u32::try_from(decimal(fields[index], key)?)
            .map_err(|_| "stream topology value overflows u32")
    };
    Ok(StreamObservation {
        items: decimal(fields[1], "items=")?,
        chunk_items: decimal(fields[2], "chunk_items=")?,
        chunks: decimal(fields[3], "chunks=")?,
        checksum: u64::from_str_radix(checksum, 16).map_err(|_| "stream checksum invalid")?,
        device: small(5, "device=")?,
        compute_major: small(6, "compute_major=")?,
        compute_minor: small(7, "compute_minor=")?,
        cuda_runtime: small(8, "cuda_runtime=")?,
        cuda_driver: small(9, "cuda_driver=")?,
        host_pinned_peak_bytes: decimal(fields[10], "host_pinned_peak_bytes=")?,
        accelerator_peak_bytes: decimal(fields[11], "accelerator_peak_bytes=")?,
        event_records: decimal(fields[16], "event_records=")?,
    })
}

pub fn validate_stream_observation(
    request: StreamRequest,
    observed: StreamObservation,
) -> Result<u64, &'static str> {
    let (chunk, chunks, events) = request.geometry()?;
    let bytes = chunk
        .checked_mul(8)
        .and_then(|n| n.checked_add(8))
        .ok_or("stream peak bytes overflow")?;
    if observed.items != request.items
        || observed.chunk_items != chunk
        || observed.chunks != chunks
        || observed.device != request.device
        || observed.host_pinned_peak_bytes != bytes
        || observed.accelerator_peak_bytes != bytes
        || observed.event_records != events
    {
        return Err("stream worker geometry or physical allocation report differs from request");
    }
    if observed.compute_major == 0 || observed.cuda_runtime == 0 || observed.cuda_driver == 0 {
        return Err("stream worker did not report CUDA topology");
    }
    let reference = smoke_reference(request.items)?;
    if observed.checksum != reference {
        return Err("stream checksum does not match independent scalar smoke oracle");
    }
    Ok(reference)
}

#[derive(Debug)]
pub struct StreamRun {
    request: StreamRequest,
    observed: StreamObservation,
    reference: u64,
    helper_path: PathBuf,
}

pub fn run_stream(request: StreamRequest) -> Result<StreamRun, String> {
    request.geometry().map_err(str::to_owned)?;
    let helper = canonical_cuda_worker_path(STREAM_HELPER)?;
    let output = Command::new(&helper)
        .args([
            "--items",
            &request.items.to_string(),
            "--chunk-items",
            &request.requested_chunk_items.to_string(),
            "--pinned-limit-bytes",
            &request.pinned_limit_bytes.to_string(),
            "--accelerator-limit-bytes",
            &request.accelerator_limit_bytes.to_string(),
            "--device",
            &request.device.to_string(),
        ])
        .output()
        .map_err(|error| format!("CUDA stream helper launch failed: {error}"))?;
    if !output.status.success() {
        return Err(format!(
            "CUDA stream helper failed ({}): {}",
            output.status,
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    let stdout = std::str::from_utf8(&output.stdout).map_err(|_| "stream output is not UTF-8")?;
    let observed = parse_stream_line(stdout).map_err(str::to_owned)?;
    let reference = validate_stream_observation(request, observed).map_err(str::to_owned)?;
    Ok(StreamRun {
        request,
        observed,
        reference,
        helper_path: helper,
    })
}

pub fn stream_receipt_json(command: &str, run: &StreamRun) -> Result<String, &'static str> {
    if command != "run" && command != "verify" {
        return Err("stream receipt command must be run or verify");
    }
    if validate_stream_observation(run.request, run.observed)? != run.reference {
        return Err("stream receipt reference drift");
    }
    if canonical_cuda_worker_path(STREAM_HELPER)
        .map_err(|_| "stream worker path is not canonical")?
        != run.helper_path
    {
        return Err("stream receipt requires the canonical worker path");
    }
    let o = run.observed;
    let r = run.request;
    Ok(format!(
        "{{\"schema\":\"{STREAM_RECEIPT_SCHEMA}\",\"source_identity\":{{\"runtime\":\"qsol-mesh-cli\",\"worker_protocol\":\"{STREAM_WORKER_PROTOCOL}\",\"helper_resolution\":\"application-target-directory/mesh-cuda-stream\"}},\"workload_identity\":{{\"workload_id\":\"{SMOKE_WORKLOAD_ID}\"}},\"requested_configuration\":{{\"command\":\"{command}\",\"items\":{},\"requested_chunk_items\":{},\"host_pinned_limit_bytes\":{},\"accelerator_limit_bytes\":{},\"device_ordinal\":{}}},\"observed_topology\":{{\"accelerator_observed\":true,\"device_ordinal\":{},\"compute_major\":{},\"compute_minor\":{},\"cuda_runtime_version\":{},\"cuda_driver_version\":{},\"evidence_source\":\"cuda-helper-process\"}},\"effective_execution\":{{\"backend\":\"nvidia-cuda\",\"effective_chunk_items\":{},\"chunk_count\":{},\"event_records\":{},\"reduction\":\"host-ordered-wrapping-u64-partials\"}},\"memory_plan\":{{\"physically_materialized\":true,\"host_pinned_peak_bytes\":{},\"accelerator_peak_bytes\":{},\"pinned_staging_allocations\":1,\"pinned_partial_allocations\":1,\"device_pool_allocations\":1,\"device_partial_allocations\":1,\"partial_bytes\":8,\"reuse_across_chunks\":true}},\"calibration\":{{\"performed\":false}},\"verification\":{{\"kind\":\"scalar-reference-equality\",\"checksum\":\"{:016x}\",\"reference\":\"{:016x}\",\"verified\":true}},\"claim_boundary\":\"helper-reported-physical-cuda-streaming-and-scalar-parity-not-independent-hardware-attestation\"}}",
        r.items, r.requested_chunk_items, r.pinned_limit_bytes, r.accelerator_limit_bytes, r.device,
        o.device, o.compute_major, o.compute_minor, o.cuda_runtime, o.cuda_driver,
        o.chunk_items, o.chunks, o.event_records, o.host_pinned_peak_bytes,
        o.accelerator_peak_bytes, o.checksum, run.reference
    ))
}

impl StreamRun {
    pub const fn observation(&self) -> StreamObservation {
        self.observed
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request() -> StreamRequest {
        StreamRequest {
            items: 1000,
            requested_chunk_items: 400,
            pinned_limit_bytes: 1608,
            accelerator_limit_bytes: 2000,
            device: 0,
        }
    }

    fn line() -> &'static str {
        "qsol.mesh.cuda-stream-worker.v1\titems=1000\tchunk_items=200\tchunks=5\tchecksum=d3886842145b489c\tdevice=0\tcompute_major=12\tcompute_minor=0\tcuda_runtime=13000\tcuda_driver=13000\thost_pinned_peak_bytes=1608\taccelerator_peak_bytes=1608\tpinned_staging_allocations=1\tpinned_partial_allocations=1\tdevice_pool_allocations=1\tdevice_partial_allocations=1\tevent_records=15\tpartial_bytes=8\n"
    }

    #[test]
    fn bounded_geometry_and_scalar_parity() {
        let observed = parse_stream_line(line()).unwrap();
        assert_eq!(
            validate_stream_observation(request(), observed),
            Ok(0xd388_6842_145b_489c)
        );
        assert!(parse_stream_line(&(line().to_owned() + line())).is_err());
        assert!(parse_stream_line(
            &line().replace("device_pool_allocations=1", "device_pool_allocations=2")
        )
        .is_err());
        assert!(validate_stream_observation(
            StreamRequest {
                pinned_limit_bytes: 1600,
                ..request()
            },
            observed
        )
        .is_err());
        assert!(validate_stream_observation(
            request(),
            StreamObservation {
                checksum: 0,
                ..observed
            }
        )
        .is_err());
    }

    #[test]
    fn invalid_budget_fails_before_launch() {
        assert!(StreamRequest {
            pinned_limit_bytes: 15,
            ..request()
        }
        .geometry()
        .is_err());
        assert!(StreamRequest {
            items: 0,
            ..request()
        }
        .geometry()
        .is_err());
    }
}
