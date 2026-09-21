// SPDX-License-Identifier: Apache-2.0

use std::thread;

pub const CONTRACT_SCHEMA: &str = "qsol.mesh.contract.v1";
pub const CONTRACT_VERSION: &str = "1.0.0";
pub const SMOKE_WORKLOAD_ID: &str = "mesh-smoke-v1";
const SMOKE_SEED: u64 = 0x4d45_5348_5f53_4d4b;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Command {
    Inspect,
    Calibrate,
    Plan,
    Run,
    Verify,
    Receipt,
}

impl Command {
    pub const ALL: [Self; 6] = [
        Self::Inspect,
        Self::Calibrate,
        Self::Plan,
        Self::Run,
        Self::Verify,
        Self::Receipt,
    ];

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Inspect => "inspect",
            Self::Calibrate => "calibrate",
            Self::Plan => "plan",
            Self::Run => "run",
            Self::Verify => "verify",
            Self::Receipt => "receipt",
        }
    }

    pub fn parse(value: &str) -> Option<Self> {
        Self::ALL
            .into_iter()
            .find(|command| command.as_str() == value)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SmokeRun {
    pub items: u64,
    pub requested_workers: usize,
    pub effective_workers: usize,
    pub checksum: u64,
    pub reference: u64,
}

pub fn available_workers() -> usize {
    thread::available_parallelism().map_or(1, |n| n.get())
}

fn mix64(mut x: u64) -> u64 {
    x ^= x >> 30;
    x = x.wrapping_mul(0xbf58_476d_1ce4_e5b9);
    x ^= x >> 27;
    x = x.wrapping_mul(0x94d0_49bb_1331_11eb);
    x ^ (x >> 31)
}

fn checksum_range(start: u64, end: u64) -> u64 {
    let mut sum = 0_u64;
    for id in start..end {
        sum = sum.wrapping_add(mix64(id ^ SMOKE_SEED));
    }
    sum
}

pub fn smoke_reference(items: u64) -> Result<u64, &'static str> {
    if items == 0 {
        return Err("items must be greater than zero");
    }
    Ok(checksum_range(0, items))
}

pub fn run_smoke(items: u64, requested_workers: usize) -> Result<SmokeRun, &'static str> {
    if items == 0 {
        return Err("items must be greater than zero");
    }
    if requested_workers == 0 {
        return Err("workers must be greater than zero");
    }

    let effective = requested_workers.min(usize::try_from(items).unwrap_or(usize::MAX));
    let base = items / effective as u64;
    let extra = items % effective as u64;

    let partials = thread::scope(|scope| {
        let mut start = 0_u64;
        let mut handles = Vec::with_capacity(effective);
        for worker in 0..effective {
            let len = base + u64::from((worker as u64) < extra);
            let end = start + len;
            handles.push(scope.spawn(move || checksum_range(start, end)));
            start = end;
        }
        handles
            .into_iter()
            .map(|handle| handle.join().expect("smoke worker panicked"))
            .collect::<Vec<_>>()
    });

    let checksum = partials
        .into_iter()
        .fold(0_u64, |sum, value| sum.wrapping_add(value));
    let reference = smoke_reference(items)?;
    if checksum != reference {
        return Err("parallel checksum does not match scalar reference");
    }

    Ok(SmokeRun {
        items,
        requested_workers,
        effective_workers: effective,
        checksum,
        reference,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn command_surface_remains_stable() {
        let commands: Vec<_> = Command::ALL.into_iter().map(Command::as_str).collect();
        assert_eq!(
            commands,
            ["inspect", "calibrate", "plan", "run", "verify", "receipt"]
        );
    }

    #[test]
    fn smoke_vector_is_stable() {
        assert_eq!(smoke_reference(1_000), Ok(0xd388_6842_145b_489c));
    }

    #[test]
    fn worker_counts_preserve_exact_result() {
        for workers in [1, 2, 3, 7, 32, 64] {
            let run = run_smoke(10_000, workers).unwrap();
            assert_eq!(run.checksum, 0x7cf0_a124_7592_acff);
            assert_eq!(run.checksum, run.reference);
        }
    }

    #[test]
    fn workers_are_bounded_by_work_items() {
        assert_eq!(run_smoke(3, 99).unwrap().effective_workers, 3);
    }

    #[test]
    fn invalid_zeroes_fail_closed() {
        assert!(run_smoke(0, 1).is_err());
        assert!(run_smoke(1, 0).is_err());
    }
}
