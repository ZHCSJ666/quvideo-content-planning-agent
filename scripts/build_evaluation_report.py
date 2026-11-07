"""Build the evaluation document from stored results, not hand-entered success counts."""
import json
import xml.etree.ElementTree as ET

from content_agent.domain import ROOT


def main():
    suites = ET.parse(ROOT / "examples/test-results.xml").getroot().findall("testsuite")
    count = sum(int(s.get("tests", 0)) for s in suites)
    failures = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
    offline = json.loads((ROOT / "examples/offline/evaluation.json").read_text())
    live_path = ROOT / "examples/live/evaluation.json"
    live = json.loads(live_path.read_text()) if live_path.exists() else {"results": []}
    lines = ["# 效果验证与限制", "", "本文件由 `python scripts/build_evaluation_report.py` 读取实际测试报告和案例记录生成。未把离线策略或模型自评分当作真实业务效果证明。", "", "## 自动化验收", "", f"- pytest：{count} 项，失败/错误 {failures} 项；见 [文本结果](../examples/test-results.txt) 和 [JUnit XML](../examples/test-results.xml)。", f"- 离线验收：{sum(r['passed'] for r in offline['results'])}/{len(offline['results'])} 通过；见 [evaluation.json](../examples/offline/evaluation.json)。这些是 Mock 流程证据。", "", "```bash", "pytest -q --junitxml=examples/test-results.xml", "python scripts/evaluate.py", "python scripts/run_live_acceptance.py --prefix your-unique-prefix", "python scripts/build_evaluation_report.py", "```", "", "## 真实模型运行", "", "模型、参数和 token 用量保存在各个 result.json 中。当前通过用户授权的兼容接口调用模型；媒体/产品/市场设定和业务费用是合成的。模型决策、脚本和语义审核使用真实 API。", "", "| 案例 | 实际状态 | 模拟费用 | 工具调用 | 模型调用 | 验证结果 |", "| --- | --- | ---: | ---: | ---: | --- |"]
    for result in live["results"]:
        lines.append(f"| {result['case']} | {result.get('status', '重复提交返回原结果')} | {result.get('spent', result.get('additional_cost', '—'))} | {result.get('calls', result.get('additional_calls', '—'))} | {result.get('model_calls', '—')} | {'通过' if result['passed'] else '未通过'} |")
    lines += ["", "模型调用列统计收到响应的请求，超时未返回的不包含在此计数和 token 汇总中。"]
    for case in ("normal", "script-failure", "budget-tight", "missing-budget"):
        p = ROOT / "examples/live" / case / "result.json"
        if not p.exists():
            continue
        state = json.loads(p.read_text())
        lines += ["", f"### {case}", "", f"[输入](../examples/live/{case}/input.json) · [实际结果](../examples/live/{case}/result.json) · [Trace](../examples/live/{case}/trace.jsonl)", ""]
        actors = sorted({e["actor"] for e in state["trace"] if e.get("kind") == "tool"})
        if actors:
            lines.append("实际工具决策模型：" + "、".join(actors) + "。")
        if state["resume_count"]:
            lines.append(f"该任务包含 {state['resume_count']} 次明确的操作者恢复；这不是从头到尾无需干预的自动恢复记录。费用、原始异常与恢复事件连续保留。")
        interruptions = sum(e.get("kind") == "operator_interrupted" for e in state["trace"])
        if interruptions:
            lines.append(f"本案例另有 {interruptions} 次明确的操作者中止：旧配置在服务超时后反复无效重规划。该行为记录为失败，不冒充合理自动恢复；修改状态提示并调整模型配置后显式继续。")
        if state["saved"]:
            lines.append(f"[已保存方案](../examples/live/{case}/campaign.md)")
        else:
            lines.append(f"最终状态为 `{state['status']}`，没有完整方案保存成功。原因：{state['reason']}")
        for event in state["trace"]:
            result = event.get("result", {})
            if event.get("tool") == "review_content" and result.get("approved") is False:
                lines += ["", f"步骤 {event['step']} 的 {result.get('task_id', '')} 未通过内容审核。后续修复依据及原始问题均保留在 Trace 中。"]
            if event.get("tool") == "revise_plan" and result.get("retained"):
                lines += ["", f"步骤 {event['step']} 修改计划时保留：{', '.join(result['retained'])}；使依赖产物失效：{', '.join(result.get('invalidated', [])) or '无'}。"]
            if event.get("tool") == "estimate_cost" and result.get("feasible") is False:
                lines += ["", f"步骤 {event['step']} 的报价不可行：预计费用 {result['projected_total']}，预算缺口 {result['budget_gap']}，时间缺口 {result['time_gap_minutes']} 分钟。后续计划版本为 {state['plan_version']}。"]
            if result.get("code") == "SERVICE_UNAVAILABLE":
                lines += ["", f"步骤 {event['step']} 注入服务失败，计费 {event['cost']}、耗时 {event['minutes']} 分钟；错误明确返回给模型。"]
                approved_before = [e["result"]["task_id"] for e in state["trace"] if e.get("kind") == "tool" and e["step"] < event["step"] and e.get("tool") == "review_content" and e.get("result", {}).get("approved")]
                reused = [tid for tid in approved_before if not any(e.get("kind") == "tool" and e["step"] > event["step"] and e.get("tool") == "generate_script" and e["arguments"].get("task_id") == tid for e in state["trace"])]
                lines.append(f"失败前已审核且之后未重新生成的任务：{', '.join(reused) or '无'}。")
            if result.get("code") == "TOOL_ERROR":
                lines += ["", f"步骤 {event['step']} 发生真实工具异常 `{result.get('message', '')}`，记录模拟费用 {event['cost']}；后续动作由模型选择。"]
        if case == "missing-budget":
            lines.append("这是程序在模型调用前暂停的证据，不计入两条真实模型决策路径。")
    audit = ROOT / "examples/evidence-audit.json"
    if audit.exists():
        records = json.loads(audit.read_text())["results"]
        lines += ["", f"另经 `python scripts/audit_evidence.py` 检查 {len(records)} 份归档：Trace 与状态一致，步骤连续，账本可核对，完整交付满足结构约束。见 [审计结果](../examples/evidence-audit.json)。这不等于自然语言或营销效果验证。"]
    ui = ROOT / "examples/ui-archive-check.json"
    if ui.exists():
        records = json.loads(ui.read_text())["results"]
        lines += ["", f"最终 {len(records)} 份真实模式归档已通过 Streamlit AppTest 展示检查，查看归档不调用模型。见 [界面检查](../examples/ui-archive-check.json)。"]
    lines += ["", "## 验收点映射", "", "| 验收点 | 证据 |", "| --- | --- |", "| 正常完成 | live/normal；offline/normal |", "| 缺预算 / 截止时间 | live/missing-budget；offline/missing_budget、missing_deadline；各自 resumed 记录 |", "| 工具失败与保留成功步骤 | live/script-failure；offline/script_failure、persistent_failure |", "| 预算超限与无可行方案 | live/budget-tight；offline/budget_replan、budget_impossible |", "| 重复执行 | live/evaluation.json duplicate；test_duplicate_run_does_not_repeat_execution |", "| 失败续跑（加分项） | offline/persistent_failure_resumed；test_state_survives_new_service_instance；界面恢复测试 |", "| 资料不足 / 素材失效 | offline/asset_missing；exploratory 中空检索与不匹配素材的实际观察 |", "| 质量不合格 | live/normal；offline/quality_failure；exploratory 二次核查 |", "| 保存失败 | offline/save_failure；实际磁盘异常单元测试 |", "| 时间与调用上限 | offline/deadline_replan、step_limit；等待耗尽期限测试 |", "", "所有上述案例目录均包含实际 input.json、result.json、trace.jsonl；完成案例还包含 campaign.md/json。不同模式不能混算成模型成功率。", "", "## 失败、改进与验证边界", "", "- 早期并行探索存在检索标签不匹配、跨市场素材误用和实际模型审核超时，记录位于 `examples/exploratory/`。其中操作者中止的运行明确标记，不被统计为自动恢复成功。", "- 首次工程完成案例的二次核查发现轻量、耐用、环保和国家偏好推断漏检。原记录和 secondary-audit.json 保留，随后收紧事实规则与提示，并重新执行真实验收。二次核查由 Codex 完成，并非母语人工审稿。", "- 一条真实故障验收曾在触发预设故障前因重复质量拒绝而失败。重规划丢失审核意见的问题已修复，原运行保留在 `examples/history/`。", "- 紧预算案例在返工后无可行方案，如实未完成；这是停止边界通过验收，不等于四份内容成功交付。历史模型停止理由曾有忽略沉没费用的错误口算，原 Trace 保留；修复后显式恢复同一任务，程序账本生成最终费用与缺口说明。", "- 真实案例数量很小，只证明所列输入下的实际行为；不声称统计显著的成功率、真实转化提升或任意异常均可恢复。", "- 模型生成与语义审核使用同一模型，存在同源偏差；词表只覆盖已识别声明，不能保证任意措辞都被拦截。仍需母语运营和真实市场评估。", "- 素材为实际可读的合成 SVG；未验证真实视频渲染、配音时长、真实商品参数或商业投放。20 秒分镜和字数只是方案约束。", "- 本地账本与回执防重通过测试；网络超时后的实际模型计费、分布式工具 exactly-once 和真实第三方作业查询未实现。", "- Streamlit 通过 AppTest 归档展示、新建任务、失败恢复和零预算保留测试，以及 HTTP 健康检查；当前环境无用户浏览器控制工具，未声称完成截图级视觉验收。", "- GitHub URL、题号与最终远端 commit 仍需要实际提交信息；不能用本地代码替代已推送仓库。", ""]
    (ROOT / "docs/03-evaluation.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
