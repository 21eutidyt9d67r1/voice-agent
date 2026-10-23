from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from .service import MockToolCallService


MOCK_NOTE = " Mock data only: nothing real is booked or sent, and this service stores nothing the caller provides."


class MockError(BaseModel):
    code: str
    message: str


class EchoData(BaseModel):
    text: str


class EchoResult(BaseModel):
    mock: Literal[True]
    tool: Literal["mock_tool_call_echo"]
    request_id: str
    status: Literal["succeeded", "failed"]
    data: EchoData | None
    error: MockError | None


class MockResult(BaseModel):
    """Common fields of every business mock; the rest mirrors the real tool's result."""

    model_config = ConfigDict(extra="allow")

    mock: Literal[True]
    tool: str
    ok: bool
    error: MockError | None


def _result(payload: dict[str, Any]) -> MockResult:
    return MockResult.model_validate(payload)


Text = Annotated[str, Field(max_length=4000)]
ShortText = Annotated[str, Field(max_length=300)]
Email = Annotated[str, Field(max_length=254)]
LocalDateTime = Annotated[
    str,
    Field(
        min_length=10,
        max_length=40,
        description="ISO 8601 local date and time without an offset, for example 2026-10-22T09:00:00.",
    ),
]
TimeZone = Annotated[
    str,
    Field(min_length=1, max_length=64, description="Windows time zone name such as Pacific Standard Time."),
]
IsoDate = Annotated[str, Field(min_length=10, max_length=10, description="Date as YYYY-MM-DD.")]
Rating = Annotated[int, Field(ge=1, le=5)]


def register_tools(mcp: FastMCP, service: MockToolCallService) -> None:
    @mcp.tool(
        name="mock_tool_call_echo",
        description="Return synthetic test data only; never performs a real business action.",
    )
    def mock_tool_call_echo(
        request_id: Annotated[
            str,
            Field(min_length=1, max_length=128, pattern=r"\S", description="Caller-generated correlation ID."),
        ],
        text: Annotated[str, Field(max_length=4096, description="Fictional text to echo.")],
        mode: Annotated[
            Literal["success", "business_error"],
            Field(description="success echoes the text; business_error returns a synthetic business failure."),
        ] = "success",
    ) -> EchoResult:
        return EchoResult.model_validate(service.echo(request_id, text, mode))

    # ------------------------------------------------------------ calendar

    @mcp.tool(
        name="mock_tool_call_find_meeting_times",
        description=(
            "Find free meeting slots on the mock calendar, like Work IQ FindMeetingTimes. Suggestions are in "
            "UTC, each listing end before start." + MOCK_NOTE
        ),
    )
    def mock_tool_call_find_meeting_times(
        meetingDuration: Annotated[str, Field(max_length=16, description="ISO 8601 duration such as PT30M or PT1H30M.")],
        startDateTime: LocalDateTime,
        endDateTime: LocalDateTime,
        timeZone: TimeZone,
        attendeeEmails: Annotated[list[Email], Field(max_length=10)] = [],
        maxCandidates: Annotated[int, Field(ge=1, le=10)] = 5,
        returnSuggestionReasons: bool = False,
    ) -> MockResult:
        return _result(service.find_meeting_times(
            meetingDuration, startDateTime, endDateTime, timeZone,
            list(attendeeEmails), maxCandidates, returnSuggestionReasons,
        ))

    @mcp.tool(
        name="mock_tool_call_get_user_date_and_time_zone_settings",
        description="Return today's date, the current time, and the calendar owner's time zone." + MOCK_NOTE,
    )
    def mock_tool_call_get_user_date_and_time_zone_settings() -> MockResult:
        return _result(service.get_user_date_and_time_zone_settings())

    @mcp.tool(
        name="mock_tool_call_create_event",
        description="Create an event on the mock calendar and record the invite, like Work IQ CreateEvent." + MOCK_NOTE,
    )
    def mock_tool_call_create_event(
        subject: Annotated[str, Field(min_length=1, max_length=255)],
        startDateTime: LocalDateTime,
        endDateTime: LocalDateTime,
        timeZone: TimeZone,
        attendeeEmails: Annotated[list[Email], Field(max_length=10)] = [],
        isOnlineMeeting: bool = False,
        bodyContentType: Literal["Text", "HTML"] = "Text",
        body: Text = "",
        location: ShortText = "",
    ) -> MockResult:
        return _result(service.create_event(
            subject, startDateTime, endDateTime, timeZone, list(attendeeEmails), isOnlineMeeting, body, location,
        ))

    @mcp.tool(
        name="mock_tool_call_list_calendar_view",
        description="List mock calendar events in a time range whose subject contains the given text, like Work IQ ListCalendarView." + MOCK_NOTE,
    )
    def mock_tool_call_list_calendar_view(
        startDateTime: LocalDateTime,
        endDateTime: LocalDateTime,
        timeZone: TimeZone,
        subject: ShortText = "",
        top: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> MockResult:
        return _result(service.list_calendar_view(startDateTime, endDateTime, timeZone, subject, top))

    @mcp.tool(
        name="mock_tool_call_update_event",
        description="Move or rename an existing mock calendar event, like Work IQ UpdateEvent." + MOCK_NOTE,
    )
    def mock_tool_call_update_event(
        eventId: Annotated[str, Field(min_length=1, max_length=64)],
        startDateTime: Annotated[str, Field(max_length=40)] = "",
        endDateTime: Annotated[str, Field(max_length=40)] = "",
        timeZone: Annotated[str, Field(max_length=64)] = "",
        subject: ShortText = "",
        location: ShortText = "",
    ) -> MockResult:
        return _result(service.update_event(eventId, startDateTime, endDateTime, timeZone, subject, location))

    @mcp.tool(
        name="mock_tool_call_cancel_event",
        description="Cancel an existing mock calendar event, like Work IQ CancelEvent." + MOCK_NOTE,
    )
    def mock_tool_call_cancel_event(
        eventId: Annotated[str, Field(min_length=1, max_length=64)],
        comment: ShortText = "",
    ) -> MockResult:
        return _result(service.cancel_event(eventId, comment))

    # ---------------------------------------------------- presence and mail

    @mcp.tool(
        name="mock_tool_call_get_user_presence",
        description="Read a directory user's presence, like Work IQ Teams GetUserPresence." + MOCK_NOTE,
    )
    def mock_tool_call_get_user_presence(userEmail: Email) -> MockResult:
        return _result(service.get_user_presence(userEmail))

    @mcp.tool(
        name="mock_tool_call_send_email_with_attachments",
        description="Record an email as sent, like Work IQ Mail SendEmailWithAttachments; no email leaves the service." + MOCK_NOTE,
    )
    def mock_tool_call_send_email_with_attachments(
        to: Annotated[list[Email] | Email, Field(description="Recipient email address or list of addresses.")],
        subject: Annotated[str, Field(min_length=1, max_length=255)],
        body: Text,
        contentType: Literal["Text", "HTML"] = "Text",
        cc: Annotated[list[Email], Field(max_length=10)] = [],
    ) -> MockResult:
        recipients = [to] if isinstance(to, str) else list(to)
        return _result(service.send_email_with_attachments(recipients, subject, body, contentType, list(cc)))

    # ------------------------------------------------------------ salesforce

    @mcp.tool(
        name="mock_tool_call_salesforce_search",
        description=(
            "Search mock CRM Contacts by exact email address, or by full or partial name. Returns up to 5 "
            "contacts with Id, Name, Email, Phone, Title and Account name." + MOCK_NOTE
        ),
    )
    def mock_tool_call_salesforce_search(email: Email = "", name: ShortText = "") -> MockResult:
        return _result(service.salesforce_search(email, name))

    @mcp.tool(
        name="mock_tool_call_salesforce_get_contact",
        description="Get one mock CRM Contact by Contact Id, or by exact email address; found=false when none." + MOCK_NOTE,
    )
    def mock_tool_call_salesforce_get_contact(
        contact_id: Annotated[str, Field(max_length=18)] = "",
        email: Email = "",
    ) -> MockResult:
        return _result(service.salesforce_get_contact(contact_id, email))

    @mcp.tool(
        name="mock_tool_call_salesforce_create_lead",
        description="Create a mock CRM Lead for a prospect. Returns the new Lead Id." + MOCK_NOTE,
    )
    def mock_tool_call_salesforce_create_lead(
        last_name: Annotated[str, Field(min_length=1, max_length=80)],
        company: Annotated[str, Field(min_length=1, max_length=255)],
        first_name: Annotated[str, Field(max_length=40)] = "",
        email: Email = "",
        phone: Annotated[str, Field(max_length=40)] = "",
        title: Annotated[str, Field(max_length=128)] = "",
        description: Text = "",
    ) -> MockResult:
        return _result(service.salesforce_create_lead({
            "last_name": last_name, "company": company, "first_name": first_name, "email": email,
            "phone": phone, "title": title, "description": description,
        }))

    # --------------------------------------------------------------- zendesk

    @mcp.tool(
        name="mock_tool_call_zendesk_search",
        description=(
            "Search the mock help desk by keyword. type=articles searches Help Center articles; type=tickets "
            "searches tickets (a numeric query is read as a ticket id). Returns up to 5 matches with id, title, "
            "status, url and a snippet." + MOCK_NOTE
        ),
    )
    def mock_tool_call_zendesk_search(
        query: Annotated[str, Field(min_length=1, max_length=300)],
        type: Literal["articles", "tickets"] = "articles",
    ) -> MockResult:
        return _result(service.zendesk_search(query, type))

    @mcp.tool(
        name="mock_tool_call_zendesk_add_comment",
        description=(
            "Add a comment to an existing mock help desk ticket. Internal by default; set public=true to make it "
            "visible to the requester. Returns the ticket id and status after the update." + MOCK_NOTE
        ),
    )
    def mock_tool_call_zendesk_add_comment(
        ticket_id: Annotated[str, Field(min_length=1, max_length=20)],
        comment: Annotated[str, Field(min_length=1, max_length=4000)],
        public: bool = False,
    ) -> MockResult:
        return _result(service.zendesk_add_comment(ticket_id, comment, public))

    @mcp.tool(
        name="mock_tool_call_zendesk_create_ticket",
        description=(
            "Create a new mock help desk ticket for an escalation when the caller has no existing ticket. "
            "Returns the new ticket id and status." + MOCK_NOTE
        ),
    )
    def mock_tool_call_zendesk_create_ticket(
        subject: Annotated[str, Field(min_length=1, max_length=150)],
        description: Annotated[str, Field(min_length=1, max_length=4000)],
        requester_name: Annotated[str, Field(max_length=100)] = "",
        requester_email: Email = "",
        priority: Literal["low", "normal", "high", "urgent"] = "normal",
    ) -> MockResult:
        return _result(service.zendesk_create_ticket(subject, description, requester_name, requester_email, priority))

    # ---------------------------------------------------------------- twilio

    @mcp.tool(
        name="mock_tool_call_twilio_send_message",
        description=(
            "Record an SMS as queued, like Twilio send message; no text is delivered. Returns the message SID "
            "and status." + MOCK_NOTE
        ),
    )
    def mock_tool_call_twilio_send_message(
        to: Annotated[str, Field(min_length=1, max_length=32, description="Recipient phone number in E.164 format, for example +14255550142.")],
        body: Annotated[str, Field(min_length=1, max_length=300, description="Message text, at most 300 characters.")],
    ) -> MockResult:
        return _result(service.twilio_send_message(to, body))

    # ---------------------------------------------------------------- orders

    @mcp.tool(
        name="mock_tool_call_order_lookup",
        description=(
            "Look up a mock online store order by order number, or by the account email. Returns status, items, "
            "carrier, tracking number, and the estimated delivery window." + MOCK_NOTE
        ),
    )
    def mock_tool_call_order_lookup(
        order_number: Annotated[str, Field(max_length=20)] = "",
        email: Email = "",
    ) -> MockResult:
        return _result(service.order_lookup(order_number, email))

    # ----------------------------------------------------------------- hotel

    @mcp.tool(
        name="mock_tool_call_hotel_check_availability",
        description="Check mock hotel room availability and the total before taxes for a stay." + MOCK_NOTE,
    )
    def mock_tool_call_hotel_check_availability(
        check_in: IsoDate,
        check_out: IsoDate,
        guests: Annotated[int, Field(ge=1, le=8)],
        room_type: ShortText = "",
    ) -> MockResult:
        return _result(service.hotel_check_availability(check_in, check_out, guests, room_type))

    @mcp.tool(
        name="mock_tool_call_hotel_create_reservation",
        description="Create a mock hotel reservation and return its confirmation number." + MOCK_NOTE,
    )
    def mock_tool_call_hotel_create_reservation(
        first_name: Annotated[str, Field(min_length=1, max_length=60)],
        last_name: Annotated[str, Field(min_length=1, max_length=60)],
        email: Email,
        room_type: Annotated[str, Field(min_length=1, max_length=60)],
        check_in: IsoDate,
        check_out: IsoDate,
        guests: Annotated[int, Field(ge=1, le=8)],
        package: ShortText = "",
    ) -> MockResult:
        return _result(service.hotel_create_reservation(
            first_name, last_name, email, room_type, check_in, check_out, guests, package,
        ))

    @mcp.tool(
        name="mock_tool_call_hotel_get_reservation",
        description="Find a mock hotel reservation by confirmation number and last name." + MOCK_NOTE,
    )
    def mock_tool_call_hotel_get_reservation(
        confirmation_number: Annotated[str, Field(min_length=1, max_length=12)],
        last_name: Annotated[str, Field(min_length=1, max_length=60)],
    ) -> MockResult:
        return _result(service.hotel_get_reservation(confirmation_number, last_name))

    @mcp.tool(
        name="mock_tool_call_hotel_cancel_reservation",
        description="Cancel a mock hotel reservation; reports a one-night fee inside 48 hours of arrival." + MOCK_NOTE,
    )
    def mock_tool_call_hotel_cancel_reservation(
        confirmation_number: Annotated[str, Field(min_length=1, max_length=12)],
        last_name: Annotated[str, Field(min_length=1, max_length=60)],
    ) -> MockResult:
        return _result(service.hotel_cancel_reservation(confirmation_number, last_name))

    # ------------------------------------------------- coaching and research

    @mcp.tool(
        name="mock_tool_call_quiz_record_result",
        description="Record a finished quiz score for the participant's learning record." + MOCK_NOTE,
    )
    def mock_tool_call_quiz_record_result(
        quiz_name: Annotated[str, Field(min_length=1, max_length=120)],
        score: Annotated[int, Field(ge=0, le=100)],
        total: Annotated[int, Field(ge=1, le=100)],
        passing_score: Annotated[int, Field(ge=0, le=100)],
        participant_name: Annotated[str, Field(max_length=100)] = "",
        missed_questions: Annotated[list[Annotated[int, Field(ge=1, le=100)]], Field(max_length=100)] = [],
    ) -> MockResult:
        return _result(service.quiz_record_result(
            quiz_name, participant_name, score, total, passing_score, list(missed_questions),
        ))

    @mcp.tool(
        name="mock_tool_call_training_record_session",
        description="Record a role-play debrief: the scenario, four 1-5 scores, and the key takeaway." + MOCK_NOTE,
    )
    def mock_tool_call_training_record_session(
        scenario: Annotated[str, Field(min_length=1, max_length=120)],
        communication: Rating,
        objection_handling: Rating,
        empathy: Rating,
        resolution: Rating,
        key_takeaway: Annotated[str, Field(min_length=1, max_length=500)],
        participant_name: Annotated[str, Field(max_length=100)] = "",
    ) -> MockResult:
        return _result(service.training_record_session(
            scenario,
            participant_name,
            {
                "communication": communication,
                "objection_handling": objection_handling,
                "empathy": empathy,
                "resolution": resolution,
            },
            key_takeaway,
        ))

    @mcp.tool(
        name="mock_tool_call_research_save_interview_notes",
        description="Save a research interview recap, only when the participant consented to notes." + MOCK_NOTE,
    )
    def mock_tool_call_research_save_interview_notes(
        consent_given: bool,
        summary: Annotated[str, Field(min_length=1, max_length=4000)],
        participant_name: Annotated[str, Field(max_length=100)] = "",
        planning_ease_rating: Annotated[int, Field(ge=0, le=5, description="1-5, or 0 when not asked.")] = 0,
        confidence_rating: Annotated[int, Field(ge=0, le=5, description="1-5, or 0 when not asked.")] = 0,
    ) -> MockResult:
        return _result(service.research_save_interview_notes(
            consent_given,
            participant_name,
            summary,
            {"planning_ease": planning_ease_rating, "confidence": confidence_rating},
        ))
