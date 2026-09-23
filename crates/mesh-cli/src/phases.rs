use qsol_mesh_core::{
    adaptive::{phase_receipt_json, run_phases, PhaseRequest, MAX_PHASES},
    available_workers, Command,
};

pub fn print(command: Command, args: &[String]) -> Result<(), String> {
    let mut request = PhaseRequest {
        phase_items: Vec::new(),
        calibration_items: 10_000,
        repeats: 3,
        near_tie_bps: 500,
        cuda: false,
        device: 0,
    };
    let mut json = false;
    let mut seen = std::collections::HashSet::new();
    let mut args = args.iter();
    while let Some(flag) = args.next() {
        if !seen.insert(flag.as_str()) {
            return Err(format!("{flag} may be specified only once"));
        }
        match flag.as_str() {
            "--json" => json = true,
            "--cuda" => request.cuda = true,
            "--phase-items" => {
                let values = args
                    .next()
                    .ok_or("--phase-items requires a comma-separated list")?;
                for value in values.split(',') {
                    if request.phase_items.len() == MAX_PHASES {
                        return Err("phase count must be between 1 and 64".into());
                    }
                    request
                        .phase_items
                        .push(value.parse().map_err(|_| "phase items must be u64")?);
                }
            }
            "--calibration-items" | "--repeats" | "--near-tie-bps" | "--device" => {
                let value = args
                    .next()
                    .ok_or_else(|| format!("{flag} requires a value"))?;
                match flag.as_str() {
                    "--calibration-items" => {
                        request.calibration_items =
                            value.parse().map_err(|_| "calibration items must be u64")?
                    }
                    "--repeats" => {
                        request.repeats = value.parse().map_err(|_| "repeats must be usize")?
                    }
                    "--near-tie-bps" => {
                        request.near_tie_bps =
                            value.parse().map_err(|_| "near-tie-bps must be u32")?
                    }
                    _ => request.device = value.parse().map_err(|_| "device must be u32")?,
                }
            }
            _ => return Err(format!("unsupported phase runtime argument: {flag}")),
        }
    }
    if seen.contains("--device") && !request.cuda {
        return Err("--device requires --cuda".into());
    }
    request.validate()?;
    let run = run_phases(&request, available_workers())?;
    let receipt = phase_receipt_json(command.as_str(), &run)?;
    if json {
        println!("{receipt}");
    } else {
        println!(
            "mesh-smoke-phases-v1 phases={} verified=true",
            request.phase_items.len()
        );
    }
    Ok(())
}
