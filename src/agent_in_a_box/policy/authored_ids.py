"""Determining-policy extraction: report Cedar's answer by the names authors wrote.

Cedar names parsed policies policy0, policy1, ... in source order, and its
determining-policy list ("reasons") and error messages use those positional
ids. Learners need the authored names, so every policy must carry
@id("...") and this module maps one onto the other.
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass

import cedarpy

POSITIONAL_ID = re.compile(r"`(policy\d+)`")


class PolicyIdError(ValueError):
    """A policy has no @id, or two policies share one."""


@dataclass(frozen=True)
class ParsedPolicies:
    policy_set: cedarpy.PolicySet
    names: dict[str, str]  # Cedar's positional id (policy0, ...) -> the authored @id
    json: dict[str, dict]  # positional id -> the policy in Cedar's JSON format


@functools.lru_cache(maxsize=64)
def parse(policy_text: str) -> ParsedPolicies:
    """Parse once per distinct policy text, and require an @id on every policy."""
    policies_json = json.loads(cedarpy.policies_to_json_str(policy_text))["staticPolicies"]
    names = {}
    for positional_id, policy in policies_json.items():
        authored_id = policy.get("annotations", {}).get("id")
        if not authored_id:
            raise PolicyIdError(f"every policy needs an @id(\"...\") annotation; {positional_id} "
                                "has none")
        names[positional_id] = authored_id
    if len(set(names.values())) != len(names):
        raise PolicyIdError("two policies share an @id")
    return ParsedPolicies(cedarpy.PolicySet.from_str(policy_text), names, policies_json)


def determining(reasons: list[str], names: dict[str, str]) -> tuple[str, ...]:
    """Cedar's determining policies, by authored @id, sorted."""
    return tuple(sorted(names.get(policy_id, policy_id) for policy_id in reasons))


def with_authored_ids(message: str, names: dict[str, str]) -> tuple[str | None, str]:
    """Rewrite Cedar's positional policy ids in a message to the authored @ids.
    Returns the first policy id mentioned (or None) and the rewritten message."""
    first = POSITIONAL_ID.search(message)
    first_id = names.get(first[1]) if first else None
    for positional_id in POSITIONAL_ID.findall(message):
        authored_id = names.get(positional_id, positional_id)
        message = message.replace(f"`{positional_id}`", f"`{authored_id}`")
    return first_id, message
