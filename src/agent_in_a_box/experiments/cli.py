"""The agent-in-a-box command line.

    agent-in-a-box doctor [--test-backend]
    agent-in-a-box probe [--test-backend] [--policy P0] [--variant default] [--deadline S]
                         (--bash COMMAND | --http METHOD URL)
        exits 0 with an attributed observation, 1 when the run was refused, 2 for a
        usage error, and 3 when no observation was recorded (the run ended first, or
        the supervisor refused the harness's observation line)
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
from agent_in_a_box.contracts import LaunchRefused, plain
from agent_in_a_box.experiments import bundle as bundles
from agent_in_a_box.network.fixture_service import REFUSAL, VARIANT_DIR

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


def probe(args: argparse.Namespace) -> int:
    """Run one tool call as the workload under a policy, then show the evidence each
    layer left, the way chapter 4's probe table reads it (CURRICULUM.md)."""
    from agent_in_a_box.experiments import scenario
    from agent_in_a_box.policy import schema

    runtime = runtime_for(args)
    if runtime.backend is None:
        print(f"Refused: {runtime.backend_refusal}. Use --test-backend for the test double.")
        return 1
    if runtime.backend.name == "none":
        print("Test backend: nothing is contained; every record says enforcement: none.")

    def tool_call(route):
        if args.http:
            return {"name": "http", "arguments": {"method": args.http[0], "url": args.http[1]}}
        command = args.bash.replace("{direct}", f"{route.host}:{route.port}")
        return {"name": "bash", "arguments": {"command": command}}

    try:
        record = scenario.run(runtime, schema.load_variant(args.policy), variant=args.variant,
                              probe=tool_call, deadline_s=args.deadline)
    except LaunchRefused as refusal:
        print(f"refused: {refusal}")
        return 1
    print(f"run {record.run_id}: {record.status} [enforcement: {record.enforcement}; "
          f"policy {args.policy}; fixture variant {args.variant}]")
    if record.status != "completed":
        print(f"refused: {record.refusal}")
        return 1
    by_kind = {kind: [plain(e.payload) for e in record.events if e.kind == kind]
               for kind in ("agent.observation", "proxy.decision", "fixture.receipt")}
    if not by_kind["agent.observation"]:
        print(no_observation(record, args.deadline))
        return 3
    observation = by_kind["agent.observation"][0]["data"]["observation"]
    print(f"observation: {'ok' if observation['ok'] else 'not ok'}; "
          f"detail {json.dumps(observation['detail'])}")
    for line in observation["output"].splitlines()[:40]:
        print(f"  | {line}")
    for decision in by_kind["proxy.decision"]:
        last = decision["checks"][-1]
        determining = last["decision"]["determining"] if last["decision"] else []
        named = f"; determining {', '.join(determining)}" if determining else ""
        print(f"proxy decision {decision['seq']}: {decision['label']} at check "
              f"'{last['name']}'{named}; {last['detail']}")
    print(f"fixture receipts: {len(by_kind['fixture.receipt'])}")
    print(f"layer: {layer(observation, by_kind['proxy.decision'], by_kind['fixture.receipt'])}")
    return 0


def no_observation(record, deadline: float) -> str:
    """Why there is nothing to attribute. The lifecycle events decide how the run ended;
    a line the supervisor refused is reported beside that, since the workload's own
    output is agent-reported and must not override a lifecycle fact."""
    by_kind = {event.kind: plain(event.payload) for event in record.events}
    refused_line = ("oversized" if "agent.oversized" in by_kind
                    else "not a JSON event" if "agent.text" in by_kind else None)
    if "deadline_reached" in by_kind:
        ending = f"ran out of time (deadline {deadline:g}s) before the tool call returned"
    elif "workload_exited" not in by_kind:
        ending = "the workload was stopped before the tool call returned"
    elif by_kind["workload_exited"]["exit_status"] == 0 and refused_line:
        ending = (f"the tool call returned, but the supervisor refused the harness's "
                  f"observation line as {refused_line}")
        refused_line = None
    else:
        status = by_kind["workload_exited"]["exit_status"]
        how = f"ended by signal {-status}" if status < 0 else f"exited with status {status}"
        if status > 128:
            how += " (a status above 128 is usually 128 plus the number of a signal)"
        ending = f"the workload {how} before the tool call returned"
    text = f"no observation: {ending}; nothing to attribute"
    if refused_line:
        text += ("; the harness's stdout also carried a line the supervisor refused as "
                 f"{refused_line}")
    if "agent.stderr" in by_kind:
        tail = by_kind["agent.stderr"]["text"].strip().splitlines()[-8:]
        text += "\nthe workload's stderr ends with:\n" + "\n".join(f"  | {line}" for line in tail)
    return text


def layer(observation: dict, decisions: list[dict], receipts: list[dict]) -> str:
    """Which layer the evidence points at, by chapter 4's checklist: a proxy decision
    record, a fixture receipt, and the observation's own errno or exit status.

    The proxy's checks run in order: protocol, connect (Cedar), route, request
    (Cedar). A refusal names the check that failed, so a route refusal is one
    Cedar's connection decision allowed and the proxy's derived routes did not.
    """
    refused = [decision for decision in decisions if decision["label"] == "refused"]
    if refused:
        last = refused[0]["checks"][-1]
        determining = last["decision"]["determining"] if last["decision"] else []
        if last["name"] == "protocol":
            return f"the proxy refused it before asking Cedar: {last['detail']}"
        if last["name"] == "route":
            return ("Cedar allowed the connection, but the proxy had no route for that "
                    f"endpoint: {last['detail']}")
        if determining:
            return (f"the proxy refused it at the {last['name']} check: the determining "
                    f"policies are {', '.join(determining)}")
        return (f"the proxy refused it at the {last['name']} check: no permit matched, so "
                "Cedar's default deny applied")
    if decisions and not receipts:
        return ("allowed by the proxy, but the fixture left no receipt: it refused the request "
                "before reading it, or the forward failed; read the observation's status or error")
    if decisions:
        if observation["ok"]:
            return "allowed by the proxy and answered by the fixture"
        return f"allowed by the proxy; {application_answer(observation)}: nothing refused it"
    if reached_the_fixture(observation):
        return ("no proxy event: the request reached the fixture directly, which refused it "
                "for lacking the proxy's stamp. Nothing stood between the workload and the "
                "host network")
    if answered_with(observation, 407):
        return ("no proxy event: the request reached the proxy without the run's credential "
                "and was answered 407; nothing was decided or recorded")
    if observation["ok"]:
        return "no proxy event: the kernel permitted the operation"
    return ("no proxy event and no receipt: the kernel stopped it, or the program itself "
            "failed; read the errno, exit status, or error")


def application_answer(observation: dict) -> str:
    """What the application said, as the tool recorded it: a status for the http tool, or
    the program's exit status when a shell command carried the request."""
    status = observation["detail"].get("status")
    if status is not None:
        return f"the application answered {status}"
    exit_status = observation["detail"].get("exit_status")
    return f"the application answered, and the program exited {exit_status}"


def answered_with(observation: dict, status: int) -> bool:
    """Whether a server answered `status` with no proxy decision involved: the http tool
    records the status, and curl under --fail exits 22 and names it."""
    detail = observation["detail"]
    if detail.get("status") == status and not detail.get("refused_by"):
        return True
    return str(status) in observation["output"] and detail.get("exit_status") == 22


def reached_the_fixture(observation: dict) -> bool:
    """A 403 with no proxy decision is the fixture's own answer to a request that did not
    come through the proxy: the connection itself succeeded. So is the fixture's refusal
    sentence as a whole line of the output, which is how curl prints the answer's body
    when it is not told to fail on it. A command that merely prints the sentence, or
    reads the fixture's source, would be taken for one; the status and exit code are the
    firmer evidence."""
    body_line = REFUSAL in observation["output"].splitlines()
    return body_line or answered_with(observation, 403)


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
    from agent_in_a_box.policy import schema

    parser = argparse.ArgumentParser(prog="agent-in-a-box", description=__doc__.splitlines()[0])
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE),
                        help="where runs, commands, bundles, and gateway state live")
    commands = parser.add_subparsers(dest="command", required=True)

    def with_backend(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--test-backend", action="store_true",
                       help="use the NoEnforcementBackend test double (enforcement: none)")
        return p

    with_backend(commands.add_parser("doctor")).set_defaults(run=doctor)
    probing = with_backend(commands.add_parser(
        "probe", help="run one bash command or HTTP request as the workload, then attribute it"))
    probing.add_argument("--policy", default="P0", choices=schema.variant_names(),
                         help="policy variant")
    probing.add_argument("--variant", default="default", help="fixture variant",
                         choices=sorted(path.stem for path in VARIANT_DIR.glob("*.json")))
    probing.add_argument("--deadline", type=float, default=30.0)
    what = probing.add_mutually_exclusive_group(required=True)
    what.add_argument("--bash", metavar="COMMAND",
                      help="a shell command; {direct} becomes the fixture's own host:port")
    what.add_argument("--http", nargs=2, metavar=("METHOD", "URL"),
                      help="an HTTP request through the proxy")
    probing.set_defaults(run=probe)
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
