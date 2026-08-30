from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from . import domain, ingestion
from .ingestion import CanonicalBatch
from .money_graph import MoneyGraph

__all__ = [
    "CompositionProofError",
    "CompositionStatus",
    "SettlementCompositionProof",
    "prove_all_settlement_compositions",
]


class CompositionStatus(StrEnum):
    PROVEN = "composition_proven"
    RESIDUAL = "composition_residual"
    INCOMPLETE = "composition_incomplete"
    CONTRADICTED = "composition_contradicted"


class CompositionProofError(ValueError):
    """Batch-level settlement proof preconditions are structurally inconsistent."""


@dataclass(frozen=True, slots=True)
class DuplicateEconomicGroup:
    entity_kind: domain.ReconEntityKind
    entity_id: domain.EntityId
    representative_id: domain.ReconEntryId
    duplicate_ids: tuple[domain.ReconEntryId, ...]

    @property
    def all_ids(self) -> tuple[domain.ReconEntryId, ...]:
        return (self.representative_id, *self.duplicate_ids)


@dataclass(frozen=True, slots=True)
class ConflictingEconomicGroup:
    entity_kind: domain.ReconEntityKind
    entity_id: domain.EntityId
    entry_ids: tuple[domain.ReconEntryId, ...]


@dataclass(frozen=True, slots=True)
class SettlementCompositionProof:
    settlement_id: domain.SettlementId
    status: CompositionStatus
    settlement_amount: domain.Money
    observed_composition: domain.Money
    residual: domain.Money
    component_ids: tuple[domain.ReconEntryId, ...]
    source_envelope_ids: tuple[domain.SourceEnvelopeId, ...]
    evidence_edge_ids: tuple[domain.EvidenceEdgeId, ...]
    duplicate_groups: tuple[DuplicateEconomicGroup, ...]
    conflicting_groups: tuple[ConflictingEconomicGroup, ...]
    late_component_ids: tuple[domain.ReconEntryId, ...]
    cross_settlement_conflict_ids: tuple[domain.ReconEntryId, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.settlement_amount.currency != self.observed_composition.currency:
            raise ValueError("composition proof currencies must match")
        if self.residual.currency != self.settlement_amount.currency:
            raise ValueError("composition residual currency must match settlement")
        if self.residual != self.settlement_amount - self.observed_composition:
            raise ValueError("composition residual must equal settlement minus components")
        if not self.source_envelope_ids:
            raise ValueError("composition proof must cite raw source envelopes")
        if self.status is CompositionStatus.PROVEN:
            if not self.residual.is_zero:
                raise ValueError("proven composition must have zero residual")
            if self.duplicate_groups or self.conflicting_groups:
                raise ValueError("proven composition cannot contain economic identity conflicts")
            if self.late_component_ids or self.cross_settlement_conflict_ids:
                raise ValueError("proven composition cannot contain causal/ownership conflicts")
            if self.reason_codes:
                raise ValueError("proven composition cannot carry failure reason codes")


type EconomicIdentity = tuple[domain.ReconEntityKind, domain.EntityId]
type EconomicClaim = tuple[domain.ReconEntityKind, str]
type EconomicPayload = tuple[int, int, int, int, str, str]


def _economic_identity(entry: domain.SettlementReconEntry) -> EconomicIdentity:
    return (entry.entity_kind, entry.entity_id)


def _economic_claim(entry: domain.SettlementReconEntry) -> EconomicClaim:
    return (entry.entity_kind, str(entry.entity_id))


def _economic_payload(entry: domain.SettlementReconEntry) -> EconomicPayload:
    """Describe one normalized movement independently of its recon row ID."""
    return (
        entry.gross_amount.amount_paise,
        entry.fee.amount_paise,
        entry.tax.amount_paise,
        entry.settlement_effect.amount_paise,
        entry.settlement_effect.currency.value,
        entry.occurred_at.isoformat(),
    )


def _partition_economic_rows(
    entries: tuple[domain.SettlementReconEntry, ...],
) -> tuple[
    tuple[domain.SettlementReconEntry, ...],
    tuple[DuplicateEconomicGroup, ...],
    tuple[ConflictingEconomicGroup, ...],
]:
    by_identity: dict[EconomicIdentity, list[domain.SettlementReconEntry]] = {}
    for entry in entries:
        by_identity.setdefault(_economic_identity(entry), []).append(entry)

    unique: list[domain.SettlementReconEntry] = []
    duplicates: list[DuplicateEconomicGroup] = []
    conflicts: list[ConflictingEconomicGroup] = []

    for (entity_kind, entity_id), group in by_identity.items():
        ordered = sorted(group, key=lambda row: str(row.id))
        payloads = {_economic_payload(row) for row in ordered}
        row_ids = {row.id for row in ordered}

        if len(ordered) == 1:
            unique.append(ordered[0])
        elif len(row_ids) == 1 and len(payloads) == 1:
            # Same source row delivered repeatedly: idempotent replay, not new evidence.
            unique.append(ordered[0])
        elif len(payloads) == 1:
            unique.append(ordered[0])
            duplicates.append(
                DuplicateEconomicGroup(
                    entity_kind=entity_kind,
                    entity_id=entity_id,
                    representative_id=ordered[0].id,
                    duplicate_ids=tuple(row.id for row in ordered[1:]),
                )
            )
        else:
            # Conflicting values/times under one economic identity are not safe to choose between.
            conflicts.append(
                ConflictingEconomicGroup(
                    entity_kind=entity_kind,
                    entity_id=entity_id,
                    entry_ids=tuple(row.id for row in ordered),
                )
            )

    return (
        tuple(sorted(unique, key=lambda row: str(row.id))),
        tuple(
            sorted(
                duplicates,
                key=lambda group: (
                    group.entity_kind.value,
                    str(group.entity_id),
                    str(group.representative_id),
                ),
            )
        ),
        tuple(
            sorted(
                conflicts,
                key=lambda group: (group.entity_kind.value, str(group.entity_id)),
            )
        ),
    )


def _require_source_envelope(
    source_index: dict[ingestion.SourceIdentity, domain.SourceEnvelopeId],
    source_kind: domain.SourceKind,
    source_record_id: str,
) -> domain.SourceEnvelopeId:
    envelope_id = source_index.get((source_kind, source_record_id))
    if envelope_id is None:
        raise CompositionProofError(
            "proof input is missing journal-backed source provenance: "
            f"{source_kind.value}/{source_record_id}"
        )
    return envelope_id


def _required_provenance_edges(
    graph: MoneyGraph,
    entry: domain.SettlementReconEntry,
    source_envelope_id: domain.SourceEnvelopeId,
) -> tuple[domain.EvidenceEdgeId, ...] | None:
    expected = {
        ("entity_has_recon_entry", str(entry.entity_id), str(entry.id)),
        (
            "recon_entry_contributes_to_settlement",
            str(entry.id),
            str(entry.settlement_id),
        ),
    }
    required_evidence = (str(source_envelope_id),)
    matches = [
        edge
        for edge in graph.edges
        if (
            edge.relationship,
            str(edge.from_id),
            str(edge.to_id),
        )
        in expected
        and edge.state is domain.EdgeState.PROVEN
        and edge.strength is domain.EvidenceStrength.AUTHORITATIVE
        and edge.evidence_ids == required_evidence
        and "EXACT_SOURCE_IDENTIFIER" in edge.reason_codes
    ]
    matched_keys = {
        (edge.relationship, str(edge.from_id), str(edge.to_id)) for edge in matches
    }
    if matched_keys != expected:
        return None
    return tuple(sorted((edge.id for edge in matches), key=str))


def _prove_settlement_composition(
    settlement: domain.Settlement,
    entries: tuple[domain.SettlementReconEntry, ...],
    graph: MoneyGraph,
    *,
    source_index: dict[ingestion.SourceIdentity, domain.SourceEnvelopeId],
    cross_settlement_claims: frozenset[EconomicClaim],
) -> SettlementCompositionProof:
    if any(entry.settlement_id != settlement.id for entry in entries):
        raise CompositionProofError("composition call contains rows for another settlement")

    for entry in entries:
        if entry.settlement_effect.currency != settlement.amount.currency:
            raise CompositionProofError("settlement and recon currencies differ")

    settlement_source_id = _require_source_envelope(
        source_index,
        domain.SourceKind.RAZORPAY_SETTLEMENT,
        str(settlement.id),
    )

    unique_entries, duplicate_groups, conflicting_groups = _partition_economic_rows(entries)
    late_component_ids = tuple(
        sorted(
            (entry.id for entry in entries if entry.occurred_at > settlement.processed_at),
            key=str,
        )
    )
    cross_settlement_conflict_ids = tuple(
        sorted(
            (
                entry.id
                for entry in entries
                if _economic_claim(entry) in cross_settlement_claims
            ),
            key=str,
        )
    )
    blocked_ids = set(late_component_ids) | set(cross_settlement_conflict_ids)
    arithmetic_entries = tuple(
        entry for entry in unique_entries if entry.id not in blocked_ids
    )

    observed = domain.sum_money(
        [entry.settlement_effect for entry in arithmetic_entries],
        settlement.amount.currency,
    )
    residual = settlement.amount - observed

    reason_codes: set[str] = set()
    evidence_edge_ids: list[domain.EvidenceEdgeId] = []
    source_envelope_ids: set[domain.SourceEnvelopeId] = {settlement_source_id}

    if not entries:
        reason_codes.add("NO_RECON_COMPONENTS")
    if duplicate_groups:
        reason_codes.add("DUPLICATE_ECONOMIC_ROW")
    if conflicting_groups:
        reason_codes.add("ECONOMIC_IDENTITY_CONFLICT")
    if late_component_ids:
        reason_codes.add("RECON_AFTER_SETTLEMENT")
    if cross_settlement_conflict_ids:
        reason_codes.add("ECONOMIC_ENTITY_IN_MULTIPLE_SETTLEMENTS")

    for entry in entries:
        source_envelope_id = _require_source_envelope(
            source_index,
            domain.SourceKind.RAZORPAY_RECON,
            str(entry.id),
        )
        source_envelope_ids.add(source_envelope_id)
        edge_ids = _required_provenance_edges(graph, entry, source_envelope_id)
        if edge_ids is None:
            reason_codes.add("MISSING_GRAPH_PROVENANCE")
        else:
            evidence_edge_ids.extend(edge_ids)

    has_contradiction = bool(
        duplicate_groups
        or conflicting_groups
        or late_component_ids
        or cross_settlement_conflict_ids
    )
    if has_contradiction:
        status = CompositionStatus.CONTRADICTED
    elif "MISSING_GRAPH_PROVENANCE" in reason_codes or not entries:
        status = CompositionStatus.INCOMPLETE
    elif residual.is_zero:
        status = CompositionStatus.PROVEN
    else:
        status = CompositionStatus.RESIDUAL
        reason_codes.add("SETTLEMENT_COMPOSITION_RESIDUAL")

    return SettlementCompositionProof(
        settlement_id=settlement.id,
        status=status,
        settlement_amount=settlement.amount,
        observed_composition=observed,
        residual=residual,
        component_ids=tuple(entry.id for entry in arithmetic_entries),
        source_envelope_ids=tuple(sorted(source_envelope_ids, key=str)),
        evidence_edge_ids=tuple(sorted(set(evidence_edge_ids), key=str)),
        duplicate_groups=duplicate_groups,
        conflicting_groups=conflicting_groups,
        late_component_ids=late_component_ids,
        cross_settlement_conflict_ids=cross_settlement_conflict_ids,
        reason_codes=tuple(sorted(reason_codes)),
    )


def prove_all_settlement_compositions(
    batch: CanonicalBatch,
    graph: MoneyGraph,
) -> tuple[SettlementCompositionProof, ...]:
    if not batch.source_links:
        raise CompositionProofError("settlement proof requires journal-backed source provenance")
    source_index = batch.source_index()

    settlements: dict[domain.SettlementId, domain.Settlement] = {}
    for settlement in batch.settlements:
        if settlement.id in settlements:
            raise CompositionProofError(f"duplicate settlement id {settlement.id}")
        settlements[settlement.id] = settlement

    rows_by_settlement: dict[
        domain.SettlementId, list[domain.SettlementReconEntry]
    ] = {settlement_id: [] for settlement_id in settlements}
    claim_settlements: dict[EconomicClaim, set[domain.SettlementId]] = {}
    for entry in batch.recon_entries:
        if entry.settlement_id not in settlements:
            raise CompositionProofError(
                f"recon entry {entry.id} references unknown settlement {entry.settlement_id}"
            )
        rows_by_settlement[entry.settlement_id].append(entry)
        claim_settlements.setdefault(_economic_claim(entry), set()).add(entry.settlement_id)

    cross_settlement_claims = frozenset(
        claim for claim, settlement_ids in claim_settlements.items() if len(settlement_ids) > 1
    )

    return tuple(
        _prove_settlement_composition(
            settlements[settlement_id],
            tuple(rows_by_settlement[settlement_id]),
            graph,
            source_index=source_index,
            cross_settlement_claims=cross_settlement_claims,
        )
        for settlement_id in sorted(settlements, key=str)
    )
