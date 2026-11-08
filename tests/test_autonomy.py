"""Offline fixtures validate the evidence checker; they cannot pass as live evidence."""
import copy
import pytest

from content_agent.evaluation import audit_autonomy
from content_agent.service import Service


def fixture_run(tmp_path, scenario):
    service = Service(tmp_path)
    baseline = {}
    captured = False
    def event(e):
        nonlocal captured
        if e.get("result", {}).get("code") == "SERVICE_UNAVAILABLE" and not captured:
            captured = True
            s = service.store.get("fixture")
            baseline.update({t["id"]: {"task": copy.deepcopy(t), "artifact": copy.deepcopy(s["artifacts"][t["id"]])} for t in s["plan"] if s["artifacts"].get(t["id"], {}).get("status") == "approved"})
    try:
        state = service.run("fixture", {"theme": "fixture", "budget_units": 100, "deadline_hours": 48}, scenario=scenario, on_event=event)
    finally:
        service.close()
    return state, baseline


def audit(state, baseline, scenario="script_once"):
    return audit_autonomy(state, scenario, state["brief"], baseline, {"model": "unit-fixture"})


@pytest.mark.parametrize("scenario", ["script_once", "persistent_failure"])
def test_offline_behavior_passes_but_cannot_be_live_evidence(tmp_path, scenario):
    state, baseline = fixture_run(tmp_path, scenario)
    result = audit(state, baseline, scenario)
    assert not result["passed"]
    assert not result["checks"]["live_model_decisions"]
    assert all(value for key, value in result["checks"].items() if key not in {"live_model_decisions", "fixed_model_configuration"})
    if scenario == "persistent_failure":
        assert "DE-2" in state["reason"] and "SERVICE_UNAVAILABLE" in state["reason"]
        assert "恢复同一任务" in state["reason"]


def test_manual_resume_disqualifies_autonomy(tmp_path):
    state, baseline = fixture_run(tmp_path, "script_once")
    state["resume_count"] = 1
    state["trace"].append({"kind": "resume"})
    assert not audit(state, baseline)["checks"]["no_human_resume_or_interruption"]


def test_changed_prior_success_is_detected(tmp_path):
    state, baseline = fixture_run(tmp_path, "script_once")
    state["artifacts"]["DE-1"]["script"]["title"] = "Replaced content"
    assert not audit(state, baseline)["checks"]["prior_success_preserved"]


def test_limit_fallback_is_not_a_proactive_stop(tmp_path):
    state, baseline = fixture_run(tmp_path, "persistent_failure")
    state["trace"].append({"kind": "limit"})
    assert not audit(state, baseline, "persistent_failure")["checks"]["no_runtime_error_or_limit_fallback"]


def test_failure_without_prior_success_does_not_prove_preservation(tmp_path):
    state, _ = fixture_run(tmp_path, "script_once")
    assert not audit(state, {})["checks"]["prior_success_preserved"]
