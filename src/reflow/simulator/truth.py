from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from random import Random

from reflow.domain import (
    Adjustment,
    AdjustmentId,
    BankEntry,
    BankEntryId,
    MerchantOrder,
    Money,
    OrderId,
    PaymentEvent,
    PaymentEventKind,
    PaymentId,
    ReconEntityKind,
    ReconEntryId,
    Refund,
    RefundId,
    Settlement,
    SettlementId,
    SettlementReconEntry,
    Transfer,
    TransferId,
    sum_money,
)


class BankExpectation(StrEnum):
    MATCHED = "matched"
    MISSING = "missing"
    MISMATCHED = "mismatched"


@dataclass(frozen=True, slots=True)
class WorldConfig:
    settlement_count: int = 12
    min_payments: int = 2
    max_payments: int = 8
    high_cardinality_payments: int = 250
    base_time: datetime = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)

    def __post_init__(self) -> None:
        if self.settlement_count < 1:
            raise ValueError("settlement_count must be positive")
        if self.min_payments < 1 or self.max_payments < self.min_payments:
            raise ValueError("invalid payment cardinality range")
        if self.high_cardinality_payments < self.max_payments:
            raise ValueError("high_cardinality_payments must be >= max_payments")
        if self.base_time.tzinfo is None or self.base_time.utcoffset() is None:
            raise ValueError("base_time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class TruthSettlementCase:
    scenario: str
    orders: tuple[MerchantOrder, ...]
    payment_events: tuple[PaymentEvent, ...]
    refunds: tuple[Refund, ...]
    transfers: tuple[Transfer, ...]
    adjustments: tuple[Adjustment, ...]
    recon_entries: tuple[SettlementReconEntry, ...]
    settlement: Settlement
    bank_entries: tuple[BankEntry, ...]
    bank_expectation: BankExpectation


@dataclass(frozen=True, slots=True)
class HiddenWorld:
    seed: int
    cases: tuple[TruthSettlementCase, ...]

    @property
    def transaction_count(self) -> int:
        return sum(len(case.payment_events) for case in self.cases)

    @property
    def recon_count(self) -> int:
        return sum(len(case.recon_entries) for case in self.cases)

    def validate(self) -> None:
        settlement_ids: set[SettlementId] = set()
        settlement_utrs: set[str] = set()
        bank_utrs: set[str] = set()
        order_ids: set[OrderId] = set()
        payment_ids: set[PaymentId] = set()
        event_ids: set[str] = set()
        refund_ids: set[RefundId] = set()
        transfer_ids: set[TransferId] = set()
        adjustment_ids: set[AdjustmentId] = set()
        recon_ids: set[ReconEntryId] = set()
        bank_ids: set[BankEntryId] = set()

        for case in self.cases:
            if case.settlement.id in settlement_ids:
                raise AssertionError("duplicate settlement id in hidden truth")
            settlement_ids.add(case.settlement.id)
            if case.settlement.utr is not None:
                if case.settlement.utr in settlement_utrs:
                    raise AssertionError("duplicate settlement UTR in hidden truth")
                settlement_utrs.add(case.settlement.utr)

            case_order_ids = {order.id for order in case.orders}
            for order in case.orders:
                if order.id in order_ids:
                    raise AssertionError("duplicate order id in hidden truth")
                order_ids.add(order.id)

            case_payment_ids = {event.payment_id for event in case.payment_events}
            new_payment_ids = case_payment_ids - payment_ids
            if len(new_payment_ids) != len(case_payment_ids):
                raise AssertionError("payment id reused across settlement cases")
            for event in case.payment_events:
                if event.source_event_id in event_ids:
                    raise AssertionError("duplicate payment event id in hidden truth")
                event_ids.add(event.source_event_id)
                if event.order_id is not None and event.order_id not in case_order_ids:
                    raise AssertionError("payment event references unknown order")
                if event.occurred_at > case.settlement.processed_at:
                    raise AssertionError("payment event occurs after settlement processing")
            payment_ids.update(case_payment_ids)

            case_refund_ids: set[RefundId] = set()
            for refund in case.refunds:
                if refund.id in refund_ids:
                    raise AssertionError("duplicate refund id in hidden truth")
                refund_ids.add(refund.id)
                case_refund_ids.add(refund.id)
                if refund.payment_id not in payment_ids:
                    raise AssertionError("refund references an unknown or future payment")
                if refund.created_at > case.settlement.processed_at:
                    raise AssertionError("refund occurs after its settlement processing")

            case_transfer_ids: set[TransferId] = set()
            for transfer in case.transfers:
                if transfer.id in transfer_ids:
                    raise AssertionError("duplicate transfer id in hidden truth")
                transfer_ids.add(transfer.id)
                case_transfer_ids.add(transfer.id)
                if transfer.payment_id is not None and transfer.payment_id not in payment_ids:
                    raise AssertionError("transfer references an unknown or future payment")
                if transfer.created_at > case.settlement.processed_at:
                    raise AssertionError("transfer occurs after its settlement processing")

            case_adjustment_ids: set[AdjustmentId] = set()
            for adjustment in case.adjustments:
                if adjustment.id in adjustment_ids:
                    raise AssertionError("duplicate adjustment id in hidden truth")
                adjustment_ids.add(adjustment.id)
                case_adjustment_ids.add(adjustment.id)
                if adjustment.created_at > case.settlement.processed_at:
                    raise AssertionError("adjustment occurs after its settlement processing")

            for entry in case.recon_entries:
                if entry.id in recon_ids:
                    raise AssertionError("duplicate recon id in hidden truth")
                recon_ids.add(entry.id)
                if entry.settlement_id != case.settlement.id:
                    raise AssertionError("recon entry points at wrong settlement")
                if entry.occurred_at > case.settlement.processed_at:
                    raise AssertionError("recon entry occurs after settlement processing")
                if entry.entity_kind is ReconEntityKind.PAYMENT:
                    if entry.entity_id not in case_payment_ids:
                        raise AssertionError("payment recon references unknown payment")
                    if (
                        entry.gross_amount.amount_paise <= 0
                        or entry.settlement_effect
                        != entry.gross_amount - entry.fee - entry.tax
                    ):
                        raise AssertionError("invalid payment recon arithmetic in hidden truth")
                elif entry.entity_kind is ReconEntityKind.REFUND:
                    if entry.entity_id not in case_refund_ids:
                        raise AssertionError("refund recon references unknown refund")
                    if (
                        entry.gross_amount.amount_paise >= 0
                        or not entry.fee.is_zero
                        or not entry.tax.is_zero
                        or entry.settlement_effect != entry.gross_amount
                    ):
                        raise AssertionError("invalid refund recon arithmetic in hidden truth")
                elif entry.entity_kind is ReconEntityKind.TRANSFER:
                    if entry.entity_id not in case_transfer_ids:
                        raise AssertionError("transfer recon references unknown transfer")
                    if (
                        not entry.fee.is_zero
                        or not entry.tax.is_zero
                        or entry.settlement_effect != entry.gross_amount
                    ):
                        raise AssertionError("invalid transfer recon arithmetic in hidden truth")
                elif entry.entity_kind is ReconEntityKind.ADJUSTMENT:
                    if entry.entity_id not in case_adjustment_ids:
                        raise AssertionError("adjustment recon references unknown adjustment")
                    if (
                        not entry.fee.is_zero
                        or not entry.tax.is_zero
                        or entry.settlement_effect != entry.gross_amount
                    ):
                        raise AssertionError("invalid adjustment recon arithmetic in hidden truth")

            expected = sum_money([entry.settlement_effect for entry in case.recon_entries])
            if expected != case.settlement.amount:
                raise AssertionError("settlement composition does not conserve money")

            bank_total = sum_money([entry.amount for entry in case.bank_entries])
            for bank_entry in case.bank_entries:
                if bank_entry.id in bank_ids:
                    raise AssertionError("duplicate bank entry id in hidden truth")
                bank_ids.add(bank_entry.id)
                if bank_entry.occurred_at < case.settlement.processed_at:
                    raise AssertionError("bank credit precedes settlement processing")
                if bank_entry.utr != case.settlement.utr:
                    raise AssertionError("bank truth UTR does not match settlement UTR")
                if bank_entry.utr is None:
                    raise AssertionError("standard settlement bank truth requires UTR")
                if bank_entry.utr in bank_utrs:
                    raise AssertionError("bank UTR reused across transactions in hidden truth")
                bank_utrs.add(bank_entry.utr)

            if case.bank_expectation is BankExpectation.MATCHED:
                if len(case.bank_entries) != 1 or bank_total != case.settlement.amount:
                    raise AssertionError("matched bank truth is inconsistent")
            elif case.bank_expectation is BankExpectation.MISSING:
                if case.bank_entries:
                    raise AssertionError("missing-bank truth must contain no bank entries")
            elif (
                case.bank_expectation is BankExpectation.MISMATCHED
                and (len(case.bank_entries) != 1 or bank_total == case.settlement.amount)
            ):
                raise AssertionError("mismatched bank truth must carry one non-zero residual")


def _fee_and_tax(gross_paise: int) -> tuple[int, int]:
    """Synthetic pricing only: 2% fee plus 18% tax on the fee, rounded to paise."""
    fee = (gross_paise * 2 + 50) // 100
    tax = (fee * 18 + 50) // 100
    return fee, tax


def _scenario_for(index: int) -> str:
    scenarios = (
        "clean",
        "refund",
        "adjustment",
        "immediate_bank_credit",
        "missing_bank_receipt",
        "incorrect_bank_amount",
        "cross_period_refund",
        "same_amount_collision",
        "high_cardinality",
        "transfer",
    )
    return scenarios[index % len(scenarios)]


def _previous_captured_payment(cases: list[TruthSettlementCase]) -> PaymentEvent:
    if not cases:
        raise AssertionError("cross-period refund requires a prior settlement case")
    for event in cases[-1].payment_events:
        if event.kind is PaymentEventKind.CAPTURED:
            return event
    raise AssertionError("prior settlement case has no captured payment")


def generate_world(seed: int, config: WorldConfig | None = None) -> HiddenWorld:
    cfg = config or WorldConfig()
    rng = Random(seed)
    cases: list[TruthSettlementCase] = []
    previous_settlement_amount: Money | None = None

    for case_index in range(cfg.settlement_count):
        scenario = _scenario_for(case_index)
        case_time = cfg.base_time + timedelta(days=case_index)
        settlement_id = SettlementId(f"setl_{case_index:06d}")
        payment_count = (
            cfg.high_cardinality_payments
            if scenario == "high_cardinality"
            else rng.randint(cfg.min_payments, cfg.max_payments)
        )

        orders: list[MerchantOrder] = []
        events: list[PaymentEvent] = []
        refunds: list[Refund] = []
        transfers: list[Transfer] = []
        adjustments: list[Adjustment] = []
        recon: list[SettlementReconEntry] = []

        for payment_index in range(payment_count):
            stem = f"{case_index:06d}_{payment_index:05d}"
            order_id = OrderId(f"order_{stem}")
            payment_id = PaymentId(f"pay_{stem}")
            gross = rng.randint(5_000, 250_000)
            amount = Money(gross)
            event_offset = timedelta(microseconds=payment_index * 4)
            orders.append(MerchantOrder(order_id, amount, case_time))
            events.append(
                PaymentEvent(
                    source_event_id=f"evt_created_{stem}",
                    payment_id=payment_id,
                    order_id=order_id,
                    kind=PaymentEventKind.CREATED,
                    amount=amount,
                    occurred_at=case_time + event_offset,
                    received_at=case_time + event_offset + timedelta(microseconds=1),
                )
            )
            events.append(
                PaymentEvent(
                    source_event_id=f"evt_captured_{stem}",
                    payment_id=payment_id,
                    order_id=order_id,
                    kind=PaymentEventKind.CAPTURED,
                    amount=amount,
                    occurred_at=case_time + event_offset + timedelta(microseconds=2),
                    received_at=case_time + event_offset + timedelta(microseconds=3),
                )
            )
            fee, tax = _fee_and_tax(gross)
            recon.append(
                SettlementReconEntry(
                    id=ReconEntryId(f"recon_pay_{stem}"),
                    settlement_id=settlement_id,
                    entity_kind=ReconEntityKind.PAYMENT,
                    entity_id=payment_id,
                    gross_amount=amount,
                    fee=Money(fee),
                    tax=Money(tax),
                    settlement_effect=Money(gross - fee - tax),
                    occurred_at=case_time + timedelta(minutes=1),
                )
            )

        if scenario in {"refund", "cross_period_refund"}:
            source_payment = (
                _previous_captured_payment(cases)
                if scenario == "cross_period_refund"
                else events[1]
            )
            payment_id = source_payment.payment_id
            payment_amount = source_payment.amount.amount_paise
            refund_amount = min(payment_amount // 3, 25_000)
            refund_time = case_time + timedelta(hours=1)
            refund = Refund(
                id=RefundId(f"rfnd_{case_index:06d}_00000"),
                payment_id=payment_id,
                amount=Money(refund_amount),
                created_at=refund_time,
            )
            refunds.append(refund)
            recon.append(
                SettlementReconEntry(
                    id=ReconEntryId(f"recon_refund_{case_index:06d}_00000"),
                    settlement_id=settlement_id,
                    entity_kind=ReconEntityKind.REFUND,
                    entity_id=refund.id,
                    gross_amount=Money(-refund_amount),
                    fee=Money.zero(),
                    tax=Money.zero(),
                    settlement_effect=Money(-refund_amount),
                    occurred_at=refund_time,
                )
            )

        if scenario == "adjustment":
            amount_paise = rng.choice((-1, 1)) * rng.randint(100, 2_500)
            adjustment = Adjustment(
                id=AdjustmentId(f"adj_{case_index:06d}_00000"),
                amount=Money(amount_paise),
                created_at=case_time + timedelta(hours=2),
                reason="synthetic settlement correction",
            )
            adjustments.append(adjustment)
            recon.append(
                SettlementReconEntry(
                    id=ReconEntryId(f"recon_adj_{case_index:06d}_00000"),
                    settlement_id=settlement_id,
                    entity_kind=ReconEntityKind.ADJUSTMENT,
                    entity_id=adjustment.id,
                    gross_amount=adjustment.amount,
                    fee=Money.zero(),
                    tax=Money.zero(),
                    settlement_effect=adjustment.amount,
                    occurred_at=adjustment.created_at,
                )
            )

        if scenario == "transfer":
            transfer = Transfer(
                id=TransferId(f"trf_{case_index:06d}_00000"),
                payment_id=events[1].payment_id,
                amount=Money(-rng.randint(100, 1_500)),
                created_at=case_time + timedelta(hours=2),
            )
            transfers.append(transfer)
            recon.append(
                SettlementReconEntry(
                    id=ReconEntryId(f"recon_trf_{case_index:06d}_00000"),
                    settlement_id=settlement_id,
                    entity_kind=ReconEntityKind.TRANSFER,
                    entity_id=transfer.id,
                    gross_amount=transfer.amount,
                    fee=Money.zero(),
                    tax=Money.zero(),
                    settlement_effect=transfer.amount,
                    occurred_at=transfer.created_at,
                )
            )

        current_total = sum_money([entry.settlement_effect for entry in recon])
        if scenario == "same_amount_collision" and previous_settlement_amount is not None:
            delta = previous_settlement_amount - current_total
            if not delta.is_zero:
                adjustment = Adjustment(
                    id=AdjustmentId(f"adj_{case_index:06d}_collision"),
                    amount=delta,
                    created_at=case_time + timedelta(hours=2),
                    reason="force same-amount collision for identity testing",
                )
                adjustments.append(adjustment)
                recon.append(
                    SettlementReconEntry(
                        id=ReconEntryId(f"recon_adj_{case_index:06d}_collision"),
                        settlement_id=settlement_id,
                        entity_kind=ReconEntityKind.ADJUSTMENT,
                        entity_id=adjustment.id,
                        gross_amount=delta,
                        fee=Money.zero(),
                        tax=Money.zero(),
                        settlement_effect=delta,
                        occurred_at=adjustment.created_at,
                    )
                )
                current_total = previous_settlement_amount

        if current_total.amount_paise <= 0:
            raise AssertionError("generator produced non-positive settlement")

        utr = f"UTR{case_index:012d}"
        settlement_time = case_time + timedelta(hours=6)
        settlement = Settlement(settlement_id, current_total, settlement_time, utr)

        bank_expectation = BankExpectation.MATCHED
        bank_entries: list[BankEntry] = []
        if scenario == "missing_bank_receipt":
            bank_expectation = BankExpectation.MISSING
        elif scenario == "incorrect_bank_amount":
            bank_expectation = BankExpectation.MISMATCHED
            bank_entries.append(
                BankEntry(
                    BankEntryId(f"bank_{case_index:06d}_a"),
                    Money(current_total.amount_paise - 137),
                    settlement_time + timedelta(hours=1),
                    f"RAZORPAY {utr}",
                    utr,
                )
            )
        else:
            bank_time = (
                settlement_time
                if scenario == "immediate_bank_credit"
                else settlement_time + timedelta(hours=1)
            )
            bank_entries.append(
                BankEntry(
                    BankEntryId(f"bank_{case_index:06d}_a"),
                    current_total,
                    bank_time,
                    f"RAZORPAY SETTLEMENT {utr}",
                    utr,
                )
            )

        cases.append(
            TruthSettlementCase(
                scenario=scenario,
                orders=tuple(orders),
                payment_events=tuple(events),
                refunds=tuple(refunds),
                transfers=tuple(transfers),
                adjustments=tuple(adjustments),
                recon_entries=tuple(recon),
                settlement=settlement,
                bank_entries=tuple(bank_entries),
                bank_expectation=bank_expectation,
            )
        )
        previous_settlement_amount = current_total

    world = HiddenWorld(seed=seed, cases=tuple(cases))
    world.validate()
    return world