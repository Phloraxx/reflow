from __future__ import annotations

import hashlib
from dataclasses import dataclass

from . import domain, ingestion, payment_state

type EdgeKey = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class MoneyGraph:
    nodes: frozenset[domain.EntityId]
    edges: tuple[domain.EvidenceEdge, ...]

    @property
    def edge_keys(self) -> frozenset[EdgeKey]:
        return frozenset(edge_key(edge) for edge in self.edges)


@dataclass(frozen=True, slots=True)
class EdgeMetrics:
    true_positive: int
    false_positive: int
    false_negative: int
    precision: float
    recall: float


def _edge_id(
    relationship: str,
    from_id: domain.EntityId,
    to_id: domain.EntityId,
    evidence_ids: tuple[str, ...],
) -> domain.EvidenceEdgeId:
    material = "\0".join(
        (relationship, str(from_id), str(to_id), *sorted(evidence_ids))
    ).encode()
    return domain.EvidenceEdgeId(f"edge_{hashlib.sha256(material).hexdigest()[:24]}")


def _edge(
    *,
    relationship: str,
    from_id: domain.EntityId,
    to_id: domain.EntityId,
    evidence_ids: tuple[str, ...],
) -> domain.EvidenceEdge:
    evidence = tuple(sorted(set(evidence_ids)))
    return domain.EvidenceEdge(
        id=_edge_id(relationship, from_id, to_id, evidence),
        from_id=from_id,
        to_id=to_id,
        relationship=relationship,
        strength=domain.EvidenceStrength.AUTHORITATIVE,
        state=domain.EdgeState.PROVEN,
        evidence_ids=evidence,
        reason_codes=("EXACT_SOURCE_IDENTIFIER",),
    )


def build_money_graph(batch: ingestion.CanonicalBatch) -> MoneyGraph:
    nodes: set[domain.EntityId] = set()
    nodes.update(order.id for order in batch.orders)
    nodes.update(event.payment_id for event in batch.payment_events)
    nodes.update(settlement.id for settlement in batch.settlements)
    nodes.update(entry.id for entry in batch.bank_entries)

    events_by_payment: dict[domain.PaymentId, list[domain.PaymentEvent]] = {}
    for event in batch.payment_events:
        events_by_payment.setdefault(event.payment_id, []).append(event)

    edges: list[domain.EvidenceEdge] = []
    for state in payment_state.reduce_all_payments(batch.payment_events):
        if state.order_id is None:
            continue
        nodes.add(state.order_id)
        evidence_ids = tuple(
            event.source_event_id
            for event in events_by_payment[state.payment_id]
            if event.order_id == state.order_id
        )
        edges.append(
            _edge(
                relationship="order_has_payment",
                from_id=state.order_id,
                to_id=state.payment_id,
                evidence_ids=evidence_ids,
            )
        )

    for recon in sorted(batch.recon_entries, key=lambda row: str(row.id)):
        nodes.add(recon.entity_id)
        nodes.add(recon.id)
        nodes.add(recon.settlement_id)
        edges.extend(
            (
                _edge(
                    relationship="entity_has_recon_entry",
                    from_id=recon.entity_id,
                    to_id=recon.id,
                    evidence_ids=(str(recon.id),),
                ),
                _edge(
                    relationship="recon_entry_contributes_to_settlement",
                    from_id=recon.id,
                    to_id=recon.settlement_id,
                    evidence_ids=(str(recon.id),),
                ),
            )
        )

    unique_edges = {edge.id: edge for edge in edges}
    return MoneyGraph(
        nodes=frozenset(nodes),
        edges=tuple(sorted(unique_edges.values(), key=lambda edge: str(edge.id))),
    )


def edge_key(edge: domain.EvidenceEdge) -> EdgeKey:
    return (edge.relationship, str(edge.from_id), str(edge.to_id))


def evaluate_edges(graph: MoneyGraph, expected: set[EdgeKey]) -> EdgeMetrics:
    actual = set(graph.edge_keys)
    true_positive = len(actual & expected)
    false_positive = len(actual - expected)
    false_negative = len(expected - actual)
    precision = true_positive / len(actual) if actual else (1.0 if not expected else 0.0)
    recall = true_positive / len(expected) if expected else 1.0
    return EdgeMetrics(
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        precision=precision,
        recall=recall,
    )
