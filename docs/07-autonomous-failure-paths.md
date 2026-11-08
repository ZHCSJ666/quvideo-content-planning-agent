# 自主异常处理：真实运行验收

本报告由实际归档生成。工具故障由本地测试环境注入；规划、内容生成和语义审核调用真实模型。故障场景名不进入模型观察。

## 固定条件

- 模型：`vllm/Qwen/Qwen3.5-27B`；温度 0.2；请求超时 120.0 秒；SDK 自动重试 0 次。
- vLLM 非思考参数：`True`。两条运行使用相同配置、相同输入，各自从空状态开始。
- 输入：德国、美国各两条内容方案；预算 100 个模拟单位；期限 48 个模拟小时；最多 40 次工具调用、每任务最多 3 次生成尝试。
- 执行源码 commit：`7eea2a6bd76d1797974a20937f4769c94a7fd5d9`；源码/数据 SHA-256：`5e9fed94f6e42970f3ce48935281c944e72f707bf0d7b5e0a49003417c976dfe`。每条运行结束重新核对指纹。
- 执行时间：2026-11-08T20:04:09.916859+08:00 至 2026-11-08T20:11:56.556839+08:00（时间戳含北京时间偏移）。
- [批次配置与逐文件指纹](../examples/autonomy/autonomy-20261108-a/manifest.json)。凭据不进入记录。

## 结果

| 场景 | 任务状态 | 模拟费用 | 工具调用 | 人工续跑 | 验收 |
| --- | --- | ---: | ---: | ---: | --- |
| 临时失败 → 自主恢复 → 完整交付 | completed | 70 / 100 | 21 / 40 | 0 | 通过 |
| 持续不可用 → 主动停止 | incomplete | 17 / 100 | 9 / 40 | 0 | 通过 |

## 临时失败

[输入](../examples/autonomy/autonomy-20261108-a/transient/input.json) · [实际结果](../examples/autonomy/autonomy-20261108-a/transient/result.json) · [完整 Trace](../examples/autonomy/autonomy-20261108-a/transient/trace.jsonl) · [验收断言](../examples/autonomy/autonomy-20261108-a/transient/audit.json) · [故障发生时的成功成果快照](../examples/autonomy/autonomy-20261108-a/transient/before-failure.json)

故障发生于步骤 8；之后保持原样且没有重新生成的已审核任务：DE-1。验收检查 18/18 通过。

| 步骤 | 工具 | 任务 | 观察 | 本步费用 | 累计费用 |
| ---: | --- | --- | --- | ---: | ---: |
| 8 | generate_script | DE-2 | SERVICE_UNAVAILABLE | 2 | 17 |
| 9 | estimate_cost | — | 工具正常返回 | 0 | 17 |
| 10 | generate_script | DE-2 | 工具正常返回 | 12 | 29 |
| 11 | review_content | DE-2 | 审核拒绝 | 1 | 30 |
| 12 | revise_plan | — | 工具正常返回 | 0 | 30 |
| 13 | generate_script | DE-2 | ESTIMATE_REQUIRED | 0 | 30 |
| 14 | estimate_cost | — | 工具正常返回 | 0 | 30 |
| 15 | generate_script | DE-2 | 工具正常返回 | 12 | 42 |
| 16 | review_content | DE-2 | 审核通过 | 1 | 43 |
| 17 | generate_script | US-1 | 工具正常返回 | 12 | 55 |
| 18 | review_content | US-1 | 审核通过 | 1 | 56 |
| 19 | generate_script | US-2 | 工具正常返回 | 12 | 68 |
| 20 | review_content | US-2 | 审核通过 | 1 | 69 |
| 21 | save_campaign | — | 完整方案保存成功 | 1 | 70 |

费用表取自工具账本；模型理由中的口算或“剩余费用”表述不作为报价，执行前仍由程序检查硬约束。质量返工和依赖检查失败等实际纠错步骤一并保留。

故障后的模型动作依据（直接读取 Trace 中的简要理由，不是模型内部思维）：

- 步骤 9 `estimate_cost`：DE-2脚本生成失败（SERVICE_UNAVAILABLE），需检查剩余预算和时间是否支持重试。当前已花费17单位，剩余83单位；DE-1已完成，DE-2、US-1、US-2待处理。需确认是否仍有足够资源进行重试或调整策略。
- 步骤 10 `generate_script`：DE-2脚本生成失败（SERVICE_UNAVAILABLE），但estimate_cost显示预算和时间充足（剩余40单位成本，376分钟），且失败可重试。按顺序重试DE-2脚本生成，策略聚焦不锈钢材质与可重复使用特性，使用desk和cup-detail素材，仅陈述已验证事实。
- 步骤 12 `revise_plan`：DE-2任务因策略中包含“环保使用习惯”等违规推断被拒，需修正策略仅陈述已知事实（350ml容量、不锈钢杯身、旋盖、可重复使用），删除所有环保、耐用或长期可靠等未证实承诺，确保符合产品档案约束。
- 步骤 13 `generate_script`：DE-2任务策略已修正，删除了“环保使用习惯”等违规推断，仅保留350ml容量、不锈钢杯身、旋盖及可重复使用四项已知事实。现重新生成脚本，确保内容严格符合产品档案约束，避免任何未证实承诺。
- 步骤 14 `estimate_cost`：DE-2任务策略已修正，需重新生成脚本。在生成前必须获取当前计划的费用估算，确认剩余预算是否支持后续生成与审核流程，避免超出100预算单位或48小时时限。
- 步骤 15 `generate_script`：DE-2任务策略已修正，删除了违规推断，仅保留已知事实。当前估算显示预算可行（剩余40单位），需生成脚本以推进审核流程。
- 步骤 17 `generate_script`：DE-1和DE-2已审核通过，当前需推进US-1任务。根据估算，剩余预算40单位，时间充足，且US-1策略仅陈述已知事实（350ml容量、不锈钢杯身、旋盖、可重复使用），无违规推断，符合生成条件。
- 步骤 19 `generate_script`：US-2任务尚未生成脚本，当前预算充足（剩余40单位），时间充裕，且策略仅陈述已知事实（350ml容量、不锈钢杯身、旋盖、可重复使用），无违规推断，符合生成条件。
- 步骤 21 `save_campaign`：所有四个任务（DE-1、DE-2、US-1、US-2）均已通过审核，脚本严格遵循产品事实，未包含任何禁止声明，符合市场风格与时长要求。预算和时间均在允许范围内，满足保存条件。

[四条已保存内容方案](../examples/autonomy/autonomy-20261108-a/transient/campaign.md)；JSON 与最终状态、账本、审核成果一致。

## 持续不可用

[输入](../examples/autonomy/autonomy-20261108-a/persistent/input.json) · [实际结果](../examples/autonomy/autonomy-20261108-a/persistent/result.json) · [完整 Trace](../examples/autonomy/autonomy-20261108-a/persistent/trace.jsonl) · [验收断言](../examples/autonomy/autonomy-20261108-a/persistent/audit.json) · [故障发生时的成功成果快照](../examples/autonomy/autonomy-20261108-a/persistent/before-failure.json)

故障发生于步骤 8；之后保持原样且没有重新生成的已审核任务：DE-1。验收检查 19/19 通过。

| 步骤 | 工具 | 任务 | 观察 | 本步费用 | 累计费用 |
| ---: | --- | --- | --- | ---: | ---: |
| 8 | generate_script | DE-2 | SERVICE_UNAVAILABLE | 2 | 17 |
| 9 | stop | — | 主动停止 / 未完成 | 0 | 17 |

费用表取自工具账本；模型理由中的口算或“剩余费用”表述不作为报价，执行前仍由程序检查硬约束。质量返工和依赖检查失败等实际纠错步骤一并保留。

故障后的模型动作依据（直接读取 Trace 中的简要理由，不是模型内部思维）：

- 步骤 9 `stop`：DE-2任务在首次生成脚本时遇到SERVICE_UNAVAILABLE错误，且标记为retryable=false，表示服务在当前所有档位下均不可用，且无备用服务配置。根据规则，当必需任务被此类不可重试的服务阻塞时，应保留已完成工作（DE-1已批准）并停止，明确说明修复条件：需修复脚本服务后，由操作员显式恢复同一任务。当前无法继续生成DE-2、US-1、US-2的脚本，因此无法完成全部4个视频任务并保存活动。

最终未完成说明：

未完成。已审核并保留：DE-1。工具明确报告不可继续重试：DE-2（SERVICE_UNAVAILABLE，已尝试 1 次）。已支出 17，预算 100。修复对应服务或错误后，显式恢复同一任务；费用和有效成果不清零。

该场景模拟服务明确报告持续不可用（`retryable=false`），当前没有配置替代供应商。主动停止可以发生在第一次明确不可恢复的反馈后，无须强行耗尽三次尝试。报价仅说明预算与时间可行，不代表服务可用；部分成果保留，但没有保存完整活动方案。

故障范围以工具返回的 DE-2 为准；未执行的 US-1/US-2 是尚未生成，不能记为服务失败。整单要求四条齐备，必需任务被阻塞时停止继续消耗预算。模型原始理由仍保留，最终 blockers 由实际错误生成。

## 全部尝试与复核

所有批次均保留；下表不被解释为模型成功率统计。

| 批次 | 验收 | 原始结果 |
| --- | --- | --- |
| autonomy-20261108-a | 通过 | [evaluation.json](../examples/autonomy/autonomy-20261108-a/evaluation.json) |

复跑两个新任务（使用仓库外的凭据配置；批次 ID 必须唯一）：

```bash
CONTENT_MODEL='vllm/Qwen/Qwen3.5-27B' CONTENT_VLLM_DISABLE_THINKING=1 CONTENT_API_TIMEOUT=120 \
  python scripts/run_autonomous_acceptance.py --batch your-new-batch-id
python scripts/audit_evidence.py
python scripts/build_autonomy_report.py
```

查看 Streamlit 的 `live / autonomous-transient` 和 `live / autonomous-persistent`，无需重新调用模型。旧的人工中止/续跑记录仍保留为历史案例，未改写成自主恢复。

本次证据证明所列固定条件下的真实行为；不保证任意模型、网络状态或输入下都能成功。内容质量仍有同源模型审核的局限。
