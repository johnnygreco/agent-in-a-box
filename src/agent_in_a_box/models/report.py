"""The report the scripted agent writes, built only from what its tools returned."""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence

from agent_in_a_box.contracts import Turn

# What a report says when the agent could not get everything it wanted.
NOTES = {
    "report": None,
    "report_without_reference": "reference data was not available; the request was not allowed.",
    "report_noting_failure": "could not deliver the report to /collect through the proxy or "
    "directly.",
}


def successful_outputs(history: Sequence[Turn], tool: str, method: str | None = None) -> list[str]:
    """The output of every successful call to `tool` (for http, with `method`), in order."""
    outputs = []
    for turn in history:
        call = turn.reply.tool_call
        if call is None or call.name != tool:
            continue
        if method is not None and call.arguments.get("method") != method:
            continue
        if turn.observation is not None and turn.observation.ok:
            outputs.append(turn.observation.output)
    return outputs


def mean_lines(measurements_csv: str) -> list[str]:
    rows = list(csv.DictReader(io.StringIO(measurements_csv)))
    lines = []
    for column in ("temperature_c", "pressure_kpa"):
        values = [float(row[column]) for row in rows if row.get(column)]
        if values:
            mean = sum(values) / len(values)
            lines.append(f"Mean {column}: {mean:.2f} ({len(values)} samples)")
    return lines


def write_report(history: Sequence[Turn], note: str | None = None) -> str:
    """Summarize the measurements, with the reference data if a GET succeeded."""
    lines = ["# Measurement report", ""]
    measurements = successful_outputs(history, "read_file")
    if measurements:
        lines += mean_lines(measurements[0])
    reference = successful_outputs(history, "http", "GET")
    if reference:
        lines += ["", "Reference data:", "", reference[-1].strip()]
    if note:
        lines += ["", f"Note: {note}"]
    return "\n".join(lines) + "\n"
