import argparse
import json
from pathlib import Path

from .service import SCENARIOS, Service


def main():
    p = argparse.ArgumentParser(description="跨市场内容规划 Agent · live / explicit offline mock")
    p.add_argument("--state-dir", type=Path, help="Local durable state directory")
    sub = p.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Create task; identical ID and request return existing result without execution")
    run.add_argument("--id", required=True)
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--mode", choices=["offline", "live"], default="offline")
    run.add_argument("--scenario", choices=SCENARIOS, default="normal")
    resume = sub.add_parser("resume", help="Resume missing information or failed task")
    resume.add_argument("--id", required=True)
    resume.add_argument("--budget", type=int)
    resume.add_argument("--deadline-hours", type=float)
    resume.add_argument("--repair", action="store_true", help="Explicitly clear injected failure and reset failed attempt counters")
    resume.add_argument("--additional-calls", type=int, default=20)
    resume.add_argument("--wait-minutes", type=int, default=0, help="Advance simulated clock for time spent waiting")
    show = sub.add_parser("show")
    show.add_argument("--id", required=True)
    export = sub.add_parser("export")
    export.add_argument("--id", required=True)
    export.add_argument("--output", type=Path, required=True)
    sub.add_parser("list")
    args = p.parse_args()
    service = Service(args.state_dir)

    def progress(event):
        if event.get("kind") == "tool":
            observation = {k: v for k, v in event["result"].items() if k in {"code", "approved", "feasible", "message", "projected_total", "budget_gap", "retained", "invalidated", "path", "status"}}
            print(json.dumps({"step": event["step"], "tool": event["tool"], "reason": event["decision_reason"], "ok": event["result"]["ok"], "observation": observation, "cost": event["cost"], "spent": event["after"]["spent"]}, ensure_ascii=False), flush=True)

    try:
        if args.command == "run":
            result = service.run(args.id, json.loads(args.input.read_text()), args.mode, args.scenario, progress)
        elif args.command == "resume":
            patch = {}
            if args.budget is not None:
                patch["budget_units"] = args.budget
            if args.deadline_hours is not None:
                patch["deadline_hours"] = args.deadline_hours
            result = service.resume(args.id, patch, repair=args.repair, additional_calls=args.additional_calls, wait_minutes=args.wait_minutes, on_event=progress)
        elif args.command == "show":
            result = service.store.get(args.id)
            if result is None:
                raise ValueError("Task not found")
        elif args.command == "export":
            print(service.export(args.id, args.output))
            return 0
        else:
            print(json.dumps([{k: s[k] for k in ("task_id", "status", "mode", "spent", "calls")} for s in service.store.list_runs()], ensure_ascii=False, indent=2))
            return 0
        print(json.dumps({k: result[k] for k in ("task_id", "status", "reason", "mode", "spent", "elapsed_minutes", "calls", "saved")}, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "completed" else 2
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 1
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
