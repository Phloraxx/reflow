from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from . import domain
from .ingestion import CanonicalBatch
from .money_graph import MoneyGraph


class CompositionStatus(StrEnum):
    PROVEN = "composition_proven"
    RESIDUAL = "composition_residual"
    INCOMPLETE = "composition_incomplete"
    CONTRADICTED = "composition_contradicted"


class CompositionProofError(ValueError):
    """Batch-level settlement proof preconditions are structurally inconsistent."""


@dataclass(frozen=True, slots=True)
class DuplicateEconomicGroup:
    representative_id: domain.ReconEntryId
    duplicate_ids: tuple[domain.ReconEntryId, ...]

    @property
    def all_ids(self) -> tuple[domain.ReconEntryId, ...]:
        return (self.representative_id, *self.duplicate_ids)


@dataclass(frozen=True, slots=True)
class SettlementCompositionProof:
    settlement_id: domain.SettlementId
    status: CompositionStatus
    settlement_amount: domain.Money
    observed_composition: domain.Money
    residual: domain.Money
    component_ids: tuple[domain.ReconEntryId, ...]
    evidence_edge_ids: tuple[domain.EvidenceEdgeId, ...]
    duplicate_groups: tuple[DuplicateEconomicGroup, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.settlement_amount.currency != self.observed_composition.currency:
            raise ValueError("composition proof currencies must match")
        if self.residual.currency != self.settlement_amount.currency:
            raise ValueError("composition residual currency must match settlement")
        if self.residual != self.settlement_amount - self.observed_composition:
            raise ValueError("composition residual must equal settlement minus components")
        if self.status is CompositionStatus.PROVEN:
            if not self.residual.is_zero:
                raise ValueError("proven composition must have zero residual")
            if self.duplicate_groups:
                raise ValueError("proven composition cannot contain duplicate evidence")
            if self.reason_codes:
                raise ValueError("proven composition cannot carry failure reason codes")


type EconomicFingerprint = tuple[
    str,
    str,
    str,
    int,
    int,
    int,
    int,
    str,
]


def _economic_fingerprint(entry: domain.SettlementReconEntry) -> EconomicFingerprint:
    """Identify an exact economic movement independently of its recon row ID."""
    return (
        str(entry.settlement_id),
        entry.entity_kind.value,
        str(entry.entity_id),
        entry.gross_amount.amount_paise,
        entry.fee.amount_paise,
        entry.tax.amount_paise,
        entry.settlement_effect.amount_paise,
        entry.occurred_at.isoformat(),
    )


def _deduplicate_economic_rows(
    entries: tuple[domain.SettlementReconEntry, ...],
) -> tuple[
    tuple[domain.SettlementReconEntry, ...],
    tuple[DuplicateEconomicGroup, ...],
]:
    by_fingerprint: dict[EconomicFingerprint, list[domain.SettlementReconEntry]] = {}
    for entry in entries:
        by_fingerprint.setdefault(_economic_fingerprint(entry), []).append(entry)

    unique: list[domain.SettlementReconEntry] = []
    duplicates: list[DuplicateEconomicGroup] = []
    for group in by_fingerprint.values():
        ordered = sorted(group, key=lambda row: str(row.id))
        unique.append(ordered[0])
        if len(ordered) > 1:
            duplicates.append(
                DuplicateEconomicGroup(
                    representative_id=ordered[0].id,
                    duplicate_ids=tuple(row.id for row in ordered[1:]),
                )
            )

    return (
        tuple(sorted(unique, key=lambda row: str(row.id))),
        tuple(sorted(duplicates, key=lambda group: str(group.representative_id))),
    )


def _required_provenance_edges(
    graph: MoneyGraph,
    entry: domain.SettlementReconEntry,
) -> tuple[domain.EvidenceEdgeId, ...] | None:
    expected = {
        ("entity_has_recon_entry", str(entry.entity_id), str(entry.id)),
        (
            "recon_entry_contributes_to_settlement",
            str(entry.id),
            str(entry.settlement_id),
        ),
    }
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
    ]
    matched_keys = {
        (edge.relationship, str(edge.from_id), str(edge.to_id)) for edge in matches
    }
    if matched_keys != expected:
        return None
    return tuple(sorted((edge.id for edge in matches), key=str))


def prove_settlement_composition(
    settlement: domain.Settlement,
    entries: tuple[domain.SettlementReconEntry, ...],
    graph: MoneyGraph,
) -> SettlementCompositionProof:
    if any(entry.settlement_id != settlement.id for entry in entries):
        raise CompositionProofError("composition call contains rows for another settlement")

    unique_entries, duplicate_groups = _deduplicate_economic_rows(entries)
    observed = domain.sum_money(
        [entry.settlement_effect for entry in unique_entries],
        settlement.amount.currency,
    )
    residual = settlement.amount - observed

    reason_codes: set[str] = set()
    evidence_edge_ids: list[domain.EvidenceEdgeId] = []

    if not entries:
        reason_codes.add("NO_RECON_COMPONENTS")

    if duplicate_groups:
        reason_codes.add("DUPLICATE_ECONOMIC_ROW")

    for entry in unique_entries:
        if entry.settlement_effect.currency != settlement.amount.currency:
            raise CompositionProofError("settlement and recon currencies differ")
        edge_ids = _required_provenance_edges(graph, entry)
        if edge_ids is None:
            reason_codes.add("MISSING_GRAPH_PROVENANCE")
        else:
            evidence_edge_ids.extend(edge_ids)

    if duplicate_groups:
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
        component_ids=tuple(entry.id for entry in unique_entries),
        evidence_edge_ids=tuple(sorted(set(evidence_edge_ids), key=str)),
        duplicate_groups=duplicate_groups,
        reason_codes=tuple(sorted(reason_codes)),
    )


def prove_all_settlement_compositions(
    batch: CanonicalBatch,
    graph: MoneyGraph,
) -> tuple[SettlementCompositionProof, ...]:
    settlements: dict[domain.SettlementId, domain.Settlement] = {}
    for settlement in batch.settlements:
        if settlement.id in settlements:
            raise CompositionProofError(f"duplicate settlement id {settlement.id}")
        settlements[settlement.id] = settlement

    rows_by_settlement: dict[
        domain.SettlementId, list[domain.SettlementReconEntry]
    ] = {settlement_id: [] for settlement_id in settlements}
    for entry in batch.recon_entries:
        if entry.settlement_id not in settlements:
            raise CompositionProofError(
                f"recon entry {entry.id} references unknown settlement {entry.settlement_id}"
            )
        rows_by_settlement[entry.settlement_id].append(entry)

    return tuple(
        prove_settlement_composition(
            settlements[settlement_id],
            tuple(rows_by_settlement[settlement_id]),
            graph,
        )
        for settlement_id in sorted(settlements, key=str)
    )
