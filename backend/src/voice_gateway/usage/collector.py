from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from typing import Callable

from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, HistogramMetricFamily

from .store import UsageStore


class UsageCollector:
    """Build bounded Prometheus series from the durable accounting database."""

    def __init__(self, store: UsageStore,
                 alice_job_counts: Callable[[], dict[str, int]] | None = None) -> None:
        self.store = store
        self.alice_job_counts = alice_job_counts

    def collect(self):
        try:
            snapshot = self.store.metrics_snapshot()
        except Exception:
            # A metrics scrape must never make the service endpoint fail when
            # the archive is temporarily unavailable or is being detached.
            return
        started = GaugeMetricFamily(
            "zateya_accounting_started_timestamp_seconds",
            "Unix timestamp at which durable accounting began.",
        )
        started.add_metric([], float(snapshot["accounting_started_at"]))
        yield started
        metrics = snapshot["metrics"]
        specs = (
            ("turns", "zateya_turns_total", "Text turns by terminal outcome.",
             ["channel", "outcome"]),
            ("notes", "zateya_notes_total", "Published notes by operation.",
             ["channel", "operation"]),
            ("operations", "zateya_operations_total", "Completed turns by knowledge operation.",
             ["channel", "operation"]),
            ("provider_calls", "zateya_provider_calls_total", "Provider calls by outcome.",
             ["channel", "stage", "model", "outcome"]),
            ("usage_unknown", "zateya_usage_unknown_total", "Calls whose cost cannot be determined.",
             ["channel", "stage", "model"]),
            ("usage_tokens", "zateya_usage_tokens_total", "Provider token usage.",
             ["channel", "stage", "model", "direction"]),
            ("provider_cost", "zateya_provider_cost_total", "Provider cost by currency and source.",
             ["channel", "stage", "model", "currency", "cost_kind"]),
            ("completed_count", "zateya_completed_notes_costed_total",
             "Saved captures included in cost accounting.",
             ["channel", "currency", "cost_kind"]),
            ("completed_cost", "zateya_completed_note_cost_total",
             "Provider cost of completed saved notes.",
             ["channel", "currency", "cost_kind"]),
            ("completed_excluded", "zateya_completed_note_cost_excluded_total",
             "Saved notes excluded from cost totals.", ["channel", "reason"]),
        )
        for key, name, help_text, labels in specs:
            family = CounterMetricFamily(name, help_text, labels=labels)
            for label_values, value in sorted(metrics.get(key, [])):
                family.add_metric(list(label_values), float(value))
            yield family

        bucket_rows = metrics.get("stage_bucket", [])
        sums = dict(metrics.get("stage_sum", []))
        grouped = defaultdict(list)
        for labels, value in bucket_rows:
            grouped[labels[:3]].append((labels[3], float(value)))
        stage_family = HistogramMetricFamily(
            "zateya_stage_duration_seconds", "Duration of processing stages.",
            labels=["channel", "stage", "outcome"],
        )
        for labels, buckets in sorted(grouped.items()):
            ordered = sorted(buckets, key=lambda item: float("inf") if item[0] == "+Inf" else float(item[0]))
            stage_family.add_metric(list(labels), ordered, float(sums.get(labels, 0)))
        yield stage_family

        if self.alice_job_counts is not None:
            jobs = GaugeMetricFamily(
                "zateya_alice_jobs", "Durable Alice jobs by current status.", labels=["status"]
            )
            for status, count in sorted(self.alice_job_counts().items()):
                jobs.add_metric([status], count)
            yield jobs

    @staticmethod
    def _stage_durations(calls, events):
        buckets = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)
        observations = defaultdict(list)
        for row in calls:
            if row["state"] == "finished" and row["elapsed_seconds"] is not None:
                observations[(row["channel"], row["stage"], row["outcome"])].append(
                    row["elapsed_seconds"]
                )
        for row in events:
            observations[(row["channel"], row["stage"], row["outcome"])].append(
                row["elapsed_seconds"]
            )
        family = HistogramMetricFamily(
            "zateya_stage_duration_seconds", "Duration of processing stages.",
            labels=["channel", "stage", "outcome"],
        )
        for labels, values in sorted(observations.items()):
            counts = [(str(bound), sum(value <= bound for value in values)) for bound in buckets]
            counts.append(("+Inf", len(values)))
            family.add_metric(list(labels), counts, sum(values))
        return family

    @staticmethod
    def _provider_metrics(calls):
        call_counts = Counter()
        unknown_counts = Counter()
        token_counts = Counter()
        cost_totals: dict[tuple, Decimal] = defaultdict(Decimal)
        for row in calls:
            labels = (row["channel"], row["stage"], row["model"])
            if row["state"] == "finished":
                call_counts[labels + (row["outcome"] or "unknown",)] += 1
            if row["state"] != "finished" or row["cost_amount"] is None:
                unknown_counts[labels] += 1
            if row["input_tokens"] is not None:
                token_counts[labels + ("input",)] += row["input_tokens"]
            if row["output_tokens"] is not None:
                token_counts[labels + ("output",)] += row["output_tokens"]
            if row["cost_amount"] is not None:
                cost_totals[labels + (row["cost_currency"], row["cost_kind"])] += Decimal(
                    row["cost_amount"]
                )

        calls_family = CounterMetricFamily(
            "zateya_provider_calls_total", "Provider calls by outcome.",
            labels=["channel", "stage", "model", "outcome"],
        )
        for labels, value in sorted(call_counts.items()):
            calls_family.add_metric(list(labels), value)
        yield calls_family

        unknown = CounterMetricFamily(
            "zateya_usage_unknown_total", "Calls whose cost cannot be determined.",
            labels=["channel", "stage", "model"],
        )
        for labels, value in sorted(unknown_counts.items()):
            unknown.add_metric(list(labels), value)
        yield unknown

        tokens = CounterMetricFamily(
            "zateya_usage_tokens_total", "Provider token usage.",
            labels=["channel", "stage", "model", "direction"],
        )
        for labels, value in sorted(token_counts.items()):
            tokens.add_metric(list(labels), value)
        yield tokens

        costs = CounterMetricFamily(
            "zateya_provider_cost_total", "Provider cost by currency and source.",
            labels=["channel", "stage", "model", "currency", "cost_kind"],
        )
        for labels, value in sorted(cost_totals.items()):
            costs.add_metric(list(labels), float(value))
        yield costs

    @staticmethod
    def _turn_metrics(turns, calls):
        turn_counts = Counter(
            (row["channel"], row["outcome"]) for row in turns if row["outcome"] != "pending"
        )
        operation_counts = Counter(
            (row["channel"], row["operation"])
            for row in turns if row["outcome"] != "pending" and row["operation"] != "none"
        )
        note_counts = Counter(
            (row["channel"], row["operation"])
            for row in turns
            if row["note_saved"] and row["operation"] in {"capture", "amend"}
        )
        turns_family = CounterMetricFamily(
            "zateya_turns_total", "Text turns by terminal outcome.",
            labels=["channel", "outcome"],
        )
        for labels, value in sorted(turn_counts.items()):
            turns_family.add_metric(list(labels), value)
        yield turns_family

        notes_family = CounterMetricFamily(
            "zateya_notes_total", "Published notes by operation.",
            labels=["channel", "operation"],
        )
        for labels, value in sorted(note_counts.items()):
            notes_family.add_metric(list(labels), value)
        yield notes_family

        operations = CounterMetricFamily(
            "zateya_operations_total", "Completed turns by knowledge operation.",
            labels=["channel", "operation"],
        )
        for labels, value in sorted(operation_counts.items()):
            operations.add_metric(list(labels), value)
        yield operations

        by_turn = defaultdict(list)
        for row in calls:
            by_turn[row["turn_id"]].append(row)
        completed_counts = Counter()
        completed_costs: dict[tuple, Decimal] = defaultdict(Decimal)
        excluded = Counter()
        for turn in turns:
            if not turn["note_saved"] or turn["operation"] not in {"capture", "amend"}:
                continue
            base = (turn["channel"], turn["operation"])
            rows = by_turn[turn["turn_id"]]
            if not rows or any(r["state"] != "finished" or r["cost_amount"] is None for r in rows):
                if turn["operation"] == "capture":
                    excluded[(turn["channel"], "incomplete_usage")] += 1
                continue
            currencies = {r["cost_currency"] for r in rows}
            if len(currencies) != 1:
                if turn["operation"] == "capture":
                    excluded[(turn["channel"], "mixed_currency")] += 1
                continue
            kind = "reported" if all(r["cost_kind"] == "reported" for r in rows) else "estimated"
            total = sum((Decimal(r["cost_amount"]) for r in rows), Decimal(0))
            if turn["operation"] == "capture":
                currency = currencies.pop()
                completed_costs[(turn["channel"], currency, kind)] += total
                completed_counts[(turn["channel"], currency, kind)] += 1

        completed = CounterMetricFamily(
            "zateya_completed_notes_costed_total", "Saved captures included in cost accounting.",
            labels=["channel", "currency", "cost_kind"],
        )
        for labels, value in sorted(completed_counts.items()):
            completed.add_metric(list(labels), value)
        yield completed

        completed_cost = CounterMetricFamily(
            "zateya_completed_note_cost_total", "Provider cost of completed saved notes.",
            labels=["channel", "currency", "cost_kind"],
        )
        for labels, value in sorted(completed_costs.items()):
            completed_cost.add_metric(list(labels), float(value))
        yield completed_cost

        excluded_family = CounterMetricFamily(
            "zateya_completed_note_cost_excluded_total",
            "Saved notes excluded from cost totals.",
            labels=["channel", "reason"],
        )
        for labels, value in sorted(excluded.items()):
            excluded_family.add_metric(list(labels), value)
        yield excluded_family
