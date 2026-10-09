"""Read a policy's scope and conditions from Cedar's JSON policy format.

Cedar prints any parsed policy as JSON
(https://docs.cedarpolicy.com/policies/json-format.html). The compiler reads
that form instead of parsing policy text itself. Examples of the scope shapes
read here:

    action == A            {"op": "==", "entity": A}
    action in [A, B]       {"op": "in", "entities": [A, B]}
    resource in E          {"op": "in", "entity": E}
    resource is T in E     {"op": "is", "entity_type": T, "in": {"entity": E}}
    principal / resource   {"op": "All"}
"""

from __future__ import annotations

from typing import Any

from agent_in_a_box.policy import schema


def scope_actions(policy: dict[str, Any]) -> set[str] | None:
    """Action ids in the policy's action scope, or None when the scope is every action."""
    scope = policy["action"]
    if scope["op"] == "All":
        return None
    if "entities" in scope:
        entities = scope["entities"]
    else:
        entities = [scope["entity"]]
    return {entity["id"] for entity in entities if entity["type"] == schema.ACTION_TYPE}


def resource_may_be(policy: dict[str, Any], type_name: str) -> bool:
    """Whether the resource scope can match an entity of type `type_name`."""
    scope = policy["resource"]
    if scope["op"] == "All":
        return True
    if "entity_type" in scope:
        return scope["entity_type"] == type_name
    return scope["entity"]["type"] == type_name


def scope_entity(policy: dict[str, Any], type_name: str) -> str | None:
    """The id of the `type_name` entity named by `resource == E`, `resource in E`,
    or `resource is T in E`; None for any other resource scope."""
    scope = policy["resource"]
    if scope["op"] in ("==", "in"):
        entity = scope["entity"]
    elif scope["op"] == "is" and "in" in scope:
        entity = scope["in"]["entity"]
    else:
        return None
    if entity["type"] != type_name:
        return None
    return entity["id"]


def when_paths(policy: dict[str, Any]) -> list[str] | None:
    """The paths of a policy whose only condition is
    `when { resource in FilesystemPath::"/a" || resource in FilesystemPath::"/b" ... }`,
    or None if the policy has any other condition shape."""
    conditions = policy.get("conditions", [])
    if len(conditions) != 1 or conditions[0]["kind"] != "when":
        return None
    paths: list[str] = []
    if not collect_resource_in_paths(conditions[0]["body"], paths):
        return None
    return paths


def collect_resource_in_paths(expression: dict[str, Any], paths: list[str]) -> bool:
    """Append the path of each `resource in FilesystemPath::"..."` test in an `||`
    tree to `paths`. Return False if any part of the tree is something else."""
    if "||" in expression:
        either = expression["||"]
        left_ok = collect_resource_in_paths(either["left"], paths)
        return left_ok and collect_resource_in_paths(either["right"], paths)
    test = expression.get("in")
    if test is None or test.get("left") != {"Var": "resource"}:
        return False
    entity = test.get("right", {}).get("Value", {}).get("__entity")
    if entity is None or entity.get("type") != schema.FILESYSTEM_PATH:
        return False
    paths.append(entity["id"])
    return True
