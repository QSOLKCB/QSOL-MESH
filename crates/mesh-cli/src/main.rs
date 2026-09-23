// SPDX-License-Identifier: Apache-2.0

use qsol_mesh_core::{
    accelerator::{
        cuda_smoke_receipt_json, cuda_smoke_timing_receipt_json, run_cuda_smoke,
        run_cuda_smoke_timed,
    },
    available_workers,
    concurrent_split::{concurrent_split_receipt_json, run_concurrent_smoke_partition},
    galaxy_runtime::verify_cpu_parity,
    memory::{build_streaming_memory_plan, memory_plan_receipt_json, MemoryPlanRequest},
    memory_runtime::{run_stream, stream_receipt_json, StreamRequest},
    planner::{calibrate_cpu_smoke_host, calibrated_plan_receipt_json, DEFAULT_NEAR_TIE_BPS},
    run_smoke,
    static_split::{
        run_static_smoke_partition, static_split_receipt_json, validate_static_split_request,
        StaticSplitRequest,
    },
    Command, CONTRACT_SCHEMA, CONTRACT_VERSION, SMOKE_WORKLOAD_ID,
};
use std::{env, path::PathBuf, process::ExitCode};

fn usage() -> &'static str {
    "Usage:\n  mesh inspect [--json]\n  mesh run smoke [--items N] [--workers N] [--json]\n  mesh verify smoke [--items N] [--workers N] [--json]\n  mesh run smoke-cuda [--items N] [--device N] [--timing] [--json]\n  mesh verify smoke-cuda [--items N] [--device N] [--timing] [--json]\n  mesh verify smoke-stream [--items N] [--chunk-items N] [--pinned-limit-bytes N] [--accelerator-limit-bytes N] [--device N] [--json]\n  mesh run smoke-static --cpu-items N [--items N] [--cpu-workers N] [--device N] [--json]\n  mesh verify smoke-static --cpu-items N [--items N] [--cpu-workers N] [--device N] [--json]\n  mesh run smoke-concurrent --cpu-items N [--items N] [--cpu-workers N] [--device N] [--json]\n  mesh verify smoke-concurrent --cpu-items N [--items N] [--cpu-workers N] [--device N] [--json]\n  mesh verify galaxy-cpu --binary PATH [--logical U64] [--resident N] [--frames N] [--seed N] [--partitions N] [--json]\n  mesh calibrate smoke [--calibration-items N] [--full-items N] [--repeats N] [--near-tie-bps N] [--json]\n  mesh plan memory [--total-bytes N] [--chunk-bytes N] [--pinned-limit-bytes N] [--accelerator-limit-bytes N] [--partial-bytes N] [--json]\n  mesh <calibrate|plan|receipt> [--json]\n"
}

fn print_smoke_stream(command: Command, args: &[String]) -> Result<(), String> {
    let mut request = StreamRequest {
        items: 100_000,
        requested_chunk_items: 16_384,
        pinned_limit_bytes: 131_080,
        accelerator_limit_bytes: 131_080,
        device: 0,
    };
    let mut seen = std::collections::HashSet::new();
    let mut json = false;
    let mut index = 0;
    while index < args.len() {
        let flag = args[index].as_str();
        if !seen.insert(flag) {
            return Err(format!("duplicate stream option: {flag}"));
        }
        if flag == "--json" {
            json = true;
            index += 1;
            continue;
        }
        let value = args
            .get(index + 1)
            .ok_or_else(|| format!("{flag} requires a value"))?;
        let number: u64 = value.parse().map_err(|_| format!("{flag} must be u64"))?;
        match flag {
            "--items" => request.items = number,
            "--chunk-items" => request.requested_chunk_items = number,
            "--pinned-limit-bytes" => request.pinned_limit_bytes = number,
            "--accelerator-limit-bytes" => request.accelerator_limit_bytes = number,
            "--device" => request.device = number.try_into().map_err(|_| "--device must be u32")?,
            _ => return Err(format!("unsupported stream option: {flag}")),
        }
        index += 2;
    }
    let run = run_stream(request)?;
    if json {
        println!(
            "{}",
            stream_receipt_json(command.as_str(), &run).map_err(str::to_owned)?
        );
    } else {
        let observed = run.observation();
        println!(
            "smoke-stream chunks={} chunk_items={} checksum={:016x} verified=true",
            observed.chunks, observed.chunk_items, observed.checksum
        );
    }
    Ok(())
}

fn print_galaxy_cpu_parity(args: &[String]) -> Result<(), String> {
    let mut binary = None;
    let mut logical = u64::MAX;
    let mut resident = 8_388_608_u64;
    let mut frames = 8_u32;
    let mut seed = 303_u32;
    let mut partitions = 2_usize;
    let mut json = false;
    let mut seen = std::collections::HashSet::new();
    let mut index = 0;
    while index < args.len() {
        let flag = args[index].as_str();
        if !seen.insert(flag) {
            return Err(format!("duplicate GALAXY option: {flag}"));
        }
        if flag == "--json" {
            json = true;
            index += 1;
            continue;
        }
        let value = args
            .get(index + 1)
            .ok_or_else(|| format!("{flag} requires a value"))?;
        match flag {
            "--binary" => binary = Some(PathBuf::from(value)),
            "--logical" => logical = value.parse().map_err(|_| "--logical must be u64")?,
            "--resident" => resident = value.parse().map_err(|_| "--resident must be u64")?,
            "--frames" => frames = value.parse().map_err(|_| "--frames must be u32")?,
            "--seed" => seed = value.parse().map_err(|_| "--seed must be u32")?,
            "--partitions" => {
                partitions = value.parse().map_err(|_| "--partitions must be usize")?
            }
            _ => return Err(format!("unsupported GALAXY option: {flag}")),
        }
        index += 2;
    }
    let binary = binary.ok_or("--binary is required for GALAXY CPU parity")?;
    let binary = binary
        .canonicalize()
        .map_err(|error| format!("GALAXY binary path is invalid: {error}"))?;
    let parity = verify_cpu_parity(&binary, logical, resident, frames, seed, partitions)?;
    if json {
        println!(
            "{{\"schema\":\"qsol.mesh.galaxy-cpu-parity-receipt.v1\",\"source_identity\":{{\"runtime\":\"qsol-mesh-cli\",\"upstream_protocol\":\"galaxy.cpu-range.v1\"}},\"workload_identity\":{{\"workload_id\":\"galaxy-v0.4.0-bam-lut-q30\",\"frozen_cpu_runtime_blob\":\"b12220565f6059482f706d46db1d9d2c29a9cc82\"}},\"requested_configuration\":{{\"logical_population\":{logical},\"resident_particles\":{resident},\"frames\":{frames},\"seed\":{seed},\"partitions\":{partitions}}},\"observed_topology\":{{\"status\":\"not-observed\",\"source\":\"external-galaxy-cpu-range-process\"}},\"effective_execution\":{{\"backend\":\"galaxy-owned-cpu-range\",\"partial_count\":{}}},\"memory_plan\":{{\"status\":\"not-observed\",\"owner\":\"galaxy-cpu-runtime\",\"mesh_materializes_logical_population\":false}},\"calibration\":{{\"performed\":false,\"placement_decision_influenced\":false}},\"verification\":{{\"full_checksum\":\"{:016x}\",\"partitioned_checksum\":\"{:016x}\",\"partitioned_parity\":true,\"archived_oracle_verified\":{}}},\"claim_boundary\":\"external-galaxy-cpu-range-output-parity-not-gpu-execution-not-binary-provenance\"}}",
            parity.partitioned.len(),
            parity.full.checksum,
            parity.checksum,
            parity.archived_oracle_verified
        );
    } else {
        println!(
            "galaxy-cpu checksum={:016x} partitions={} parity=true archived_oracle_verified={}",
            parity.checksum,
            parity.partitioned.len(),
            parity.archived_oracle_verified
        );
    }
    Ok(())
}

fn parse_smoke(args: &[String]) -> Result<(u64, usize, bool), String> {
    let (mut items, mut workers, mut json) = (100_000_u64, available_workers(), false);
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--json" => {
                json = true;
                i += 1;
            }
            "--items" | "--workers" => {
                let flag = args[i].as_str();
                let value = args
                    .get(i + 1)
                    .ok_or_else(|| format!("{flag} requires a value"))?;
                if flag == "--items" {
                    items = value.parse().map_err(|_| "--items must be u64")?;
                } else {
                    workers = value.parse().map_err(|_| "--workers must be usize")?;
                }
                i += 2;
            }
            other => return Err(format!("unsupported argument: {other}")),
        }
    }
    Ok((items, workers, json))
}

fn parse_cuda_smoke(args: &[String]) -> Result<(u64, u32, bool, bool), String> {
    let mut items = 100_000_u64;
    let mut device = 0_u32;
    let mut timing = false;
    let mut json = false;
    let mut seen_items = false;
    let mut seen_device = false;
    let mut seen_timing = false;
    let mut seen_json = false;

    let mut i = 0;
    while i < args.len() {
        let flag = args[i].as_str();
        if flag == "--json" {
            if seen_json {
                return Err("--json may be specified only once".into());
            }
            seen_json = true;
            json = true;
            i += 1;
            continue;
        }
        if flag == "--timing" {
            if seen_timing {
                return Err("--timing may be specified only once".into());
            }
            seen_timing = true;
            timing = true;
            i += 1;
            continue;
        }
        if flag == "--helper" {
            return Err("--helper overrides are not admitted for verified CUDA execution".into());
        }

        let value = args
            .get(i + 1)
            .ok_or_else(|| format!("{flag} requires a value"))?;
        match flag {
            "--items" => {
                if seen_items {
                    return Err("--items may be specified only once".into());
                }
                seen_items = true;
                items = value.parse::<u64>().map_err(|_| "--items must be u64")?;
            }
            "--device" => {
                if seen_device {
                    return Err("--device may be specified only once".into());
                }
                seen_device = true;
                device = value.parse::<u32>().map_err(|_| "--device must be u32")?;
            }
            other => return Err(format!("unsupported CUDA smoke argument: {other}")),
        }
        i += 2;
    }

    if items == 0 {
        return Err("--items must be greater than zero".into());
    }

    Ok((items, device, timing, json))
}
fn parse_static_split(args: &[String]) -> Result<(StaticSplitRequest, bool), String> {
    let mut items = 100_000_u64;
    let mut cpu_items = None;
    let mut cpu_workers = available_workers();
    let mut device_ordinal = 0_u32;
    let mut json = false;
    let mut seen_items = false;
    let mut seen_cpu_items = false;
    let mut seen_cpu_workers = false;
    let mut seen_device = false;
    let mut seen_json = false;

    let mut i = 0;
    while i < args.len() {
        let flag = args[i].as_str();
        if flag == "--json" {
            if seen_json {
                return Err("--json may be specified only once".into());
            }
            seen_json = true;
            json = true;
            i += 1;
            continue;
        }
        if flag == "--helper" {
            return Err("--helper overrides are not admitted for verified CUDA execution".into());
        }

        let value = args
            .get(i + 1)
            .ok_or_else(|| format!("{flag} requires a value"))?;
        match flag {
            "--items" => {
                if seen_items {
                    return Err("--items may be specified only once".into());
                }
                seen_items = true;
                items = value.parse::<u64>().map_err(|_| "--items must be u64")?;
            }
            "--cpu-items" => {
                if seen_cpu_items {
                    return Err("--cpu-items may be specified only once".into());
                }
                seen_cpu_items = true;
                cpu_items = Some(
                    value
                        .parse::<u64>()
                        .map_err(|_| "--cpu-items must be u64")?,
                );
            }
            "--cpu-workers" => {
                if seen_cpu_workers {
                    return Err("--cpu-workers may be specified only once".into());
                }
                seen_cpu_workers = true;
                cpu_workers = value
                    .parse::<usize>()
                    .map_err(|_| "--cpu-workers must be usize")?;
            }
            "--device" => {
                if seen_device {
                    return Err("--device may be specified only once".into());
                }
                seen_device = true;
                device_ordinal = value.parse::<u32>().map_err(|_| "--device must be u32")?;
            }
            other => return Err(format!("unsupported static split argument: {other}")),
        }
        i += 2;
    }

    let cpu_items =
        cpu_items.ok_or_else(|| "--cpu-items is required for a fixed static split".to_owned())?;
    let request = StaticSplitRequest {
        items,
        cpu_items,
        cpu_workers,
        device_ordinal,
    };
    validate_static_split_request(request).map_err(str::to_owned)?;
    Ok((request, json))
}

fn parse_calibration(args: &[String]) -> Result<(u64, u64, usize, u32, bool), String> {
    let mut calibration_items = 10_000_u64;
    let mut full_items = 100_000_u64;
    let mut repeats = 3_usize;
    let mut near_tie_bps = DEFAULT_NEAR_TIE_BPS;
    let mut json = false;
    let mut seen_json = false;
    let mut seen_calibration = false;
    let mut seen_full = false;
    let mut seen_repeats = false;
    let mut seen_margin = false;

    let mut i = 0;
    while i < args.len() {
        let flag = args[i].as_str();
        if flag == "--json" {
            if seen_json {
                return Err("--json may be specified only once".into());
            }
            seen_json = true;
            json = true;
            i += 1;
            continue;
        }

        let value = args
            .get(i + 1)
            .ok_or_else(|| format!("{flag} requires a value"))?;
        match flag {
            "--calibration-items" => {
                if seen_calibration {
                    return Err("--calibration-items may be specified only once".into());
                }
                seen_calibration = true;
                calibration_items = value
                    .parse::<u64>()
                    .map_err(|_| "--calibration-items must be u64")?;
            }
            "--full-items" => {
                if seen_full {
                    return Err("--full-items may be specified only once".into());
                }
                seen_full = true;
                full_items = value
                    .parse::<u64>()
                    .map_err(|_| "--full-items must be u64")?;
            }
            "--repeats" => {
                if seen_repeats {
                    return Err("--repeats may be specified only once".into());
                }
                seen_repeats = true;
                repeats = value
                    .parse::<usize>()
                    .map_err(|_| "--repeats must be usize")?;
            }
            "--near-tie-bps" => {
                if seen_margin {
                    return Err("--near-tie-bps may be specified only once".into());
                }
                seen_margin = true;
                near_tie_bps = value
                    .parse::<u32>()
                    .map_err(|_| "--near-tie-bps must be u32")?;
            }
            other => return Err(format!("unsupported calibration argument: {other}")),
        }
        i += 2;
    }

    if calibration_items == 0 {
        return Err("--calibration-items must be greater than zero".into());
    }
    if full_items < calibration_items {
        return Err("--full-items must be at least --calibration-items".into());
    }
    if repeats == 0 {
        return Err("--repeats must be greater than zero".into());
    }
    if near_tie_bps >= 10_000 {
        return Err("--near-tie-bps must be less than 10000".into());
    }

    Ok((calibration_items, full_items, repeats, near_tie_bps, json))
}

fn parse_memory_plan(args: &[String]) -> Result<(MemoryPlanRequest, bool), String> {
    let mut request = MemoryPlanRequest {
        total_bytes: 1_073_741_824,
        requested_chunk_bytes: 67_108_864,
        host_pinned_limit_bytes: 67_108_864,
        accelerator_limit_bytes: 268_435_456,
        partial_bytes: 24,
    };
    let mut json = false;
    let mut seen_json = false;
    let mut seen_total = false;
    let mut seen_chunk = false;
    let mut seen_pinned = false;
    let mut seen_accelerator = false;
    let mut seen_partial = false;

    let mut i = 0;
    while i < args.len() {
        let flag = args[i].as_str();
        if flag == "--json" {
            if seen_json {
                return Err("--json may be specified only once".into());
            }
            seen_json = true;
            json = true;
            i += 1;
            continue;
        }

        let value = args
            .get(i + 1)
            .ok_or_else(|| format!("{flag} requires a value"))?;
        let parsed = value
            .parse::<u64>()
            .map_err(|_| format!("{flag} must be u64"))?;

        match flag {
            "--total-bytes" => {
                if seen_total {
                    return Err("--total-bytes may be specified only once".into());
                }
                seen_total = true;
                request.total_bytes = parsed;
            }
            "--chunk-bytes" => {
                if seen_chunk {
                    return Err("--chunk-bytes may be specified only once".into());
                }
                seen_chunk = true;
                request.requested_chunk_bytes = parsed;
            }
            "--pinned-limit-bytes" => {
                if seen_pinned {
                    return Err("--pinned-limit-bytes may be specified only once".into());
                }
                seen_pinned = true;
                request.host_pinned_limit_bytes = parsed;
            }
            "--accelerator-limit-bytes" => {
                if seen_accelerator {
                    return Err("--accelerator-limit-bytes may be specified only once".into());
                }
                seen_accelerator = true;
                request.accelerator_limit_bytes = parsed;
            }
            "--partial-bytes" => {
                if seen_partial {
                    return Err("--partial-bytes may be specified only once".into());
                }
                seen_partial = true;
                request.partial_bytes = parsed;
            }
            other => return Err(format!("unsupported memory plan argument: {other}")),
        }
        i += 2;
    }

    Ok((request, json))
}

fn print_inspect(json: bool) {
    let workers = available_workers();
    if json {
        println!(
            "{{\"schema\":\"qsol.mesh.inspect.v1\",\"arch\":\"{}\",\"os\":\"{}\",\"available_parallelism\":{workers}}}",
            env::consts::ARCH,
            env::consts::OS
        );
    } else {
        println!(
            "arch={} os={} available_parallelism={workers}",
            env::consts::ARCH,
            env::consts::OS
        );
    }
}

fn print_smoke(command: Command, args: &[String]) -> Result<(), String> {
    let (items, workers, json) = parse_smoke(args)?;
    let run = run_smoke(items, workers).map_err(str::to_owned)?;
    if json {
        let available = available_workers();
        println!(
            "{{\"schema\":\"qsol.mesh.smoke-receipt.v1\",\"source_identity\":{{\"runtime\":\"qsol-mesh-cli\",\"mesh_contract_schema\":\"{CONTRACT_SCHEMA}\",\"mesh_contract_version\":\"{CONTRACT_VERSION}\"}},\"workload_identity\":{{\"workload_id\":\"{SMOKE_WORKLOAD_ID}\",\"workload_contract_version\":\"1.0.0\"}},\"requested_configuration\":{{\"command\":\"{}\",\"items\":{},\"workers\":{}}},\"observed_topology\":{{\"arch\":\"{}\",\"os\":\"{}\",\"available_parallelism\":{}}},\"effective_execution\":{{\"backend\":\"cpu\",\"workers\":{},\"reduction\":\"worker-index-order-wrapping-u64\"}},\"memory_plan\":{{\"domains\":[\"host-pageable\"],\"per_item_materialization\":false,\"temporary_state\":\"O(workers)\"}},\"calibration\":{{\"performed\":false}},\"verification\":{{\"kind\":\"scalar-reference-equality\",\"checksum\":\"{:016x}\",\"reference\":\"{:016x}\",\"verified\":true}},\"claim_boundary\":\"runtime-bring-up-only-not-performance-evidence\"}}",
            command.as_str(),
            run.items,
            run.requested_workers,
            env::consts::ARCH,
            env::consts::OS,
            available,
            run.effective_workers,
            run.checksum,
            run.reference
        );
    } else {
        println!(
            "{} items={} workers={}/{} checksum={:016x} verified=true",
            SMOKE_WORKLOAD_ID,
            run.items,
            run.effective_workers,
            run.requested_workers,
            run.checksum
        );
    }
    Ok(())
}

fn print_cuda_smoke(command: Command, args: &[String]) -> Result<(), String> {
    let (items, device, timing, json) = parse_cuda_smoke(args)?;
    if timing {
        let run = run_cuda_smoke_timed(items, device)?;
        if json {
            println!(
                "{}",
                cuda_smoke_timing_receipt_json(command.as_str(), run).map_err(str::to_owned)?
            );
        } else {
            let observation = run.observation();
            println!(
                "{} backend=nvidia-cuda device={} blocks={} threads_per_block={} checksum={:016x} timing=true launcher_total_ns={} worker_total_ns={} setup_host_ns={} kernel_device_ns={} transfer_host_ns={} teardown_host_ns={} verification_ns={} verified=true",
                SMOKE_WORKLOAD_ID,
                observation.device_ordinal,
                observation.blocks,
                observation.threads_per_block,
                observation.checksum,
                run.launcher_total_ns(),
                observation.worker_total_ns,
                observation.setup_host_ns,
                observation.kernel_device_ns,
                observation.transfer_host_ns,
                observation.teardown_host_ns,
                run.verification_ns()
            );
        }
    } else {
        let run = run_cuda_smoke(items, device)?;
        if json {
            println!(
                "{}",
                cuda_smoke_receipt_json(command.as_str(), run).map_err(str::to_owned)?
            );
        } else {
            let observation = run.observation();
            println!(
                "{} backend=nvidia-cuda device={} blocks={} threads_per_block={} checksum={:016x} verified=true",
                SMOKE_WORKLOAD_ID,
                observation.device_ordinal,
                observation.blocks,
                observation.threads_per_block,
                observation.checksum
            );
        }
    }
    Ok(())
}

fn print_static_split(command: Command, args: &[String]) -> Result<(), String> {
    let (request, json) = parse_static_split(args)?;
    let run = run_static_smoke_partition(request)?;
    if json {
        println!(
            "{}",
            static_split_receipt_json(command.as_str(), &run).map_err(str::to_owned)?
        );
    } else {
        let cpu = run.cpu();
        let cuda = run.cuda().observation();
        println!(
            "{} static-split cpu=[0,{}) workers={}/{} cuda=[{}, {}) device={} checksum={:016x} concurrent=false verified=true",
            SMOKE_WORKLOAD_ID,
            request.cpu_items,
            cpu.effective_workers,
            cpu.requested_workers,
            request.cpu_items,
            request.items,
            cuda.device_ordinal,
            run.checksum()
        );
    }
    Ok(())
}

fn print_concurrent_split(command: Command, args: &[String]) -> Result<(), String> {
    let (request, json) = parse_static_split(args)?;
    let run = run_concurrent_smoke_partition(request)?;
    if json {
        println!(
            "{}",
            concurrent_split_receipt_json(command.as_str(), &run).map_err(str::to_owned)?
        );
    } else {
        let cpu = run.cpu();
        let cuda = run.cuda().observation();
        println!(
            "{} concurrent-split cpu=[0,{}) workers={}/{} cuda=[{}, {}) device={} checksum={:016x} concurrent_dispatch=true kernel_overlap_measured=false verified=true",
            SMOKE_WORKLOAD_ID,
            request.cpu_items,
            cpu.effective_workers,
            cpu.requested_workers,
            request.cpu_items,
            request.items,
            cuda.device_ordinal,
            run.checksum()
        );
    }
    Ok(())
}

fn print_calibration(args: &[String]) -> Result<(), String> {
    let (calibration_items, full_items, repeats, near_tie_bps, json) = parse_calibration(args)?;
    let plan = calibrate_cpu_smoke_host(
        available_workers(),
        calibration_items,
        full_items,
        repeats,
        near_tie_bps,
    )
    .map_err(str::to_owned)?;

    if json {
        println!(
            "{}",
            calibrated_plan_receipt_json(&plan).map_err(str::to_owned)?
        );
    } else {
        println!(
            "calibrated-plan candidates={} provisional={} selected={} canonical_retained={} reason={}",
            plan.candidates.len(),
            plan.provisional_candidate_id,
            plan.selected_candidate_id,
            plan.canonical_retained,
            plan.selection_reason
        );
    }
    Ok(())
}

fn print_memory_plan(args: &[String]) -> Result<(), String> {
    let (request, json) = parse_memory_plan(args)?;
    let plan = build_streaming_memory_plan(request).map_err(str::to_owned)?;
    if json {
        println!(
            "{}",
            memory_plan_receipt_json(&plan).map_err(str::to_owned)?
        );
    } else {
        println!(
            "memory-plan strategy={} total_bytes={} effective_chunk_bytes={} chunks={} physically_materialized=false",
            plan.strategy, plan.request.total_bytes, plan.effective_chunk_bytes, plan.chunk_count
        );
    }
    Ok(())
}

fn stub(command: Command, args: &[String]) -> Result<(), String> {
    if args.iter().any(|arg| arg != "--json") {
        return Err("only --json is accepted for unimplemented commands".into());
    }
    if args.iter().any(|arg| arg == "--json") {
        println!(
            "{{\"schema\":\"qsol.mesh.cli-stub.v1\",\"contract_schema\":\"{CONTRACT_SCHEMA}\",\"contract_version\":\"{CONTRACT_VERSION}\",\"command\":\"{}\",\"status\":\"not-implemented\"}}",
            command.as_str()
        );
    } else {
        println!("mesh {}: not implemented", command.as_str());
    }
    Ok(())
}

fn main() -> ExitCode {
    let args: Vec<String> = env::args().skip(1).collect();
    if args.is_empty() || args.iter().any(|arg| arg == "--help" || arg == "-h") {
        print!("{}", usage());
        return ExitCode::SUCCESS;
    }

    let Some(command) = Command::parse(&args[0]) else {
        eprintln!("mesh: unknown command: {}\n{}", args[0], usage());
        return ExitCode::from(2);
    };

    let result = match command {
        Command::Inspect => {
            if args[1..].iter().any(|arg| arg != "--json") {
                Err("mesh inspect only accepts --json".into())
            } else {
                print_inspect(args[1..].iter().any(|arg| arg == "--json"));
                Ok(())
            }
        }
        Command::Run | Command::Verify if args.get(1).map(String::as_str) == Some("smoke") => {
            print_smoke(command, &args[2..])
        }
        Command::Run | Command::Verify if args.get(1).map(String::as_str) == Some("smoke-cuda") => {
            print_cuda_smoke(command, &args[2..])
        }
        Command::Verify if args.get(1).map(String::as_str) == Some("smoke-stream") => {
            print_smoke_stream(command, &args[2..])
        }
        Command::Run if args.get(1).map(String::as_str) == Some("smoke-stream") => {
            Err("smoke-stream is admitted only by verify".into())
        }
        Command::Run | Command::Verify
            if args.get(1).map(String::as_str) == Some("smoke-static") =>
        {
            print_static_split(command, &args[2..])
        }
        Command::Run | Command::Verify
            if args.get(1).map(String::as_str) == Some("smoke-concurrent") =>
        {
            print_concurrent_split(command, &args[2..])
        }
        Command::Verify if args.get(1).map(String::as_str) == Some("galaxy-cpu") => {
            print_galaxy_cpu_parity(&args[2..])
        }
        Command::Calibrate if args.get(1).map(String::as_str) == Some("smoke") => {
            print_calibration(&args[2..])
        }
        Command::Plan if args.get(1).map(String::as_str) == Some("memory") => {
            print_memory_plan(&args[2..])
        }
        _ => stub(command, &args[1..]),
    };

    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("mesh: {error}");
            ExitCode::from(2)
        }
    }
}
