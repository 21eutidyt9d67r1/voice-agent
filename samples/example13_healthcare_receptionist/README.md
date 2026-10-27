# Healthcare Receptionist with Handoff

## Conclusion

`agent.json` is a Voice Agent for a fictional practice, Greenfield Medical
Center, that handles appointment and change requests as a staged handoff graph.
It is the same conversation design that the Microsoft Foundry **Healthcare
receptionist** template creates. It gives no medical advice.

By default, its business tools run on the shared **mock-tool-call** MCP server:
Microsoft 365 calendar tools to find and book a visit, and a Zendesk ticket that
files a cancel or reschedule request for the front desk. The mocks take the
same arguments and return the same fields as the real tools, but results are
fictional and nothing real is booked or sent. To connect real systems, use **Connect my tools** in the Portal Editor or a Foundry Toolbox in your own Project; see
[Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try emergency screening, patient-detail capture, office-hours slot
filtering, and read-backs that must get a yes before a visit is booked or a
request is filed.

## Workflow

| Stage | Purpose |
| --- | --- |
| `greeting` | Find out whether the caller wants a new visit, a change, an office answer, or has an urgent issue. |
| `collect_info` | Capture the patient's full name and date of birth, plus reason for visit and contact details for a new appointment. |
| `schedule` | Match a provider, offer returned office-hours slots, read the appointment back, and book it after a yes. |
| `cancel_reschedule` | Capture the existing appointment, mention the 24-hour policy, find new slots for a reschedule, and file a front-desk request after a yes. |
| `wrap_up` | Recap only what a tool reported: the booked visit, or the request number. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `schedule` | `mock_tool_call_find_meeting_times`, `mock_tool_call_get_user_date_and_time_zone_settings`, `mock_tool_call_create_event` |
| `cancel_reschedule` | `mock_tool_call_find_meeting_times`, `mock_tool_call_get_user_date_and_time_zone_settings`, `mock_tool_call_zendesk_create_ticket` |

The other stages have no tools. The agent does not change the calendar for a
cancel or reschedule; it files a ticket for the front desk instead.
`mock_tool_call_create_event` and `mock_tool_call_zendesk_create_ticket` each
run once, only after the caller says yes to the read-back. The event leaves out
the reason for visit and the date of birth.

## Sample data

Greenfield Medical Center, 200 Greenfield Avenue, Redmond, Washington, Monday to
Friday, 8 AM to 5 PM Pacific. Providers: Dr. Maya Patel, general medicine; Dr.
Luis Ortega, pediatrics; Dr. Hannah Kim, internal medicine. Visits are 30
minutes; bring photo ID, an insurance card, and prior records. Cancellations
need 24 hours' notice. The front desk confirms cancel and reschedule requests
within one business day. Emergencies: 911; after-hours nurse line 425-555-0150.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):

- The calendar owner is in Pacific Standard Time; meeting suggestions come back
  in UTC. About one half-hour start in five is busy.
- New tickets get a random four-digit number. The mock keeps nothing callers say, so a new
  ticket cannot be looked up later.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 13: Healthcare Receptionist**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system. Microsoft 365 (Work IQ) tools stay on mock data in the shared
Playground because they act as the signed-in user.

## Try these turns

- "I'd like a checkup with Dr. Patel next Wednesday morning." Expect name,
  date-of-birth, and contact questions (for a new patient, give "Dana Test",
  "+1 425 555 0123", and `dana.test20261020@example.com`), then
  `mock_tool_call_get_user_date_and_time_zone_settings` and
  `mock_tool_call_find_meeting_times`, and two or three slots between 8:00 AM
  and 4:30 PM Pacific.
- Pick a slot and give `dana.test20261020@example.com`. Expect the date, time,
  provider, and what to bring read back with a question whether to book it.
  After "Yes", expect `mock_tool_call_create_event` once and the booking
  reported.
- "I need to cancel my appointment on Thursday at 10 AM." Expect the 24-hour
  policy, a callback number question (give "+1 425 555 0123"), and the request
  read back. After "Yes",
  expect `mock_tool_call_zendesk_create_ticket` once, a request number, and that
  the front desk confirms within one business day.
- "I have chest pain right now." Expect a direction to call 911 and the nurse
  line, with no medical advice.

## Boundaries

- The practice, providers, phone numbers, calendar, and tickets are fictional
  and come from the mock server; there is no patient record or messaging
  system.
- `store` is `false`; enable persistence deliberately if you need it.
- To use real calendar and ticketing systems, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
