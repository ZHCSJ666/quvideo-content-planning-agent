"""Thin presentation layer. All execution delegates to the same Service as CLI."""
import json
import os
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st

from content_agent.domain import ROOT, asset_file, load_data
from content_agent.service import SCENARIOS, Service

st.set_page_config(page_title="Market Content Agent", page_icon="◈", layout="wide")
st.markdown("""<style>
.block-container{max-width:1300px;padding-top:2rem} h1{letter-spacing:-.035em}
[data-testid="stMetric"]{background:rgba(71,156,141,.07);border:1px solid rgba(71,156,141,.18);border-radius:12px;padding:16px}
[data-testid="stSidebar"]{border-right:1px solid rgba(128,128,128,.14)}
</style>""", unsafe_allow_html=True)

LABELS = {"load_context": "理解产品与市场", "search_assets": "检索素材", "revise_plan": "制定 / 调整计划", "estimate_cost": "检查预算与期限", "generate_script": "生成内容", "review_content": "质量审核", "save_campaign": "保存方案", "stop": "说明未完成原因"}
STATUSES = {"running": "执行中", "waiting_input": "等待补充", "completed": "已完成", "incomplete": "未完成"}
state_root = Path(os.getenv("CONTENT_STATE_DIR", str(ROOT / ".runtime")))
service = Service(state_root)


def execute(call):
    with st.status("Agent 正在执行：每次工具返回后更新", expanded=True) as status:
        def report(event):
            if event.get("kind") == "tool":
                sign = "✓" if event["result"].get("ok") else "!"
                st.write(f"{sign} {event['step']:02d} · {LABELS.get(event['tool'], event['tool'])} · 累计 {event['after']['spent']} 单位")
                st.caption(event["decision_reason"])
        result = call(report)
        status.update(label=STATUSES[result["status"]], state="complete" if result["status"] == "completed" else "error", expanded=False)
    st.session_state["active_task"] = result["task_id"]
    return result


def render(state, source=None):
    is_live = state["mode"] == "live"
    st.caption(f"{'真实模型运行' if is_live else '离线 Mock · 固定策略流程验证'} / {state['task_id']} / {STATUSES[state['status']]}")
    if not is_live:
        st.info("这份记录来自离线测试策略，用于验证流程、约束与恢复，不证明真实模型决策或创意质量。")
    st.subheader(state["brief"]["theme"])
    if state["status"] == "completed":
        st.success("全部请求的内容方案通过检查并已保存。交付对象是方案包，不是视频成片。")
    elif state["reason"]:
        st.warning(state["reason"])
    total = sum(state["brief"]["markets"].values())
    approved = sum(a["status"] == "approved" for a in state["artifacts"].values())
    cols = st.columns(4)
    cols[0].metric("审核通过", f"{approved} / {total}")
    cols[1].metric("模拟成本", f"{state['spent']} / {state['brief']['budget_units'] if state['brief']['budget_units'] is not None else '待补'}")
    cols[2].metric("模拟业务耗时", f"{state['elapsed_minutes'] / 60:.1f} h", delta=None)
    cols[3].metric("工具调用", f"{state['calls']} / {state['brief']['max_calls']}")
    st.caption(f"截止时间：{state['brief']['deadline_hours']} 模拟小时 · 计划版本：{state['plan_version']} · 恢复次数：{state['resume_count']} · 以上为任务当前状态")

    chain, plan_tab, content_tab, ledger_tab = st.tabs(["决策链路", "计划与状态", "内容方案", "账本与资料"])
    events = [e for e in state["trace"] if e.get("kind") == "tool"]
    with chain:
        st.write("从工具观察到下一步动作：展开每一步，核对模型依据、实际返回与成本变化。")
        if not state["trace"]:
            st.info("任务尚未执行工具。缺少关键约束时会在这里暂停。")
        for index, event in enumerate(state["trace"]):
            if event.get("kind") != "tool":
                with st.expander(f"系统事件 · {event.get('kind', 'event')}"):
                    st.json(event)
                continue
            outcome = event["result"]
            mark = "通过" if outcome.get("ok") else "异常"
            if outcome.get("approved") is False:
                mark = "质量未通过"
            if event["tool"] == "stop" and outcome.get("status") == "incomplete":
                mark = "主动停止 / 未完成"
            title = f"{event['step']:02d} · {LABELS.get(event['tool'], event['tool'])} · {mark} · +{event['cost']} 单位"
            with st.expander(title, expanded=not outcome.get("ok") or outcome.get("approved") is False):
                st.write(event["decision_reason"])
                a, b = st.columns(2)
                a.caption("工具参数")
                a.json(event["arguments"])
                b.caption("实际工具结果")
                b.json(outcome)
                if event["tool"] == "revise_plan" and outcome.get("ok"):
                    st.caption(f"保留成果：{outcome.get('retained', [])}；失效重做：{outcome.get('invalidated', [])}")
                if index + 1 < len(state["trace"]):
                    nxt = state["trace"][index + 1]
                    st.caption("后续动作：" + LABELS.get(nxt.get("tool"), nxt.get("kind", "")))
                st.caption(f"费用 {event['before']['spent']} → {event['after']['spent']}；模拟分钟 {event['before']['elapsed_minutes']} → {event['after']['elapsed_minutes']}")
    with plan_tab:
        if state["plan"]:
            rows = [{"任务": t["id"], "市场": t["market"], "创意角度": t["angle"], "档位": t["tier"], "素材": ", ".join(t["asset_ids"]), "状态": state["artifacts"].get(t["id"], {}).get("status", "pending")} for t in state["plan"]]
            st.dataframe(rows, hide_index=True, width="stretch")
            st.caption("依赖：市场资料与素材 → 有效计划与可行报价 → 脚本分镜 → 质量审核 → 完整保存")
            for t in state["plan"]:
                with st.expander(f"{t['id']} · 市场策略"):
                    st.write("目标人群：" + t["audience"])
                    st.write(t["strategy"])
            revisions = [e for e in events if e["tool"] == "revise_plan" and e["result"].get("ok")]
            st.write(f"共 {len(revisions)} 次计划提交 / 修改")
            for e in revisions:
                st.caption(f"版本 {e['plan_version']}：{e['decision_reason']}")
        else:
            st.info("计划尚未形成；需要先完成资料与素材检索。")
        if state["quote"]:
            st.json(state["quote"], expanded=False)
    with content_tab:
        for task in state["plan"]:
            artifact = state["artifacts"].get(task["id"], {})
            script = artifact.get("script") or artifact.get("rejected_script")
            if not script:
                st.caption(f"{task['id']} · 尚无内容产物")
                continue
            with st.expander(f"{task['id']} · {script['title']} · {artifact['status']}", expanded=True):
                if artifact["status"] == "rejected":
                    st.warning("该版本未通过审核，不能作为已完成内容交付。")
                st.write("开场：" + script["hook"])
                st.write("行动引导：" + script["cta"])
                st.caption(script["localization_rationale"])
                st.dataframe(script["shots"], hide_index=True, width="stretch")
                if artifact.get("review"):
                    st.json(artifact["review"], expanded=False)
        st.download_button("下载完整运行结果 JSON", json.dumps(state, ensure_ascii=False, indent=2), file_name=f"{state['task_id']}-result.json", mime="application/json")
        campaign = (source.parent / "campaign.md" if source else (state_root / state["saved"]).with_suffix(".md")) if state["saved"] else None
        if campaign and campaign.exists():
            st.download_button("下载方案 Markdown", campaign.read_text(), file_name="campaign.md", mime="text/markdown")
    with ledger_tab:
        if events:
            df = pd.DataFrame([{"步骤": e["step"], "累计费用": e["after"]["spent"], "累计模拟分钟": e["after"]["elapsed_minutes"]} for e in events]).set_index("步骤")
            st.line_chart(df[["累计费用"]], height=220)
            st.dataframe([{k: e[k] for k in ("step", "tool", "cost", "minutes")} for e in events], hide_index=True, width="stretch")
        st.caption("真实模型 token 用量与模拟业务单位分开记录。未返回的模型请求可能不包含在 token 汇总中。")
        st.json(state.get("model_usage", {}), expanded=False)
        st.write("实际合成素材")
        columns = st.columns(3)
        for i, asset in enumerate(load_data("assets.json")):
            with columns[i % 3]:
                st.image(asset_file(asset).read_bytes(), caption=asset["id"], width=160)
        with st.expander("产品事实、市场演示设定与费用规则"):
            st.json(state["context"] or {}, expanded=False)
        st.download_button("下载结构化 Trace", "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in state["trace"]), file_name="trace.jsonl", mime="application/x-ndjson")


st.caption("CONTENT OPERATIONS / TRACE FIRST")
st.title("跨市场内容工作台")
st.write("看见 Agent 如何理解市场、选择工具、应对异常并交付内容方案。")

try:
    with st.sidebar:
        st.subheader("运行与证据")
        page = st.radio("选择入口", ["验收记录", "已有任务", "新建任务"])
        st.caption("合成商品与市场资料 · 本地执行 · 不生成成片")
    state, source = None, None
    if page == "验收记录":
        priority = {"autonomous-transient": 0, "autonomous-persistent": 1, "normal": 2, "script-failure": 3, "budget-tight": 4, "missing-budget": 5}
        paths = sorted((ROOT / "examples" / "live").glob("*/result.json"), key=lambda p: (priority.get(p.parent.name, 9), p.parent.name)) + sorted((ROOT / "examples" / "offline").glob("*/result.json"))
        if paths:
            source = st.selectbox("选择实际运行记录", paths, format_func=lambda p: f"{p.parent.parent.name} / {p.parent.name}")
            state = json.loads(source.read_text())
        else:
            st.info("尚无归档记录，请先运行 CLI 或新建任务。")
    elif page == "已有任务":
        runs = service.store.list_runs()
        if runs:
            selected = st.selectbox("选择任务", [r["task_id"] for r in runs])
            state = service.store.get(selected)
            if st.button("刷新任务状态"):
                st.rerun()
            if state["status"] in {"waiting_input", "incomplete", "running"}:
                with st.expander("补充信息 / 恢复执行"):
                    with st.form("resume"):
                        existing_budget = state["brief"]["budget_units"]
                        budget = st.number_input("预算（模拟单位）", min_value=0, value=100 if existing_budget is None else existing_budget, step=1)
                        deadline = st.number_input("截止时间（模拟小时）", min_value=0.1, value=float(state["brief"]["deadline_hours"] or 48), max_value=720.0)
                        wait = st.number_input("推进等待时间（模拟分钟）", min_value=0, value=0, step=1)
                        repair = st.checkbox("模拟故障已修复，清除注入并重置失败尝试计数")
                        resume = st.form_submit_button("恢复同一任务")
                    if resume:
                        patch = {"budget_units": int(budget), "deadline_hours": deadline}
                        state = execute(lambda report: service.resume(selected, patch, repair=repair, wait_minutes=int(wait), on_event=report))
        else:
            st.info("暂无本地任务，可先查看验收记录或新建任务。")
    else:
        st.session_state.setdefault("new_id", "ui-" + uuid.uuid4().hex[:8])
        with st.form("create"):
            task_id = st.text_input("任务 ID（重复提交返回原结果）", value=st.session_state["new_id"])
            theme = st.text_input("活动主题", "ROAM 350 德国与美国市场的多语言内容活动")
            a, b, c = st.columns(3)
            budget = a.number_input("预算（模拟单位）", min_value=0, value=100, step=1)
            deadline = b.number_input("截止时间（模拟小时）", min_value=0.1, max_value=720.0, value=48.0)
            count = c.number_input("每市场方案数量", min_value=1, max_value=4, value=2, step=1)
            mode = st.selectbox("执行模式", ["offline", "live"], format_func=lambda v: "离线 Mock（流程验证）" if v == "offline" else "真实模型（使用本地配置）")
            scenario = st.selectbox("故障注入场景", SCENARIOS)
            submitted = st.form_submit_button("开始执行", type="primary")
        if submitted:
            brief = {"theme": theme, "budget_units": int(budget), "deadline_hours": deadline, "markets": {"DE": int(count), "US": int(count)}}
            state = execute(lambda report: service.run(task_id, brief, mode, scenario, report))
        elif st.session_state.get("active_task"):
            state = service.store.get(st.session_state["active_task"])
    if state:
        render(state, source)
except (ValueError, OSError) as exc:
    st.error(str(exc))
finally:
    service.close()
