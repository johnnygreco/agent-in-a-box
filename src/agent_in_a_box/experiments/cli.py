"""The agent-in-a-box command line.

    agent-in-a-box doctor [--test-backend]
    agent-in-a-box gateway serve [--port N] [--test-backend]
    agent-in-a-box trailer|chapter5 [--test-backend] [--session NAME] [--gateway STATE_FILE]
    agent-in-a-box site-data --published [--bundles DIR] [--out DIR]
    agent-in-a-box site-data --trailer BUNDLE --chapter5 BUNDLE [--out DIR]   (development)
    agent-in-a-box bundle show PATH | agent-in-a-box bundle replay PATH

Without --test-backend, runs use this host's native backend or are refused.
--test-backend selects the NoEnforcementBackend, a test double that contains
nothing; every record it produces says `enforcement: none`.
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
from pathlib import Path

from agent_in_a_box import composition
from agent_in_a_box.contracts import plain
from agent_in_a_box.experiments import bundle as bundles

DEFAULT_STATE = composition.REPO_ROOT / ".agent-in-a-box"


def runtime_for(args: argparse.Namespace) -> composition.Runtime:
    return composition.assemble(composition.RuntimeConfig(
        backend="none" if args.test_backend else None, allow_test_backend=args.test_backend,
        runs_dir=Path(args.state_dir) / "runs"))


def doctor(args: argparse.Namespace) -> int:
    from agent_in_a_box.policy import toolchain

    ok = True
    try:
        manifest = toolchain.manifest()
        print(f"toolchain: ok (cedar-policy {manifest['cedar_policy']}, SymCC "
              f"{manifest['cedar_policy_symcc']}, cedarpy {manifest['cedarpy']}, "
              f"{manifest['cvc5']})")
    except toolchain.ToolchainError as exc:
        ok = False
        print(f"toolchain: FAILED: {exc}")
    runtime = runtime_for(args)
    if runtime.backend is None:
        print(f"backend: none available: {runtime.backend_refusal}")
        print("native execution: disabled; runs are refused (no fallback)")
        return 1
    report = runtime.backend.doctor()
    for check in report.checks:
        print(f"backend {report.backend}: {check.name}: {'ok' if check.ok else 'FAILED'}: "
              f"{check.detail}")
    for note in runtime.backend.capabilities().notes:
        print(f"  note: {note}")
    print(f"native execution: {'enabled' if report.native_execution else 'disabled'}")
    return 0 if ok and report.ok else 1


def gateway(args: argparse.Namespace) -> int:
    from agent_in_a_box.gateway.server import serve

    serve(runtime_for(args), args.port)
    return 0


def start_gateway(args: argparse.Namespace) -> tuple[subprocess.Popen, Path]:
    argv = [sys.executable, "-m", "agent_in_a_box.experiments.cli", "--state-dir", args.state_dir,
            "gateway", "serve"] + (["--test-backend"] if args.test_backend else [])
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, text=True)
    line = (process.stdout.readline() if process.stdout else "").split()
    if line[:1] != ["READY"]:
        process.kill()
        raise SystemExit(f"gateway did not start: {line}")
    return process, Path(line[2])


def experiment(args: argparse.Namespace) -> int:
    """Run the trailer or chapter 5 through a gateway (started here unless given)."""
    from agent_in_a_box.client import GatewayClient
    from agent_in_a_box.experiments.chapter5 import run_chapter5
    from agent_in_a_box.experiments.trailer import run_trailer

    script = {"trailer": run_trailer, "chapter5": run_chapter5}[args.command]
    if args.gateway:
        process = None
        state = Path(args.gateway)
    else:
        process, state = start_gateway(args)
    try:
        client = GatewayClient.from_state(state)
        health = client.health()
        if health["enforcement"] is None:
            print(f"Refused: {health['backend_refusal']}. Use --test-backend for the test double.")
            return 1
        if health["enforcement"] == "none":
            print("Test backend: nothing is contained; every record says enforcement: none.")
        outcome = script(client, args.session or f"{args.command}-{secrets.token_hex(4)}")
        print(json.dumps(outcome["observed"], indent=1))
        print("as expected" if outcome["as_expected"] else "NOT as expected")
        return 0 if outcome["as_expected"] else 2
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=10)


def site_data(args: argparse.Namespace) -> int:
    """Write the website's view models.

    --published: only publishable evidence (experiments/publish.py), for the
    deployed site. Otherwise: development bundles, for local work only.
    """
    from agent_in_a_box.experiments import publish, views

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    evaluator = composition.select_evaluator("cedarpy")
    if args.published:
        try:
            native = publish.native_recordings(Path(args.bundles))
        except publish.PublishRefused as refusal:
            print(f"Refused to publish: {refusal}", file=sys.stderr)
            return 1
        written = {
            "chapter0.json": publish.chapter0(evaluator, native),
            "chapter5.json": publish.chapter5(evaluator, native),
            "glossary.json": views.glossary(),
        }
    else:
        if not (args.trailer and args.chapter5):
            print("development data needs --trailer and --chapter5", file=sys.stderr)
            return 2
        written = {
            "chapter0.json": views.chapter0(bundles.load(Path(args.trailer)), evaluator),
            "chapter5.json": views.chapter5(bundles.load(Path(args.chapter5)), evaluator),
            "glossary.json": views.glossary(),
        }
    for name, data in written.items():
        (out / name).write_text(json.dumps(data, indent=1) + "\n")
    print(f"wrote {', '.join(written)} to {out}")
    return 0


def bundle_command(args: argparse.Namespace) -> int:
    document = bundles.load(Path(args.path))
    if args.action == "show":
        print(f"{document['title']} [{document['viewed_as']}; enforcement: "
              f"{', '.join(document['enforcement']) or 'no runs'}; bundle {document['bundle_id']}]")
        for step in document["steps"]:
            print(f"  {step['command_id']}: {step['kind']} {step['status']}")
        return 0
    report = bundles.replay(document, runtime_for(args).evaluator)
    print(json.dumps(plain(report), indent=1))
    return 0 if not report["mismatched"] else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-in-a-box", description=__doc__.splitlines()[0])
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE),
                        help="where runs, commands, bundles, and gateway state live")
    commands = parser.add_subparsers(dest="command", required=True)

    def with_backend(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--test-backend", action="store_true",
                       help="use the NoEnforcementBackend test double (enforcement: none)")
        return p

    with_backend(commands.add_parser("doctor")).set_defaults(run=doctor)
    serve = with_backend(commands.add_parser("gateway").add_subparsers(
        dest="gateway_command", required=True).add_parser("serve"))
    serve.add_argument("--port", type=int, default=0)
    serve.set_defaults(run=gateway)
    for name in ("trailer", "chapter5"):
        run = with_backend(commands.add_parser(name))
        run.add_argument("--session", help="name for this experiment's command IDs")
        run.add_argument("--gateway", help="state file of a running gateway")
        run.set_defaults(run=experiment)
    site = commands.add_parser("site-data")
    site.add_argument("--published", action="store_true",
                      help="publishable evidence only: analysis now, native bundles from --bundles")
    site.add_argument("--bundles", default=str(composition.REPO_ROOT / "bundles"),
                      help="native recordings to publish (published mode)")
    site.add_argument("--trailer", help="chapter 0 trailer bundle (development mode)")
    site.add_argument("--chapter5", help="chapter 5 bundle (development mode)")
    site.add_argument("--out", default=str(composition.REPO_ROOT / "website" / "src" / "data"))
    site.set_defaults(run=site_data)
    show = with_backend(commands.add_parser("bundle"))
    show.add_argument("action", choices=["show", "replay"])
    show.add_argument("path")
    show.set_defaults(run=bundle_command)

    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
