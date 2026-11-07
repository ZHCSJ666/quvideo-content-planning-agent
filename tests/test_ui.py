from pathlib import Path
from streamlit.testing.v1 import AppTest
from content_agent.domain import ROOT


def test_archive_trace_view_renders_without_api(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_STATE_DIR", str(tmp_path))
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "跨市场内容工作台"
    assert len(app.metric) == 4
    app.selectbox[0].set_value(ROOT / "examples/offline/normal/result.json").run()
    assert any("离线" in element.value for element in app.info)


def test_new_offline_run_uses_same_service_and_completes(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_STATE_DIR", str(tmp_path))
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    app.radio[0].set_value("新建任务").run()
    next(b for b in app.button if b.label == "开始执行").click().run()
    assert not app.exception
    assert any("全部请求" in item.value for item in app.success)
    assert list((tmp_path / "outputs").glob("*/campaign.json"))


def test_ui_resume_preserves_previous_work(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_STATE_DIR", str(tmp_path))
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    app.radio[0].set_value("新建任务").run()
    next(s for s in app.selectbox if s.label == "故障注入场景").set_value("persistent_failure")
    next(b for b in app.button if b.label == "开始执行").click().run()
    assert not app.exception
    app.radio[0].set_value("已有任务").run()
    app.checkbox[0].set_value(True)
    next(b for b in app.button if b.label == "恢复同一任务").click().run()
    assert not app.exception
    assert any("全部请求" in item.value for item in app.success)
    assert app.metric[1].value == "61 / 100"


def test_ui_resume_does_not_replace_zero_budget(tmp_path, monkeypatch):
    from content_agent.service import Service
    service = Service(tmp_path)
    service.run("zero-budget", {"theme": "杯子活动", "budget_units": 0, "deadline_hours": 48, "max_calls": 4})
    service.close()
    monkeypatch.setenv("CONTENT_STATE_DIR", str(tmp_path))
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    app.radio[0].set_value("已有任务").run()
    assert not app.exception
    assert next(n for n in app.number_input if n.label == "预算（模拟单位）").value == 0
