# Copyright (c) Microsoft. All rights reserved.
"""Language-aware Azure voice selection using the selected project's regional catalog."""

from __future__ import annotations

import copy
import json
import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import requests
from aiohttp import web
from azure.core.exceptions import AzureError

if TYPE_CHECKING:
    from common import AgentsConfig

logger = logging.getLogger(__name__)
# The checked-in priorities serve config, Editor, and runtime voice selection.
VOICE_PRESETS = json.loads((Path(__file__).parent / "static" / "voice-presets.json").read_text(encoding="utf-8"))
# Refresh successful regional catalog/region lookups after ten minutes.
CATALOG_TTL_SECONDS = 600
# Limit public catalog requests so a failed lookup does not stall publication.
CATALOG_TIMEOUT_SECONDS = 20


class VoicePolicyError(ValueError):
    """A selection error that the UI must display instead of silently defaulting."""

    def __init__(self, message: str, *, code: str = "voice_unavailable") -> None:
        super().__init__(message)
        self.code = code


def normalize_language(language: str) -> str:
    """Normalize an explicit locale.

    Parameters
    ----------
    language : str
        Language and region, such as ``hi-IN``.

    Returns
    -------
    str
        Canonical language-region spelling.

    Raises
    ------
    VoicePolicyError
        If a language-region locale was not supplied.
    """
    if not re.fullmatch(r"[a-zA-Z]{2,3}-[a-zA-Z]{2}", language):
        raise VoicePolicyError("Choose a language-region locale, for example hi-IN.", code="invalid_voice_language")
    primary, region = language.split("-")
    return f"{primary.lower()}-{region.upper()}"


def _voice_name(value: Any) -> str:
    return str(value.get("name") or "") if isinstance(value, dict) else str(value or "")


def _supports_language(voice: dict[str, Any], language: str) -> bool:
    locales = [voice.get("Locale"), *(voice.get("SecondaryLocaleList") or [])]
    return any(str(locale).casefold() == language.casefold() for locale in locales)


def _voice_gender(name: str, voices: list[dict[str, Any]]) -> str:
    for voice in voices:
        if str(voice["ShortName"]).casefold() == name.casefold():
            return str(voice.get("Gender") or "Female")
    for genders in VOICE_PRESETS.values():
        for gender, names in genders.items():
            if name.casefold() in [candidate.casefold() for candidate in names]:
                return gender
    return "Female"


@dataclass(frozen=True)
class VoiceResolution:
    """The selected voice and the reason for an observable substitution."""

    language: str
    gender: str
    requested: str
    selected: str

    def as_dict(self, target: str) -> dict[str, Any]:
        """Return a UI-safe selection report.

        Parameters
        ----------
        target : str
            Definition field that was checked.

        Returns
        -------
        dict[str, Any]
            Selected voice, changed flag, and user-visible explanation.
        """
        changed = self.requested != self.selected
        return {
            "target": target,
            "language": self.language,
            "gender": self.gender,
            "requested_voice": self.requested,
            "voice": self.selected,
            "changed": changed,
            "reason": (
                f"Using {self.selected} for {self.language}; the preferred voice is unavailable or another language was selected."
                if changed
                else "The selected voice is listed for this region and language."
            ),
        }


def select_voice(
    voices: list[dict[str, Any]],
    *,
    language: str,
    requested: str = "",
    gender: str = "",
    automatic: bool = False,
) -> VoiceResolution:
    """Select a catalog-listed voice without falling back to an unrelated language.

    Parameters
    ----------
    voices : list[dict[str, Any]]
        Regional Azure voice catalog.
    language : str
        Output locale.
    requested : str
        Authored or explicitly selected voice.
    gender : str
        Optional Female/Male preference; otherwise preserve the authored voice.
    automatic : bool
        Prefer the language's preset over an available authored voice.

    Returns
    -------
    VoiceResolution
        Selection, retaining preferred spelling when the catalog differs only in case.

    Raises
    ------
    VoicePolicyError
        If the locale, gender, or available catalog cannot satisfy the request.
    """
    language = normalize_language(language)
    gender = gender or _voice_gender(requested, voices)
    if gender not in {"Female", "Male"}:
        raise VoicePolicyError("Voice preference must be Female or Male.", code="invalid_voice_gender")
    available = {str(voice["ShortName"]).casefold(): voice for voice in voices if _supports_language(voice, language)}
    priorities = VOICE_PRESETS.get(language, {}).get(gender, [])
    candidates = list(priorities) if automatic else [requested, *priorities]
    # Native-locale GA voices precede multilingual and preview last-resort voices.
    remaining = sorted(
        available.values(),
        key=lambda voice: (
            str(voice.get("Locale")).casefold() != language.casefold(),
            voice.get("Gender") != gender,
            voice.get("Status") != "GA",
            str(voice["ShortName"]),
        ),
    )
    candidates.extend(str(voice["ShortName"]) for voice in remaining)
    for name in candidates:
        if name.casefold() in available:
            logger.info("Voice selection: locale=%s changed=%s", language, name != requested)
            return VoiceResolution(language, gender, requested, name)
    logger.error("No catalog-listed voice supports locale=%s", language)
    raise VoicePolicyError(
        f"No available Azure voice supports {language} in this region. Select another region or language."
    )


@dataclass
class VoicePolicy:
    """Successful public catalogs are cached; failures are never cached as empty success."""

    discover_projects: Callable[[AgentsConfig, str], list[dict[str, str]]]
    _regions: dict[str, tuple[float, str]] = field(default_factory=dict, repr=False)
    _catalogs: dict[str, tuple[float, list[dict[str, Any]]]] = field(default_factory=dict, repr=False)
    _lock: Any = field(default_factory=threading.Lock, repr=False)

    def region(self, cfg: AgentsConfig, override: str = "") -> str:
        """Resolve the selected project region or require an explicit override.

        Parameters
        ----------
        cfg : AgentsConfig
            Browser-selected project configuration.
        override : str
            User-provided Azure region when management-plane discovery is unavailable.

        Returns
        -------
        str
            A validated Azure region name, not an arbitrary catalog hostname.

        Raises
        ------
        VoicePolicyError
            If the project region cannot be discovered or the override is invalid.
        """
        if override:
            return self._validate_region(override)
        with self._lock:
            cached = self._regions.get(cfg.host)
        if cached and time.monotonic() - cached[0] < CATALOG_TTL_SECONDS:
            logger.debug("Using cached project voice region")
            return cached[1]
        try:
            matches = [item for item in self.discover_projects(cfg, cfg.host) if item["endpoint"] == cfg.host]
        except (requests.RequestException, AzureError, RuntimeError) as error:
            logger.error("Voice region discovery failed: %s", type(error).__name__)
            raise VoicePolicyError(
                "Cannot read the project region. Enter its Azure region to check voices.", code="voice_region_unknown"
            ) from error
        regions = {item.get("region") for item in matches if item.get("region")}
        if len(regions) != 1:
            logger.error("Voice region discovery returned no unique region")
            raise VoicePolicyError(
                "Project region is unknown. Enter its Azure region to check voices.", code="voice_region_unknown"
            )
        region = self._validate_region(str(regions.pop()))
        with self._lock:
            self._regions[cfg.host] = (time.monotonic(), region)
        logger.info("Resolved voice region=%s", region)
        return region

    def _validate_region(self, region: str) -> str:
        normalized = region.strip().lower().replace(" ", "")
        if not re.fullmatch(r"[a-z][a-z0-9]{1,40}", normalized):
            raise VoicePolicyError("Enter an Azure region such as westus2.", code="invalid_voice_region")
        return normalized

    def catalog(self, region: str) -> list[dict[str, Any]]:
        """Fetch a regional Azure catalog without credentials or redirects.

        Parameters
        ----------
        region : str
            Azure public-cloud region.

        Returns
        -------
        list[dict[str, Any]]
            Nonempty validated catalog.

        Raises
        ------
        VoicePolicyError
            If the endpoint fails or its catalog is empty/malformed.
        """
        region = self._validate_region(region)
        with self._lock:
            cached = self._catalogs.get(region)
        if cached and time.monotonic() - cached[0] < CATALOG_TTL_SECONDS:
            logger.debug("Using cached regional voice catalog: region=%s", region)
            return cached[1]
        logger.debug("Fetching public voice catalog for region=%s", region)
        try:
            response = requests.get(
                f"https://{region}.tts.speech.microsoft.com/synthesize/list/cognitive-service/voices",
                params={"showHidden": "true"},
                timeout=CATALOG_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
            response.raise_for_status()
            voices = response.json()
            if response.is_redirect or not isinstance(voices, list) or not voices:
                raise ValueError("Empty or invalid catalog")
            if any(
                not isinstance(voice, dict) or not voice.get("ShortName") or not voice.get("Locale") for voice in voices
            ):
                raise ValueError("Malformed catalog entry")
        except (requests.RequestException, ValueError) as error:
            logger.error("Voice catalog lookup failed: region=%s error=%s", region, type(error).__name__)
            raise VoicePolicyError(
                "Cannot check regional voice availability. Retry; no voice was silently substituted.",
                code="voice_catalog_unavailable",
            ) from error
        with self._lock:
            self._catalogs[region] = (time.monotonic(), voices)
        return voices

    def resolve(self, cfg: AgentsConfig, body: dict[str, Any]) -> dict[str, Any]:
        """Resolve root and standard handoff voices in a copy of an authored definition.

        Parameters
        ----------
        cfg : AgentsConfig
            Selected project.
        body : dict[str, Any]
            Definition, optional language/gender/region, and automatic/fallback mode.

        Returns
        -------
        dict[str, Any]
            Copied definition, resolved region, and substitution reports.

        Raises
        ------
        VoicePolicyError
            Invalid selection or unavailable regional voices.
        """
        definition = body.get("definition")
        if not isinstance(definition, dict) or definition.get("kind") != "voice":
            raise VoicePolicyError("A voice Agent definition is required.", code="invalid_voice_definition")
        self._validate_selection(body, definition)
        mode = body.get("mode", "fallback")
        if mode not in {"automatic", "fallback"}:
            raise VoicePolicyError("Voice mode must be automatic or fallback.", code="invalid_voice_mode")
        if mode == "automatic" and definition.get("model") == "azure-realtime":
            raise VoicePolicyError(
                "Azure Realtime uses native voices; select its native voice explicitly.", code="unsupported_voice_type"
            )
        if mode == "fallback" and not self._needs_catalog(definition, body):
            logger.info("Authored native/custom voice retained; Azure standard fallback does not apply")
            return {"definition": copy.deepcopy(definition), "region": "", "resolutions": []}
        region = self.region(cfg, str(body.get("region") or ""))
        voices = self.catalog(region)
        resolved = copy.deepcopy(definition)
        output = resolved.setdefault("audio", {}).setdefault("output", {})
        reports = self._resolve_output(output, body, voices, automatic=mode == "automatic")
        reports.extend(self._resolve_nodes(resolved, body, voices, automatic=mode == "automatic"))
        return {"definition": resolved, "region": region, "resolutions": reports}

    def _resolve_nodes(
        self,
        resolved: dict[str, Any],
        body: dict[str, Any],
        voices: list[dict[str, Any]],
        *,
        automatic: bool,
    ) -> list[dict[str, Any]]:
        reports = []
        for node in (resolved.get("handoff") or {}).get("nodes", []):
            config = node.get("config") or {}
            if "voice" not in config:
                continue
            node_settings = {key: value for key, value in body.items() if key != "voice"}
            node_reports = self._resolve_output(config, node_settings, voices, automatic=automatic)
            for report in node_reports:
                report["target"] = f"handoff.nodes[{node['id']}].config.voice"
            reports.extend(node_reports)
        return reports

    def _validate_selection(self, body: dict[str, Any], definition: dict[str, Any]) -> None:
        for field_name in ("mode", "voice", "language", "gender", "region"):
            if field_name in body and not isinstance(body[field_name], str):
                raise VoicePolicyError(f"{field_name} must be a string.", code="invalid_voice_request")
        audio = definition.get("audio", {})
        if not isinstance(audio, dict) or not isinstance(audio.get("output", {}), dict):
            raise VoicePolicyError("audio.output must be an object.", code="invalid_voice_definition")
        self._validate_voice_output(audio.get("output", {}))
        input_audio = audio.get("input", {})
        if not isinstance(input_audio, dict) or not isinstance(input_audio.get("transcription", {}), dict):
            raise VoicePolicyError("audio.input.transcription must be an object.", code="invalid_voice_definition")
        handoff = definition.get("handoff", {})
        if not isinstance(handoff, dict) or not isinstance(handoff.get("nodes", []), list):
            raise VoicePolicyError("handoff.nodes must be an array.", code="invalid_voice_definition")
        for node in handoff.get("nodes", []):
            if not isinstance(node, dict) or not node.get("id") or not isinstance(node.get("config", {}), dict):
                raise VoicePolicyError(
                    "Each handoff node needs an id and a config object.", code="invalid_voice_definition"
                )
            self._validate_voice_output(node.get("config", {}))

    def _validate_voice_output(self, output: dict[str, Any]) -> None:
        voice = output.get("voice")
        if voice is not None and not isinstance(voice, (str, dict)):
            raise VoicePolicyError("voice must be a name or descriptor object.", code="invalid_voice_definition")
        if isinstance(voice, dict):
            if not isinstance(voice.get("name"), str):
                raise VoicePolicyError("A voice descriptor needs a name.", code="invalid_voice_definition")
            if voice.get("type") is not None and not isinstance(voice["type"], str):
                raise VoicePolicyError("The voice descriptor type must be a string.", code="invalid_voice_definition")
        if output.get("voice_type") is not None and not isinstance(output["voice_type"], str):
            raise VoicePolicyError("voice_type must be a string.", code="invalid_voice_definition")

    def _needs_catalog(self, definition: dict[str, Any], body: dict[str, Any]) -> bool:
        output = (definition.get("audio") or {}).get("output") or {}
        outputs = [output, *((node.get("config") or {}) for node in (definition.get("handoff") or {}).get("nodes", []))]
        for index, item in enumerate(outputs):
            name = _voice_name(item.get("voice"))
            if index == 0:
                name = str(body.get("voice") or name)
            descriptor = item.get("voice")
            voice_type = descriptor.get("type") if isinstance(descriptor, dict) else item.get("voice_type")
            if "-" in name and voice_type in {None, "azure-standard"}:
                return True
        return False

    def _resolve_output(
        self,
        output: dict[str, Any],
        body: dict[str, Any],
        voices: list[dict[str, Any]],
        *,
        automatic: bool,
    ) -> list[dict[str, Any]]:
        name = str(body.get("voice") or _voice_name(output.get("voice")))
        descriptor = output.get("voice")
        voice_type = descriptor.get("type") if isinstance(descriptor, dict) else output.get("voice_type")
        if voice_type not in {None, "azure-standard", "openai"}:
            if automatic:
                raise VoicePolicyError(
                    "Automatic selection does not replace custom or Azure-native realtime voices.",
                    code="unsupported_voice_type",
                )
            return []
        if name and "-" not in name and not automatic:
            return []
        definition = body["definition"]
        transcription = ((definition.get("audio") or {}).get("input") or {}).get("transcription") or {}
        voice_language = "-".join(name.split("-")[:2]) if "-" in name else ""
        language = body.get("language")
        if not language:
            language = voice_language if body.get("voice") else transcription.get("language") or voice_language
        language = language or "en-US"
        resolution = select_voice(
            voices,
            language=str(language),
            requested=name,
            gender=str(body.get("gender") or ""),
            automatic=automatic,
        )
        if isinstance(descriptor, dict):
            output["voice"] = {**descriptor, "type": "azure-standard", "name": resolution.selected}
        else:
            output["voice"] = resolution.selected
            output["voice_type"] = "azure-standard"
        return [resolution.as_dict("audio.output.voice")]


# Share the typed resolver across demo_server and template_portal routes without a global credential cache.
VOICE_POLICY_KEY = web.AppKey("voice_policy", VoicePolicy)
