"""Pure helpers for materializing portable Voice Agent definitions."""

from __future__ import annotations

from typing import Any


def materialize_handoff_instruction_inheritance(
    definition: dict[str, Any],
) -> dict[str, Any]:
    """Expand shared instructions for service versions that reject the flag."""
    handoff = definition.get("handoff")
    if not isinstance(handoff, dict):
        return definition
    nodes = handoff.get("nodes")
    if not isinstance(nodes, list):
        return definition

    base_instructions = definition.get("instructions")
    for node in nodes:
        if not isinstance(node, dict):
            continue
        config = node.get("config")
        if not isinstance(config, dict):
            continue
        inherit = config.pop("inherit_from_base_instructions", None)
        if inherit is None:
            continue
        if not isinstance(inherit, bool):
            raise ValueError(
                "handoff node inherit_from_base_instructions must be a boolean."
            )
        if not inherit:
            continue
        node_instructions = config.get("instructions")
        if base_instructions is not None and not isinstance(base_instructions, str):
            raise ValueError("Voice Agent instructions must be a string or null.")
        if node_instructions is not None and not isinstance(node_instructions, str):
            raise ValueError("Handoff node instructions must be a string or null.")
        if not node_instructions:
            config["instructions"] = base_instructions
        elif base_instructions:
            config["instructions"] = f"{base_instructions}\n\n{node_instructions}"

    return definition
