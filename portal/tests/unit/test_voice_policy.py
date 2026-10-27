"""Mocked selection and regional-catalog regressions; never call Azure."""

from __future__ import annotations

import asyncio
import copy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import demo_server
import voice_policy
from voice_policy import VoicePolicy, VoicePolicyError, select_voice


def catalog_voice(name: str, locale: str, gender: str = "Female", **fields: object) -> dict:
    """Build one deterministic catalog row."""
    return {"ShortName": name, "Locale": locale, "Gender": gender, "Status": "GA", **fields}


@pytest.fixture
def regional_policy() -> VoicePolicy:
    """Avoid management-plane discovery and public catalog calls."""
    policy = VoicePolicy(Mock(return_value=[{"endpoint": "project", "region": "westus2"}]))
    policy.catalog = Mock(
        return_value=[
            catalog_voice("en-us-emma:DragonHDOmniLatestNeural", "en-US"),
            catalog_voice("en-US-BrianNeural", "en-US", "Male"),
            catalog_voice("hi-IN-SwaraNeural", "hi-IN"),
            catalog_voice("hi-IN-MadhurNeural", "hi-IN", "Male"),
        ]
    )
    return policy


class TestVoiceSelection:
    def test_select_voice_mock_catalog_casing(self) -> None:
        result = select_voice(
            [catalog_voice("en-us-emma:DragonHDOmniLatestNeural", "en-US")],
            language="en-US",
            automatic=True,
        )
        assert result.selected == "en-US-Emma:DragonHDOmniLatestNeural"

    def test_select_voice_mock_hindi_neural_fallback(self) -> None:
        result = select_voice(
            [catalog_voice("hi-IN-SwaraNeural", "hi-IN")],
            language="hi-IN",
            requested="en-US-Emma:DragonHDOmniLatestNeural",
            automatic=True,
        )
        assert result.selected == "hi-IN-SwaraNeural"

    def test_select_voice_mock_preserves_male_preference(self) -> None:
        voices = [catalog_voice("hi-IN-SwaraNeural", "hi-IN"), catalog_voice("hi-IN-MadhurNeural", "hi-IN", "Male")]
        result = select_voice(
            voices, language="hi-IN", requested="en-US-Brian:DragonHDOmniLatestNeural", automatic=True
        )
        assert result.selected == "hi-IN-MadhurNeural"

    def test_select_voice_mock_preserves_available_explicit_voice(self) -> None:
        voice = catalog_voice("en-US-BrianNeural", "en-US", "Male")
        assert select_voice([voice], language="en-US", requested=voice["ShortName"]).selected == voice["ShortName"]

    def test_select_voice_mock_uses_multilingual_when_native_missing(self) -> None:
        voice = catalog_voice("en-US-AvaMultilingualNeural", "en-US", SecondaryLocaleList=["hi-IN"])
        assert select_voice([voice], language="hi-IN", automatic=True).selected == voice["ShortName"]

    def test_select_voice_mock_unrelated_language_is_not_fallback(self) -> None:
        with pytest.raises(VoicePolicyError, match="No available"):
            select_voice([catalog_voice("en-US-EmmaNeural", "en-US")], language="hi-IN", automatic=True)

    @pytest.mark.parametrize("locale", ["", "auto", "hi", "en-US,hi-IN", "en-US.example"])
    def test_select_voice_mock_invalid_locale(self, locale: str) -> None:
        with pytest.raises(VoicePolicyError):
            select_voice([], language=locale)

    def test_select_voice_mock_other_catalog_language(self) -> None:
        voice = catalog_voice("pt-BR-FranciscaNeural", "pt-BR")
        assert select_voice([voice], language="pt-BR", automatic=True).selected == voice["ShortName"]


class TestRegionalPolicy:
    def test_region_mock_selected_project_and_cache(self, regional_policy: VoicePolicy) -> None:
        cfg = SimpleNamespace(host="project")
        assert regional_policy.region(cfg) == "westus2"
        assert regional_policy.region(cfg) == "westus2"
        regional_policy.discover_projects.assert_called_once()

    def test_region_mock_unknown_requires_manual_region(self) -> None:
        policy = VoicePolicy(Mock(return_value=[]))
        with pytest.raises(VoicePolicyError, match="unknown"):
            policy.region(SimpleNamespace(host="project"))
        assert policy.region(SimpleNamespace(host="project"), "Central India") == "centralindia"

    def test_region_mock_project_switch_is_not_cached_as_old_region(self) -> None:
        discover = Mock(
            side_effect=[
                [{"endpoint": "first", "region": "westus2"}],
                [{"endpoint": "second", "region": "centralindia"}],
            ]
        )
        policy = VoicePolicy(discover)
        assert policy.region(SimpleNamespace(host="first")) == "westus2"
        assert policy.region(SimpleNamespace(host="second")) == "centralindia"

    @pytest.mark.parametrize("region", ["evil.example", "westus2/", "https://westus2", "../westus2"])
    def test_region_mock_rejects_host_injection(self, region: str) -> None:
        with pytest.raises(VoicePolicyError):
            VoicePolicy(Mock()).region(SimpleNamespace(host="project"), region)

    def test_catalog_mock_cache_and_no_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        response = Mock(is_redirect=False)
        response.json.return_value = [catalog_voice("hi-IN-SwaraNeural", "hi-IN")]
        request = Mock(return_value=response)
        monkeypatch.setattr(voice_policy.requests, "get", request)
        policy = VoicePolicy(Mock())
        assert policy.catalog("centralindia") == policy.catalog("centralindia")
        request.assert_called_once()
        assert "headers" not in request.call_args.kwargs
        assert request.call_args.kwargs["allow_redirects"] is False

    def test_catalog_mock_failure_is_not_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        request = Mock(side_effect=requests.Timeout())
        monkeypatch.setattr(voice_policy.requests, "get", request)
        policy = VoicePolicy(Mock())
        for _ in range(2):
            with pytest.raises(VoicePolicyError, match="Cannot check"):
                policy.catalog("westus2")
        assert request.call_count == 2

    @pytest.mark.parametrize("payload", [[], {}, [{"ShortName": "bad"}]])
    def test_catalog_mock_invalid_response(self, monkeypatch: pytest.MonkeyPatch, payload: object) -> None:
        response = Mock(is_redirect=False)
        response.json.return_value = payload
        monkeypatch.setattr(voice_policy.requests, "get", Mock(return_value=response))
        with pytest.raises(VoicePolicyError, match="Cannot check"):
            VoicePolicy(Mock()).catalog("westus2")

    def test_resolve_mock_root_nodes_and_preserves_original(self, regional_policy: VoicePolicy) -> None:
        definition = {
            "kind": "voice",
            "model": "gpt-realtime",
            "audio": {"output": {"voice": {"type": "azure-standard", "name": "en-US-Emma:DragonHDOmniLatestNeural"}}},
            "handoff": {
                "nodes": [
                    {
                        "id": "male",
                        "config": {"voice": {"type": "azure-standard", "name": "en-US-Brian:DragonHDOmniLatestNeural"}},
                    },
                    {"id": "inherited", "config": {}},
                ]
            },
        }
        original = copy.deepcopy(definition)
        result = regional_policy.resolve(
            SimpleNamespace(host="project"),
            {
                "definition": definition,
                "language": "hi-IN",
                "mode": "automatic",
            },
        )
        assert definition == original
        assert result["definition"]["audio"]["output"]["voice"]["name"] == "hi-IN-SwaraNeural"
        assert result["definition"]["handoff"]["nodes"][0]["config"]["voice"]["name"] == "hi-IN-MadhurNeural"
        assert result["definition"]["handoff"]["nodes"][1]["config"] == {}

    def test_resolve_mock_native_voice_not_replaced(self, regional_policy: VoicePolicy) -> None:
        definition = {"kind": "voice", "audio": {"output": {"voice": "alloy", "voice_type": "openai"}}}
        result = regional_policy.resolve(SimpleNamespace(host="project"), {"definition": definition})
        assert result["definition"] == definition
        assert result["resolutions"] == []

    def test_resolve_mock_custom_voice_not_auto_replaced(self, regional_policy: VoicePolicy) -> None:
        definition = {"kind": "voice", "audio": {"output": {"voice": {"type": "azure-custom", "name": "personal"}}}}
        with pytest.raises(VoicePolicyError, match="custom"):
            regional_policy.resolve(SimpleNamespace(host="project"), {"definition": definition, "mode": "automatic"})

    @pytest.mark.parametrize(
        "definition",
        [
            {"kind": "voice", "audio": "bad"},
            {"kind": "voice", "audio": {"output": []}},
            {"kind": "voice", "audio": {"output": {"voice": 5}}},
            {"kind": "voice", "audio": {"output": {"voice": {"name": 5}}}},
            {"kind": "voice", "audio": {"output": {"voice": "en-US-EmmaNeural", "voice_type": []}}},
            {"kind": "voice", "handoff": {"nodes": ["bad"]}},
        ],
    )
    def test_resolve_mock_invalid_definition_shape(self, regional_policy: VoicePolicy, definition: dict) -> None:
        with pytest.raises(VoicePolicyError):
            regional_policy.resolve(SimpleNamespace(host="project"), {"definition": definition})
        regional_policy.catalog.assert_not_called()


async def _resolve_http(body: object, policy: VoicePolicy) -> tuple[int, dict]:
    args = demo_server.parse_args(
        [
            "--project-endpoint",
            "https://test.services.ai.azure.com/api/projects/test",
            "--no-record-sessions",
        ]
    )
    app = demo_server.build_app(args)
    app[voice_policy.VOICE_POLICY_KEY] = policy
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/api/voices/resolve", json=body)
        return response.status, await response.json()


class TestVoiceRoute:
    def test_resolve_http_mock_automatic_hindi(self, regional_policy: VoicePolicy) -> None:
        body = {
            "definition": {"kind": "voice", "audio": {"output": {"voice": "en-US-EmmaNeural"}}},
            "language": "hi-IN",
            "mode": "automatic",
            "region": "centralindia",
        }
        status, result = asyncio.run(_resolve_http(body, regional_policy))
        assert status == 200
        assert result["definition"]["audio"]["output"]["voice"] == "hi-IN-SwaraNeural"
        assert result["region"] == "centralindia"
        assert result["resolutions"][0]["changed"]

    def test_resolve_http_mock_invalid_body(self, regional_policy: VoicePolicy) -> None:
        status, result = asyncio.run(_resolve_http([], regional_policy))
        assert status == 400
        assert result["code"] == "invalid_voice_request"

    def test_resolve_http_mock_unknown_region_not_success(self) -> None:
        body = {"definition": {"kind": "voice", "audio": {"output": {"voice": "hi-IN-SwaraNeural"}}}}
        status, result = asyncio.run(_resolve_http(body, VoicePolicy(Mock(return_value=[]))))
        assert status == 502
        assert result["code"] == "voice_region_unknown"
