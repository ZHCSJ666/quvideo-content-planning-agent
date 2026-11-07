import copy
import pytest
from content_agent.domain import Brief, initial_state
from content_agent.providers import OfflineProvider
from content_agent.storage import Store
from content_agent.tools import ToolRunner


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path)
    provider = OfflineProvider()
    state = initial_state(Brief(theme="cup", budget_units=100, deadline_hours=48), "tools", "offline", "normal")
    store.create(state)
    yield store, provider, ToolRunner(store, provider), state
    store.close()


def advance(env, until):
    store, provider, runner, state = env
    for _ in range(40):
        if until(state):
            return state
        action = provider.decide(state)
        state["decision"] = action
        state = runner.execute(state, action)
    raise AssertionError("did not reach target")


def test_duplicate_receipt_does_not_charge_twice(env):
    store, provider, runner, state = env
    action = {"name": "search_assets", "args": {"market": "DE", "reason": "test"}}
    a = runner.execute(state, action)
    b = runner.execute(state, action)
    assert a == b and a["spent"] == 1
    assert len(a["trace"]) == 1


def test_overbudget_quote_never_charges(env):
    state = advance(env, lambda s: s["quote"] is not None)
    assert not state["quote"]["feasible"]
    assert state["spent"] == 2
    assert state["quote"]["projected_total"] == 119


def test_success_has_actual_files_and_balanced_ledger(env):
    state = advance(env, lambda s: s["status"] == "completed")
    assert state["spent"] == sum(e["cost"] for e in state["trace"])
    assert state["elapsed_minutes"] == sum(e["minutes"] for e in state["trace"])
    assert state["spent"] == 55
    assert (env[0].root / state["saved"]).exists()
    assert len(state["artifacts"]) == 4


def test_cannot_save_unreviewed_content(env):
    state = advance(env, lambda s: len(s["plan"]) == 4)
    out = env[2].execute(state, {"name": "save_campaign", "args": {"reason": "attempt early save"}})
    assert out["last_result"]["code"] == "QUALITY_GATE"
    assert out["status"] != "completed" and out["saved"] is None


def test_sunk_cost_and_success_preserved_when_later_step_fails(env):
    env[3]["scenario"] = "script_once"
    state = advance(env, lambda s: (s["last_result"] or {}).get("code") == "SERVICE_UNAVAILABLE")
    assert state["artifacts"]["DE-1"]["status"] == "approved"
    assert "DE-2" not in state["artifacts"]
    assert state["trace"][-1]["cost"] == 2
    before = copy.deepcopy(state["artifacts"]["DE-1"])
    repaired = advance((*env[:3], state), lambda s: s["status"] == "completed")
    assert repaired["artifacts"]["DE-1"] == before
    assert repaired["spent"] == 57


def test_plan_changes_cannot_reset_exhausted_attempts(env):
    from content_agent.providers import public_state
    env[3]["scenario"] = "persistent_failure"
    state = advance(env, lambda s: s["attempts"].get("DE-2") == 3)
    before_spent = state["spent"]
    preserved = copy.deepcopy(state["artifacts"]["DE-1"])
    plan = copy.deepcopy(state["plan"])
    plan[1]["tier"] = "economy"
    plan[1]["strategy"] += "；调整表现形式"
    runner = env[2]
    state = runner.execute(state, {"name": "revise_plan", "args": {"tasks": plan, "reason": "try a different service"}})
    state = runner.execute(state, {"name": "estimate_cost", "args": {"reason": "verify new plan"}})
    state = runner.execute(state, {"name": "generate_script", "args": {"task_id": "DE-2", "reason": "attempt after plan edit"}})
    assert state["last_result"]["code"] == "ATTEMPTS_EXHAUSTED"
    assert state["last_result"]["retryable"] is False
    assert state["spent"] == before_spent
    assert state["artifacts"]["DE-1"] == preserved
    visible = public_state(state)
    assert visible["attempts"]["DE-2"] == 3
    assert "scenario" not in visible


def test_quality_failure_cannot_be_marked_success(env):
    env[3]["scenario"] = "quality_once"
    state = advance(env, lambda s: any(a["status"] == "rejected" for a in s["artifacts"].values()))
    assert state["status"] != "completed"
    assert state["artifacts"]["DE-2"]["review"]["issues"]


def test_scope_revision_retains_unaffected_artifact(env):
    state = advance(env, lambda s: s["artifacts"].get("DE-1", {}).get("status") == "approved")
    plan = copy.deepcopy(state["plan"])
    plan[-1]["tier"] = "economy"
    out = env[2].execute(state, {"name": "revise_plan", "args": {"tasks": plan, "reason": "adjust only pending work"}})
    assert out["last_result"]["retained"] == ["DE-1"]
    assert out["artifacts"]["DE-1"] == state["artifacts"]["DE-1"]


def test_preflight_budget_guard(env):
    state = env[3]
    state["brief"]["budget_units"] = 0
    out = env[2].execute(state, {"name": "search_assets", "args": {"market": "DE", "reason": "test guard"}})
    assert out["last_result"]["code"] == "BUDGET_BLOCKED"
    assert out["spent"] == 0


def test_actual_disk_failure_never_reports_completed(env, monkeypatch):
    state = advance(env, lambda s: len(s["artifacts"]) == 4 and all(a["status"] == "approved" for a in s["artifacts"].values()))
    def fail(_state):
        raise OSError("disk failure")
    monkeypatch.setattr(env[2], "write_package", fail)
    out = env[2].execute(state, {"name": "save_campaign", "args": {"reason": "save approved package"}})
    assert out["status"] != "completed" and out["saved"] is None
    assert out["spent"] == state["spent"]


def test_repeating_approved_generation_is_free(env):
    state = advance(env, lambda s: s["artifacts"].get("DE-1", {}).get("status") == "approved")
    out = env[2].execute(state, {"name": "generate_script", "args": {"task_id": "DE-1", "reason": "repeat test"}})
    assert out["last_result"]["code"] == "REUSED"
    assert out["spent"] == state["spent"]
    assert out["artifacts"] == state["artifacts"]


def test_invalidated_task_requires_new_generation_but_preserves_sunk_cost(env):
    state = advance(env, lambda s: s["artifacts"].get("DE-1", {}).get("status") == "approved")
    plan = copy.deepcopy(state["plan"])
    plan[0]["angle"] = "全新创意依赖不同表达，需要重新生成"
    out = env[2].execute(state, {"name": "revise_plan", "args": {"tasks": plan, "reason": "explicit creative revision"}})
    assert "DE-1" not in out["artifacts"]
    assert out["last_result"]["invalidated"] == ["DE-1"]
    assert out["spent"] == state["spent"]


def test_second_write_failure_never_reports_completed(env, monkeypatch):
    state = advance(env, lambda s: len(s["artifacts"]) == 4 and all(a["status"] == "approved" for a in s["artifacts"].values()))
    original = env[2].write_package
    calls = []
    def fail_second(s):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("second write failed")
        original(s)
    monkeypatch.setattr(env[2], "write_package", fail_second)
    out = env[2].execute(state, {"name": "save_campaign", "args": {"reason": "save approved package"}})
    assert out["status"] != "completed" and out["saved"] is None
    assert out["trace"][-1]["result"]["code"] == "SAVE_FAILED"
    assert out["spent"] == state["spent"]


def test_replanning_invalidates_content_but_retains_actionable_failure_feedback(env):
    env[3]["scenario"] = "quality_once"
    state = advance(env, lambda s: s["artifacts"].get("DE-2", {}).get("status") == "rejected")
    feedback = copy.deepcopy(state["feedback"]["DE-2"])
    plan = copy.deepcopy(state["plan"])
    plan[1]["strategy"] += "；严格纠正上次未证实的保温声明"
    out = env[2].execute(state, {"name": "revise_plan", "args": {"tasks": plan, "reason": "repair strategy after factual rejection"}})
    assert "DE-2" not in out["artifacts"]
    assert out["feedback"]["DE-2"] == feedback
    assert feedback["review"]["issues"]
    assert out["artifacts"]["DE-1"] == state["artifacts"]["DE-1"]


def test_stop_reports_authoritative_gap_not_model_invented_prices(env):
    state = advance(env, lambda s: s["quote"] is not None)
    state["brief"]["budget_units"] = 10
    action = {"name": "stop", "args": {"reason": "模型错误建议：只需14单位即可完成"}}
    state["decision"] = action
    out = env[2].execute(state, action)
    assert "最低完成预计总费用 35" in out["reason"]
    assert "缺口 25" in out["reason"]
    assert "14" not in out["reason"]
    assert "14" in out["trace"][-1]["decision_reason"]


def test_markdown_failure_cannot_publish_completed_manifest(env, monkeypatch):
    import json
    from content_agent.storage import atomic_text as real_write
    state = advance(env, lambda s: len(s["artifacts"]) == 4 and all(a["status"] == "approved" for a in s["artifacts"].values()))
    md_calls = []
    def fail_second_markdown(path, text):
        if path.suffix == ".md":
            md_calls.append(1)
            if len(md_calls) == 2:
                raise OSError("disk unavailable during final Markdown write")
        real_write(path, text)
    monkeypatch.setattr("content_agent.tools.atomic_text", fail_second_markdown)
    out = env[2].execute(state, {"name": "save_campaign", "args": {"reason": "save"}})
    assert out["status"] != "completed"
    p = env[0].root / "outputs" / state["task_id"] / "campaign.json"
    assert not p.exists() or json.loads(p.read_text())["status"] != "completed"
