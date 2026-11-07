"""Generate actual offline transcripts and assertions; live runs use CLI explicitly."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from content_agent.domain import ROOT
from content_agent.service import Service


def main():
    results = []
    fixtures = ROOT / "examples" / "inputs"
    def brief(name):
        return json.loads((fixtures / (name + ".json")).read_text())
    with TemporaryDirectory(dir=ROOT / ".runtime", prefix="evaluation-") as tmp:
        service = Service(tmp)
        for name, input_name, scenario, expected in [
            ("normal", "normal", "normal", "completed"),
            ("budget_replan", "budget_tight", "normal", "completed"),
            ("budget_impossible", "impossible", "normal", "incomplete"),
            ("deadline_replan", "deadline_tight", "normal", "completed"),
            ("script_failure", "normal", "script_once", "completed"),
            ("persistent_failure", "normal", "persistent_failure", "incomplete"),
            ("asset_missing", "normal", "asset_missing", "completed"),
            ("quality_failure", "normal", "quality_once", "completed"),
            ("save_failure", "normal", "save_once", "completed"),
            ("step_limit", "step_limit", "normal", "incomplete"),
            ("missing_budget", "missing_budget", "normal", "waiting_input"),
            ("missing_deadline", "missing_deadline", "normal", "waiting_input"),
        ]:
            r = service.run(name, brief(input_name), scenario=scenario)
            assert r["status"] == expected, (name, r["reason"])
            service.export(name, ROOT / "examples" / "offline" / name)
            results.append({"case": name, "expected": expected, "actual": r["status"], "spent": r["spent"], "calls": r["calls"], "passed": True})
        before = service.store.get("normal")
        repeated = service.run("normal", brief("normal"))
        assert before == repeated
        results.append({"case": "duplicate", "passed": True, "additional_cost": 0, "additional_calls": 0})
        for name, patch, repair in [("missing_budget", {"budget_units": 100}, False), ("missing_deadline", {"deadline_hours": 48}, False), ("persistent_failure", {}, True)]:
            r = service.resume(name, patch, repair=repair)
            assert r["status"] == "completed", r["reason"]
            service.export(name, ROOT / "examples" / "offline" / (name + "_resumed"))
            results.append({"case": name + "_resumed", "actual": r["status"], "passed": True})
        service.close()
    (ROOT / "examples" / "offline" / "evaluation.json").write_text(json.dumps({"mode": "offline_mock", "claim": "workflow validation only; not model decision evidence", "results": results}, ensure_ascii=False, indent=2))
    print(f"{len(results)} offline acceptance cases passed")


if __name__ == "__main__":
    (ROOT / ".runtime").mkdir(exist_ok=True)
    main()
