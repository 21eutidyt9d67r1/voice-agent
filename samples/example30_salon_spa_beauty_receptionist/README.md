# Salon and Spa Receptionist with Handoff

## Conclusion

`agent.json` is a Voice Agent for a fictional salon, Contoso Salon and Spa, that
answers menu questions and books appointments as a staged handoff graph. It is
the same conversation design that the Microsoft Foundry **Salon and spa
receptionist** template creates.

By default, its business tools run on the shared **mock-tool-call** MCP server:
Microsoft 365 calendar tools to find open times and create the appointment, and
a Twilio SMS tool for an optional reminder text. The mocks take the same
arguments and return the same fields as the real tools, but results are
fictional and nothing real is booked or sent. To connect real systems, use **Connect my tools** in the Portal Editor or a Foundry Toolbox in your own Project; see
[Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try menu-grounded answers, stylist matching, and a confirmed booking
with an optional reminder text.

## Workflow

| Stage | Purpose |
| --- | --- |
| `greeting` | Greet the caller and find out what they need. |
| `service_inquiry` | Give prices and durations from the sample menu only. |
| `book_appointment` | Capture service, stylist, and new or existing client, then offer returned open times. |
| `confirm` | Read back the appointment, book it after a yes, and offer a reminder text. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `book_appointment` | `mock_tool_call_find_meeting_times`, `mock_tool_call_get_user_date_and_time_zone_settings` |
| `confirm` | `mock_tool_call_create_event`, `mock_tool_call_twilio_send_message` |

`greeting`, `service_inquiry`, and `end` have no tools. Each write runs at most
once, only after the client says yes to the read-back.

## Sample data

Contoso Salon and Spa, 25 Contoso Avenue, Seattle, Tuesday to Saturday, 9 AM to
7 PM Pacific. Menu includes a women's haircut and style $65 (60 minutes),
balayage from $180 (3 hours, consultation recommended), and a classic facial $90
(60 minutes). Stylists: Jessica, Marco, Priya, and Lee. Services of $150 or more
need a $50 deposit paid in person.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):

- Meeting suggestions come back in UTC; the calendar owner is in Pacific
  Standard Time. About one half-hour start in five is busy.
- Any valid E.164 number, such as +14255550123, is queued. Texting
  **+15005550001** fails with error code `21211`.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 30: Salon and Spa Receptionist**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system. Microsoft 365 (Work IQ) tools stay on mock data in the shared
Playground because they act as the signed-in user.

## Try these turns

- "I'd like a women's haircut with Jessica on Saturday." Expect a question
  about new or existing client, then up to three 60-minute times within opening
  hours returned by `mock_tool_call_find_meeting_times`.
- Pick a time and give an email. Expect the service, stylist, date, time, $65,
  and 60 minutes read back. After "yes", expect one
  `mock_tool_call_create_event` call, the booking reported, and a reminder
  offer.
- Accept the reminder with "+1 500 555 0001". Expect one
  `mock_tool_call_twilio_send_message` call and the reminder reported as not
  sent. Use +14255550123 instead and it is reported as sent.
- "How much is balayage?" Expect from $180, 3 hours, and the in-person deposit.
- "I'm unhappy with my last color." Expect a note for the salon manager, read
  back.

## Boundaries

- The salon, menu, stylists, calendar, and SMS results are fictional and come
  from the mock server; no appointment or text is real.
- `store` is `false`; enable persistence deliberately if you need it.
- To use real calendar and SMS systems, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
