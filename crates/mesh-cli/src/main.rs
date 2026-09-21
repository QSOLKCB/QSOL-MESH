// SPDX-License-Identifier: Apache-2.0

use qsol_mesh_core::{Command, CONTRACT_SCHEMA, CONTRACT_VERSION};
use std::{env, process::ExitCode};

fn usage() -> &'static str {
    "QSOL-MESH architecture bootstrap\n\nUsage:\n  mesh <inspect|calibrate|plan|run|verify|receipt> [--json]\n  mesh --help\n\nPR #1 exposes command identity only. Execution backends are intentionally not implemented.\n"
}

fn json_stub(command: Command) -> String {
    format!(
        "{{\"schema\":\"qsol.mesh.cli-stub.v1\",\"contract_schema\":\"{CONTRACT_SCHEMA}\",\"contract_version\":\"{CONTRACT_VERSION}\",\"command\":\"{}\",\"status\":\"not-implemented\",\"semantic_authority\":\"workload\",\"execution_authority\":\"mesh\"}}",
        command.as_str()
    )
}

fn text_stub(command: Command) -> String {
    format!("mesh {}: not implemented in architecture bootstrap; semantic authority remains with the workload", command.as_str())
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
    let json = args[1..].iter().any(|arg| arg == "--json");
    let unsupported: Vec<_> = args[1..]
        .iter()
        .filter(|arg| arg.as_str() != "--json")
        .collect();
    if !unsupported.is_empty() {
        eprintln!("mesh: unsupported arguments in architecture bootstrap: {unsupported:?}");
        return ExitCode::from(2);
    }
    println!(
        "{}",
        if json {
            json_stub(command)
        } else {
            text_stub(command)
        }
    );
    ExitCode::SUCCESS
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn json_stub_is_explicitly_non_implemented() {
        let output = json_stub(Command::Inspect);
        assert!(output.contains("\"status\":\"not-implemented\""));
        assert!(output.contains("\"semantic_authority\":\"workload\""));
    }
}
