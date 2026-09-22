// SPDX-License-Identifier: Apache-2.0
//! GALAXY adapter boundary.
//!
//! MESH owns range geometry, placement, compact reduction, and verification.
//! GALAXY remains the semantic authority: this module deliberately contains no
//! particle generation, address mixer, physics, projection, or GPU kernel.

pub const GALAXY_ADAPTER_SCHEMA: &str = "qsol.mesh.galaxy-adapter.v1";
pub const GALAXY_WORKLOAD_ID: &str = "galaxy-v0.4.0-bam-lut-q30";
pub const GALAXY_FROZEN_RELEASE_COMMIT: &str = "6f17a734b9241359d36a9bf3d208b8527a456327";
pub const GALAXY_CPU_RUNTIME_BLOB: &str = "b12220565f6059482f706d46db1d9d2c29a9cc82";
pub const GALAXY_ARCHIVED_CPU_EVIDENCE_COMMIT: &str = "b9e61d20d0fe0fa99f302a2ed13aa1215a60c5f3";
pub const GALAXY_ARCHIVED_BAM_LUT_CHECKSUM: u64 = 0x8d6f_07bd_77e2_fc16;
pub const GALAXY_ARCHIVED_FLOAT_CHECKSUM: u64 = 0xadf6_d6e3_0d3a_d26d;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LogicalRange {
    pub start: u64,
    pub end: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RegenerationRequest {
    pub logical_population: u64,
    pub range: LogicalRange,
    pub frames: u32,
    pub seed: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct GalaxyPartial {
    pub range: LogicalRange,
    pub checksum: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Placement {
    Cpu,
    Accelerator,
}

impl Placement {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Cpu => "cpu",
            Self::Accelerator => "accelerator",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BaselineKind {
    CpuOnly,
    AcceleratorOnly,
    HeterogeneousStatic,
}

impl BaselineKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::CpuOnly => "cpu-only",
            Self::AcceleratorOnly => "accelerator-only",
            Self::HeterogeneousStatic => "heterogeneous-static",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BaselineSlice {
    pub range: LogicalRange,
    pub placement: Placement,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ArchivedOracle {
    pub source_commit: &'static str,
    pub logical_population: u64,
    pub resident_particles: u64,
    pub frames: u32,
    pub seed: u32,
    pub checksum: u64,
}

pub const fn archived_bam_lut_oracle() -> ArchivedOracle {
    ArchivedOracle {
        source_commit: GALAXY_ARCHIVED_CPU_EVIDENCE_COMMIT,
        logical_population: u64::MAX,
        resident_particles: 8_388_608,
        frames: 8,
        seed: 303,
        checksum: GALAXY_ARCHIVED_BAM_LUT_CHECKSUM,
    }
}

pub fn partition_logical_ids(
    logical_population: u64,
    requested_partitions: usize,
) -> Result<Vec<LogicalRange>, &'static str> {
    if logical_population == 0 {
        return Err("logical population must be greater than zero");
    }
    if requested_partitions == 0 {
        return Err("partition count must be greater than zero");
    }

    let requested = u64::try_from(requested_partitions).unwrap_or(u64::MAX);
    let effective = logical_population.min(requested);
    let effective_usize =
        usize::try_from(effective).map_err(|_| "partition count exceeds platform capacity")?;
    let base = logical_population / effective;
    let extra = logical_population % effective;

    let mut ranges = Vec::with_capacity(effective_usize);
    let mut start = 0_u64;
    for index in 0..effective_usize {
        let len = base + u64::from((index as u64) < extra);
        let end = start
            .checked_add(len)
            .ok_or("logical range arithmetic overflow")?;
        ranges.push(LogicalRange { start, end });
        start = end;
    }

    if start != logical_population {
        return Err("partitioning failed to cover the logical population");
    }
    Ok(ranges)
}

pub fn regeneration_requests(
    logical_population: u64,
    requested_partitions: usize,
    frames: u32,
    seed: u32,
) -> Result<Vec<RegenerationRequest>, &'static str> {
    if frames == 0 {
        return Err("frames must be greater than zero");
    }
    Ok(
        partition_logical_ids(logical_population, requested_partitions)?
            .into_iter()
            .map(|range| RegenerationRequest {
                logical_population,
                range,
                frames,
                seed,
            })
            .collect(),
    )
}

pub fn reduce_partials(
    logical_population: u64,
    partials: &[GalaxyPartial],
) -> Result<u64, &'static str> {
    if logical_population == 0 {
        return Err("logical population must be greater than zero");
    }
    if partials.is_empty() {
        return Err("at least one partial is required");
    }

    let mut ordered = partials.to_vec();
    ordered.sort_by_key(|partial| partial.range.start);

    let mut cursor = 0_u64;
    let mut checksum = 0_u64;
    for partial in ordered {
        if partial.range.start >= partial.range.end {
            return Err("partial range must be non-empty");
        }
        if partial.range.end > logical_population {
            return Err("partial range exceeds logical population");
        }
        if partial.range.start != cursor {
            return Err("partial ranges must form one gap-free non-overlapping cover");
        }
        checksum = checksum.wrapping_add(partial.checksum);
        cursor = partial.range.end;
    }

    if cursor != logical_population {
        return Err("partial ranges do not cover the logical population");
    }
    Ok(checksum)
}

pub fn verify_oracle(actual: u64, expected: u64) -> Result<(), &'static str> {
    if actual == expected {
        Ok(())
    } else {
        Err("GALAXY checksum does not match the declared oracle")
    }
}

/// Produce a requested baseline geometry only. This is not execution evidence
/// and deliberately does not claim that an accelerator exists or ran.
pub fn requested_baseline_plan(
    logical_population: u64,
    kind: BaselineKind,
) -> Result<Vec<BaselineSlice>, &'static str> {
    match kind {
        BaselineKind::CpuOnly => Ok(vec![BaselineSlice {
            range: partition_logical_ids(logical_population, 1)?[0],
            placement: Placement::Cpu,
        }]),
        BaselineKind::AcceleratorOnly => Ok(vec![BaselineSlice {
            range: partition_logical_ids(logical_population, 1)?[0],
            placement: Placement::Accelerator,
        }]),
        BaselineKind::HeterogeneousStatic => {
            if logical_population < 2 {
                return Err("heterogeneous baseline requires at least two logical items");
            }
            let ranges = partition_logical_ids(logical_population, 2)?;
            Ok(vec![
                BaselineSlice {
                    range: ranges[0],
                    placement: Placement::Cpu,
                },
                BaselineSlice {
                    range: ranges[1],
                    placement: Placement::Accelerator,
                },
            ])
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ranges_cover_without_gap_or_overlap() {
        assert_eq!(
            partition_logical_ids(10, 3).unwrap(),
            vec![
                LogicalRange { start: 0, end: 4 },
                LogicalRange { start: 4, end: 7 },
                LogicalRange { start: 7, end: 10 },
            ]
        );
    }

    #[test]
    fn partitioning_handles_the_maximum_galaxy_population() {
        let ranges = partition_logical_ids(u64::MAX, 3).unwrap();
        assert_eq!(ranges[0].start, 0);
        assert_eq!(ranges.last().unwrap().end, u64::MAX);
        assert!(ranges.windows(2).all(|pair| pair[0].end == pair[1].start));
    }

    #[test]
    fn regeneration_requests_keep_semantics_outside_mesh() {
        let requests = regeneration_requests(9, 2, 8, 303).unwrap();
        assert_eq!(requests.len(), 2);
        assert_eq!(requests[0].logical_population, 9);
        assert_eq!(requests[0].frames, 8);
        assert_eq!(requests[0].seed, 303);
        assert_eq!(requests[0].range, LogicalRange { start: 0, end: 5 });
        assert_eq!(requests[1].range, LogicalRange { start: 5, end: 9 });
    }

    #[test]
    fn reduction_is_completion_order_independent_and_wrapping() {
        let partials = [
            GalaxyPartial {
                range: LogicalRange { start: 4, end: 8 },
                checksum: 2,
            },
            GalaxyPartial {
                range: LogicalRange { start: 0, end: 4 },
                checksum: u64::MAX,
            },
        ];
        assert_eq!(reduce_partials(8, &partials), Ok(1));
    }

    #[test]
    fn reduction_rejects_gaps_overlaps_and_incomplete_cover() {
        let gap = [
            GalaxyPartial {
                range: LogicalRange { start: 0, end: 3 },
                checksum: 1,
            },
            GalaxyPartial {
                range: LogicalRange { start: 4, end: 8 },
                checksum: 2,
            },
        ];
        let overlap = [
            GalaxyPartial {
                range: LogicalRange { start: 0, end: 5 },
                checksum: 1,
            },
            GalaxyPartial {
                range: LogicalRange { start: 4, end: 8 },
                checksum: 2,
            },
        ];
        let incomplete = [GalaxyPartial {
            range: LogicalRange { start: 0, end: 7 },
            checksum: 1,
        }];

        assert!(reduce_partials(8, &gap).is_err());
        assert!(reduce_partials(8, &overlap).is_err());
        assert!(reduce_partials(8, &incomplete).is_err());
    }

    #[test]
    fn archived_galaxy_oracle_is_pinned_exactly() {
        let oracle = archived_bam_lut_oracle();
        assert_eq!(
            oracle.source_commit,
            "b9e61d20d0fe0fa99f302a2ed13aa1215a60c5f3"
        );
        assert_eq!(oracle.logical_population, u64::MAX);
        assert_eq!(oracle.resident_particles, 8_388_608);
        assert_eq!(oracle.frames, 8);
        assert_eq!(oracle.seed, 303);
        assert_eq!(oracle.checksum, 0x8d6f_07bd_77e2_fc16);
        assert_eq!(verify_oracle(oracle.checksum, oracle.checksum), Ok(()));
        assert!(verify_oracle(oracle.checksum ^ 1, oracle.checksum).is_err());
    }

    #[test]
    fn baseline_plans_are_static_geometry_not_capability_claims() {
        let cpu = requested_baseline_plan(10, BaselineKind::CpuOnly).unwrap();
        assert_eq!(cpu[0].placement, Placement::Cpu);
        let accelerator = requested_baseline_plan(10, BaselineKind::AcceleratorOnly).unwrap();
        assert_eq!(accelerator[0].placement, Placement::Accelerator);
        let heterogeneous = requested_baseline_plan(10, BaselineKind::HeterogeneousStatic).unwrap();
        assert_eq!(heterogeneous[0].range, LogicalRange { start: 0, end: 5 });
        assert_eq!(heterogeneous[0].placement, Placement::Cpu);
        assert_eq!(heterogeneous[1].range, LogicalRange { start: 5, end: 10 });
        assert_eq!(heterogeneous[1].placement, Placement::Accelerator);
    }

    #[test]
    fn invalid_requests_fail_closed() {
        assert!(partition_logical_ids(0, 1).is_err());
        assert!(partition_logical_ids(1, 0).is_err());
        assert!(regeneration_requests(1, 1, 0, 303).is_err());
        assert!(requested_baseline_plan(1, BaselineKind::HeterogeneousStatic).is_err());
    }
}
