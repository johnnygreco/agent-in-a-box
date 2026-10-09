"""Self-test of the conformance suite's own code, under the test backend.

This checks that the probe table builds tool calls and that check_expected
reads run evidence correctly, so the suite's first native run fails only
for native reasons. Only probes whose expectation does not depend on a
kernel boundary run here; nothing in this file is boundary evidence.
"""

from __future__ import annotations

import pytest

from agent_in_a_box import composition
from tests.backends.conformance.test_conformance import (
    PROBES, check_expected, probe_paths, run_probe,
)

NO_BOUNDARY_NEEDED = {
    "read a granted file",
    "GET through the proxy",
    "POST through the proxy under P0",
    "GET through the proxy when the fixture has no data",
    "detach and sleep",
}


@pytest.mark.parametrize("probe", [probe for probe in PROBES if probe.name in NO_BOUNDARY_NEEDED],
                         ids=lambda probe: probe.name)
def test_suite_machinery(probe, tmp_path):
    config = composition.RuntimeConfig(backend="none", allow_test_backend=True,
                                       runs_dir=tmp_path / "runs")
    record = run_probe(composition.assemble(config), probe, tmp_path)
    assert record.enforcement == "none"
    check_expected(record, probe, probe_paths(tmp_path))


def test_every_probe_in_the_curriculum_table_is_in_the_suite():
    from agent_in_a_box.policy.schema import REPO_ROOT

    table = (REPO_ROOT / "CURRICULUM.md").read_text().split("## Controlled probes", 1)[1]
    table = table.split("\n## ", 1)[0]
    rows = [line.split("|")[1].strip() for line in table.splitlines()
            if line.startswith("| ") and not line.startswith("| Probe") and "---" not in line]
    names = {probe.name.lower() for probe in PROBES}
    for row in rows:
        assert row.split(" (variant")[0].lower() in names, row
