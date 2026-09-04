"""Provider-shaped Razorpay Instant Settlement ingestion boundary."""

from .razorpay_integration import compile_instant_settlement_api_entity

__all__ = ["compile_instant_settlement_api_entity"]
