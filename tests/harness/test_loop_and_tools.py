"""The loop runs real tools and turns failures into observations."""

from __future__ import annotations

from agent_in_a_box.contracts import ToolCall
from agent_in_a_box.harness import tools
from agent_in_a_box.harness.loop import run_agent
from agent_in_a_box.models.probe import ProbeModel


def test_loop_emits_agent_reported_events(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("hello\n")
    events = []
    monkeypatch.chdir(tmp_path)
    history = run_agent("t", ProbeModel(ToolCall("read_file", {"path": "a.txt"})),
                        tools.TOOLS, events.append)
    assert [e["kind"] for e in events] == ["agent_start", "model_reply", "observation",
                                          "model_reply", "agent_finish"]
    assert history[0].observation.ok and history[0].observation.output == "hello\n"


def test_unknown_tool_is_an_observation_not_a_crash():
    events = []
    history = run_agent("t", ProbeModel(ToolCall("teleport", {})), tools.TOOLS, events.append)
    assert not history[0].observation.ok


def test_failures_become_observations(tmp_path):
    missing = tools.read_file({"path": str(tmp_path / "missing")})
    assert not missing.ok and missing.detail["errno"] is not None
    assert tools.bash({"command": "exit 3"}).detail["exit_status"] == 3
    assert not tools.http({"method": "GET", "url": "http://127.0.0.1:9/x"}).ok


def test_search_reports_matches(tmp_path):
    (tmp_path / "f.txt").write_text("alpha\nbeta\n")
    found = tools.search({"pattern": "beta", "path": str(tmp_path)})
    assert found.detail["matches"] == 1 and "f.txt:2: beta" in found.output


def test_output_is_bounded():
    assert len(tools.bash({"command": "head -c 20000 /dev/zero | tr '\\0' x"}).output) < 9000
