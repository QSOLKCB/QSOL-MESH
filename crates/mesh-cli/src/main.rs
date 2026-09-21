// SPDX-License-Identifier: Apache-2.0

use qsol_mesh_core::{
    available_workers, run_smoke, Command, CONTRACT_SCHEMA, CONTRACT_VERSION, SMOKE_WORKLOAD_ID,
};
use std::{env, process::ExitCode};

fn usage() -> &'static str {
    "Usage:\n  mesh inspect [--json]\n  mesh run smoke [--items N] [--workers N] [--json]\n  mesh verify smoke [--items N] [--workers N] [--json]\n  mesh <calibrate|plan|receipt> [--json]\n"
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
