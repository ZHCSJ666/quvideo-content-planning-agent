"""Render the selected autonomous pair and all recorded attempts, without model calls."""
import json
from content_agent.domain import ROOT


def main():
    latest = json.loads((ROOT / "examples/autonomy/latest.json").read_text())
    report_path = ROOT / latest["evaluation"]
    report = json.loads(report_path.read_text())
    manifest = json.loads(report_path.with_name("manifest.json").read_text())
    config = manifest["model_config"]
    lines = ["# 自主异常处理：真实运行验收", "", "本报告由实际归档生成。工具故障由本地测试环境注入；规划、内容生成和语义审核调用真实模型。故障场景名不进入模型观察。", "", "## 固定条件", "", f"- 模型：`{config['model']}`；温度 {config['temperature']}；请求超时 {config['timeout_seconds']} 秒；SDK 自动重试 {config['sdk_retries']} 次。", f"- vLLM 非思考参数：`{config['vllm_disable_thinking']}`。两条运行使用相同配置、相同输入，各自从空状态开始。", "- 输入：德国、美国各两条内容方案；预算 100 个模拟单位；期限 48 个模拟小时；最多 40 次工具调用、每任务最多 3 次生成尝试。", f"- 执行源码 commit：`{manifest['git_commit']}`；源码/数据 SHA-256：`{manifest['source']['sha256']}`。每条运行结束重新核对指纹。", f"- 执行时间：{manifest['started_at']} 至 {manifest['finished_at']}（时间戳含北京时间偏移）。", f"- [批次配置与逐文件指纹](../{str(report_path.with_name('manifest.json').relative_to(ROOT))})。凭据不进入记录。", "", "## 结果", "", "| 场景 | 任务状态 | 模拟费用 | 工具调用 | 人工续跑 | 验收 |", "| --- | --- | ---: | ---: | ---: | --- |"]
    for record in report["results"]:
        label = "临时失败 → 自主恢复 → 完整交付" if record["case"].endswith("transient") else "持续不可用 → 主动停止"
        lines.append(f"| {label} | {record['status']} | {record['spent']} / 100 | {record['calls']} / 40 | {record['resume_count']} | {'通过' if record['passed'] else '未通过'} |")
    for record in report["results"]:
        directory = ROOT / record["evidence"]
        state = json.loads((directory / "result.json").read_text())
        audit = json.loads((directory / "audit.json").read_text())
        label = "临时失败" if record["case"].endswith("transient") else "持续不可用"
        base = "../" + record["evidence"]
        lines += ["", f"## {label}", "", f"[输入]({base}/input.json) · [实际结果]({base}/result.json) · [完整 Trace]({base}/trace.jsonl) · [验收断言]({base}/audit.json) · [故障发生时的成功成果快照]({base}/before-failure.json)", "", f"故障发生于步骤 {audit['fault_step']}；之后保持原样且没有重新生成的已审核任务：{', '.join(audit['preserved_tasks'])}。验收检查 {sum(audit['checks'].values())}/{len(audit['checks'])} 通过。", "", "| 步骤 | 工具 | 任务 | 观察 | 本步费用 | 累计费用 |", "| ---: | --- | --- | --- | ---: | ---: |"]
        for event in state["trace"]:
            if event.get("kind") != "tool" or event["step"] < audit["fault_step"]:
                continue
            result = event["result"]
            observation = result.get("code") or ("审核通过" if result.get("approved") is True else "审核拒绝" if result.get("approved") is False else "工具正常返回")
            if event["tool"] == "stop" and result.get("status") == "incomplete":
                observation = "主动停止 / 未完成"
            elif event["tool"] == "save_campaign" and result.get("ok"):
                observation = "完整方案保存成功"
            lines.append(f"| {event['step']} | {event['tool']} | {event['arguments'].get('task_id', '—')} | {observation} | {event['cost']} | {event['after']['spent']} |")
        lines += ["", "费用表取自工具账本；模型理由中的口算或“剩余费用”表述不作为报价，执行前仍由程序检查硬约束。质量返工和依赖检查失败等实际纠错步骤一并保留。", "", "故障后的模型动作依据（直接读取 Trace 中的简要理由，不是模型内部思维）：", ""]
        for event in audit["actions_after_fault"]:
            if event["tool"] in {"estimate_cost", "generate_script", "revise_plan", "stop", "save_campaign"}:
                lines.append(f"- 步骤 {event['step']} `{event['tool']}`：{event['reason']}")
        if state["saved"]:
            lines += ["", f"[四条已保存内容方案]({base}/campaign.md)；JSON 与最终状态、账本、审核成果一致。"]
        else:
            lines += ["", "最终未完成说明：", "", state["reason"], "", "该场景模拟服务明确报告持续不可用（`retryable=false`），当前没有配置替代供应商。主动停止可以发生在第一次明确不可恢复的反馈后，无须强行耗尽三次尝试。报价仅说明预算与时间可行，不代表服务可用；部分成果保留，但没有保存完整活动方案。"]
            lines += ["", "故障范围以工具返回的 DE-2 为准；未执行的 US-1/US-2 是尚未生成，不能记为服务失败。整单要求四条齐备，必需任务被阻塞时停止继续消耗预算。模型原始理由仍保留，最终 blockers 由实际错误生成。"]
    index = json.loads((ROOT / "examples/autonomy/index.json").read_text())
    lines += ["", "## 全部尝试与复核", "", "所有批次均保留；下表不被解释为模型成功率统计。", "", "| 批次 | 验收 | 原始结果 |", "| --- | --- | --- |"]
    for batch in index["batches"]:
        lines.append(f"| {batch['batch']} | {'通过' if batch['passed'] else '未通过'} | [evaluation.json](../{batch['evaluation']}) |")
    lines += ["", "复跑两个新任务（使用仓库外的凭据配置；批次 ID 必须唯一）：", "", "```bash", f"CONTENT_MODEL='{config['model']}' CONTENT_VLLM_DISABLE_THINKING=1 CONTENT_API_TIMEOUT=120 \\", "  python scripts/run_autonomous_acceptance.py --batch your-new-batch-id", "python scripts/audit_evidence.py", "python scripts/build_autonomy_report.py", "```", "", "查看 Streamlit 的 `live / autonomous-transient` 和 `live / autonomous-persistent`，无需重新调用模型。旧的人工中止/续跑记录仍保留为历史案例，未改写成自主恢复。", "", "本次证据证明所列固定条件下的真实行为；不保证任意模型、网络状态或输入下都能成功。内容质量仍有同源模型审核的局限。", ""]
    (ROOT / "docs/07-autonomous-failure-paths.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
