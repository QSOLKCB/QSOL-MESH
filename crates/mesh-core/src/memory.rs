// SPDX-License-Identifier: Apache-2.0
//! Auditable memory-plan broker.
//!
//! This module plans ownership, lifetimes, transfers, and reusable bounded
//! buffers. It does not pin host pages or allocate accelerator memory. Physical
//! materialization remains the responsibility of a real backend.

pub const MEMORY_PLAN_SCHEMA: &str = "qsol.mesh.memory-plan.v1";
pub const MEMORY_PLAN_RECEIPT_SCHEMA: &str = "qsol.mesh.memory-plan-receipt.v1";
pub const MEMORY_BROKER_WORKLOAD_ID: &str = "mesh-memory-broker-v1";
pub const MEMORY_PLAN_CLAIM_BOUNDARY: &str =
    "planning-only-not-physical-allocation-evidence";
pub const STREAM_REDUCE_DISCARD_STRATEGY: &str = "stream-reduce-discard-template-v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MemoryDomain {
    HostPageable,
    HostPinned,
    AcceleratorLocal,
}

impl MemoryDomain {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::HostPageable => "host-pageable",
            Self::HostPinned => "host-pinned",
            Self::AcceleratorLocal => "accelerator-local",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AllocationRole {
    SourceWindow,
    PinnedStaging,
    AcceleratorPool,
    PartialResult,
}

impl AllocationRole {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::SourceWindow => "source-window",
            Self::PinnedStaging => "pinned-staging",
            Self::AcceleratorPool => "accelerator-pool",
            Self::PartialResult => "partial-result",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EventKind {
    SourceReady,
    StageHostPinned,
    UploadAccelerator,
    Execute,
    DownloadPartial,
    Reduce,
    Discard,
}

impl EventKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::SourceReady => "source-ready",
            Self::StageHostPinned => "stage-host-pinned",
            Self::UploadAccelerator => "upload-accelerator",
            Self::Execute => "execute",
            Self::DownloadPartial => "download-partial",
            Self::Reduce => "reduce",
            Self::Discard => "discard",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TransferKind {
    StageCopy,
    Upload,
    PartialDownload,
}

impl TransferKind {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::StageCopy => "stage-copy",
            Self::Upload => "upload",
            Self::PartialDownload => "partial-download",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryEvent {
    pub id: u32,
    pub kind: EventKind,
    pub depends_on: Vec<u32>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct MemoryAllocation {
    pub id: u32,
    pub role: AllocationRole,
    pub domain: MemoryDomain,
    pub bytes: u64,
    pub live_from_event: u32,
    pub live_through_event: u32,
    pub reused_across_chunks: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct MemoryTransfer {
    pub id: u32,
    pub kind: TransferKind,
    pub event_id: u32,
    pub source_allocation: u32,
    pub destination_allocation: u32,
    pub bytes: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct MemoryPlanRequest {
    pub total_bytes: u64,
    pub requested_chunk_bytes: u64,
    pub host_pinned_limit_bytes: u64,
    pub accelerator_limit_bytes: u64,
    pub partial_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryPlan {
    pub request: MemoryPlanRequest,
    pub effective_chunk_bytes: u64,
    pub chunk_count: u64,
    pub events: Vec<MemoryEvent>,
    pub allocations: Vec<MemoryAllocation>,
    pub transfers: Vec<MemoryTransfer>,
    pub strategy: &'static str,
    pub physically_materialized: bool,
}

fn event_position(events: &[MemoryEvent], event_id: u32) -> Option<usize> {
    events.iter().position(|event| event.id == event_id)
}

fn allocation_by_id(
    allocations: &[MemoryAllocation],
    allocation_id: u32,
) -> Option<&MemoryAllocation> {
    allocations
        .iter()
        .find(|allocation| allocation.id == allocation_id)
}

fn validate_unique_event_ids(events: &[MemoryEvent]) -> Result<(), &'static str> {
    for (index, event) in events.iter().enumerate() {
        if events[..index]
            .iter()
            .any(|previous| previous.id == event.id)
        {
            return Err("memory event IDs must be unique");
        }
        for (dependency_index, dependency) in event.depends_on.iter().enumerate() {
            if event.depends_on[..dependency_index].contains(dependency) {
                return Err("memory event dependencies must be unique");
            }
            let Some(position) = event_position(events, *dependency) else {
                return Err("memory event dependency does not exist");
            };
            if position >= index {
                return Err("memory event dependencies must reference earlier events");
            }
        }
    }
    Ok(())
}

fn validate_unique_allocation_ids(
    allocations: &[MemoryAllocation],
) -> Result<(), &'static str> {
    for (index, allocation) in allocations.iter().enumerate() {
        if allocations[..index]
            .iter()
            .any(|previous| previous.id == allocation.id)
        {
            return Err("memory allocation IDs must be unique");
        }
    }
    Ok(())
}

fn validate_unique_transfer_ids(transfers: &[MemoryTransfer]) -> Result<(), &'static str> {
    for (index, transfer) in transfers.iter().enumerate() {
        if transfers[..index]
            .iter()
            .any(|previous| previous.id == transfer.id)
        {
            return Err("memory transfer IDs must be unique");
        }
    }
    Ok(())
}

fn peak_live_bytes(plan: &MemoryPlan, domain: MemoryDomain) -> Result<u64, &'static str> {
    let mut peak = 0_u64;
    for event_index in 0..plan.events.len() {
        let mut live = 0_u64;
        for allocation in &plan.allocations {
            if allocation.domain != domain {
                continue;
            }
            let Some(start) = event_position(&plan.events, allocation.live_from_event) else {
                return Err("allocation lifetime start event does not exist");
            };
            let Some(end) = event_position(&plan.events, allocation.live_through_event) else {
                return Err("allocation lifetime end event does not exist");
            };
            if start <= event_index && event_index <= end {
                live = live
                    .checked_add(allocation.bytes)
                    .ok_or("peak live memory arithmetic overflow")?;
            }
        }
        peak = peak.max(live);
    }
    Ok(peak)
}

pub fn validate_memory_plan(plan: &MemoryPlan) -> Result<(), &'static str> {
    if plan.request.total_bytes == 0 {
        return Err("total bytes must be greater than zero");
    }
    if plan.request.requested_chunk_bytes == 0 {
        return Err("requested chunk bytes must be greater than zero");
    }
    if plan.request.host_pinned_limit_bytes == 0 {
        return Err("host pinned limit must be greater than zero");
    }
    if plan.request.accelerator_limit_bytes == 0 {
        return Err("accelerator limit must be greater than zero");
    }
    if plan.request.partial_bytes == 0 {
        return Err("partial bytes must be greater than zero");
    }
    if plan.effective_chunk_bytes == 0 || plan.chunk_count == 0 {
        return Err("effective memory plan geometry must be nonzero");
    }
    if plan.effective_chunk_bytes > plan.request.total_bytes
        || plan.effective_chunk_bytes > plan.request.requested_chunk_bytes
        || plan.effective_chunk_bytes > plan.request.host_pinned_limit_bytes
        || plan.effective_chunk_bytes > plan.request.accelerator_limit_bytes
    {
        return Err("effective chunk exceeds a declared plan bound");
    }
    if plan.request.partial_bytes > plan.effective_chunk_bytes {
        return Err("partial bytes must not exceed effective chunk bytes");
    }
    if plan.events.is_empty() {
        return Err("memory plan requires at least one event");
    }
    if plan.allocations.is_empty() {
        return Err("memory plan requires at least one allocation");
    }
    if plan.strategy != STREAM_REDUCE_DISCARD_STRATEGY {
        return Err("unsupported memory plan strategy");
    }
    if plan.physically_materialized {
        return Err("planning-only memory plan must not claim physical materialization");
    }

    validate_unique_event_ids(&plan.events)?;
    validate_unique_allocation_ids(&plan.allocations)?;
    validate_unique_transfer_ids(&plan.transfers)?;

    for allocation in &plan.allocations {
        if allocation.bytes == 0 {
            return Err("memory allocation bytes must be greater than zero");
        }
        let Some(start) = event_position(&plan.events, allocation.live_from_event) else {
            return Err("allocation lifetime start event does not exist");
        };
        let Some(end) = event_position(&plan.events, allocation.live_through_event) else {
            return Err("allocation lifetime end event does not exist");
        };
        if start > end {
            return Err("allocation lifetime start must not follow its end");
        }
    }

    for transfer in &plan.transfers {
        if transfer.bytes == 0 {
            return Err("memory transfer bytes must be greater than zero");
        }
        let Some(event_index) = event_position(&plan.events, transfer.event_id) else {
            return Err("memory transfer event does not exist");
        };
        let Some(source) = allocation_by_id(&plan.allocations, transfer.source_allocation) else {
            return Err("memory transfer source allocation does not exist");
        };
        let Some(destination) =
            allocation_by_id(&plan.allocations, transfer.destination_allocation)
        else {
            return Err("memory transfer destination allocation does not exist");
        };
        if source.id == destination.id || source.domain == destination.domain {
            return Err("memory transfer must cross distinct allocations and domains");
        }
        if transfer.bytes > source.bytes || transfer.bytes > destination.bytes {
            return Err("memory transfer exceeds allocation byte extent");
        }

        let source_start =
            event_position(&plan.events, source.live_from_event).ok_or("source lifetime missing")?;
        let source_end = event_position(&plan.events, source.live_through_event)
            .ok_or("source lifetime missing")?;
        let destination_start = event_position(&plan.events, destination.live_from_event)
            .ok_or("destination lifetime missing")?;
        let destination_end = event_position(&plan.events, destination.live_through_event)
            .ok_or("destination lifetime missing")?;

        if event_index < source_start
            || event_index > source_end
            || event_index < destination_start
            || event_index > destination_end
        {
            return Err("memory transfer occurs outside an allocation lifetime");
        }
    }

    if peak_live_bytes(plan, MemoryDomain::HostPinned)?
        > plan.request.host_pinned_limit_bytes
    {
        return Err("host pinned peak exceeds declared limit");
    }
    if peak_live_bytes(plan, MemoryDomain::AcceleratorLocal)?
        > plan.request.accelerator_limit_bytes
    {
        return Err("accelerator peak exceeds declared limit");
    }
    if !plan
        .events
        .iter()
        .any(|event| event.kind == EventKind::Reduce)
        || !plan
            .events
            .iter()
            .any(|event| event.kind == EventKind::Discard)
    {
        return Err("stream-reduce-discard plan requires reduce and discard events");
    }

    Ok(())
}

pub fn build_streaming_memory_plan(
    request: MemoryPlanRequest,
) -> Result<MemoryPlan, &'static str> {
    if request.total_bytes == 0 {
        return Err("total bytes must be greater than zero");
    }
    if request.requested_chunk_bytes == 0 {
        return Err("requested chunk bytes must be greater than zero");
    }
    if request.host_pinned_limit_bytes == 0 {
        return Err("host pinned limit must be greater than zero");
    }
    if request.accelerator_limit_bytes == 0 {
        return Err("accelerator limit must be greater than zero");
    }
    if request.partial_bytes == 0 {
        return Err("partial bytes must be greater than zero");
    }

    let effective_chunk_bytes = request
        .total_bytes
        .min(request.requested_chunk_bytes)
        .min(request.host_pinned_limit_bytes)
        .min(request.accelerator_limit_bytes);
    if request.partial_bytes > effective_chunk_bytes {
        return Err("partial bytes must not exceed effective chunk bytes");
    }
    let chunk_count = ((request.total_bytes - 1) / effective_chunk_bytes)
        .checked_add(1)
        .ok_or("chunk count arithmetic overflow")?;

    let events = vec![
        MemoryEvent {
            id: 0,
            kind: EventKind::SourceReady,
            depends_on: vec![],
        },
        MemoryEvent {
            id: 1,
            kind: EventKind::StageHostPinned,
            depends_on: vec![0],
        },
        MemoryEvent {
            id: 2,
            kind: EventKind::UploadAccelerator,
            depends_on: vec![1],
        },
        MemoryEvent {
            id: 3,
            kind: EventKind::Execute,
            depends_on: vec![2],
        },
        MemoryEvent {
            id: 4,
            kind: EventKind::DownloadPartial,
            depends_on: vec![3],
        },
        MemoryEvent {
            id: 5,
            kind: EventKind::Reduce,
            depends_on: vec![4],
        },
        MemoryEvent {
            id: 6,
            kind: EventKind::Discard,
            depends_on: vec![5],
        },
    ];

    let allocations = vec![
        MemoryAllocation {
            id: 0,
            role: AllocationRole::SourceWindow,
            domain: MemoryDomain::HostPageable,
            bytes: effective_chunk_bytes,
            live_from_event: 0,
            live_through_event: 1,
            reused_across_chunks: false,
        },
        MemoryAllocation {
            id: 1,
            role: AllocationRole::PinnedStaging,
            domain: MemoryDomain::HostPinned,
            bytes: effective_chunk_bytes,
            live_from_event: 0,
            live_through_event: 2,
            reused_across_chunks: true,
        },
        MemoryAllocation {
            id: 2,
            role: AllocationRole::AcceleratorPool,
            domain: MemoryDomain::AcceleratorLocal,
            bytes: effective_chunk_bytes,
            live_from_event: 1,
            live_through_event: 6,
            reused_across_chunks: true,
        },
        MemoryAllocation {
            id: 3,
            role: AllocationRole::PartialResult,
            domain: MemoryDomain::HostPageable,
            bytes: request.partial_bytes,
            live_from_event: 3,
            live_through_event: 5,
            reused_across_chunks: true,
        },
    ];

    let transfers = vec![
        MemoryTransfer {
            id: 0,
            kind: TransferKind::StageCopy,
            event_id: 1,
            source_allocation: 0,
            destination_allocation: 1,
            bytes: effective_chunk_bytes,
        },
        MemoryTransfer {
            id: 1,
            kind: TransferKind::Upload,
            event_id: 2,
            source_allocation: 1,
            destination_allocation: 2,
            bytes: effective_chunk_bytes,
        },
        MemoryTransfer {
            id: 2,
            kind: TransferKind::PartialDownload,
            event_id: 4,
            source_allocation: 2,
            destination_allocation: 3,
            bytes: request.partial_bytes,
        },
    ];

    let plan = MemoryPlan {
        request,
        effective_chunk_bytes,
        chunk_count,
        events,
        allocations,
        transfers,
        strategy: STREAM_REDUCE_DISCARD_STRATEGY,
        physically_materialized: false,
    };
    validate_memory_plan(&plan)?;
    Ok(plan)
}

fn event_dependencies_json(event: &MemoryEvent) -> String {
    event
        .depends_on
        .iter()
        .map(u32::to_string)
        .collect::<Vec<_>>()
        .join(",")
}

pub fn memory_plan_receipt_json(plan: &MemoryPlan) -> Result<String, &'static str> {
    validate_memory_plan(plan)?;

    let allocations = plan
        .allocations
        .iter()
        .map(|allocation| {
            format!(
                "{{\"id\":{},\"role\":\"{}\",\"domain\":\"{}\",\"bytes\":{},\"live_from_event\":{},\"live_through_event\":{},\"reused_across_chunks\":{}}}",
                allocation.id,
                allocation.role.as_str(),
                allocation.domain.as_str(),
                allocation.bytes,
                allocation.live_from_event,
                allocation.live_through_event,
                allocation.reused_across_chunks
            )
        })
        .collect::<Vec<_>>()
        .join(",");

    let transfers = plan
        .transfers
        .iter()
        .map(|transfer| {
            format!(
                "{{\"id\":{},\"kind\":\"{}\",\"event_id\":{},\"source_allocation\":{},\"destination_allocation\":{},\"bytes\":{}}}",
                transfer.id,
                transfer.kind.as_str(),
                transfer.event_id,
                transfer.source_allocation,
                transfer.destination_allocation,
                transfer.bytes
            )
        })
        .collect::<Vec<_>>()
        .join(",");

    let events = plan
        .events
        .iter()
        .map(|event| {
            format!(
                "{{\"id\":{},\"kind\":\"{}\",\"depends_on\":[{}]}}",
                event.id,
                event.kind.as_str(),
                event_dependencies_json(event)
            )
        })
        .collect::<Vec<_>>()
        .join(",");

    let host_pageable_peak = peak_live_bytes(plan, MemoryDomain::HostPageable)?;
    let host_pinned_peak = peak_live_bytes(plan, MemoryDomain::HostPinned)?;
    let accelerator_peak = peak_live_bytes(plan, MemoryDomain::AcceleratorLocal)?;

    Ok(format!(
        "{{\"schema\":\"{MEMORY_PLAN_RECEIPT_SCHEMA}\",\"source_identity\":{{\"runtime\":\"qsol-mesh-cli\",\"memory_plan_schema\":\"{MEMORY_PLAN_SCHEMA}\",\"memory_plan_version\":\"1.0.0\"}},\"workload_identity\":{{\"workload_id\":\"{MEMORY_BROKER_WORKLOAD_ID}\",\"workload_contract_version\":\"1.0.0\"}},\"requested_configuration\":{{\"total_bytes\":{},\"requested_chunk_bytes\":{},\"host_pinned_limit_bytes\":{},\"accelerator_limit_bytes\":{},\"partial_bytes\":{}}},\"observed_topology\":{{\"observed\":false,\"reason\":\"planning-only-no-physical-memory-observation\"}},\"effective_execution\":{{\"kind\":\"planning-only\",\"executor\":\"none\",\"physically_materialized\":false}},\"memory_plan\":{{\"strategy\":\"{}\",\"effective_chunk_bytes\":{},\"chunk_count\":{},\"template_repeated_per_chunk\":true,\"physically_materialized\":false,\"peak_live_bytes\":{{\"host-pageable\":{},\"host-pinned\":{},\"accelerator-local\":{}}},\"allocations\":[{}],\"transfers\":[{}],\"events\":[{}]}},\"calibration\":{{\"performed\":false}},\"verification\":{{\"kind\":\"structural-memory-plan-validation\",\"verified\":true}},\"claim_boundary\":\"{MEMORY_PLAN_CLAIM_BOUNDARY}\"}}",
        plan.request.total_bytes,
        plan.request.requested_chunk_bytes,
        plan.request.host_pinned_limit_bytes,
        plan.request.accelerator_limit_bytes,
        plan.request.partial_bytes,
        plan.strategy,
        plan.effective_chunk_bytes,
        plan.chunk_count,
        host_pageable_peak,
        host_pinned_peak,
        accelerator_peak,
        allocations,
        transfers,
        events
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request() -> MemoryPlanRequest {
        MemoryPlanRequest {
            total_bytes: 1_000,
            requested_chunk_bytes: 400,
            host_pinned_limit_bytes: 256,
            accelerator_limit_bytes: 300,
            partial_bytes: 24,
        }
    }

    #[test]
    fn chunk_geometry_is_bounded_by_every_declared_limit() {
        let plan = build_streaming_memory_plan(request()).unwrap();
        assert_eq!(plan.effective_chunk_bytes, 256);
        assert_eq!(plan.chunk_count, 4);
        assert_eq!(peak_live_bytes(&plan, MemoryDomain::HostPinned), Ok(256));
        assert_eq!(
            peak_live_bytes(&plan, MemoryDomain::AcceleratorLocal),
            Ok(256)
        );
    }

    #[test]
    fn huge_logical_byte_extent_does_not_materialize_per_chunk_state() {
        let plan = build_streaming_memory_plan(MemoryPlanRequest {
            total_bytes: u64::MAX,
            requested_chunk_bytes: 1,
            host_pinned_limit_bytes: 1,
            accelerator_limit_bytes: 1,
            partial_bytes: 1,
        })
        .unwrap();
        assert_eq!(plan.chunk_count, u64::MAX);
        assert_eq!(plan.events.len(), 7);
        assert_eq!(plan.allocations.len(), 4);
        assert_eq!(plan.transfers.len(), 3);
    }

    #[test]
    fn receipt_has_required_evidence_sections_and_no_materialization_claim() {
        let plan = build_streaming_memory_plan(request()).unwrap();
        let receipt = memory_plan_receipt_json(&plan).unwrap();
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
        assert!(receipt.contains("\"physically_materialized\":false"));
        assert!(receipt.contains("\"strategy\":\"stream-reduce-discard-template-v1\""));
    }

    #[test]
    fn forward_or_cyclic_event_dependencies_fail_closed() {
        let mut plan = build_streaming_memory_plan(request()).unwrap();
        plan.events[0].depends_on = vec![6];
        assert_eq!(
            validate_memory_plan(&plan),
            Err("memory event dependencies must reference earlier events")
        );
    }

    #[test]
    fn transfer_extent_and_lifetime_are_validated() {
        let mut plan = build_streaming_memory_plan(request()).unwrap();
        plan.transfers[2].bytes = plan.effective_chunk_bytes + 1;
        assert_eq!(
            validate_memory_plan(&plan),
            Err("memory transfer exceeds allocation byte extent")
        );

        let mut plan = build_streaming_memory_plan(request()).unwrap();
        plan.transfers[1].event_id = 5;
        assert_eq!(
            validate_memory_plan(&plan),
            Err("memory transfer occurs outside an allocation lifetime")
        );
    }

    #[test]
    fn declared_domain_budgets_are_enforced() {
        let mut plan = build_streaming_memory_plan(request()).unwrap();
        plan.allocations[1].bytes = plan.request.host_pinned_limit_bytes + 1;
        assert_eq!(
            validate_memory_plan(&plan),
            Err("host pinned peak exceeds declared limit")
        );

        let mut plan = build_streaming_memory_plan(request()).unwrap();
        plan.allocations[2].bytes = plan.request.accelerator_limit_bytes + 1;
        assert_eq!(
            validate_memory_plan(&plan),
            Err("accelerator peak exceeds declared limit")
        );
    }

    #[test]
    fn physical_materialization_claim_is_forbidden_in_planning_layer() {
        let mut plan = build_streaming_memory_plan(request()).unwrap();
        plan.physically_materialized = true;
        assert_eq!(
            validate_memory_plan(&plan),
            Err("planning-only memory plan must not claim physical materialization")
        );
    }

    #[test]
    fn invalid_zeroes_and_oversized_partials_fail_closed() {
        let mut invalid = request();
        invalid.total_bytes = 0;
        assert!(build_streaming_memory_plan(invalid).is_err());

        let mut invalid = request();
        invalid.partial_bytes = 257;
        assert_eq!(
            build_streaming_memory_plan(invalid),
            Err("partial bytes must not exceed effective chunk bytes")
        );
    }
}
