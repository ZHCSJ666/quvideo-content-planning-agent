"""Serial real-model acceptance. Requires credentials; no automatic mock fallback."""
import argparse
import json
import time
import uuid
import shutil

from content_agent.domain import ROOT
from content_agent.service import Service


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prefix", default="review-" + uuid.uuid4().hex[:8])
    p.add_argument("--cases", nargs="+", choices=["normal", "script-failure", "budget-tight"], help="Rerun only selected cases; retain other evidence and archive replaced runs")
    args = p.parse_args()
    service = Service()
    evaluation = ROOT / "examples/live/evaluation.json"
    results = json.loads(evaluation.read_text())["results"] if args.cases and evaluation.exists() else []
    if args.cases:
        results = [r for r in results if r["case"] not in args.cases]
    try:
        for suffix, input_name, scenario in [
            ("normal", "normal", "normal"),
            ("script-failure", "normal", "script_once"),
            ("budget-tight", "budget_tight", "normal"),
        ]:
            if args.cases and suffix not in args.cases:
                continue
            task_id = f"{args.prefix}-{suffix}"
            brief = json.loads((ROOT / "examples" / "inputs" / (input_name + ".json")).read_text())
            existing = service.store.get(task_id)
            # If this exact acceptance task is already running in a CLI, wait for its receipt.
            deadline = time.monotonic() + 1200
            while existing and existing["status"] == "running" and time.monotonic() < deadline:
                time.sleep(2)
                existing = service.store.get(task_id)
            if existing and existing["status"] == "running":
                raise RuntimeError("Existing task still running; inspect it before retrying")
            def progress(e):
                if e.get("kind") == "tool":
                    print(json.dumps({"case": suffix, "step": e["step"], "tool": e["tool"], "reason": e["decision_reason"], "ok": e["result"]["ok"], "spent": e["after"]["spent"]}, ensure_ascii=False), flush=True)
            r = service.run(task_id, brief, mode="live", scenario=scenario, on_event=progress)
            destination = ROOT / "examples" / "live" / suffix
            if (destination / "result.json").exists():
                old_id = json.loads((destination / "result.json").read_text())["task_id"]
                service.validate_id(old_id)
                if old_id != task_id:
                    shutil.copytree(destination, ROOT / "examples/history" / f"{suffix}-{old_id}", dirs_exist_ok=True)
                    # Remove stale audit metadata, not historical evidence.
                    audit = destination / "secondary-audit.json"
                    if audit.exists():
                        audit.unlink()
            service.export(task_id, destination)
            record = {"case": suffix, "task_id": task_id, "status": r["status"], "spent": r["spent"], "calls": r["calls"], "model_calls": r["model_calls"], "model_usage": r["model_usage"], "passed": r["status"] == "completed"}
            record["resume_count"] = r["resume_count"]
            record["tool_actors"] = sorted({e["actor"] for e in r["trace"] if e.get("kind") == "tool"})
            if suffix == "script-failure":
                record["injected_failure_observed"] = any(e.get("result", {}).get("code") == "SERVICE_UNAVAILABLE" for e in r["trace"])
                record["passed"] = record["passed"] and record["injected_failure_observed"]
                record["recovery_mode"] = "explicit_operator_resume" if r["resume_count"] else "autonomous_within_one_run"
                failures = [e["step"] for e in r["trace"] if e.get("result", {}).get("code") == "SERVICE_UNAVAILABLE"]
                before_failure = [e["result"]["task_id"] for e in r["trace"] if failures and e.get("tool") == "review_content" and e["step"] < failures[0] and e.get("result", {}).get("approved")]
                record["preserved_approved_tasks"] = [tid for tid in before_failure if not any(e.get("tool") == "generate_script" and e["step"] > failures[0] and e["arguments"].get("task_id") == tid for e in r["trace"])]
                record["passed"] = record["passed"] and bool(record["preserved_approved_tasks"])
            if suffix == "budget-tight":
                record["infeasible_quote_observed"] = any(e.get("tool") == "estimate_cost" and e.get("result", {}).get("feasible") is False for e in r["trace"])
                gap = (r.get("last_result") or {}).get("gap") or {}
                record["acceptance_rule"] = "Observe infeasible quote and replan; complete within budget OR explicitly stop when the cheapest remaining completion cannot fit. Never mark partial content complete."
                record["minimum_budget_gap_at_stop"] = gap.get("minimum_budget_gap")
                legitimate_stop = r["status"] == "incomplete" and gap.get("minimum_budget_gap", 0) > 0 and r["saved"] is None
                record["passed"] = record["infeasible_quote_observed"] and r["plan_version"] >= 2 and r["spent"] <= r["brief"]["budget_units"] and (record["passed"] or legitimate_stop)
            results.append(record)
            print(json.dumps(record, ensure_ascii=False), flush=True)
            (ROOT / "examples" / "live" / "evaluation.json").write_text(json.dumps({"mode": "live", "results": results}, ensure_ascii=False, indent=2))
        if args.cases:
            if not all(r["passed"] for r in results if r["case"] in args.cases):
                raise SystemExit(2)
            return
        # Missing data is a pre-model pause, clearly distinguished from decision evidence.
        task_id = f"{args.prefix}-missing-budget"
        brief = json.loads((ROOT / "examples" / "inputs" / "missing_budget.json").read_text())
        r = service.run(task_id, brief, mode="live")
        service.export(task_id, ROOT / "examples" / "live" / "missing-budget")
        results.append({"case": "missing-budget", "status": r["status"], "model_calls": r["model_calls"], "passed": r["status"] == "waiting_input"})
        # Re-executing a completed request must be a no-op even in live mode.
        task_id = f"{args.prefix}-normal"
        before = service.store.get(task_id)
        same = service.run(task_id, json.loads((ROOT / "examples/inputs/normal.json").read_text()), mode="live")
        assert same == before
        results.append({"case": "duplicate", "passed": True, "additional_calls": 0, "additional_cost": 0})
        (ROOT / "examples" / "live" / "evaluation.json").write_text(json.dumps({"mode": "live", "results": results}, ensure_ascii=False, indent=2))
        if not all(r["passed"] for r in results):
            raise SystemExit(2)
    finally:
        service.close()


if __name__ == "__main__":
    main()
