from __future__ import annotations

import logging

from prometheus_client import Counter

from .models import CallContext, Cost, UsageObservation
from .pricing import price_usage
from .store import UsageStore

logger = logging.getLogger(__name__)


class UsageRecorder:
    """Best-effort accounting that never masks provider behavior."""

    def __init__(self, store: UsageStore, *, write_errors: Counter | None = None,
                 rates: dict | None = None) -> None:
        self.store = store
        self.write_errors = write_errors
        self.rates = rates or {"version": 1, "rates": []}

    def price(self, context: CallContext, usage: UsageObservation) -> Cost:
        return price_usage(context.stage, context.model, usage, self.rates)

    def _failed(self, exc: Exception) -> None:
        if self.write_errors is not None:
            self.write_errors.inc()
        logger.warning("usage accounting write failed: %s", type(exc).__name__)

    def begin_call(self, context: CallContext) -> str | None:
        try:
            return self.store.begin_call(context)
        except Exception as exc:
            self._failed(exc)
            return None

    def finish_call(
        self,
        call_id: str | None,
        *,
        outcome: str,
        elapsed_seconds: float,
        usage: UsageObservation,
        cost: Cost,
    ) -> None:
        if call_id is None:
            return
        try:
            self.store.finish_call(
                call_id, outcome=outcome, elapsed_seconds=elapsed_seconds, usage=usage, cost=cost
            )
        except Exception as exc:
            self._failed(exc)

    def finish_turn(self, turn_id: str, **fields) -> None:
        try:
            self.store.finish_turn(turn_id, **fields)
        except Exception as exc:
            self._failed(exc)
