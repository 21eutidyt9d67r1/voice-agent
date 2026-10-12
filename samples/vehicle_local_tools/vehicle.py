"""Allowlisted vehicle tools backed only by an in-memory simulator."""

from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import dataclass, field
from typing import Any

SEARCH_TOOL = "search_vehicle_tools"
SEARCH_TAGS = {
    "get_vehicle_status": "read current status state settings overview cabin temperature media volume navigation destination",
    "set_cabin_temperature": "climate cabin temperature heat heating warm warmer cool cooler cooling air conditioning ac celsius",
    "set_media_volume": "media music audio sound volume louder quieter loud quiet mute stereo",
    "start_navigation": "navigate navigation directions destination route map address travel go drive library",
}


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def search_tool() -> dict[str, Any]:
    return {
        "type": "function", "name": SEARCH_TOOL,
        "description": (
            "Search the trusted local vehicle capability catalog by intent. "
            "Returns up to three matching function definitions. Search before using "
            "a vehicle function that is not currently available."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 200}},
            "required": ["query"], "additionalProperties": False,
        },
    }


def search(query: str, available: frozenset[str]) -> list[dict[str, Any]]:
    if (
        not isinstance(query, str) or not query.strip() or len(query) > 200
        or any(ord(character) < 32 or ord(character) == 127 for character in query)
    ):
        raise ToolRejected("query must be 1 to 200 characters without control characters.")
    terms = set(re.findall(r"[a-z0-9]+", query.lower())) - {
        "a", "an", "the", "to", "of", "and", "my", "me", "please", "tool", "tools",
        "set", "get", "can", "you", "i", "want", "use", "with", "for",
    }
    ranked = []
    for tool in tools():
        if tool["name"] not in available:
            continue
        fields = [
            (tool["name"].replace("_", " "), 4),
            (SEARCH_TAGS[tool["name"]], 3),
            (tool["description"], 1),
        ]
        score = sum(len(terms & set(re.findall(r"[a-z0-9]+", text.lower()))) * weight for text, weight in fields)
        if score:
            ranked.append((score, tool))
    ranked.sort(key=lambda item: (-item[0], item[1]["name"]))
    return [tool for _score, tool in ranked[:3]]


def tools() -> list[dict[str, Any]]:
    specifications = [
        ("get_vehicle_status", "Read the simulated cabin, media, and navigation state.", {}),
        ("set_cabin_temperature", "Set simulated cabin temperature in degrees Celsius.", {
            "temperature_c": {"type": "number", "minimum": 16, "maximum": 30},
        }),
        ("set_media_volume", "Set simulated media volume from 0 to 60 percent.", {
            "volume_percent": {"type": "integer", "minimum": 0, "maximum": 60},
        }),
        ("start_navigation", "Set a simulated destination, not a real route or ETA.", {
            "destination": {"type": "string", "minLength": 1, "maxLength": 200},
        }),
    ]
    return [{
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False,
        },
    } for name, description, properties in specifications]


class ToolRejected(ValueError):
    """A local policy or argument validation rejection."""


@dataclass
class SimulatedVehicle:
    temperature_c: float = 21.0
    volume_percent: int = 20
    destination: str | None = None

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        expected = {
            "get_vehicle_status": set(),
            "set_cabin_temperature": {"temperature_c"},
            "set_media_volume": {"volume_percent"},
            "start_navigation": {"destination"},
        }
        if name not in expected:
            raise ToolRejected("This function is not permitted by the local vehicle.")
        if set(arguments) != expected[name]:
            raise ToolRejected("Arguments must match the local tool contract exactly.")
        if name == "set_cabin_temperature":
            value = arguments["temperature_c"]
            if type(value) not in (int, float) or not 16 <= value <= 30 or not math.isfinite(value):
                raise ToolRejected("temperature_c must be a finite number from 16 to 30.")
            self.temperature_c = float(value)
        elif name == "set_media_volume":
            value = arguments["volume_percent"]
            if type(value) is not int or not 0 <= value <= 60:
                raise ToolRejected("volume_percent must be an integer from 0 to 60.")
            self.volume_percent = value
        elif name == "start_navigation":
            value = arguments["destination"]
            if (
                not isinstance(value, str) or not value.strip() or len(value) > 200
                or any(ord(character) < 32 or ord(character) == 127 for character in value)
            ):
                raise ToolRejected("destination must be 1 to 200 characters without control characters.")
            self.destination = value.strip()
        return {
            "ok": True, "simulated": True,
            "state": {
                "temperature_c": self.temperature_c,
                "volume_percent": self.volume_percent,
                "destination": self.destination,
            },
        }


def parse_arguments(raw: str) -> dict[str, Any]:
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ToolRejected("Duplicate argument keys are not permitted.")
            result[key] = value
        return result

    def reject_constant(_value):
        raise ToolRejected("Non-finite JSON numbers are not permitted.")

    if not isinstance(raw, str) or len(raw) > 4096:
        raise ToolRejected("Tool arguments must be a JSON object of at most 4096 characters.")
    try:
        arguments = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (json.JSONDecodeError, RecursionError) as error:
        raise ToolRejected("Tool arguments are not valid JSON.") from error
    if not isinstance(arguments, dict):
        raise ToolRejected("Tool arguments must be an object.")
    return arguments


@dataclass
class Dispatcher:
    vehicle: SimulatedVehicle = field(default_factory=SimulatedVehicle)
    completed: dict[str, tuple[str, str, dict[str, Any]]] = field(default_factory=dict)
    discovery: bool = False
    available: frozenset[str] = field(default_factory=lambda: frozenset(SEARCH_TAGS))
    discovered: list[str] = field(default_factory=list)

    def response_tools(self) -> list[dict[str, Any]]:
        selected = self.discovered if self.discovery else self.available
        return [search_tool(), *[tool for tool in tools() if tool["name"] in selected and tool["name"] in self.available]]

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == SEARCH_TOOL:
            if set(arguments) != {"query"}:
                raise ToolRejected("Search requires exactly one query argument.")
            matches = search(arguments["query"], self.available)
            for match in matches:
                if match["name"] in self.discovered:
                    self.discovered.remove(match["name"])
                self.discovered.append(match["name"])
            self.discovered = self.discovered[-12:]
            return {
                "ok": True, "simulated": True, "matches": matches,
                "instruction": (
                    "Matching tools are now available for the next response. Choose the "
                    "appropriate tool and validate any ambiguous user intent."
                    if matches else
                    "No local capabilities match. Explain that this capability is unavailable "
                    "or ask for clarification. Do not invent a tool or claim an action."
                ),
            }
        if name not in self.available:
            raise ToolRejected("This function is not available on the local vehicle.")
        if self.discovery and name not in self.discovered:
            raise ToolRejected("Search for this capability before executing it.")
        return self.vehicle.execute(name, arguments)

    def dispatch(self, call: dict[str, Any], *, cancelled: bool = False) -> dict[str, Any]:
        call_id, name, raw = call.get("call_id"), call.get("name"), call.get("arguments")
        if not isinstance(call_id, str) or not call_id or len(call_id) > 256:
            raise RuntimeError("A completed tool call must contain a valid call_id.")
        if not isinstance(name, str) or not isinstance(raw, str):
            raise RuntimeError("A completed tool call must contain a name and JSON arguments.")
        if call_id in self.completed:
            previous_name, previous_raw, result = self.completed[call_id]
            if (name, raw) != (previous_name, previous_raw):
                raise RuntimeError("A call_id was reused with different tool arguments.")
            return result
        if len(self.completed) >= 1000:
            raise RuntimeError("Session reached 1000 tool calls. Start a new session.")
        try:
            result = (
                {"ok": False, "simulated": True, "cancelled": True, "error": "Interrupted before local execution."}
                if cancelled else self.execute(name, parse_arguments(raw))
            )
        except ToolRejected as error:
            result = {"ok": False, "simulated": True, "error": str(error)}
        self.completed[call_id] = (name, raw, result)
        print(f"Local tool {name}: {json.dumps(result, ensure_ascii=False)}")
        return result
