// SPDX-License-Identifier: Apache-2.0

use qsol_mesh_core::{
    accelerator::{cuda_smoke_receipt_json, run_cuda_smoke_with_helper},
    available_workers,
    memory::{build_streaming_memory_plan, memory_plan_receipt_json, MemoryPlanRequest},
    planner::{calibrate_cpu_smoke_host, calibrated_plan_receipt_json, DEFAULT_NEAR_TIE_BPS},
    run_smoke, Command, CONTRACT_SCHEMA, CONTRACT_VERSION, SMOKE_WORKLOAD_ID,
};
use std::{env, path::PathBuf, process::ExitCode};

fn usage() -> &'static str {
    "Usage:\n  mesh inspect [--json]\n  mesh run smoke [--items N] [--workers N] [--json]\n  mesh verify smoke [--items N] [--workers N] [--json]\n  mesh run smoke-cuda [--items N] [--device N] [--helper PATH] [--json]\n  mesh verify smoke-cuda [--items N] [--device N] [--helper PATH] [--json]\n  mesh calibrate smoke [--calibration-items N] [--full-items N] [--repeats N] [--near-tie-bps N] [--json]\n  mesh plan memory [--total-bytes N] [--chunk-bytes N] [--pinned-limit-bytes N] [--accelerator-limit-bytes N] [--partial-bytes N] [--json]\n  mesh <calibrate|plan|receipt> [--json]\n"
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

fn parse_cuda_smoke(args: &[String]) -> Result<(u64, u32, PathBuf, bool), String> {
    let mut items = 100_000_u64;
    let mut device = 0_u32;
    let mut helper = env::var_os("QSOL_MESH_CUDA_HELPER")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("target/mesh-cuda-smoke"));
    let mut json = false;
    let mut seen_items = false;
    let mut seen_device = false;
    let mut seen_helper = false;
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
            "--helper" => {
                if seen_helper {
                    return Err("--helper may be specified only once".into());
                }
                seen_helper = true;
                if value.is_empty() {
                    return Err("--helper must not be empty".into());
                }
                helper = PathBuf::from(value);
            }
            other => return Err(format!("unsupported CUDA smoke argument: {other}")),
        }
        i += 2;
    }

    if items == 0 {
        return Err("--items must be greater than zero".into());
    }

    Ok((items, device, helper, json))
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
    let (items, device, helper, json) = parse_cuda_smoke(args)?;
    let run = run_cuda_smoke_with_helper(&helper, items, device)?;
    if json {
        println!(
            "{}",
            cuda_smoke_receipt_json(command.as_str(), &helper, run).map_err(str::to_owned)?
        );
    } else {
        println!(
            "{} backend=nvidia-cuda device={} blocks={} threads_per_block={} checksum={:016x} verified=true",
            SMOKE_WORKLOAD_ID,
            run.observation.device_ordinal,
            run.observation.blocks,
            run.observation.threads_per_block,
            run.observation.checksum
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
