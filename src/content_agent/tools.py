"""Business tools. Every execution produces a structured receipt, including failure."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from .domain import Brief, ROOT, Review, Script, VideoTask, asset_file, digest, load_data, script_errors, validate_plan
from .storage import Store, atomic_text


def schema(name, description, properties=None, required=()):
    properties = dict(properties or {})
    properties["reason"] = {"type": "string", "description": "Brief decision rationale grounded in the last observation; no private chain of thought."}
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": list(required) + ["reason"], "additionalProperties": False}}}


TOOL_SCHEMAS = [
    schema("load_context", "Read authoritative synthetic product facts, market briefs and cost/time rules."),
    schema("search_assets", "List actual local assets for a market. Use query='' for initial inventory. Optional query is an English TAG filter, NOT semantic search. On zero matches retry with query=''; never invent asset IDs.", {"market": {"type": "string", "enum": ["DE", "US"]}, "query": {"type": "string"}}, ["market"]),
    schema("revise_plan", "Create or replace the FULL plan, preserving required counts. Unchanged completed tasks are retained. Changed tasks invalidate only their dependent artifacts. Estimate after every revision.", {"tasks": {"type": "array", "items": VideoTask.model_json_schema()}}, ["tasks"]),
    schema("estimate_cost", "Get remaining cost/time, sunk costs, feasibility and lower-cost service alternatives. Pure quotation; does not spend funds."),
    schema("generate_script", "Produce a real 20-second localized script and storyboard for one planned task. Requires a feasible current quote. Uses selected service tier and assets.", {"task_id": {"type": "string"}}, ["task_id"]),
    schema("review_content", "Check facts, storyboard, selected assets, language and market fit. Reject or approve one generated script.", {"task_id": {"type": "string"}}, ["task_id"]),
    schema("save_campaign", "Save final campaign ONLY after every requested video is reviewed and all constraints pass."),
    schema("stop", "Return an explicit incomplete result when no feasible recovery remains. Explain completed parts, blocker and what would enable recovery."),
]


class ToolError(Exception):
    def __init__(self, code, message, *, details=None):
        self.code, self.message, self.details = code, message, details or {}
        super().__init__(message)


def current_artifact(state, task):
    a = state["artifacts"].get(task["id"])
    return a if a and a["task_hash"] == digest(task) else None


def estimate(state):
    rules = load_data("rules.json")
    cost = minutes = 0
    breakdown = []
    for task in state["plan"]:
        a = current_artifact(state, task)
        fee = duration = 0
        if not a or not a.get("script"):
            service = rules["tiers"][task["tier"]]
            fee += service["cost"]
            duration += service["minutes"]
        if not a or a.get("status") != "approved":
            fee += rules["tools"]["review_content"][0]
            duration += rules["tools"]["review_content"][1]
        cost += fee
        minutes += duration
        breakdown.append({"task_id": task["id"], "remaining_cost": fee, "remaining_minutes": duration})
    if not state["saved"]:
        cost += rules["tools"]["save_campaign"][0]
        minutes += rules["tools"]["save_campaign"][1]
    budget = state["brief"]["budget_units"]
    limit = state["brief"]["deadline_hours"]
    total = state["spent"] + cost
    finish = state["elapsed_minutes"] + minutes
    minimum_cost = 0
    minimum_minutes = 0
    for task in state["plan"]:
        a = current_artifact(state, task)
        if not a or not a.get("script"):
            minimum_cost += rules["tiers"]["economy"]["cost"]
            minimum_minutes += rules["tiers"]["economy"]["minutes"]
        if not a or a.get("status") != "approved":
            minimum_cost += rules["tools"]["review_content"][0]
            minimum_minutes += rules["tools"]["review_content"][1]
    if not state["saved"]:
        minimum_cost += 1
        minimum_minutes += 1
    return {"spent": state["spent"], "remaining_cost": cost, "projected_total": total,
            "elapsed_minutes": state["elapsed_minutes"], "remaining_minutes": minutes, "projected_finish_minutes": finish,
            "budget_gap": max(0, total - budget) if budget is not None else None,
            "time_gap_minutes": max(0, finish - int(limit * 60)) if limit is not None else None,
            "feasible": bool(state["plan"]) and budget is not None and limit is not None and total <= budget and finish <= int(limit * 60),
            "minimum_projected_total": state["spent"] + minimum_cost,
            "minimum_budget_gap": max(0, state["spent"] + minimum_cost - budget) if budget is not None else None,
            "minimum_finish_minutes": state["elapsed_minutes"] + minimum_minutes,
            "plan_version": state["plan_version"], "breakdown": breakdown, "alternatives": rules["tiers"]}


class ToolRunner:
    def __init__(self, store: Store, provider):
        self.store, self.provider = store, provider
        self.rules = load_data("rules.json")

    def execute(self, state, action):
        op_id = f"{state['task_id']}:{state['calls'] + 1}"
        previous = self.store.receipt(op_id, action)
        if previous:
            return previous
        state = copy.deepcopy(state)
        before = {"spent": state["spent"], "elapsed_minutes": state["elapsed_minutes"]}
        state["calls"] += 1
        name = action.get("name", "")
        args = action.get("args", {})
        reason = args.get("reason", "")
        cost = minutes = 0
        try:
            if name not in {s["function"]["name"] for s in TOOL_SCHEMAS}:
                raise ToolError("UNKNOWN_TOOL", "Choose one of the published tools")
            if not isinstance(reason, str) or not reason.strip():
                raise ToolError("INVALID_ARGUMENTS", "A concise decision reason is required")
            fn = next(s["function"] for s in TOOL_SCHEMAS if s["function"]["name"] == name)
            if set(args) - set(fn["parameters"]["properties"]) or not set(fn["parameters"]["required"]).issubset(args):
                raise ToolError("INVALID_ARGUMENTS", "Arguments do not match the tool contract")
            if name == "generate_script":
                task = self.task(state, args["task_id"])
                a = current_artifact(state, task)
                if a and a.get("status") in {"generated", "approved"}:
                    result = {"ok": True, "code": "REUSED", "task_id": task["id"], "status": a["status"]}
                else:
                    quote = estimate(state)
                    if state["quote"] is None or state["quote"]["plan_version"] != state["plan_version"]:
                        raise ToolError("ESTIMATE_REQUIRED", "Estimate this plan before spending")
                    if not quote["feasible"]:
                        raise ToolError("PLAN_INFEASIBLE", "Replan before generating", details=quote)
                    service = self.rules["tiers"][task["tier"]]
                    cost, minutes = service["cost"], service["minutes"]
                    self.guard(state, cost, minutes)
                    key = task["id"]
                    n = state["attempts"].get(key, 0) + 1
                    if n > self.rules["max_generation_attempts_per_task"]:
                        cost = minutes = 0
                        raise ToolError("ATTEMPTS_EXHAUSTED", "Task generation attempt limit reached across all plan versions. Changing tier, strategy or assets cannot reset it; stop and request explicit operator resume after repair.", details={"retryable": False, "task_id": key, "attempts": n - 1, "max_attempts": self.rules["max_generation_attempts_per_task"]})
                    state["attempts"][key] = n
                    if (state["scenario"] == "script_once" and key == "DE-2" and n == 1) or (state["scenario"] == "persistent_failure" and key == "DE-2"):
                        cost, minutes = self.rules["failure_cost"], self.rules["failure_minutes"]
                        raise ToolError("SERVICE_UNAVAILABLE", "Script service unavailable; result not created", details={"retryable": state["scenario"] != "persistent_failure", "task_id": key})
                    self.check_assets(state, task)
                    script = Script.model_validate(self.provider.generate(task, state))
                    if state["scenario"] == "quality_once" and key == "DE-2" and n == 1:
                        script.shots[0].voiceover += " 24 Stunden heiß."
                    state["artifacts"][key] = {"task_hash": digest(task), "status": "generated", "script": script.model_dump(), "review": None}
                    result = {"ok": True, "task_id": key, "script": script.model_dump(), "status": "generated"}
            else:
                cost, minutes = self.rules["tools"][name]
                # Repeated review/save is free; receipts also protect graph replay.
                if name == "review_content":
                    a = current_artifact(state, self.task(state, args["task_id"]))
                    if a and a["status"] == "approved":
                        cost = minutes = 0
                if name == "save_campaign" and state["saved"]:
                    cost = minutes = 0
                self.guard(state, cost, minutes)
                result = getattr(self, name)(state, **{k: v for k, v in args.items() if k != "reason"})
        except ToolError as exc:
            # Business rejection before an attempted execution does not charge.
            if exc.code not in {"SERVICE_UNAVAILABLE", "ASSET_UNAVAILABLE"}:
                cost = minutes = 0
            elif exc.code == "ASSET_UNAVAILABLE":
                cost = minutes = 0  # preflight, not an external service charge
            result = {"ok": False, "code": exc.code, "message": exc.message, **exc.details}
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            # Generation may have consumed the service even if its output is invalid.
            if name != "generate_script":
                cost = minutes = 0
            result = {"ok": False, "code": "INVALID_RESULT" if name == "generate_script" else "INVALID_ARGUMENTS", "message": str(exc)[:1000]}
        except Exception as exc:
            # Never print provider error bodies: they may include URLs/credentials.
            result = {"ok": False, "code": "TOOL_ERROR", "message": type(exc).__name__, "retryable": True}
            if name == "save_campaign":
                state["saved"], state["status"], state["reason"] = None, "running", ""
                cost = minutes = 0
        state["spent"] += cost
        state["elapsed_minutes"] += minutes
        event = {"step": state["calls"], "kind": "tool", "tool": name, "arguments": args,
                 "decision_reason": reason, "result": result, "cost": cost, "minutes": minutes,
                 "before": before, "after": {"spent": state["spent"], "elapsed_minutes": state["elapsed_minutes"]},
                 "plan_version": state["plan_version"], "actor": self.provider.label}
        state["trace"].append(event)
        state["last_result"] = result
        if state["saved"]:
            # Save result is verified before declaring completion; include the save charge.
            try:
                self.write_package(state)
            except OSError as exc:
                state["saved"], state["status"], state["reason"] = None, "running", ""
                state["spent"] -= cost
                state["elapsed_minutes"] -= minutes
                result = {"ok": False, "code": "SAVE_FAILED", "message": type(exc).__name__}
                state["last_result"] = result
                event.update(result=result, cost=0, minutes=0, after=dict(before))
        self.store.commit_operation(op_id, action, state)
        return state

    def guard(self, state, cost, minutes):
        b = state["brief"]
        if b["budget_units"] is None or b["deadline_hours"] is None:
            raise ToolError("MISSING_CONSTRAINTS", "Budget and deadline must be supplied")
        if cost > 0 and state["spent"] + cost > b["budget_units"]:
            raise ToolError("BUDGET_BLOCKED", "Tool would exceed remaining budget")
        if minutes > 0 and state["elapsed_minutes"] + minutes > int(b["deadline_hours"] * 60):
            raise ToolError("DEADLINE_BLOCKED", "Tool would exceed deadline")

    def task(self, state, task_id):
        for task in state["plan"]:
            if task["id"] == task_id:
                return task
        raise ToolError("UNKNOWN_TASK", "Create a valid full plan first")

    def check_assets(self, state, task):
        catalog = {a["id"]: a for a in state["catalog"]}
        missing = []
        for aid in task["asset_ids"]:
            a = catalog[aid]
            p = asset_file(a)
            if (state["scenario"] == "asset_missing" and aid == "commute") or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != a["sha256"]:
                missing.append(aid)
                a["available"] = False
        if missing:
            raise ToolError("ASSET_UNAVAILABLE", "Selected assets are missing or changed; choose other catalog assets", details={"asset_ids": missing})

    def load_context(self, state):
        state["context"] = {"product": load_data("product.json"), "markets": load_data("markets.json"), "rules": self.rules}
        return {"ok": True, **state["context"]}

    def search_assets(self, state, market, query=""):
        if market not in {"DE", "US"}:
            raise ToolError("INVALID_ARGUMENTS", "Unsupported market")
        assets = [a for a in load_data("assets.json") if market in a["markets"] and (not query or any(t in query.lower() for t in a["tags"]) or query.lower() in a["id"])]
        for a in assets:
            p = asset_file(a)
            a["available"] = p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == a["sha256"]
        by_id = {a["id"]: a for a in state["catalog"]}
        by_id.update({a["id"]: a for a in assets})
        state["catalog"] = list(by_id.values())
        if market not in state["searches"]:
            state["searches"].append(market)
        result = {"ok": True, "assets": assets, "count": len(assets), "synthetic": True}
        if not assets:
            result["hint"] = "No tag match. Retry with query='' to list this market's assets, or use a returned English tag. Do not borrow assets from an incompatible market."
            result["available_tags"] = sorted({tag for a in load_data("assets.json") if market in a["markets"] for tag in a["tags"]})
        return result

    def revise_plan(self, state, tasks):
        if not state["context"] or set(state["searches"]) != set(state["brief"]["markets"]):
            raise ToolError("CONTEXT_REQUIRED", "Read context and search both markets before planning")
        parsed = [VideoTask.model_validate(t) for t in tasks]
        validate_plan(parsed, Brief.model_validate(state["brief"]), state["catalog"])
        plan = [t.model_dump() for t in parsed]
        retained, invalidated = [], []
        for task in plan:
            a = state["artifacts"].get(task["id"])
            if a and a["task_hash"] == digest(task):
                retained.append(task["id"])
            elif a:
                invalidated.append(task["id"])
                del state["artifacts"][task["id"]]
        state["plan"] = plan
        state["plan_version"] += 1
        state["quote"] = None
        return {"ok": True, "plan_version": state["plan_version"], "plan": plan, "retained": retained, "invalidated": invalidated}

    def estimate_cost(self, state):
        if not state["plan"]:
            raise ToolError("PLAN_REQUIRED", "Create a plan first")
        state["quote"] = estimate(state)
        return {"ok": True, **state["quote"]}

    def review_content(self, state, task_id):
        task = self.task(state, task_id)
        a = current_artifact(state, task)
        if not a or not a.get("script"):
            raise ToolError("DEPENDENCY_MISSING", "Generate this script before review")
        if a["status"] == "approved":
            return {"ok": True, "code": "REUSED", "task_id": task_id, "review": a["review"]}
        self.check_assets(state, task)
        errors = script_errors(Script.model_validate(a["script"]), task, state["context"]["product"])
        if errors:
            review = Review(approved=False, language_score=1, market_fit_score=1, evidence_score=1, issues=errors, rationale="Deterministic validation failed; repair before semantic review")
        else:
            review = Review.model_validate(self.provider.review(task, a["script"], state))
        threshold = self.rules["quality_threshold"]
        approved = review.approved and not review.issues and min(review.language_score, review.market_fit_score, review.evidence_score) >= threshold
        a["status"] = "approved" if approved else "rejected"
        a["review"] = review.model_dump()
        if not approved:
            # Keep rejected content in the trace/artifact for audit, but future estimate reserves regeneration.
            a["rejected_script"] = a.pop("script")
            state.setdefault("feedback", {})[task_id] = {"review": review.model_dump(), "rejected_script": a["rejected_script"]}
        else:
            state.setdefault("feedback", {}).pop(task_id, None)
        return {"ok": True, "task_id": task_id, "approved": approved, "review": review.model_dump()}

    def save_campaign(self, state):
        if state["saved"]:
            return {"ok": True, "code": "REUSED", "path": state["saved"]}
        validate_plan([VideoTask.model_validate(t) for t in state["plan"]], Brief.model_validate(state["brief"]), state["catalog"])
        if any(not current_artifact(state, t) or current_artifact(state, t)["status"] != "approved" for t in state["plan"]):
            raise ToolError("QUALITY_GATE", "Every requested video must pass review before final save")
        for task in state["plan"]:
            self.check_assets(state, task)
        if not estimate(state)["feasible"]:
            raise ToolError("PLAN_INFEASIBLE", "Final package exceeds constraints")
        if state["scenario"] == "save_once" and not state["attempts"].get("save"):
            state["attempts"]["save"] = 1
            raise ToolError("SAVE_FAILED", "Injected local write failure; reviewed content preserved")
        path = self.store.root / "outputs" / state["task_id"] / "campaign.json"
        state["saved"] = str(path.relative_to(self.store.root))
        # Persist a package first; only then declare success. The final write includes the receipt.
        self.write_package(state)
        if not path.is_file():
            raise ToolError("SAVE_FAILED", "Output missing after write")
        state["status"] = "completed"
        state["reason"] = "All requested localized plans passed checks and were saved."
        return {"ok": True, "path": state["saved"], "videos": len(state["plan"])}

    def write_package(self, state):
        path = self.store.root / state["saved"]
        package = {k: state[k] for k in ("task_id", "brief", "mode", "status", "plan", "artifacts", "spent", "elapsed_minutes", "plan_version")}
        package["disclaimer"] = "Synthetic product/market/media; plan delivery only, no rendered video; model review is not human market validation."
        lines = [f"# {state['brief']['theme']}", "", f"模式：{state['mode']} · 成本：{state['spent']} · 模拟耗时：{state['elapsed_minutes']} 分钟", "", "任务完成状态以 campaign.json 与运行结果为准。", "", package["disclaimer"]]
        for task in state["plan"]:
            script = state["artifacts"][task["id"]]["script"]
            lines += ["", f"## {task['id']} · {script['title']}", "", f"受众：{task['audience']}", f"策略：{task['strategy']}", f"开场：{script['hook']}", f"行动引导：{script['cta']}", f"本地化依据：{script['localization_rationale']}", "", "| 时间 | 素材 | 画面 | 配音 | 屏幕文字 |", "| --- | --- | --- | --- | --- |"]
            for shot in script["shots"]:
                values = [f"{shot['start']}–{shot['end']}s", shot["asset_id"], shot["visual"], shot["voiceover"], shot["on_screen"]]
                lines.append("| " + " | ".join(str(v).replace("|", "/").replace("\n", " ") for v in values) + " |")
        atomic_text(path.with_suffix(".md"), "\n".join(lines) + "\n")
        # The primary completion manifest is written last. A Markdown failure must
        # not leave a JSON manifest that already claims completion.
        atomic_text(path, json.dumps(package, ensure_ascii=False, indent=2))

    def stop(self, state):
        state["status"] = "incomplete"
        gap = estimate(state) if state["plan"] else None
        approved = [t["id"] for t in state["plan"] if current_artifact(state, t) and current_artifact(state, t)["status"] == "approved"]
        preserved = "、".join(approved) or "无"
        # Model chooses to stop; code reports authoritative financial/status facts.
        # Raw model suggestions remain in Trace, never become an unverified quotation.
        if gap and gap["minimum_budget_gap"]:
            detail = f"已支出 {state['spent']}；最低完成预计总费用 {gap['minimum_projected_total']}，预算 {state['brief']['budget_units']}，缺口 {gap['minimum_budget_gap']}。需用户明确调整预算或范围后恢复。"
        elif gap and gap["minimum_finish_minutes"] > int(state["brief"]["deadline_hours"] * 60):
            detail = f"最低完成预计需累计 {gap['minimum_finish_minutes']} 分钟，超过截止时间 {state['brief']['deadline_hours']} 小时。需用户明确调整期限或范围后恢复。"
        elif any(n >= self.rules["max_generation_attempts_per_task"] for n in state["attempts"].values()):
            detail = "存在已达到生成尝试上限的任务；修复服务或内容问题后可显式恢复。累计费用与有效成果保留。"
        else:
            detail = "模型选择停止；当前工具结果未证明存在可完成路径。具体阻碍与模型建议见 Trace，建议中的报价须重新估算确认。"
        state["reason"] = f"未完成。已审核并保留：{preserved}。{detail}"
        return {"ok": True, "status": "incomplete", "reason": state["reason"], "gap": gap, "approved_tasks": approved}
