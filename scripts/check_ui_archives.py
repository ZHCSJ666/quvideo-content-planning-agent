"""Check every live archive in Streamlit without allowing execution or model access."""
import json
import os
import tempfile
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from content_agent.domain import ROOT


def main():
    paths = sorted((ROOT / "examples/live").glob("*/result.json"))
    assert paths, "No live archives to check"
    records = []
    (ROOT / ".runtime").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / ".runtime", prefix="ui-archive-") as runtime:
        with patch.dict(os.environ, {"CONTENT_STATE_DIR": runtime}), \
             patch("content_agent.providers.LiveProvider.__init__", side_effect=AssertionError("Archive view must not initialize a model")), \
             patch("content_agent.service.Service.run", side_effect=AssertionError("Archive view must not execute tasks")), \
             patch("content_agent.service.Service.resume", side_effect=AssertionError("Archive view must not resume tasks")):
            app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
            assert not app.exception
            for path in paths:
                state = json.loads(path.read_text())
                app.selectbox[0].set_value(path).run()
                assert not app.exception, path
                metrics = [m.value for m in app.metric]
                approved = sum(a["status"] == "approved" for a in state["artifacts"].values())
                budget = state["brief"]["budget_units"]
                assert metrics == [f"{approved} / {sum(state['brief']['markets'].values())}", f"{state['spent']} / {budget if budget is not None else '待补'}", f"{state['elapsed_minutes'] / 60:.1f} h", f"{state['calls']} / {state['brief']['max_calls']}"]
                if state["status"] == "completed":
                    assert any("全部请求" in e.value for e in app.success), path
                elif state["reason"]:
                    assert any(state["reason"] in e.value for e in app.warning), path
                if path.parent.name == "autonomous-persistent":
                    assert any("主动停止 / 未完成" in e.label for e in app.expander), path
                records.append({"case": path.parent.name, "rendered_without_api": True, "metrics": metrics})
    report = {"method": "Streamlit AppTest with model initialization, task execution and resume disabled; no screenshot/browser visual validation", "results": records}
    (ROOT / "examples/ui-archive-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"{len(records)} live archives rendered with execution and model access disabled")


if __name__ == "__main__":
    main()
