"""Run directories and the workload's environment.

Each run gets a fresh directory with four parts:

    workspace/  copied from fixtures/workspace; the logical /workspace
    home/       the workload's HOME
    tmp/        the workload's TMPDIR
    private/    policy, proxy configuration, decision records, evidence;
                never inside any grant, and denied by every profile
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
import time
from pathlib import Path

from agent_in_a_box.contracts import RunSpec, WorkloadSpec
from agent_in_a_box.policy.schema import REPO_ROOT

WORKSPACE_FIXTURE = REPO_ROOT / "fixtures" / "workspace"


def new_run_id() -> str:
    return time.strftime("run-%Y%m%d-%H%M%S-") + secrets.token_hex(3)


def create_run(runs_dir: Path, run_id: str | None = None) -> RunSpec:
    run_id = run_id or new_run_id()
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_dir = Path(os.path.realpath(runs_dir)) / run_id
    run_dir.mkdir()
    shutil.copytree(WORKSPACE_FIXTURE, run_dir / "workspace", symlinks=True,
                    ignore=shutil.ignore_patterns(".keep"))
    for name in ("home", "tmp", "private"):
        (run_dir / name).mkdir()
    (run_dir / "private").chmod(0o700)
    return RunSpec(run_id=run_id, run_dir=str(run_dir), workspace=str(run_dir / "workspace"),
                   home=str(run_dir / "home"), tmp=str(run_dir / "tmp"),
                   private=str(run_dir / "private"))


def workload(run: RunSpec, task: str, proxy_port: int, deadline_s: float = 60.0,
             probe: dict | None = None) -> WorkloadSpec:
    """The harness command and a sanitized environment: no inherited secrets.

    With `probe` (a tool call), the harness runs the one-call probe model.
    """
    proxy = f"http://127.0.0.1:{proxy_port}"
    env = {
        "PATH": os.pathsep.join([os.path.dirname(sys.executable), "/usr/bin", "/bin"]),
        "HOME": run.home,
        "TMPDIR": run.tmp,
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "HTTP_PROXY": proxy,
        "http_proxy": proxy,
        "NO_PROXY": "",
        "no_proxy": "",
    }
    return WorkloadSpec(
        run_id=run.run_id,
        argv=(sys.executable, "-m", "agent_in_a_box.harness", "--task", task)
        + (("--model", "probe", "--probe", json.dumps(probe)) if probe else ()),
        env=env,
        cwd=run.workspace,
        stdout_path=str(Path(run.private) / "agent-events.jsonl"),
        stderr_path=str(Path(run.private) / "agent-stderr.txt"),
        deadline_s=deadline_s,
        output_limit_bytes=1 << 20,
    )
