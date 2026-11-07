import copy
import pytest
from content_agent.service import Service

BRIEF = {"theme": "便携杯跨境推广", "budget_units": 100, "deadline_hours": 48}


@pytest.fixture
def service(tmp_path):
    s = Service(tmp_path)
    yield s
    s.close()


def test_graph_completes_with_real_artifacts(service):
    r = service.run("normal", BRIEF)
    assert r["status"] == "completed", r["reason"]
    assert r["plan_version"] == 2
    assert r["spent"] == 55


def test_missing_fields_pause_and_resume_same_thread(service):
    r = service.run("missing", {"theme": "cup"})
    assert r["status"] == "waiting_input" and r["calls"] == 0
    assert r["trace"][0]["kind"] == "clarification"
    assert set(r["trace"][0]["missing"]) == {"budget_units", "deadline_hours"}
    r = service.resume("missing", {"budget_units": 100, "deadline_hours": 48})
    assert r["status"] == "completed", r["reason"]
    assert r["task_id"] == "missing"


def test_duplicate_run_does_not_repeat_execution(service):
    a = service.run("same", BRIEF)
    b = service.run("same", BRIEF)
    assert a == b
    with pytest.raises(ValueError):
        service.run("same", {**BRIEF, "budget_units": 90})


def test_failure_resume_keeps_success_and_sunk_costs(service):
    failed = service.run("failure", BRIEF, scenario="persistent_failure")
    assert failed["status"] == "incomplete"
    saved = copy.deepcopy(failed["artifacts"]["DE-1"])
    repaired = service.resume("failure", repair=True)
    assert repaired["status"] == "completed", repaired["reason"]
    assert repaired["artifacts"]["DE-1"] == saved
    assert repaired["spent"] == 61


@pytest.mark.parametrize("scenario", ["script_once", "asset_missing", "quality_once", "save_once"])
def test_faults_recover_without_fake_success(service, scenario):
    r = service.run(scenario, BRIEF, scenario=scenario)
    assert r["status"] == "completed", r["reason"]
    assert any(e.get("result", {}).get("ok") is False or e.get("result", {}).get("approved") is False for e in r["trace"])
    assert all(a["status"] == "approved" for a in r["artifacts"].values())


def test_budget_infeasible_returns_gap(service):
    r = service.run("no-budget", {**BRIEF, "budget_units": 10})
    assert r["status"] == "incomplete"
    assert r["spent"] <= 10 and r["saved"] is None
    assert r["last_result"]["gap"]["budget_gap"] > 0


def test_deadline_replans_to_faster_service(service):
    r = service.run("deadline", {**BRIEF, "deadline_hours": 5})
    assert r["status"] == "completed"
    assert all(t["tier"] == "economy" for t in r["plan"])
    assert r["elapsed_minutes"] <= 300


def test_tool_limit_is_explicit(service):
    r = service.run("limit", {**BRIEF, "max_calls": 4})
    assert r["status"] == "incomplete" and r["calls"] == 4
    assert "limit" in r["reason"]


def test_path_traversal_rejected(service):
    with pytest.raises(ValueError):
        service.run("../bad", BRIEF)


def test_partial_clarification_preserves_budget(service):
    service.run("partial", {"theme": "cup"})
    r = service.resume("partial", {"budget_units": 100})
    assert r["status"] == "waiting_input"
    assert r["brief"]["budget_units"] == 100
    r = service.resume("partial", {"deadline_hours": 48})
    assert r["status"] == "completed", r["reason"]


def test_waiting_time_can_exhaust_deadline_without_infinite_retries(service):
    service.run("expired", {**BRIEF, "max_calls": 4})
    r = service.resume("expired", wait_minutes=3000)
    assert r["status"] == "incomplete"
    assert r["last_result"]["status"] == "incomplete"
    assert r["calls"] < r["brief"]["max_calls"]


def test_model_failure_does_not_fall_back_to_fake_success(service, monkeypatch):
    class Unavailable:
        label = "test:unavailable_model"
        def decide(self, state):
            raise ConnectionError("unavailable")
    monkeypatch.setattr("content_agent.service.LiveProvider", Unavailable)
    r = service.run("model-down", BRIEF, mode="live")
    assert r["status"] == "incomplete"
    assert r["spent"] == 0 and r["calls"] == 0
    assert "ConnectionError" in r["reason"]


def test_state_survives_new_service_instance(service):
    service.run("restart", BRIEF, scenario="persistent_failure")
    service2 = Service(service.root)
    try:
        r = service2.resume("restart", repair=True)
        assert r["status"] == "completed"
        assert r["spent"] == 61
    finally:
        service2.close()


def test_keyboard_interrupt_preserves_explicit_incomplete_state(service, monkeypatch):
    class Interrupted:
        label = "test:interrupt"
        def decide(self, state):
            raise KeyboardInterrupt()
    monkeypatch.setattr("content_agent.service.LiveProvider", Interrupted)
    r = service.run("interrupted", BRIEF, mode="live")
    assert r["status"] == "incomplete"
    assert r["trace"][-1]["kind"] == "operator_interrupted"


def test_export_incomplete_task_removes_stale_complete_package(service, tmp_path):
    destination = tmp_path / "shared-export"
    complete = service.run("export-complete", BRIEF)
    assert complete["status"] == "completed"
    service.export("export-complete", destination)
    assert (destination / "campaign.json").is_file()
    service.run("export-incomplete", {**BRIEF, "max_calls": 4})
    service.export("export-incomplete", destination)
    assert not (destination / "campaign.json").exists()
    assert not (destination / "campaign.md").exists()
    assert (destination / "result.json").is_file()
