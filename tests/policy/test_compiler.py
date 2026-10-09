"""The filesystem subset compiler: accepted shapes, rejected shapes, placement.

Expectations are authored by hand from PLAN.md, Filesystem grant extraction:
a filesystem policy is accepted only when an allow-list kernel profile can
enforce exactly what it says, and rejected at load otherwise.
"""

from __future__ import annotations

import os

import pytest

from agent_in_a_box.contracts import Access, Extent
from agent_in_a_box.policy import compiler, schema
from agent_in_a_box.policy.compiler import PolicyRejected, compile_policy
from agent_in_a_box.supervisor.grants import place_grants
from agent_in_a_box.policy.evaluator import CedarpyEvaluator

EV = CedarpyEvaluator()
READ = 'Sandbox::Action::"ReadFile"'
WRITE = 'Sandbox::Action::"WriteFile"'


def compile_text(text: str):
    return compile_policy(schema.bundle_from_text("test", text), EV)


def grants(text: str) -> list[tuple[str, str]]:
    return [(g.logical, g.access.value) for g in compile_text(text).grants]


def test_p0_grants_read_and_write_separately():
    compiled = compile_policy(schema.load_variant("P0"), EV)
    assert [(g.logical, g.access, g.policy_ids) for g in compiled.grants] == [
        ("/workspace/measurements.csv", Access.READ, ("read-measurements",)),
        ("/workspace/results", Access.WRITE, ("write-results",)),
    ]


def test_write_only_grant_stays_write_only():
    """A WriteFile-only policy is never widened into a read-and-write grant."""
    text = f'@id("w")\npermit (principal, action == {WRITE}, ' \
           'resource in Sandbox::FilesystemPath::"/workspace/out");'
    assert grants(text) == [("/workspace/out", "write")]


def test_when_clause_of_resource_in_tests():
    text = (f'@id("rw")\npermit (principal is Sandbox::Process, action in [{READ}, {WRITE}], '
            'resource) when { resource in Sandbox::FilesystemPath::"/workspace/a" || '
            'resource in Sandbox::FilesystemPath::"/workspace/b" };')
    assert grants(text) == [("/workspace/a", "read"), ("/workspace/a", "write"),
                            ("/workspace/b", "read"), ("/workspace/b", "write")]


@pytest.mark.parametrize(("text", "reason"), [
    (f'forbid (principal, action == {READ}, resource in Sandbox::FilesystemPath::"/workspace/a");',
     "forbid on files"),
    ("permit (principal, action, resource);", "only ReadFile and/or WriteFile"),
    (f'permit (principal, action == {READ}, resource == Sandbox::FilesystemPath::"/workspace/a");',
     "`resource ==`"),
    (f'permit (principal == Sandbox::Process::"current", action == {READ}, '
     'resource in Sandbox::FilesystemPath::"/workspace/a");', "whole process tree"),
    (f'permit (principal, action == {READ}, resource in Sandbox::FilesystemPath::"/workspace/a") '
     "when { context has x };", "conditions"),
    (f'permit (principal, action == {READ}, resource) when '
     '{ resource in Sandbox::FilesystemPath::"/workspace/a" && true };', "one `when`"),
    (f'permit (principal, action == {READ}, resource in Sandbox::FilesystemPath::"/etc");',
     "outside the task root"),
    (f'permit (principal, action == {READ}, '
     'resource in Sandbox::FilesystemPath::"/workspace/../etc");', "not normalized"),
    (f'permit (principal, action == {READ}, resource in Sandbox::FilesystemPath::"/workspace/");',
     "not normalized"),
    ('permit (principal, action == Sandbox::Action::"NetworkConnect", '
     'resource == Sandbox::NetworkEndpoint::"Upper.example:80");', "lowercase"),
    ('permit (principal, action == Sandbox::Action::"NetworkConnect", '
     'resource == Sandbox::NetworkEndpoint::"example:0");', "1..65535"),
])
def test_rejected_shapes(text, reason):
    with pytest.raises(PolicyRejected) as info:
        compile_text('@id("p")\n' + text)
    assert reason in str(info.value)


def test_schema_errors_are_rejected_at_load():
    with pytest.raises(PolicyRejected) as info:
        compile_text('@id("p")\npermit (principal, action == Sandbox::Action::"HttpRequest", '
                     "resource) when { context.binary_path == \"/bin/sh\" };")
    assert "binary_path" in str(info.value)


def test_reserved_domain_ids():
    with pytest.raises(PolicyRejected):
        compile_text('@id("domain:D")\npermit (principal, action == Sandbox::Action::'
                     '"NetworkConnect", resource == Sandbox::NetworkEndpoint::"a.example:80");')


def test_routes_come_only_from_literal_connect_scopes():
    assert [e.endpoint for e in compile_policy(schema.load_variant("P0"), EV).proxy.eligible] == [
        "reference.fixture:80"]
    assert compile_policy(schema.load_variant("P6"), EV).proxy.eligible == ()


def test_placement_uses_canonical_paths(tmp_path):
    workspace = tmp_path / "ws"
    (workspace / "results").mkdir(parents=True)
    placed = place_grants(compile_policy(schema.load_variant("P0"), EV), str(workspace))
    root = os.path.realpath(workspace)
    assert [(g.path, g.access, g.extent, g.logical) for g in placed] == [
        (f"{root}/measurements.csv", Access.READ, Extent.SUBTREE, "/workspace/measurements.csv"),
        (f"{root}/results", Access.WRITE, Extent.SUBTREE, "/workspace/results"),
    ]


def test_symlink_leaving_the_workspace_is_rejected(tmp_path):
    workspace, outside = tmp_path / "ws", tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "results").symlink_to(outside)
    with pytest.raises(PolicyRejected) as info:
        place_grants(compile_policy(schema.load_variant("P0"), EV), str(workspace))
    assert "outside the workspace" in str(info.value)


@pytest.mark.parametrize("path", ["/workspace\nx", "relative", "/workspace/a/./b", "//workspace"])
def test_logical_path_checks(path):
    assert compiler.check_logical_path(path) is not None


# More shapes, each derived from a rule stated in PLAN.md (Filesystem grant
# extraction; Network mediation; Scope limits): the kernel profile is an
# allow-list fixed before launch, so anything that depends on a condition,
# denies, or names something other than a whole subtree cannot be compiled.
NC = 'Sandbox::Action::"NetworkConnect"'
MORE_REJECTED = [
    ("an unless clause carves a hole an allow-list cannot express",
     f'permit (principal, action == {READ}, resource)\nunless {{ resource in '
     'Sandbox::FilesystemPath::"/workspace/secret" };'),
    ("any condition at all, even one that never holds",
     f'permit (principal, action == {READ}, resource in Sandbox::FilesystemPath::"/workspace")'
     "\nwhen { false };"),
    ("a condition on the action decides per request, not before launch",
     'permit (principal, action, resource in Sandbox::FilesystemPath::"/workspace/data")\n'
     f"when {{ action != {WRITE} }};"),
    ("a condition on the principal's attributes is not a subtree",
     f'permit (principal, action == {WRITE}, resource)\nwhen {{ resource in '
     'Sandbox::FilesystemPath::"/workspace/out" && principal.user == Sandbox::User::"root" };'),
    ("every path at once is not a subtree grant",
     f"permit (principal, action == {READ}, resource is Sandbox::FilesystemPath);"),
    ("a forbid on files, even one naming no path, cannot be enforced",
     f'permit (principal, action == {WRITE}, resource in Sandbox::FilesystemPath::"/workspace");\n'
     f'@id("q")\nforbid (principal, action == {WRITE}, resource);'),
    ("a misspelled action fails schema validation",
     'permit (principal, action == Sandbox::Action::"Writefile", resource in '
     'Sandbox::FilesystemPath::"/workspace");'),
    ("a connection permit naming a host with a trailing dot can never match a request",
     f'permit (principal, action == {NC}, resource == Sandbox::NetworkEndpoint::"a.example.:80");'),
    ("a connection permit naming no port can never match a request",
     f'permit (principal, action == {NC}, resource == Sandbox::NetworkEndpoint::"a.example");'),
]


@pytest.mark.parametrize(("why", "text"), MORE_REJECTED, ids=[row[0] for row in MORE_REJECTED])
def test_more_rejected_shapes(why, text):
    with pytest.raises(PolicyRejected):
        compile_text('@id("p")\n' + text)


ROUTES = [
    ("a forbid makes nothing reachable",
     f'@id("p")\nforbid (principal, action == {NC}, resource == '
     'Sandbox::NetworkEndpoint::"a.example:443");', []),
    ("an endpoint named only in a condition gets no route",
     f'@id("p")\npermit (principal, action == {NC}, resource is Sandbox::NetworkEndpoint)\n'
     'unless { resource == Sandbox::NetworkEndpoint::"a.example:443" };', []),
    ("each named port is its own route",
     f'@id("a")\npermit (principal, action == {NC}, resource == '
     'Sandbox::NetworkEndpoint::"a.example:443");\n'
     f'@id("b")\npermit (principal, action == {NC}, resource == '
     'Sandbox::NetworkEndpoint::"a.example:8443");', ["a.example:443", "a.example:8443"]),
    ("a file policy creates no route",
     f'@id("p")\npermit (principal, action == {READ}, resource in '
     'Sandbox::FilesystemPath::"/workspace");', []),
]


@pytest.mark.parametrize(("why", "text", "routes"), ROUTES, ids=[row[0] for row in ROUTES])
def test_routes(why, text, routes):
    compiled = compile_text(text)
    assert [eligible.endpoint for eligible in compiled.proxy.eligible] == routes


def test_network_policies_grant_no_paths():
    text = (f'@id("p")\npermit (principal, action == {NC}, resource is Sandbox::NetworkEndpoint)'
            '\nwhen { resource.host_port == "a.example:443" };')
    assert grants(text) == []
