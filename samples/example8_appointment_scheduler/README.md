# Appointment Scheduler with Handoff

## Conclusion

`agent.json` is a Voice Agent for a fictional clinic, Contoso Wellness Clinic,
that handles new, reschedule, and cancel requests as a staged handoff graph. It
is the same conversation design that the Microsoft Foundry **Appointment
scheduler** template creates.

By default, its business tools run on the shared **mock-tool-call** MCP server:
Microsoft 365 calendar tools to find free times, book a visit, and find, move,
or cancel an existing one. The mocks take the same arguments and return the
same fields as the real tools, but results are fictional and nothing real is
booked or sent. To connect real systems, use **Connect my tools** in the Portal Editor or a Foundry Toolbox in your own Project; see
[Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try intent routing between booking and change requests,
one-question-at-a-time data capture, and read-backs that must get a yes before a
calendar event is created, moved, or cancelled.

## Workflow

| Stage | Purpose |
| --- | --- |
| `greeting` | Find out whether the caller wants to book, reschedule, or cancel, and hand off right away. |
| `collect_info` | Capture name, email for the confirmation, and the service, one question at a time. |
| `new_booking` | Offer two or three returned slots, read the booking back, and create the event after a yes. |
| `change_cancel` | Find the caller's event by name and date, read it back, then move or cancel it after a yes. |
| `confirm` | Read back the details and the result the tool reported, plus any prep. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `new_booking` | `mock_tool_call_find_meeting_times`, `mock_tool_call_get_user_date_and_time_zone_settings`, `mock_tool_call_create_event` |
| `change_cancel` | `mock_tool_call_list_calendar_view`, `mock_tool_call_update_event`, `mock_tool_call_cancel_event`, `mock_tool_call_find_meeting_times`, `mock_tool_call_get_user_date_and_time_zone_settings` |

The other stages have no tools. Each write (`mock_tool_call_create_event`,
`mock_tool_call_update_event`, or `mock_tool_call_cancel_event`) runs once,
only after the caller says yes to the read-back. No customer record or text
tool is connected.

## Sample data

Contoso Wellness Clinic offers an initial consultation (60 minutes), a follow-up
visit (30 minutes), and a nutrition check-in (30 minutes). Visits are Microsoft
Teams video calls, Monday to Friday, 9 AM to 5 PM in the caller's timezone. For
an initial consultation, bring a list of current medications and questions.
Bookings are calendar events named after the service and the caller, such as
"Follow-up visit with Dana Test".

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):

- The calendar owner is in Pacific Standard Time; meeting suggestions come back
  in UTC. About one half-hour start in five is busy.
- Seeded events: "Follow-up visit with Dana Test", next Thursday 10:00-10:30
  AM Pacific, and "Initial consultation with Jordan Lee", next Friday 2:00-3:00
  PM Pacific.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 8: Appointment Scheduler**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system. Microsoft 365 (Work IQ) tools stay on mock data in the shared
Playground because they act as the signed-in user.

## Try these turns

- "I'd like to book an initial consultation, Thursday afternoon, Pacific time."
  Expect name and email questions; answer "Dana Test,
  dana.test20261020@example.com". Then expect two or three slots returned by
  `mock_tool_call_find_meeting_times`.
- Pick a slot. Expect the service, date, time, timezone, email, and the
  medication-list prep read back with a question whether to book it; nothing is
  created yet.
- "Yes, book it." Expect `mock_tool_call_create_event` once, then the booked
  time and the invite with the Teams link reported as sent.
- "This is Dana Test. I need to move my follow-up visit next Thursday, Pacific
  time." When asked for the confirmation email, give
  `dana.test20261020@example.com`. Expect `mock_tool_call_list_calendar_view`
  to find the 10:00 AM visit,
  new slots, the old and new time read back, and after "Yes"
  `mock_tool_call_update_event`.
- "This is Jordan Lee, please cancel my consultation next Friday." When asked
  for the confirmation email, give `jordan.lee@example.com`. Expect the
  2:00 PM event read back, no new times offered, and after "Yes"
  `mock_tool_call_cancel_event`. Say "No, keep it" instead and nothing changes.

## Boundaries

- The clinic, services, hours, and calendar data are fictional and come from the
  mock server; no visit or invite is real. There is no patient record or mail
  system.
- `store` is `false`; enable persistence deliberately if you need it.
- To use a real calendar, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
