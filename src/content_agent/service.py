"""The only application service used by CLI, tests and Streamlit."""
import copy
import json
import re
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from .agent import build_graph
from .domain import Brief, ROOT, initial_state
from .providers import LiveProvider, OfflineProvider
from .storage import Store, atomic_text

SCENARIOS = ("normal", "script_once", "persistent_failure", "asset_missing", "quality_once", "save_once")


class Service:
    def __init__(self, root=None):
        self.root = Path(root) if root else ROOT / ".runtime"
        self.store = Store(self.root)

    def close(self):
        self.store.close()

    def validate_id(self, task_id):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", task_id):
            raise ValueError("Task ID must use 1–64 ASCII letters, digits, underscores or hyphens")

    def run(self, task_id, brief, mode="offline", scenario="normal", on_event=None):
        self.validate_id(task_id)
        if mode not in {"live", "offline"} or scenario not in SCENARIOS:
            raise ValueError("Unsupported mode or fault scenario")
        state = initial_state(Brief.model_validate(brief), task_id, mode, scenario)
        with self.store.lock(task_id):
            state, created = self.store.create(state)
            if not created:
                return state  # explicit resume is required to cause more work
            return self._invoke(state, {"run": state}, on_event)

    def resume(self, task_id, patch=None, *, repair=False, additional_calls=20, wait_minutes=0, on_event=None):
        self.validate_id(task_id)
        if not 1 <= additional_calls <= 100 or type(wait_minutes) is not int or wait_minutes < 0:
            raise ValueError("additional_calls must be 1–100 and wait_minutes must be a nonnegative integer")
        patch = patch or {}
        if set(patch) - {"budget_units", "deadline_hours"}:
            raise ValueError("Only explicitly supplied budget/deadline changes are supported on resume")
        with self.store.lock(task_id):
            state = self.store.get(task_id)
            if not state:
                raise ValueError("Task not found")
            if state["status"] == "completed":
                if patch or repair or wait_minutes:
                    raise ValueError("Completed task is immutable; create a new task for changed requirements")
                return state
            state["brief"] = Brief.model_validate({**state["brief"], **patch}).model_dump()
            state["elapsed_minutes"] += wait_minutes
            state["resume_count"] += 1
            state["trace"].append({"kind": "resume", "patch": patch, "repair": repair, "wait_minutes": wait_minutes, "reason": "Explicit operator resume; spent cost and valid artifacts retained"})
            state["brief"]["max_calls"] = min(1000, max(state["brief"]["max_calls"], state["calls"] + additional_calls))
            if repair:
                state["scenario"] = "normal"
                state["attempts"] = {k: v for k, v in state["attempts"].items() if state["artifacts"].get(k, {}).get("status") == "approved"}
            was_waiting = state["status"] == "waiting_input"
            state["status"], state["reason"], state["quote"] = "running", "", None
            self.store.save(state)
            return self._invoke(state, {"run": state}, on_event, resume_waiting=was_waiting, patch=patch)

    def _invoke(self, state, graph_input, on_event, resume_waiting=False, patch=None):
        try:
            provider = LiveProvider() if state["mode"] == "live" else OfflineProvider()
            state["model_config"] = getattr(provider, "info", {"provider": "offline_mock"})
            with SqliteSaver.from_conn_string(str(self.root / "checkpoints.sqlite")) as saver:
                graph = build_graph(self.store, provider, saver)
                config = {"configurable": {"thread_id": state["task_id"]}, "recursion_limit": 2 * state["brief"]["max_calls"] + 10}
                if resume_waiting:
                    # Update the pre-prepare checkpoint, then resume the original interrupt.
                    graph.update_state(config, {"run": state})
                    graph_input = Command(resume=patch)
                previous_count = len(state["trace"])
                for update in graph.stream(graph_input, config=config, stream_mode="values"):
                    run = update.get("run")
                    if run and on_event:
                        for event in run["trace"][previous_count:]:
                            on_event(event)
                        previous_count = len(run["trace"])
        except KeyboardInterrupt:
            current = self.store.get(state["task_id"]) or state
            current["status"] = "incomplete"
            current["reason"] = "Interrupted by operator; completed receipts preserved, use resume to continue"
            current["trace"].append({"kind": "operator_interrupted", "reason": current["reason"]})
            self.store.save(current)
        except Exception as exc:
            current = self.store.get(state["task_id"]) or state
            current["status"] = "incomplete"
            current["reason"] = "Runtime interrupted: " + type(exc).__name__
            current["trace"].append({"kind": "runtime_error", "reason": current["reason"]})
            self.store.save(current)
        current = self.store.get(state["task_id"])
        self.export(current["task_id"], self.root / "runs" / current["task_id"])
        return current

    def export(self, task_id, destination):
        state = self.store.get(task_id)
        if not state:
            raise ValueError("Task not found")
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        atomic_text(destination / "input.json", json.dumps(state["brief"], ensure_ascii=False, indent=2))
        atomic_text(destination / "result.json", json.dumps(state, ensure_ascii=False, indent=2))
        atomic_text(destination / "trace.jsonl", "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in state["trace"]))
        for suffix in (".json", ".md"):
            target = destination / ("campaign" + suffix)
            source = (self.root / state["saved"]).with_suffix(suffix) if state["saved"] else None
            if source and source.exists():
                atomic_text(target, source.read_text())
            elif target.exists():
                # Reusing an export directory must not attach a previous task's
                # successful package to a new incomplete result.
                target.unlink()
        return destination
