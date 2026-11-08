"""Two fresh, serial live runs. No resume, repair, operator decisions or mock fallback."""
import argparse
import copy
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from content_agent.domain import Brief, ROOT, canonical
from content_agent.evaluation import audit_autonomy
from content_agent.providers import LiveProvider, config
from content_agent.service import Service
from content_agent.storage import atomic_text


def save(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2))


def source_manifest():
    files = sorted([*ROOT.glob("src/**/*.py"), *[p for p in (ROOT / "data").rglob("*") if p.is_file()], ROOT / "pyproject.toml", ROOT / "requirements.lock", Path(__file__).resolve()])
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    return {"sha256": hashlib.sha256(canonical(hashes).encode()).hexdigest(), "files": hashes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", default="autonomy-" + uuid.uuid4().hex[:8])
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,43}", args.batch):
        parser.error("batch ID must be 1–44 ASCII letters, digits, underscores or hyphens")
    # Freeze credentials/config in this process; never record the key or endpoint.
    base, key, model = config()
    os.environ.update(CONTENT_API_BASE=base, CONTENT_API_KEY=key, CONTENT_MODEL=model)
    expected_model = LiveProvider().info
    source = source_manifest()
    destination = ROOT / "examples/autonomy" / args.batch
    runtime = ROOT / ".runtime/autonomy" / args.batch
    if destination.exists() or runtime.exists():
        parser.error("A batch must be fresh; existing evidence is never resumed or overwritten")
    service = Service(runtime)
    service.validate_id(args.batch)
    destination.mkdir(parents=True)
    manifest = {"batch": args.batch, "started_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(), "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "source": source, "model_config": expected_model, "protocol": "Fresh tasks, same input/model/source, serial execution, fault scenario hidden from planner, no resume/repair/config changes. All attempts retained; only a passing pair is published to the primary live gallery."}
    save(destination / "manifest.json", manifest)
    brief = Brief.model_validate(json.loads((ROOT / "examples/inputs/normal.json").read_text())).model_dump()
    records = []
    try:
        for name, scenario in [("transient", "script_once"), ("persistent", "persistent_failure")]:
            tid = args.batch + "-" + name
            snapshots = {}
            captured = False

            def progress(event):
                nonlocal captured
                if event.get("kind") != "tool":
                    return
                if event["result"].get("code") == "SERVICE_UNAVAILABLE" and not captured:
                    captured = True
                    current = service.store.get(tid)
                    snapshots.update({t["id"]: {"task": copy.deepcopy(t), "artifact": copy.deepcopy(current["artifacts"][t["id"]])} for t in current["plan"] if current["artifacts"].get(t["id"], {}).get("status") == "approved"})
                print(json.dumps({"case": name, "step": event["step"], "tool": event["tool"], "ok": event["result"].get("ok"), "approved": event["result"].get("approved"), "code": event["result"].get("code"), "spent": event["after"]["spent"], "reason": event["decision_reason"]}, ensure_ascii=False), flush=True)

            result = service.run(tid, brief, mode="live", scenario=scenario, on_event=progress)
            case_dir = destination / name
            service.export(tid, case_dir)
            audit = audit_autonomy(result, scenario, brief, snapshots, expected_model)
            audit["checks"]["source_unchanged"] = source_manifest() == source
            package_path = case_dir / "campaign.json"
            if result["saved"]:
                package = json.loads(package_path.read_text()) if package_path.exists() else {}
                audit["checks"]["export_matches_state"] = all(package.get(k) == result[k] for k in ("task_id", "status", "spent", "artifacts", "plan")) and (case_dir / "campaign.md").is_file()
            else:
                audit["checks"]["export_matches_state"] = not package_path.exists() and not (case_dir / "campaign.md").exists()
            audit["passed"] = all(audit["checks"].values())
            save(case_dir / "before-failure.json", snapshots)
            save(case_dir / "audit.json", audit)
            record = {"case": "autonomous-" + name, "task_id": tid, "status": result["status"], "spent": result["spent"], "calls": result["calls"], "model_calls": result["model_calls"], "model_usage": result["model_usage"], "resume_count": result["resume_count"], "passed": audit["passed"], "recovery_mode": "autonomous_within_one_run", "preserved_approved_tasks": audit["preserved_tasks"], "source_sha256": source["sha256"], "evidence": str(case_dir.relative_to(ROOT)), "failed_checks": [k for k, passed in audit["checks"].items() if not passed]}
            records.append(record)
            save(destination / "evaluation.json", {"mode": "live", "results": records})
            print(json.dumps(record, ensure_ascii=False), flush=True)
    finally:
        service.close()
    passed = len(records) == 2 and all(r["passed"] for r in records)
    manifest.update(finished_at=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(), passed=passed)
    save(destination / "manifest.json", manifest)
    index_path = ROOT / "examples/autonomy/index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"batches": []}
    index["batches"].append({"batch": args.batch, "passed": passed, "evaluation": str((destination / "evaluation.json").relative_to(ROOT))})
    save(index_path, index)
    if passed:
        for record in records:
            target = ROOT / "examples/live" / record["case"]
            if target.exists():
                old = json.loads((target / "result.json").read_text())["task_id"]
                archive = ROOT / "examples/history" / (record["case"] + "-" + old)
                archive.parent.mkdir(parents=True, exist_ok=True)
                target.rename(archive)
            shutil.copytree(ROOT / record["evidence"], target)
            save(target / "manifest.json", manifest)
        evaluation = ROOT / "examples/live/evaluation.json"
        existing = json.loads(evaluation.read_text()) if evaluation.exists() else {"mode": "live", "results": []}
        existing["results"] = [r for r in existing["results"] if r["case"] not in {r["case"] for r in records}] + records
        save(evaluation, existing)
        save(ROOT / "examples/autonomy/latest.json", {"batch": args.batch, "evaluation": str((destination / "evaluation.json").relative_to(ROOT))})
    else:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
