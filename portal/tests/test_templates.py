# Copyright (c) Microsoft. All rights reserved.
"""Template catalog and route tests that do not require Azure or a live MCP."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

import demo_server
from voice_policy import VoicePolicy
import template_portal
from template_portal import (
    McpProbeError,
    MODEL_OVERRIDE_KEY,
    TemplateCatalog,
    materialize_template,
    template_agent_name,
)


ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "https://sample.services.ai.azure.com/api/projects/sample-project"
MCP_TEMPLATES = [
    "finance-example-realtime",
    "finance-example-cascade-luna",
    "finance-with-otp-and-officer-search",
    "elevator-service-example",
    "frontdesk-receptionist-example",
]
# Hand-tuned handoff examples: (template ID, sample folder, graph nodes, graph edges). Their
# defaults run on mock tools; their tuned tool-free defaults are kept as a backup version.
ORIGINAL_TEMPLATES = [
    ("customer-support-example", "example5_customer_support", 5, 9),
    ("appointment-setter-example", "example6_appointment_setter", 7, 12),
    ("receptionist-messaging-example", "example7_receptionist_messaging", 6, 14),
]
# Reference-template examples bound to the shared mock-tool-call MCP server.
CONVERTED_TEMPLATES = [
    ("appointment-scheduler-example", "example8_appointment_scheduler", 6, 11),
    ("assessment-quiz-agent-example", "example9_assessment_quiz_agent", 5, 8),
    ("collections-payment-recovery-agent-example", "example10_collections_payment_recovery_agent", 5, 8),
    ("corporate-training-roleplay-coach-example", "example11_corporate_training_roleplay_coach", 5, 9),
    ("education-tutoring-example", "example12_education_tutoring", 7, 16),
    ("healthcare-receptionist-example", "example13_healthcare_receptionist", 6, 11),
    ("hotel-reservation-agent-example", "example14_hotel_reservation_agent", 6, 13),
    ("inbound-lead-qualifier-example", "example15_inbound_lead_qualifier", 7, 13),
    ("incident-response-coordinator-example", "example16_incident_response_coordinator", 8, 16),
    ("insurance-advisor-example", "example17_insurance_advisor", 7, 14),
    ("internal-knowledge-assistant-example", "example18_internal_knowledge_assistant", 7, 19),
    ("it-access-request-agent-example", "example19_it_access_request_agent", 8, 18),
    ("it-help-desk-internal-support-example", "example20_it_help_desk_internal_support", 4, 7),
    ("language-practice-tutor-example", "example21_language_practice_tutor", 5, 9),
    ("legal-intake-specialist-example", "example22_legal_intake_specialist", 9, 17),
    ("marketing-lead-capture-agent-example", "example23_marketing_lead_capture_agent", 5, 8),
    ("new-hire-onboarding-assistant-example", "example24_new_hire_onboarding_assistant", 8, 16),
    ("order-status-tracking-example", "example25_order_status_tracking", 6, 12),
    ("outbound-sales-representative-example", "example26_outbound_sales_representative", 6, 13),
    ("personal-voice-assistant-example", "example27_personal_voice_assistant", 4, 7),
    ("real-estate-lead-follow-up-example", "example28_real_estate_lead_follow_up", 7, 13),
    ("restaurant-phone-order-taker-example", "example29_restaurant_phone_order_taker", 5, 10),
    ("salon-spa-beauty-receptionist-example", "example30_salon_spa_beauty_receptionist", 5, 9),
    ("survey-feedback-intake-example", "example31_survey_feedback_intake", 5, 8),
    ("technical-support-agent-example", "example32_technical_support_agent", 6, 13),
    ("travel-agency-trip-planner-example", "example33_travel_agency_trip_planner", 6, 11),
    ("user-research-interviewer-example", "example34_user_research_interviewer", 8, 16),
]
MOCK_TOOL_TEMPLATES = [*ORIGINAL_TEMPLATES, *CONVERTED_TEMPLATES]
SHARED_MCP_TEMPLATES = list(MCP_TEMPLATES)
MOCK_TOOL_TEMPLATE_IDS = [template_id for template_id, *_ in MOCK_TOOL_TEMPLATES]
MCP_TEMPLATES = [*SHARED_MCP_TEMPLATES, *MOCK_TOOL_TEMPLATE_IDS]
EXPECTED_TEMPLATES = [*SHARED_MCP_TEMPLATES, *MOCK_TOOL_TEMPLATE_IDS]
END_CONVERSATION_TOOL = {"type": "system", "name": "end_conversation"}
MCP_BASE_URL = (
    "https://voice-agent-noauth-mcp"
    ".lemonsky-36682081.westus2.azurecontainerapps.io"
)
MCP_ROUTES = {
    "finance-example-realtime": "/mcp/finance-handoff",
    "finance-example-cascade-luna": "/mcp/finance-handoff",
    "finance-with-otp-and-officer-search": "/mcp/finance-otp-officer",
    "elevator-service-example": "/mcp/elevator-service",
    "frontdesk-receptionist-example": "/mcp/frontdesk",
    **{template_id: "/mcp/mock-tool-call" for template_id in MOCK_TOOL_TEMPLATE_IDS},
}
MOCK_TOOL_PREFIX = "mock_tool_call_"


class TemplateCatalogTests(unittest.TestCase):
    def test_tuned_handoff_examples_preserve_normal_400ms_vad(self) -> None:
        catalog = TemplateCatalog()
        expected = {
            "type": "azure_semantic_vad",
            "profile": "normal",
            "auto_truncate": True,
            "interrupt_response": True,
            "prefix_padding_ms": 800,
            "silence_duration_ms": 400,
        }

        for template_id, *_ in ORIGINAL_TEMPLATES:
            with self.subTest(template_id=template_id):
                document = catalog.document(template_id)
                assert document is not None
                self.assertEqual(
                    expected, document["definition"]["audio"]["input"]["turn_detection"],
                )
                definition = materialize_template(
                    document, model="", voice="",
                    mcp_server_url=MCP_BASE_URL + MCP_ROUTES[template_id],
                    mcp_connection_id="", mcp_public=True,
                )
                self.assertEqual(
                    expected, definition["audio"]["input"]["turn_detection"],
                )

    def test_mock_tool_examples_bind_only_mock_tools(self) -> None:
        catalog = TemplateCatalog()

        cards = {card["id"]: card for card in catalog.cards()}
        for template_id, folder, node_count, edge_count in MOCK_TOOL_TEMPLATES:
            with self.subTest(template_id=template_id):
                detail = catalog.detail(template_id)
                source = catalog.source(template_id)
                assert detail is not None and source is not None
                self.assertTrue(cards[template_id]["mock_tools"])
                self.assertTrue(cards[template_id]["tool_systems"])
                self.assertTrue(detail["requires_mcp"])
                self.assertTrue(detail["runtime_locked"])
                self.assertEqual("public", source.connection_mode)
                self.assertEqual(node_count, detail["node_count"])
                self.assertEqual(edge_count, detail["edge_count"])
                agent = json.loads(
                    (ROOT.parent / "samples" / folder / "agent.json").read_text(encoding="utf-8")
                )
                handoff = agent["definition"]["handoff"]
                self.assertEqual(template_id, agent["name"])
                self.assertEqual("end", handoff["nodes"][-1]["id"])
                self.assertEqual(
                    [END_CONVERSATION_TOOL],
                    handoff["nodes"][-1]["config"]["tools"],
                )
                tools = list(template_portal.iter_mcp_tools(agent["definition"]))
                self.assertTrue(tools)
                for tool in tools:
                    self.assertEqual("", tool["server_url"])
                    self.assertEqual("never", tool["require_approval"])
                    self.assertTrue(tool["allowed_tools"])
                    self.assertTrue(all(name.startswith(MOCK_TOOL_PREFIX) for name in tool["allowed_tools"]))
                    for key in ("project_connection_id", "authorization", "headers"):
                        self.assertNotIn(key, tool)

    def test_mock_tool_examples_preserve_authored_runtime_and_instructions(self) -> None:
        catalog = TemplateCatalog()
        for template_id, folder, *_ in MOCK_TOOL_TEMPLATES:
            with self.subTest(template_id=template_id):
                authored = json.loads(
                    (ROOT.parent / "samples" / folder / "agent.json").read_text(encoding="utf-8")
                )["definition"]
                document = catalog.document(template_id)
                self.assertIsNotNone(document)
                server_url = MCP_BASE_URL + MCP_ROUTES[template_id]
                definition = materialize_template(
                    document, model="", voice="",
                    mcp_server_url=server_url, mcp_connection_id="", mcp_public=True,
                )
                for tool in template_portal.iter_mcp_tools(authored):
                    tool["server_url"] = server_url
                self.assertEqual(authored["audio"], definition["audio"])
                self.assertEqual(authored["instructions"], definition["instructions"])
                self.assertEqual(
                    authored["handoff"]["nodes"], definition["handoff"]["nodes"],
                )

    def test_customer_support_matches_reference_privacy_and_ticket_rules(self) -> None:
        agent = json.loads(
            (ROOT.parent / "samples" / "example5_customer_support" / "agent.json").read_text(encoding="utf-8")
        )
        nodes = {node["id"]: node["config"] for node in agent["definition"]["handoff"]["nodes"]}
        self.assertIn("share its title and company", nodes["account_billing"]["instructions"])
        self.assertIn("Never read back phone numbers", nodes["account_billing"]["instructions"])
        self.assertIn("Never change an existing ticket", nodes["resolve_or_escalate"]["instructions"])
        allowed = [
            name
            for tool in template_portal.iter_mcp_tools(nodes["resolve_or_escalate"])
            for name in tool["allowed_tools"]
        ]
        self.assertIn("mock_tool_call_zendesk_create_ticket", allowed)
        self.assertNotIn("mock_tool_call_zendesk_add_comment", allowed)

    def test_mock_tool_examples_use_persona_voices(self) -> None:
        male_personas = {"Theo", "Owen", "Hugo", "Luca", "Milo", "Arjun", "Noah"}
        for template_id, folder, *_ in MOCK_TOOL_TEMPLATES:
            with self.subTest(template_id=template_id):
                definition = json.loads(
                    (ROOT.parent / "samples" / folder / "agent.json").read_text(encoding="utf-8")
                )["definition"]
                persona = definition["instructions"].split("You are ", 1)[1].split(",", 1)[0]
                expected = (
                    "en-US-Brian:DragonHDOmniLatestNeural"
                    if persona in male_personas
                    else "en-US-Emma:DragonHDOmniLatestNeural"
                )
                self.assertEqual(
                    {"type": "azure-standard", "name": expected},
                    definition["audio"]["output"]["voice"],
                )

    def test_tool_map_suggestion_and_per_system_rewrite(self) -> None:
        required = [
            "mock_tool_call_find_meeting_times",
            "mock_tool_call_create_event",
            "mock_tool_call_zendesk_search",
        ]
        available = ["FindMeetingTimes", "calendar___CreateEvent", "search_articles"]
        self.assertEqual(
            {
                "mock_tool_call_find_meeting_times": "FindMeetingTimes",
                "mock_tool_call_create_event": "calendar___CreateEvent",
                "mock_tool_call_zendesk_search": "",
            },
            template_portal.suggest_tool_map(required, available),
        )
        with self.assertRaisesRegex(ValueError, "mock_tool_call_zendesk_search"):
            template_portal.validate_tool_map(required, available, {
                "mock_tool_call_find_meeting_times": "FindMeetingTimes",
                "mock_tool_call_create_event": "calendar___CreateEvent",
            })
        with self.assertRaisesRegex(ValueError, "does not list"):
            template_portal.validate_tool_map(required, available, {
                name: "unknown_tool" for name in required
            })
        definition = {
            "instructions": "Call mock_tool_call_salesforce_search, then mock_tool_call_create_event once.",
            "handoff": {"nodes": [{"id": "book", "config": {
                "instructions": "Use mock_tool_call_salesforce_create_lead after the booking.",
                "tools": [{
                    "type": "mcp", "server_label": "mock_tool_call", "server_url": "https://mock.example/mcp",
                    "require_approval": "never",
                    "allowed_tools": [
                        "mock_tool_call_create_event",
                        "mock_tool_call_salesforce_search",
                        "mock_tool_call_salesforce_create_lead",
                    ],
                }],
            }}]},
        }
        groups = {group["id"]: group for group in template_portal.tool_groups(definition)}
        self.assertEqual(["salesforce", "work_iq"], list(groups))
        self.assertFalse(groups["work_iq"]["connectable"])
        self.assertIn("can't be connected with an MCP URL", groups["work_iq"]["note"])
        rewritten = template_portal.apply_tool_servers(definition, {
            "salesforce": ("https://crm.example/mcp", {
                "mock_tool_call_salesforce_search": "crm___search_contacts",
                "mock_tool_call_salesforce_create_lead": "create_lead",
            }),
        })
        self.assertEqual(
            "Call crm___search_contacts, then mock_tool_call_create_event once.",
            rewritten["instructions"],
        )
        config = rewritten["handoff"]["nodes"][0]["config"]
        self.assertEqual("Use create_lead after the booking.", config["instructions"])
        self.assertEqual([
            {"type": "mcp", "server_label": "mock_tool_call", "server_url": "https://mock.example/mcp",
             "require_approval": "never", "allowed_tools": ["mock_tool_call_create_event"]},
            {"type": "mcp", "server_label": "salesforce", "server_url": "https://crm.example/mcp",
             "require_approval": "never", "allowed_tools": ["crm___search_contacts", "create_lead"]},
        ], config["tools"])
        self.assertIs(definition, template_portal.apply_tool_servers(definition, {}))

    def test_frontdesk_preserves_fluency_prompt_and_complete_workflow(self) -> None:
        catalog = TemplateCatalog()
        document = catalog.document("frontdesk-receptionist-example")
        detail = catalog.detail("frontdesk-receptionist-example")
        assert document is not None and detail is not None
        self.assertEqual(document["name"], "frontdesk-receptionist-example")
        self.assertEqual(len(detail["graph"]["nodes"]), 9)
        self.assertEqual(detail["graph"]["nodes"][0]["id"], "$entrypoint")
        self.assertEqual(len(detail["graph"]["edges"]), 16)
        self.assertEqual(detail["mcp"]["source_reference"], "Hosted Front Desk MCP")
        definition = document["definition"]
        self.assertEqual(definition["model_type"], "managed")
        self.assertEqual(definition["model"], "gpt-realtime")
        self.assertFalse(definition["store"])
        self.assertNotIn("structured_inputs", definition)
        self.assertNotIn("interim_response", definition)
        self.assertNotIn("echo_cancellation", definition["audio"]["input"])
        self.assertEqual(
            definition["audio"]["input"]["turn_detection"]["profile"], "eager",
        )
        self.assertEqual(definition["tools"], [])
        self.assertEqual(definition["tool_choice"], "required")
        self.assertEqual(definition["greeting"]["tool_choice"], "none")
        handoff = definition["handoff"]
        nodes = {node["id"]: node["config"] for node in handoff["nodes"]}
        self.assertEqual(set(nodes), {
            "identify_intent", "company_info", "zendesk_search", "transfer",
            "collect_message", "save_message", "next_request", "end",
        })
        self.assertEqual(handoff["max_transfers"], 24)
        self.assertEqual(handoff["max_attempts"], 24)
        separator = "\n\n## CURRENT WORKFLOW STAGE\n"
        base, entrypoint = definition["instructions"].split(separator)
        self.assertEqual(
            hashlib.sha256(base.encode()).hexdigest(),
            "fc89fd8aa4729b17d4a61c956de435798ca3fd77098e6b715378a7b3b74ad90c",
        )
        self.assertIn("Handoff immediately to identify_intent without speaking.", entrypoint)
        expected_tools = {
            "zendesk_search": ["frontdesk_search_zendesk_articles"],
            "save_message": ["frontdesk_record_message"],
        }
        for node_id, config in nodes.items():
            with self.subTest(node_id=node_id):
                shared, stage = config["instructions"].split(separator)
                self.assertEqual(shared, base)
                self.assertNotIn("inherit_from_base_instructions", config)
                self.assertIn("Objective\n", stage)
                self.assertIn("Complete when\n", stage)
                mcp_tools = list(template_portal.iter_mcp_tools(config))
                self.assertEqual(
                    [name for tool in mcp_tools for name in tool["allowed_tools"]],
                    expected_tools.get(node_id, []),
                )
                for tool in mcp_tools:
                    self.assertEqual(tool["server_url"], "")
                    for key in ("project_connection_id", "authorization", "headers"):
                        self.assertNotIn(key, tool)
        self.assertEqual(nodes["company_info"]["tool_choice"], "required")
        self.assertIn(
            "Do not answer a company or support question in this stage",
            nodes["identify_intent"]["instructions"],
        )
        self.assertIn(
            "If transfer_call is absent or fails, be honest and offer a message.",
            nodes["transfer"]["instructions"],
        )
        self.assertIn(
            "Read the complete message back and ask for explicit confirmation.",
            nodes["collect_message"]["instructions"],
        )
        self.assertIn(
            "Never call MCP from this collection stage.",
            nodes["collect_message"]["instructions"],
        )
        self.assertIn("caller_confirmed=true", nodes["save_message"]["instructions"])
        self.assertIn(
            "Do not repeat the callback number or full message.",
            nodes["save_message"]["instructions"],
        )
        self.assertEqual(
            [(tool["type"], tool["name"]) for tool in nodes["end"]["tools"]],
            [("system", "end_conversation")],
        )
        edges = handoff["edges"]
        self.assertEqual(len({edge["id"] for edge in edges}), 16)
        known = {"$entrypoint", *nodes}
        for edge in edges:
            self.assertIn(edge["source"], known)
            self.assertIn(edge["target"], known)
            self.assertEqual(edge["target_response"], "auto")
        self.assertEqual(
            [edge["target"] for edge in edges if edge["source"] == "$entrypoint"],
            ["identify_intent"],
        )
        self.assertEqual(
            [(edge["source"], edge["target"]) for edge in edges
             if edge["target"] == "save_message"],
            [("collect_message", "save_message")],
        )
        self.assertIn(
            "explicitly confirmed the complete message readback",
            next(edge["description"] for edge in edges
                 if edge["id"] == "collect_message_to_save"),
        )

    def test_default_catalog_detects_sample_projects(self) -> None:
        catalog = TemplateCatalog()

        self.assertEqual(
            [card["id"] for card in catalog.cards()],
            EXPECTED_TEMPLATES,
        )
        self.assertEqual(catalog.errors, [])
        realtime = catalog.detail("finance-example-realtime")
        cascade = catalog.detail("finance-example-cascade-luna")
        second = catalog.detail("finance-with-otp-and-officer-search")
        third = catalog.detail("elevator-service-example")
        assert realtime is not None and cascade is not None
        assert second is not None and third is not None
        self.assertGreater(len(realtime["graph"]["nodes"]), 1)
        self.assertGreater(len(realtime["graph"]["edges"]), 1)
        # The revised defaults tune prompts per runtime but share one topology.
        for key, fields in (("nodes", ("id", "kind")), ("edges", ("id", "from", "to"))):
            self.assertEqual(
                [[item[field] for field in fields] for item in realtime["graph"][key]],
                [[item[field] for field in fields] for item in cascade["graph"][key]],
            )
        self.assertTrue(realtime["requires_mcp"])
        self.assertTrue(cascade["requires_mcp"])
        self.assertTrue(second["requires_mcp"])
        self.assertTrue(third["requires_mcp"])
        for template_id in MCP_TEMPLATES:
            with self.subTest(template_id=template_id):
                source = catalog.source(template_id)
                detail = catalog.detail(template_id)
                assert source is not None and detail is not None
                self.assertEqual("public", source.connection_mode)
                self.assertEqual(MCP_BASE_URL + MCP_ROUTES[template_id], source.mcp_server_url)
                self.assertEqual("", source.mcp_connection_id)
                self.assertIsNone(source.mcp_config_path)
                self.assertIsNone(source.mcp_token_file)
                self.assertTrue(detail["mcp"]["connection_configured"])
                self.assertFalse(detail["mcp"]["configuration_required"])
        self.assertFalse(realtime["mcp"]["allow_user_token"])
        self.assertFalse(cascade["mcp"]["allow_user_token"])
        self.assertFalse(second["mcp"]["allow_user_token"])
        self.assertFalse(third["mcp"]["allow_user_token"])
        self.assertEqual(
            "Public no-auth MCP",
            realtime["mcp"]["source_label"],
        )
        self.assertEqual(
            "VoiceAgent/shared_mcp",
            realtime["mcp"]["source_reference"],
        )
        self.assertTrue(realtime["runtime_locked"])
        self.assertTrue(cascade["runtime_locked"])
        self.assertEqual("gpt-realtime-regional", realtime["model"])
        self.assertEqual(
            "en-IN-Diya:DragonHDLatestNeural",
            realtime["voice"],
        )
        self.assertEqual("gpt-4.1-mini", cascade["model"])
        self.assertEqual(
            "en-IN-Diya:DragonHDLatestNeural",
            cascade["voice"],
        )
        self.assertEqual(realtime["agent_name"], "finance-example-realtime")
        self.assertEqual(
            cascade["agent_name"],
            "finance-example-cascade-luna",
        )
        for template_id in (
            "finance-example-realtime",
            "finance-example-cascade-luna",
        ):
            document = catalog.document(template_id)
            assert document is not None
            end = next(
                node
                for node in document["definition"]["handoff"]["nodes"]
                if node["id"] == "end"
            )
            self.assertEqual(
                "system",
                end["config"]["tools"][0]["type"],
            )
            self.assertEqual(
                "end_conversation",
                end["config"]["tools"][0]["name"],
            )
        self.assertEqual(second["agent_name"], "finance-with-otp-and-officer-search")
        self.assertEqual(third["agent_name"], "elevator-service-example")
        self.assertEqual(len(third["graph"]["nodes"]), 10)
        self.assertEqual(len(third["graph"]["edges"]), 17)
        self.assertEqual(
            "Public no-auth MCP",
            third["mcp"]["source_label"],
        )
        self.assertEqual(
            "VoiceAgent/shared_mcp",
            third["mcp"]["source_reference"],
        )
        rpc = next(
            node
            for node in realtime["graph"]["nodes"]
            if node["id"] == "rpc"
        )
        self.assertEqual(["start_call", "confirm_right_party"], rpc["tools"])
        report_issue = next(
            node
            for node in third["graph"]["nodes"]
            if node["id"] == "report_issue"
        )
        self.assertEqual(
            [
                "record_issue",
                "assess_safety",
                "mock_zendesk_create_ticket",
            ],
            report_issue["tools"],
        )
        human_handoff = next(
            node
            for node in third["graph"]["nodes"]
            if node["id"] == "human_handoff"
        )
        self.assertEqual(
            ["request_human_handoff"],
            human_handoff["tools"],
        )
        query_issue = next(
            node
            for node in third["graph"]["nodes"]
            if node["id"] == "query_issue"
        )
        self.assertEqual(
            ["mock_zendesk_get_ticket_status"],
            query_issue["tools"],
        )
        materialized = materialize_template(
            catalog.document("elevator-service-example"),
            model="",
            voice="",
            mcp_server_url="https://tools.example/mcp",
            mcp_connection_id="elevator-connection",
        )
        for node in materialized["handoff"]["nodes"]:
            config = node["config"]
            self.assertNotIn("inherit_from_base_instructions", config)
            self.assertTrue(config["instructions"].startswith("## GLOBAL POLICY\n"))
            self.assertIn("\n\n## CURRENT NODE\n", config["instructions"])

    def test_public_materialization_removes_credentials_from_every_node(self) -> None:
        catalog = TemplateCatalog()
        for template_id in MCP_TEMPLATES:
            with self.subTest(template_id=template_id):
                document = catalog.document(template_id)
                assert document is not None
                for tool in template_portal.iter_mcp_tools(document["definition"]):
                    tool.update({
                        "project_connection_id": "stale-local-connection",
                        "authorization": "synthetic-token",
                        "headers": {"Authorization": "synthetic-token"},
                    })
                original = copy.deepcopy(document)
                definition = materialize_template(
                    document,
                    model="",
                    voice="",
                    mcp_server_url=MCP_BASE_URL + MCP_ROUTES[template_id],
                    mcp_connection_id="",
                    mcp_public=True,
                )
                tools = list(template_portal.iter_mcp_tools(definition))
                self.assertTrue(tools)
                for tool in tools:
                    self.assertEqual(MCP_BASE_URL + MCP_ROUTES[template_id], tool["server_url"])
                    for key in ("project_connection_id", "authorization", "headers"):
                        self.assertNotIn(key, tool)
                self.assertEqual(original, document)

    def test_managed_materialization_still_requires_a_connection(self) -> None:
        document = TemplateCatalog().document("finance-example-realtime")
        assert document is not None
        with self.assertRaisesRegex(ValueError, "MCP connection ID is required"):
            materialize_template(
                document, model="", voice="",
                mcp_server_url="https://tools.example/mcp",
                mcp_connection_id="",
            )

    def test_template_agent_names_are_limited_to_63_characters(self) -> None:
        self.assertEqual(
            63,
            len(template_agent_name(f"local-only-{'a' * 52}", "finance-example")),
        )
        self.assertEqual(
            "local-only-finance-example",
            template_agent_name("finance-example", "finance-example"),
        )
        self.assertEqual(
            "local-only-finance-example",
            template_agent_name("local-only-finance-example", "finance-example"),
        )
        with self.assertRaisesRegex(ValueError, "at most 52 characters"):
            template_agent_name(f"local-only-{'a' * 53}", "finance-example")

    def test_catalog_rejects_projects_outside_samples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            samples = root / "samples"
            portal = root / "portal"
            shared_mcp = root / "shared_mcp"
            samples.mkdir()
            portal.mkdir()
            shared_mcp.mkdir()
            config = portal / "templates.config.json"
            config.write_text(
                json.dumps({
                    "version": 1,
                    "templates": [{"id": "outside", "folder": "../outside"}],
                }),
                encoding="utf-8",
            )

            catalog = TemplateCatalog(config, samples, shared_mcp)

        self.assertEqual(catalog.cards(), [])
        self.assertIn("must resolve under", catalog.errors[0]["error"])

    def test_portal_owns_complete_template_assets(self) -> None:
        for name in (
            "templates.html",
            "template-app.js",
            "template-graph.js",
            "template-styles.css",
        ):
            with self.subTest(name=name):
                self.assertTrue((ROOT / "static" / name).is_file())
        html = (ROOT / "static" / "templates.html").read_text(encoding="utf-8")
        app_js = (ROOT / "static" / "template-app.js").read_text(encoding="utf-8")
        styles = (ROOT / "static" / "template-styles.css").read_text(encoding="utf-8")
        self.assertIn("VoiceAgent/portal/templates.config.json", html)
        self.assertIn('id="mcp-token"', html)
        self.assertIn('type="password"', html)
        self.assertIn(">AgentRuntime</a>", html)
        self.assertNotIn('href="/templates/"', html)
        self.assertNotIn('classList.toggle("embedded"', app_js)
        self.assertNotIn(".embedded .local-template-header", styles)
        self.assertIn(".mcp-start-guide[hidden] { display: none; }", styles)
        for name in (
            "components/HandoffGraphPanel.jsx",
            "lib/projectPicker.mjs",
            "lib/projectPicker.test.mjs",
        ):
            with self.subTest(name=name):
                self.assertTrue((ROOT / "web" / "src" / name).is_file())
        handoff_panel = (
            ROOT / "web/src/components/HandoffGraphPanel.jsx"
        ).read_text(encoding="utf-8")
        self.assertIn("data.connection_only", handoff_panel)
        self.assertIn(
            "no direct MCP URL is available to test",
            handoff_panel,
        )


class TemplateRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.voice_policy_patch = patch.object(
            VoicePolicy, "resolve", side_effect=lambda cfg, body: {
                "definition": body["definition"], "region": "westus2", "resolutions": [],
            },
        )
        self.voice_policy_patch.start()
        self.addCleanup(self.voice_policy_patch.stop)
        args = demo_server.parse_args([
            "--project-endpoint",
            ENDPOINT,
            "--model",
            "forced-global-model",
            "--no-record-sessions",
        ])
        self.client = TestClient(TestServer(demo_server.build_app(args)))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()

    async def test_templates_page_and_catalog_routes(self) -> None:
        page = await self.client.get("/templates")
        self.assertEqual(page.status, 200)
        self.assertIn("three-pane", await page.text())

        config = await self.client.get("/api/config")
        self.assertEqual(config.status, 200)
        config_payload = await config.json()
        self.assertTrue(config_payload["configured"])
        self.assertEqual(config_payload["project"], "sample-project")

        templates = await self.client.get("/api/templates")
        self.assertEqual(templates.status, 200)
        payload = await templates.json()
        self.assertTrue(payload["available"])
        self.assertEqual(
            [item["id"] for item in payload["templates"]],
            EXPECTED_TEMPLATES,
        )

        detail = await self.client.get("/api/templates/finance-example-realtime")
        self.assertEqual(detail.status, 200)
        detail_payload = await detail.json()
        self.assertEqual(
            detail_payload["agent_name"],
            "finance-example-realtime",
        )
        self.assertTrue(detail_payload["runtime_locked"])
        self.assertGreater(len(detail_payload["graph"]["nodes"]), 1)
        self.assertEqual("voice", detail_payload["definition"]["kind"])
        self.assertRegex(
            detail_payload["suggested_agent_name"],
            r"^local-only-finance-example-realtime-[0-9a-f]{8}$",
        )
        for template_id in MCP_TEMPLATES:
            detail_payload = await (
                await self.client.get(f"/api/templates/{template_id}")
            ).json()
            tools = list(template_portal.iter_mcp_tools(detail_payload["definition"]))
            self.assertTrue(tools)
            self.assertEqual(
                detail_payload["definition"],
                json.loads(detail_payload["yaml"])["definition"],
            )
            for tool in tools:
                self.assertEqual(MCP_BASE_URL + MCP_ROUTES[template_id], tool["server_url"])
                self.assertNotIn("project_connection_id", tool)

    async def test_public_templates_probe_without_bearer_or_local_files(self) -> None:
        catalog = self.client.server.app[template_portal.CATALOG_KEY]
        for template_id in MCP_TEMPLATES:
            with self.subTest(template_id=template_id):
                document = catalog.document(template_id)
                assert document is not None
                names = {
                    name
                    for tool in template_portal.iter_mcp_tools(document["definition"])
                    for name in tool.get("allowed_tools") or []
                }
                with patch(
                    "template_portal.mcp_handshake",
                    return_value={"reached": True, "tools": sorted(names)},
                ) as handshake:
                    response = await self.client.get(f"/api/templates/{template_id}/mcp/probe")
                self.assertEqual(200, response.status)
                payload = await response.json()
                self.assertTrue(payload["ok"])
                self.assertEqual("", payload["start_command"])
                handshake.assert_called_once_with(MCP_BASE_URL + MCP_ROUTES[template_id], "")

    async def test_public_probe_does_not_accept_auth_gate_as_ready(self) -> None:
        for status in (401, 403):
            with self.subTest(status=status), patch(
                "template_portal.mcp_handshake",
                side_effect=McpProbeError("Authentication rejected", http_status=status),
            ):
                response = await self.client.get(
                    "/api/templates/finance-example-realtime/mcp/probe"
                )
                payload = await response.json()
                self.assertFalse(payload["ok"])
                self.assertEqual(status, payload["http_status"])

    async def test_public_probe_rejects_incomplete_tool_inventory(self) -> None:
        with patch(
            "template_portal.mcp_handshake",
            return_value={"reached": True, "tools": []},
        ):
            response = await self.client.get(
                "/api/templates/finance-example-realtime/mcp/probe"
            )
        payload = await response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("missing expected tools", payload["error"])

    async def test_existing_connection_probe_preserves_auth_gate_behavior(self) -> None:
        catalog = self.client.server.app[template_portal.CATALOG_KEY]
        source = catalog.source("finance-example-realtime")
        assert source is not None
        existing = replace(
            source, connection_mode="existing",
            mcp_connection_id="customer-owned-connection",
        )
        with (
            patch.object(catalog, "source", return_value=existing),
            patch(
                "template_portal.mcp_handshake",
                side_effect=McpProbeError("Authentication required", http_status=401),
            ),
            patch("template_portal.create_mcp_connection") as create_connection,
        ):
            response = await self.client.get(
                "/api/templates/finance-example-realtime/mcp/probe"
            )
            payload = await response.json()
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["project_connection_auth"])
            response = await self.client.post(
                "/api/templates/finance-example-realtime/mcp/configure", json={}
            )
            self.assertEqual(200, response.status)
            self.assertEqual(
                "customer-owned-connection", (await response.json())["connection_name"]
            )
            create_connection.assert_not_called()

    async def test_public_templates_configure_and_publish_without_connections(self) -> None:
        for template_id in MCP_TEMPLATES:
            with (
                self.subTest(template_id=template_id),
                patch("template_portal.validate_mcp_probe_url") as validate_url,
                patch("template_portal.create_mcp_connection") as create_connection,
                patch(
                    "template_portal.publish_agent",
                    return_value={"name": "local-only-synthetic", "version": "1"},
                ) as publish,
            ):
                configured = await self.client.post(
                    f"/api/templates/{template_id}/mcp/configure", json={}
                )
                self.assertEqual(200, configured.status)
                self.assertTrue((await configured.json())["configured"])
                response = await self.client.post(
                    f"/api/templates/{template_id}/publish", json={"name": "synthetic"}
                )
                self.assertEqual(201, response.status, await response.text())
                self.assertEqual("", (await response.json())["mcp_connection_name"])
                create_connection.assert_not_called()
                publish.assert_called_once()
                self.assertEqual(
                    {"source_template_id": template_id, "source_template_version": "."},
                    publish.call_args.kwargs["metadata"],
                )
                self.assertEqual(2, validate_url.call_count)
                validate_url.assert_called_with(MCP_BASE_URL + MCP_ROUTES[template_id])
                for tool in template_portal.iter_mcp_tools(publish.call_args.kwargs["definition"]):
                    self.assertEqual(MCP_BASE_URL + MCP_ROUTES[template_id], tool["server_url"])
                    self.assertNotIn("project_connection_id", tool)

    async def test_editor_connects_and_disconnects_one_system_of_a_working_copy(self) -> None:
        detail = await (await self.client.get("/api/templates/order-status-tracking-example")).json()
        original = detail["definition"]
        groups = (await (await self.client.post("/api/tools/groups", json={"definition": original})).json())["groups"]
        self.assertEqual(["zendesk", "twilio", "orders"], [group["id"] for group in groups])
        self.assertTrue(all(group["connected"] is None for group in groups))
        tool_map = {"mock_tool_call_zendesk_add_comment": "add_ticket_comment"}
        with patch(
            "template_portal.mcp_handshake",
            return_value={"reached": True, "tools": ["add_ticket_comment"]},
        ):
            discovered = await (await self.client.post("/api/tools/discover", json={
                "definition": original, "group": "zendesk", "server_url": "https://desk.example/mcp",
            })).json()
            self.assertEqual({"mock_tool_call_zendesk_add_comment": ""}, discovered["mapping"])
            self.assertEqual(["mock_tool_call_zendesk_add_comment"], discovered["unmapped"])
            response = await self.client.post("/api/tools/connect", json={
                "definition": original, "group": "zendesk",
                "server_url": "https://desk.example/mcp", "tool_map": tool_map,
            })
            self.assertEqual(200, response.status, await response.text())
            connected = await response.json()
        zendesk = next(group for group in connected["groups"] if group["id"] == "zendesk")
        self.assertEqual(
            {"server_url": "https://desk.example/mcp", "tools": ["add_ticket_comment"]},
            zendesk["connected"],
        )
        text = json.dumps(connected["definition"])
        self.assertNotIn("mock_tool_call_zendesk_add_comment", text)
        self.assertIn("mock_tool_call_twilio_send_message", text)
        restored = await (await self.client.post("/api/tools/disconnect", json={
            "definition": connected["definition"], "group": "zendesk", "tool_map": connected["tool_map"],
        })).json()
        def sorted_tools(value):
            if isinstance(value, dict):
                return {
                    key: sorted(item) if key == "allowed_tools" else sorted_tools(item)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [sorted_tools(item) for item in value]
            return value

        self.assertEqual(sorted_tools(original), sorted_tools(restored["definition"]))
        with patch("template_portal.mcp_handshake") as handshake:
            work_iq = await self.client.post("/api/tools/connect", json={
                "definition": (await (await self.client.get("/api/templates/appointment-scheduler-example")).json())["definition"],
                "group": "work_iq", "server_url": "https://cal.example/mcp", "tool_map": {},
            })
            self.assertEqual(400, work_iq.status)
            handshake.assert_not_called()

    async def test_public_template_configuration_keeps_private_address_guard(self) -> None:
        with patch(
            "template_portal.validate_mcp_probe_url",
            side_effect=McpProbeError("MCP probes cannot target private addresses"),
        ), patch("template_portal.create_mcp_connection") as create_connection:
            response = await self.client.post(
                "/api/templates/finance-example-realtime/mcp/configure", json={}
            )
        self.assertEqual(502, response.status)
        self.assertIn("cannot target private", (await response.json())["error"])
        create_connection.assert_not_called()

    async def test_template_assets_are_served_without_azure_credentials(self) -> None:
        for name in (
            "template-app.js",
            "template-graph.js",
            "template-styles.css",
        ):
            with self.subTest(name=name):
                response = await self.client.get(f"/static/{name}")
                self.assertEqual(response.status, 200)

        cfg = self.client.server.app[demo_server.DEFAULT_CONFIG_KEY]
        self.assertIsNone(cfg._credential)

    async def test_real_tools_guide_is_served(self) -> None:
        response = await self.client.get("/guide/real-tools")
        self.assertEqual(200, response.status)
        self.assertEqual("text/html", response.content_type)
        text = await response.text()
        self.assertIn("<h1>Use real tools with Templates</h1>", text)
        self.assertIn("<table>", text)
        self.assertIn('<a href="/guide/run-samples"', text)
        for system in ("Salesforce", "Zendesk", "Twilio"):
            self.assertIn(system, text)
        self.assertIn('<a href="/guide/logic-apps-mcp"', text)

    async def test_try_it_turns_come_from_the_sample_readme(self) -> None:
        response = await self.client.get("/api/templates/collections-payment-recovery-agent-example/try-it")
        self.assertEqual(200, response.status)
        payload = await response.json()
        self.assertEqual("collections-payment-recovery-agent-example", payload["id"])
        self.assertGreaterEqual(len(payload["turns"]), 3)
        self.assertIn("4821", payload["turns"][0])
        self.assertFalse(any("mock_tool_call_" in turn for turn in payload["turns"]))
        missing = await self.client.get("/api/templates/no-such-template/try-it")
        self.assertEqual(404, missing.status)

    async def test_finance_try_it_gives_the_test_identity(self) -> None:
        # Finance calls the shared MCP, not mock tools; its test lead is Mengyou, born 1 January.
        for template_id in ("finance-example-realtime", "finance-example-cascade-luna"):
            with self.subTest(template_id=template_id):
                response = await self.client.get(f"/api/templates/{template_id}/try-it")
                self.assertEqual(200, response.status)
                turns = " ".join((await response.json())["turns"])
                self.assertIn("Mengyou", turns)
                self.assertIn("1 January", turns)
                self.assertNotIn("1990", turns)

    async def test_shared_mcp_templates_give_their_test_data(self) -> None:
        for template_id, expected in (
            ("finance-with-otp-and-officer-search", "12345007"),
            ("elevator-service-example", "ticket 15"),
            ("frontdesk-receptionist-example", "425-555-0142"),
        ):
            with self.subTest(template_id=template_id):
                response = await self.client.get(f"/api/templates/{template_id}/try-it")
                self.assertEqual(200, response.status)
                self.assertIn(expected, " ".join((await response.json())["turns"]))

    async def test_logic_apps_mcp_guide_is_served(self) -> None:
        response = await self.client.get("/guide/logic-apps-mcp")
        self.assertEqual(200, response.status)
        self.assertEqual("text/html", response.content_type)
        text = await response.text()
        self.assertIn("<h1>Create Salesforce, Zendesk, and Work IQ MCP servers with Azure Logic Apps</h1>", text)
        self.assertIn("X-API-KEY", text)
        self.assertIn('<a href="/guide/real-tools"', text)

    def test_guide_renderer_escapes_markup_and_drops_unsafe_links(self) -> None:
        from guide_render import render_markdown

        title, body = render_markdown(
            "# Guide <b>\n\nUse `<script>` and [x](javascript:alert(1)) or [docs](https://example.com).\n"
        )
        self.assertEqual("Guide <b>", title)
        self.assertNotIn("<script>", body)
        self.assertNotIn("javascript:", body)
        self.assertIn("<code>&lt;script&gt;</code>", body)
        self.assertIn('<a href="https://example.com"', body)

    async def test_locked_variants_ignore_global_model_override(self) -> None:
        self.assertEqual(
            "forced-global-model",
            self.client.server.app[MODEL_OVERRIDE_KEY],
        )
        realtime = await (
            await self.client.get("/api/templates/finance-example-realtime")
        ).json()
        cascade = await (
            await self.client.get("/api/templates/finance-example-cascade-luna")
        ).json()

        self.assertEqual("gpt-realtime-regional", realtime["model"])
        self.assertEqual("gpt-4.1-mini", cascade["model"])

    async def test_unknown_template_and_asset_are_not_exposed(self) -> None:
        self.assertEqual(
            (await self.client.get("/api/templates/not-configured")).status,
            404,
        )
        self.assertEqual(
            (await self.client.get("/static/not-allowlisted.txt")).status,
            404,
        )

    async def test_connection_only_mcp_is_reported_as_non_probeable(self) -> None:
        agent = {
            "versions": {
                "latest": {
                    "definition": {
                        "kind": "voice",
                        "tools": [
                            {
                                "type": "mcp",
                                "server_label": "connection-only",
                                "project_connection_id": "sample-connection",
                                "allowed_tools": ["lookup"],
                            }
                        ],
                    }
                }
            }
        }
        with patch("template_portal.get_agent", return_value=agent):
            response = await self.client.post(
                "/api/mcp/probe",
                json={
                    "agent": "sample-agent",
                    "server_label": "connection-only",
                },
            )

        self.assertEqual(200, response.status)
        payload = await response.json()
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["connection_only"])
        self.assertIn("project connection", payload["error"])

    async def test_connection_backed_mcp_auth_gate_is_reachable(self) -> None:
        agent = {
            "versions": {
                "latest": {
                    "definition": {
                        "kind": "voice",
                        "tools": [
                            {
                                "type": "mcp",
                                "server_label": "connection-backed",
                                "server_url": "https://mcp.example/mcp",
                                "project_connection_id": "sample-connection",
                                "allowed_tools": ["lookup"],
                            }
                        ],
                    }
                }
            }
        }
        with (
            patch("template_portal.get_agent", return_value=agent),
            patch(
                "template_portal.mcp_handshake",
                side_effect=McpProbeError(
                    "initialize returned HTTP 401",
                    latency_ms=12,
                    http_status=401,
                ),
            ),
        ):
            response = await self.client.post(
                "/api/mcp/probe",
                json={
                    "agent": "sample-agent",
                    "server_label": "connection-backed",
                },
            )

        self.assertEqual(200, response.status)
        payload = await response.json()
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["reached"])
        self.assertTrue(payload["project_connection_auth"])

    async def test_portal_rejects_browser_provided_mcp_tokens(self) -> None:
        response = await self.client.post(
            "/api/templates/finance-example-realtime/mcp/configure",
            json={"token": "synthetic-token"},
        )
        self.assertEqual(409, response.status)
        self.assertIn("browser-provided MCP tokens are disabled", await response.text())

    async def test_portal_refreshes_managed_template_connection_server_side(self) -> None:
        catalog = self.client.server.app[template_portal.CATALOG_KEY]
        source = catalog.source("elevator-service-example")
        assert source is not None
        with tempfile.TemporaryDirectory() as directory:
            token_file = Path(directory) / "token"
            token_file.write_text("synthetic-server-token\n", encoding="utf-8")
            managed_source = replace(
                source,
                connection_mode="managed",
                mcp_server_url="https://example.com/mcp/elevator-service",
                mcp_connection_id="elevator-service-local-e2e",
                mcp_token_file=token_file,
                allowed_backends=(),
            )
            with (
                patch.object(catalog, "source", return_value=managed_source),
                patch("template_portal.create_mcp_connection") as create_connection,
            ):
                response = await self.client.post(
                    "/api/templates/elevator-service-example/mcp/configure",
                    json={},
                )

        self.assertEqual(200, response.status)
        payload = await response.json()
        self.assertTrue(payload["configured"])
        self.assertEqual(
            "elevator-service-local-e2e",
            payload["connection_name"],
        )
        create_connection.assert_called_once()
        self.assertEqual(
            "https://example.com/mcp/elevator-service",
            create_connection.call_args.kwargs["server_url"],
        )
        self.assertEqual(
            "synthetic-server-token",
            create_connection.call_args.kwargs["bearer_token"],
        )


if __name__ == "__main__":
    unittest.main()
