"""A checkpointed observe/decide/act loop; routing does not choose business tools."""
import copy
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .domain import Brief
from .tools import ToolRunner


class GraphState(TypedDict):
    run: dict


def build_graph(store, provider, checkpointer):
    runner = ToolRunner(store, provider)

    def prepare(graph_state):
        state = copy.deepcopy(graph_state["run"])
        missing = [k for k in ("budget_units", "deadline_hours") if state["brief"].get(k) is None]
        while missing:
            state["status"] = "waiting_input"
            state["reason"] = "Missing required constraints: " + ", ".join(missing)
            previous = state["trace"][-1] if state["trace"] else {}
            if previous.get("kind") != "clarification" or previous.get("missing") != missing:
                state["trace"].append({"kind": "clarification", "missing": missing, "status": "waiting_input", "reason": state["reason"]})
            store.save(state)
            patch = interrupt({"task_id": state["task_id"], "missing": missing, "message": state["reason"]})
            if not isinstance(patch, dict) or set(patch) - {"budget_units", "deadline_hours"}:
                raise ValueError("Clarification accepts only budget_units and deadline_hours")
            state["brief"] = Brief.model_validate({**state["brief"], **patch}).model_dump()
            missing = [k for k in ("budget_units", "deadline_hours") if state["brief"].get(k) is None]
        state["status"], state["reason"] = "running", ""
        store.save(state)
        return {"run": state}

    def decide(graph_state):
        state = copy.deepcopy(graph_state["run"])
        if state["calls"] >= state["brief"]["max_calls"]:
            state["status"], state["reason"] = "incomplete", "Tool call limit reached; completed artifacts preserved"
            state["trace"].append({"kind": "limit", "reason": state["reason"], "calls": state["calls"]})
        else:
            try:
                state["decision"] = provider.decide(state)
            except Exception as exc:
                state["status"] = "incomplete"
                state["reason"] = "Model decision unavailable or invalid: " + type(exc).__name__
                state["trace"].append({"kind": "model_error", "reason": state["reason"], "actor": provider.label})
        store.save(state)
        return {"run": state}

    def execute(graph_state):
        state = runner.execute(graph_state["run"], graph_state["run"]["decision"])
        return {"run": state}

    def route(graph_state):
        return "decide" if graph_state["run"]["status"] == "running" else END

    graph = StateGraph(GraphState)
    graph.add_node("prepare", prepare)
    graph.add_node("decide", decide)
    graph.add_node("execute", execute)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "decide")
    graph.add_conditional_edges("decide", lambda s: "execute" if s["run"]["status"] == "running" else END)
    graph.add_conditional_edges("execute", route)
    return graph.compile(checkpointer=checkpointer)
