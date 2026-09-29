import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "deploy/grafana/zateya.json"
SCRAPE = ROOT / "deploy/monitoring/zateya-scrape.yml"


def test_dashboard_contract_and_metric_names():
    dashboard = json.loads(DASHBOARD.read_text())
    assert dashboard["uid"] == "zateya"
    assert dashboard["time"]["from"] == "now-24h"
    datasource = dashboard["templating"]["list"][0]
    assert datasource["type"] == "datasource"
    assert datasource["query"] == "prometheus"
    variables = {item["name"] for item in dashboard["templating"]["list"]}
    assert {"datasource", "channel", "currency"} <= variables

    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    required = {
        "Backend доступен", "Ошибки задач", "Длительность этапов p50/p95",
        "Очередь Алисы", "Последняя синхронизация Git", "Расходы по этапам",
        "Неизвестная стоимость", "Расходы за период", "Средняя цена заметки",
        "Накопленные расходы", "Операции с заметками", "Начало учёта",
    }
    assert required <= panels.keys()
    expressions = "\n".join(
        target.get("expr", "") for panel in dashboard["panels"] for target in panel.get("targets", [])
    )
    for metric in (
        "zateya_turns_total", "zateya_notes_total", "zateya_stage_duration_seconds_bucket",
        "zateya_alice_jobs", "zateya_git_sync_total",
        "zateya_git_last_success_timestamp_seconds", "zateya_provider_cost_total",
        "zateya_usage_unknown_total", "zateya_accounting_started_timestamp_seconds",
        "zateya_completed_note_cost_total", "zateya_completed_notes_costed_total",
        "zateya_completed_note_cost_excluded_total",
    ):
        assert metric in expressions
    assert "increase(" in expressions
    assert "rate(" in expressions
    assert "histogram_quantile(" in expressions
    serialized = json.dumps(dashboard).lower()
    assert "password" not in serialized
    assert "api_key" not in serialized


def test_scrape_job_is_standalone_lan_only_example():
    config = yaml.safe_load(SCRAPE.read_text())
    jobs = config["scrape_configs"]
    assert len(jobs) == 1
    job = jobs[0]
    assert job["job_name"] == "zateya"
    assert job["metrics_path"] == "/metrics"
    assert job["scrape_interval"] == "15s"
    assert job["scrape_timeout"] == "5s"
    assert job["static_configs"] == [{"targets": ["192.168.11.2:7070"]}]
    assert "keenetic" not in SCRAPE.read_text().lower()
