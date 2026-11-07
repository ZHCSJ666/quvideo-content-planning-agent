import hashlib
import pytest
from pydantic import ValidationError
from content_agent.domain import Brief, Script, VideoTask, asset_file, load_data, validate_plan, script_errors


def test_actual_assets_match_metadata():
    for asset in load_data("assets.json"):
        path = asset_file(asset)
        assert path.exists()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"]
        assert b"<svg" in path.read_bytes()


@pytest.mark.parametrize("patch", [{"budget_units": -1}, {"deadline_hours": 0}, {"deadline_hours": float("nan")}, {"markets": {"DE": 0, "US": 2}}])
def test_invalid_constraints_rejected(patch):
    with pytest.raises(ValidationError):
        Brief(theme="cup", **patch)


def test_missing_constraints_are_representable_for_clarification():
    assert Brief(theme="cup").budget_units is None


def test_cannot_silently_reduce_scope():
    task = VideoTask(id="DE-1", market="DE", angle="Commuter cup", audience="commuters", strategy="Show product details in daily commute", asset_ids=["cup-hero"])
    with pytest.raises(ValueError, match="preserve"):
        validate_plan([task], Brief(theme="cup"), load_data("assets.json"))


def test_grounding_rules_catch_inferred_benefits_but_not_negative_rationale():
    from content_agent.providers import OfflineProvider
    task = {"id": "US-1", "market": "US", "audience": "demo", "angle": "demo angle", "asset_ids": ["cup-hero"]}
    script = Script.model_validate(OfflineProvider().generate(task, {}))
    script.localization_rationale = "Synthetic brief; avoid the unsupported claim lightweight."
    assert not script_errors(script, task, load_data("product.json"))
    script.shots[0].voiceover = "Lightweight and durable for every adventure."
    errors = script_errors(script, task, load_data("product.json"))
    assert any("lightweight" in e for e in errors)
    assert any("durable" in e for e in errors)
