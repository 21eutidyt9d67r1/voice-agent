# New Hire Onboarding Assistant with Handoff

## Conclusion

`agent.json` is a Voice Agent for a fictional company, Contoso, that guides a
new hire through day one as a staged handoff graph. It is the same conversation
design that the Microsoft Foundry **New hire onboarding assistant** template
creates.

By default its business tools run on the shared **mock-tool-call** MCP server:
mock Microsoft 365 calendar tools that find a free time and book the first 1:1
with the manager, and a mock Twilio text that sends the key contacts. Results
are fictional, and nothing real is booked or sent. To connect real systems, use **Connect my tools** in the Portal Editor or a Foundry Toolbox in your own Project;
see [Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try role-based branching, one-item-at-a-time walkthroughs, and a
calendar booking and a text that wait for a yes, before you connect real
calendar or SMS tools.

## Workflow

| Stage | Purpose |
| --- | --- |
| `welcome` | Welcome the new hire and ask how they are feeling. |
| `confirm_role` | Ask which role they are starting in. |
| `engineering_track` | Walk through laptop setup, GitHub access, the handbook, on-call, and the first task, then book a 1:1 with Alex Wilber. |
| `sales_track` | Walk through Salesforce access, territory, quota ramp, and the enablement library, then book a 1:1 with Megan Bowen. |
| `ops_track` | Walk through systems access, team SOPs, and key vendors, then book a 1:1 with Isaiah Langer. |
| `benefits` | Walk through medical, dental, and the 401k one at a time. |
| `wrap_up` | Share the key people to meet this week and text the contact list after the number is confirmed. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `engineering_track` | `mock_tool_call_find_meeting_times`, `mock_tool_call_get_user_date_and_time_zone_settings`, `mock_tool_call_create_event` |
| `sales_track` | `mock_tool_call_find_meeting_times`, `mock_tool_call_get_user_date_and_time_zone_settings`, `mock_tool_call_create_event` |
| `ops_track` | `mock_tool_call_find_meeting_times`, `mock_tool_call_get_user_date_and_time_zone_settings`, `mock_tool_call_create_event` |
| `wrap_up` | `mock_tool_call_twilio_send_message` |

The other stages have no tools. `mock_tool_call_create_event` runs once, only
after the new hire says yes to the read-back, and
`mock_tool_call_twilio_send_message` runs once, only after they confirm the
number.

## Sample data

Contacts: Alex Wilber, engineering tech lead (`alexw@contoso.com`); Megan
Bowen, sales manager (`meganb@contoso.com`); Isaiah Langer, operations manager
(`isaiahl@contoso.com`); Adele Vance, HR people partner (`adelev@contoso.com`);
the IT help desk (`it@contoso.com`). Benefits: medical (PPO or HMO), dental,
and a 401k with a 4 percent match; enroll within 30 days.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):

- The calendar owner is in Pacific Standard Time; meeting suggestions come back
  in UTC, and the agent converts them to the new hire's time zone.
- A text to any valid E.164 number is queued; `+15005550001` fails with error
  code 21211, and a number without a country code also fails.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 24: New Hire Onboarding Assistant**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system. Microsoft 365 (Work IQ) tools stay on mock data in the shared
Playground because they act as the signed-in user.

## Try these turns

- "I'm a new software engineer." Expect engineering items one at a time, then an
  offer to book a 1:1 with Alex Wilber.
- "Wednesday or Thursday, Pacific time." Expect
  `mock_tool_call_find_meeting_times` with `alexw@contoso.com` and two or three
  returned slots. Pick one and say "yes" to the read-back; expect
  `mock_tool_call_create_event` once and the invite reported as sent.
- "What's the 401k match?" Expect 4 percent and the 30-day enrollment window.
- "Text me the contacts at +1 425 555 0123." Expect the number read back, then
  `mock_tool_call_twilio_send_message` once and the text reported as sent.
- Give `+15005550001` instead. Expect that the text was not sent and the
  contacts read out instead.

## Boundaries

- The company, people, addresses, and tool results are fictional and come from
  the mock server; no invite or text is delivered.
- `store` is `false`; enable persistence deliberately if you need it.
- To use a real calendar or SMS service, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
