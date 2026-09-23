// SPDX-License-Identifier: Apache-2.0
//! Live CPU parity through GALAXY's own resident-range entrypoint.
//! GALAXY alone generates particles and computes contributions.

use crate::galaxy::{
    archived_bam_lut_oracle, partition_logical_ids, reduce_partials, verify_oracle, GalaxyPartial,
};
use std::{path::Path, process::Command};

pub const GALAXY_CPU_RANGE_PROTOCOL: &str = "galaxy.cpu-range.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CpuRangeRequest {
    pub logical_population: u64,
    pub resident_particles: u64,
    pub start: u64,
    pub end: u64,
    pub frames: u32,
    pub seed: u32,
}

impl CpuRangeRequest {
    pub fn validate(self) -> Result<(), &'static str> {
        if self.logical_population == 0
            || self.resident_particles == 0
            || self.resident_particles > 16_777_216
            || self.resident_particles > self.logical_population
            || self.start >= self.end
            || self.end > self.resident_particles
            || self.frames == 0
            || self.frames > 100_000
        {
            return Err("invalid GALAXY resident range geometry");
        }
        Ok(())
    }
}

fn field<'a>(value: &'a str, prefix: &str) -> Result<&'a str, &'static str> {
    value
        .strip_prefix(prefix)
        .ok_or("GALAXY range field mismatch")
}

pub fn parse_cpu_range_line(
    line: &str,
    request: CpuRangeRequest,
) -> Result<GalaxyPartial, &'static str> {
    request.validate()?;
    let fields: Vec<_> = line.trim_end_matches('\n').split('\t').collect();
    if fields.len() != 9 || fields[0] != GALAXY_CPU_RANGE_PROTOCOL {
        return Err("GALAXY CPU range protocol mismatch");
    }
    let decimal = |index, prefix| -> Result<u64, &'static str> {
        let value = field(fields[index], prefix)?;
        if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
            return Err("GALAXY range decimal field is invalid");
        }
        value.parse().map_err(|_| "GALAXY range decimal overflow")
    };
    if decimal(1, "logical=")? != request.logical_population
        || decimal(2, "resident=")? != request.resident_particles
        || decimal(3, "start=")? != request.start
        || decimal(4, "end=")? != request.end
        || decimal(5, "frames=")? != u64::from(request.frames)
        || decimal(6, "seed=")? != u64::from(request.seed)
        || field(fields[7], "backend=")? != "bam-lut-q30"
    {
        return Err("GALAXY CPU range response differs from request");
    }
    let checksum = field(fields[8], "checksum=")?;
    if checksum.len() != 16
        || !checksum
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err("GALAXY CPU range checksum must be 16 lowercase hex digits");
    }
    Ok(GalaxyPartial {
        range: crate::galaxy::LogicalRange {
            start: request.start,
            end: request.end,
        },
        checksum: u64::from_str_radix(checksum, 16)
            .map_err(|_| "GALAXY range checksum is invalid")?,
    })
}

pub fn execute_cpu_range(binary: &Path, request: CpuRangeRequest) -> Result<GalaxyPartial, String> {
    request.validate().map_err(str::to_owned)?;
    let output = Command::new(binary)
        .arg("range")
        .arg("--logical")
        .arg(request.logical_population.to_string())
        .arg("--resident")
        .arg(request.resident_particles.to_string())
        .arg("--start")
        .arg(request.start.to_string())
        .arg("--end")
        .arg(request.end.to_string())
        .arg("--frames")
        .arg(request.frames.to_string())
        .arg("--seed")
        .arg(request.seed.to_string())
        .arg("--backend")
        .arg("lut")
        .output()
        .map_err(|error| format!("GALAXY CPU range launch failed: {error}"))?;
    if !output.status.success() {
        return Err(format!("GALAXY CPU range exited with {}", output.status));
    }
    let stdout =
        std::str::from_utf8(&output.stdout).map_err(|_| "GALAXY CPU range output is not UTF-8")?;
    parse_cpu_range_line(stdout, request).map_err(str::to_owned)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CpuParity {
    pub full: GalaxyPartial,
    pub partitioned: Vec<GalaxyPartial>,
    pub checksum: u64,
    pub archived_oracle_verified: bool,
}

pub fn verify_cpu_parity(
    binary: &Path,
    logical_population: u64,
    resident_particles: u64,
    frames: u32,
    seed: u32,
    partitions: usize,
) -> Result<CpuParity, String> {
    let request = CpuRangeRequest {
        logical_population,
        resident_particles,
        start: 0,
        end: resident_particles,
        frames,
        seed,
    };
    request.validate().map_err(str::to_owned)?;
    if !(2..=256).contains(&partitions) || resident_particles < partitions as u64 {
        return Err("GALAXY CPU parity requires 2..=256 partitions".into());
    }
    let full = execute_cpu_range(binary, request)?;
    let mut partials = Vec::new();
    for range in partition_logical_ids(resident_particles, partitions).map_err(str::to_owned)? {
        partials.push(execute_cpu_range(
            binary,
            CpuRangeRequest {
                start: range.start,
                end: range.end,
                ..request
            },
        )?);
    }
    let checksum = reduce_partials(resident_particles, &partials).map_err(str::to_owned)?;
    verify_oracle(checksum, full.checksum).map_err(str::to_owned)?;
    let archived = archived_bam_lut_oracle();
    let archived_oracle_verified = logical_population == archived.logical_population
        && resident_particles == archived.resident_particles
        && frames == archived.frames
        && seed == archived.seed;
    if archived_oracle_verified {
        verify_oracle(checksum, archived.checksum).map_err(str::to_owned)?;
    }
    Ok(CpuParity {
        full,
        partitioned: partials,
        checksum,
        archived_oracle_verified,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request() -> CpuRangeRequest {
        CpuRangeRequest {
            logical_population: u64::MAX,
            resident_particles: 257,
            start: 0,
            end: 63,
            frames: 8,
            seed: 303,
        }
    }

    #[test]
    fn strict_protocol_binds_every_requested_dimension() {
        let line = "galaxy.cpu-range.v1\tlogical=18446744073709551615\tresident=257\tstart=0\tend=63\tframes=8\tseed=303\tbackend=bam-lut-q30\tchecksum=0123456789abcdef\n";
        assert_eq!(
            parse_cpu_range_line(line, request()).unwrap().checksum,
            0x0123_4567_89ab_cdef
        );
        assert!(
            parse_cpu_range_line(&line.replace("resident=257", "resident=256"), request()).is_err()
        );
        assert!(parse_cpu_range_line(
            &line.replace("backend=bam-lut-q30", "backend=float-libm"),
            request()
        )
        .is_err());
        assert!(parse_cpu_range_line(&format!("{line}{line}"), request()).is_err());
    }

    #[test]
    fn invalid_range_fails_before_worker_dispatch() {
        let bad = CpuRangeRequest {
            end: 258,
            ..request()
        };
        assert!(bad.validate().is_err());
        assert!(execute_cpu_range(Path::new("/does-not-exist"), bad).is_err());
    }
}
