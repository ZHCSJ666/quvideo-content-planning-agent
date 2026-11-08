"""Independently check exported receipts, ledgers and delivered artifact contracts."""
import json
import hashlib

from content_agent.domain import Brief, ROOT, Script, VideoTask, canonical, load_data, script_errors, validate_plan
from content_agent.evaluation import audit_autonomy


def main():
    results = []
    for mode in ("live", "offline"):
        for path in sorted((ROOT / "examples" / mode).glob("*/result.json")):
            state = json.loads(path.read_text())
            trace = [json.loads(line) for line in path.with_name("trace.jsonl").read_text().splitlines()]
            assert trace == state["trace"], path
            events = [e for e in trace if e.get("kind") == "tool"]
            assert len(events) == state["calls"], path
            assert sum(e["cost"] for e in events) == state["spent"], path
            waits = sum(e.get("wait_minutes", 0) for e in trace if e.get("kind") == "resume")
            assert sum(e["minutes"] for e in events) + waits == state["elapsed_minutes"], path
            assert [e["step"] for e in events] == list(range(1, len(events) + 1)), path
            budget = state["brief"]["budget_units"]
            if budget is not None:
                assert state["spent"] <= budget, path
            if state["status"] == "completed":
                assert state["saved"], path
                validate_plan([VideoTask.model_validate(t) for t in state["plan"]], Brief.model_validate(state["brief"]), state["catalog"])
                for task in state["plan"]:
                    artifact = state["artifacts"][task["id"]]
                    assert artifact["status"] == "approved", path
                    assert not script_errors(Script.model_validate(artifact["script"]), task, load_data("product.json")), path
                package = json.loads(path.with_name("campaign.json").read_text())
                for key in ("task_id", "status", "spent", "elapsed_minutes", "plan", "artifacts"):
                    assert package[key] == state[key], (path, key)
                assert path.with_name("campaign.md").is_file(), path
                assert state["elapsed_minutes"] <= state["brief"]["deadline_hours"] * 60, path
            else:
                assert state["saved"] is None, path
                assert not path.with_name("campaign.json").exists(), path
            if path.parent.name in {"autonomous-transient", "autonomous-persistent"}:
                manifest = json.loads(path.with_name("manifest.json").read_text())
                baseline = json.loads(path.with_name("before-failure.json").read_text())
                scenario = "script_once" if path.parent.name == "autonomous-transient" else "persistent_failure"
                checked = audit_autonomy(state, scenario, json.loads(path.with_name("input.json").read_text()), baseline, manifest["model_config"])
                assert checked["passed"], (path, checked["checks"])
                recorded = json.loads(path.with_name("audit.json").read_text())
                assert recorded["passed"] and all(recorded["checks"].values()), path
                assert all(recorded["checks"].get(key) == value for key, value in checked["checks"].items()), path
                assert hashlib.sha256(canonical(manifest["source"]["files"]).encode()).hexdigest() == manifest["source"]["sha256"], path
                for name, expected in manifest["source"]["files"].items():
                    source = (ROOT / name).resolve()
                    assert source.is_relative_to(ROOT), name
                    assert hashlib.sha256(source.read_bytes()).hexdigest() == expected, (path, name)
            results.append({"case": str(path.parent.relative_to(ROOT / "examples")), "status": state["status"], "passed": True})
    report = {"scope": "Export consistency, sequential receipts, simulated ledger, completed artifact contracts. Autonomous cases also recheck fixed model/source, no manual intervention, preserved prior work, and model-selected termination. Does not prove natural language quality or marketing performance.", "results": results}
    (ROOT / "examples/evidence-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"{len(results)} exported cases passed ledger and artifact audit")


if __name__ == "__main__":
    main()
