# Market Content Agent

面向跨境电商的多语言营销内容规划与预算优化 Agent。重点展示**模型如何依据工具反馈完成任务、修改计划和处理失败**。

默认任务：为合成便携杯 ROAM 350，在 100 个模拟单位、48 个模拟小时内，交付德国和美国市场各两条短视频内容方案。真实生成脚本、20 秒分镜与方案文件；不生成成片。

## 评审先看什么

1. `examples/live/`：真实模型工具调用、实际内容、质量审核与恢复记录。`examples/offline/` 是独立标注的固定策略流程测试，不证明真实模型决策。
2. `docs/03-evaluation.md`：验收点、测试结果、实际失败与限制。
3. `src/content_agent/agent.py`：LangGraph 的观察—决策—执行循环。
4. `src/content_agent/tools.py`：工具约束、预算计算、状态与重规划后的成果复用。
5. CLI 或 Streamlit 重跑案例，再通过 `trace.jsonl` 核对每一步的参数、理由、返回、费用与下一步。

建议的演示顺序：先对照 `live / autonomous-transient` 与 `live / autonomous-persistent`，看同一输入下模型如何根据可重试/不可重试的工具反馈选择恢复或主动停止。两条均从空状态执行，期间没有人工续跑；逐步观察、成果保留断言和运行条件见 [自主异常处理验收](docs/07-autonomous-failure-paths.md)。然后查看 `live / normal` 的质量返工与 `live / budget-tight` 的超预算重规划和停止。

这些记录展示实际发生的动作，包含模型判断失误。旧的 `live / script-failure` 涉及操作者中止和恢复，原始记录保留，不能当作全程自主恢复证据。`docs/03-evaluation.md` 说明每条案例是否通过验收、是否完整交付，两者不能混同。

## 安装

验证环境：Python 3.12，Linux；锁定的完整环境要求 Python 3.12+。使用项目内虚拟环境，不修改系统 Python。

```bash
cd 小影
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.lock` 固定已验证的依赖版本。项目使用可编辑安装，数据从仓库 `data/` 读取，因此在项目目录运行。无模型凭据也可运行离线模式与测试。

## 一分钟离线运行

```bash
content-agent run --id demo-offline --input examples/inputs/normal.json --mode offline
content-agent show --id demo-offline
content-agent export --id demo-offline --output .runtime/export/demo-offline
```

默认 `.runtime/` 保存 SQLite 状态、检查点、Trace 和输出。成功后可打开 `.runtime/outputs/demo-offline/campaign.md`。同一个 ID 和相同请求重复执行会返回原结果，不再调用模型或重复收费。

离线模式打印 `offline_mock:scripted_policy`。其脚本与评分是测试桩，只用于验证控制流程、账本、恢复和保存，不应当作内容质量展示。

## 真实模型

复制 `.env.example` 为 `.env` 并设置：

```dotenv
CONTENT_API_BASE=https://your-compatible-endpoint.example/v1
CONTENT_API_KEY=your-key
CONTENT_MODEL=your-tool-calling-model
CONTENT_API_TIMEOUT=90
```

也支持 `CONTENT_API_CONFIG` 指向仓库外的两行配置文件（第一行 base URL、第二行 key），同时设置 `CONTENT_MODEL`。凭据只在运行时读取，不写入 Trace。`CONTENT_VLLM_DISABLE_THINKING=1` 仅用于确认支持此参数的 vLLM/Qwen 服务；其他服务留空。

```bash
content-agent run --id live-demo --input examples/inputs/normal.json --mode live
content-agent run --id live-fault --input examples/inputs/normal.json --mode live --scenario script_once
content-agent export --id live-demo --output .runtime/export/live-demo
```

真实模式不会因 API 不可用而静默切换到 Mock。模型决策、脚本生成与语义审核的 token 用量在结果中单独记录；`model_calls` 统计返回响应的请求，超时且未收到响应的请求不计入该数值和 token 汇总。模拟单位不等于真实 API 费用。工具选择理由是简要可审计说明，不是模型内部思维。

## 异常、补充与续跑

```bash
# 缺预算：暂停，而不是猜一个预算
content-agent run --id needs-budget --input examples/inputs/missing_budget.json
content-agent resume --id needs-budget --budget 100

# 持续失败：保留已成功方案，明确未完成（本命令默认离线测试策略）
content-agent run --id broken --input examples/inputs/normal.json --scenario persistent_failure
# 显式模拟服务已修复，从失败部分继续；累计费用不清零
content-agent resume --id broken --repair

# 预算/时间压力：模型或离线策略选择替代档位，仍保留完整交付
content-agent run --id low-budget --input examples/inputs/budget_tight.json
content-agent run --id tight-time --input examples/inputs/deadline_tight.json
```

故障场景：`normal`、`script_once`、`persistent_failure`、`asset_missing`、`quality_once`、`save_once`。故障开关属于测试环境，模型看不到场景名，只看到工具观察。模拟等待时间通过 `resume --wait-minutes 60` 推进；恢复不自动延长截止时间。`--additional-calls` 显式给下一次恢复增加有限调用额度。

退出码：0 为完成；2 为等待输入或未完成；1 为输入/命令错误。脚本中应明确区分这些结果，不能将退出码 2 当作成功。

## 可视化

```bash
streamlit run app.py
```

界面用于选择案例、发起/恢复任务和检查执行链路。CLI 与界面复用同一个 `Service`、账本和 Agent。评审无需界面也能重现全部核心行为。页面显示 live / offline 标识，模型反馈、费用和计划变更均来自实际 Trace。

## 验证

```bash
pytest -q
python scripts/evaluate.py
# 需要真实模型配置；串行运行，并保存实际记录
python scripts/run_live_acceptance.py --prefix review-your-unique-id
# 两条严格自主故障验收：真实模型、全新任务、配置固定、没有 resume/repair
CONTENT_API_TIMEOUT=120 python scripts/run_autonomous_acceptance.py --batch your-unique-batch
python scripts/audit_evidence.py
python scripts/check_ui_archives.py
python scripts/build_autonomy_report.py
python scripts/build_evaluation_report.py
```

`evaluate.py` 运行并断言离线验收案例，将实际输入、输出和 Trace 写入 `examples/offline/`。测试覆盖预算、期限、依赖、质量门槛、工具失败、写入失败、重复执行、进程重启、恢复和调用上限。真实模型案例另存 `examples/live/`，不与离线结果混算。

`run_autonomous_acceptance.py` 保存每次批次的输入、模型配置、源码指纹、故障发生时的已成功成果快照和验收断言；只在两条路径均通过时更新主要展示记录，失败批次同样保留。当前运行参数和复跑命令见 [专项报告](docs/07-autonomous-failure-paths.md)。故障由本地工具注入，模型自主决定后续动作。

`audit_evidence.py` 独立核对导出的 Trace、累计费用/时间、调用次数和方案文件；对两条自主案例还重验源码指纹、零人工干预、成果保留及终止动作。不会将未完成任务当成完整交付。

CLI 中 `ok` 表示工具是否正常返回，`observation.approved` 表示内容是否通过审核；两者不能混同。完整参数和返回保存在 Trace，下一条事件给出模型随后采取的动作与依据。

## 结构

```text
src/content_agent/  业务契约、工具、模型接入、状态图、存储、CLI
data/               合成产品/市场资料、实际 SVG 素材、成本与耗时规则
tests/              可执行验证
examples/           输入、实际结果、结构化 Trace
docs/01–07          需求、方案、评估、个人记录与自主故障验收
app.py              轻量 Streamlit 界面
```

## 已知边界与提交

市场资料和素材为自制演示数据；语言和创意审核使用模型，尚不能替代母语运营人员审核或真实市场测试。供应商网络超时后，真实模型是否计费无法凭本地 Trace 确认。当前只保证可控本地工具与模拟账本的防重，不宣称分布式 exactly-once。

提交前如实补充本人审阅/修改记录，并确认仓库题号、GitHub URL 和最终 commit SHA。原始试题、`.env`、运行数据库和虚拟环境被 `.gitignore` 排除；公开前仍需检查暂存文件。完整提交元信息见 `submission.json`。
