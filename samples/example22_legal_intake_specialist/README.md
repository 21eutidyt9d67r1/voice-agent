# Legal Intake Specialist with Handoff

## Conclusion

`agent.json` is a Voice Agent for a fictional law firm, Contoso Law Group, that
runs confidential intake as a staged handoff graph. It is the same conversation
design that the Microsoft Foundry **Legal intake specialist** template creates.

By default its business tools run on the shared **mock-tool-call** MCP server:
mock Salesforce tools that save the intake as a lead, and mock Microsoft 365
calendar tools that find free times and book a 45-minute consultation. Results
are fictional, and nothing real is saved, booked, or sent. To connect real
systems, use **Connect my tools** in the Portal Editor or a Foundry Toolbox in your
own Project; see [Connect real tools](../../docs/05_connect_real_tools.md).

The agent gives no legal advice and quotes no fees.

## When to use this example

Use it to try confidential intake, scope screening, emergency routing, and
writes to a CRM and calendar that wait for a yes, before you connect real CRM or
calendar tools.

## Workflow

| Stage | Purpose |
| --- | --- |
| `greeting` | Introduce the firm and reassure the caller that what they share is confidential. |
| `identify_matter` | Clarify the matter type. |
| `emergency_resources` | Direct a caller in or near an emergency to emergency services. |
| `conflict_check` | Capture the other parties' names and event dates before detailed facts. |
| `refer_out` | Refer out-of-scope matters to the bar association's lawyer referral service. |
| `collect_facts` | Capture the facts and contact details, read back the intake, and save it as a lead after a yes. |
| `wrap_up` | Confirm the booked consultation, the referral, or that the firm will follow up. |
| `schedule_consultation` | Offer returned 45-minute slots and book the consultation after a yes. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `collect_facts` | `mock_tool_call_salesforce_search`, `mock_tool_call_salesforce_get_contact`, `mock_tool_call_salesforce_create_lead` |
| `schedule_consultation` | `mock_tool_call_find_meeting_times`, `mock_tool_call_get_user_date_and_time_zone_settings`, `mock_tool_call_create_event` |

The other stages have no tools. Both writes run once, only after the caller
says yes to the read-back. When the email matches an existing contact, no lead
is created and the intake is noted for the attorney.

## Sample data

Contoso Law Group, 100 Contoso Plaza, Seattle, Washington. Practice areas:
personal injury, employment law, family law, and estate planning. Not handled:
criminal defense, immigration, bankruptcy, or tax. Consultations are 45 minutes
on weekdays by video, phone, or in person; fees are discussed at the
consultation.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):

- Existing CRM contact: Jordan Lee, `jordan.lee@example.com`. Any other email,
  such as `dana.test20261020@example.com`, is new, and a lead is created with an
  id starting `00QMOCK`.
- The calendar owner is in Pacific Standard Time; meeting suggestions come back
  in UTC, and the agent converts them to the caller's time zone.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 22: Legal Intake Specialist**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system. Microsoft 365 (Work IQ) tools stay on mock data in the shared
Playground because they act as the signed-in user.

## Try these turns

- "I was rear-ended last month and hurt my back." Expect the conflict-check
  question, fact collection, and an intake summary read back with a question.
- Give `dana.test20261020@example.com` and say "yes". Expect
  `mock_tool_call_salesforce_search`, then
  `mock_tool_call_salesforce_create_lead` once and "saved for attorney review".
  With `jordan.lee@example.com`, expect no lead and "noted for the attorney".
- "Video, Tuesday or Wednesday, Pacific time." Expect
  `mock_tool_call_find_meeting_times` and two or three returned slots.
- Pick a slot and confirm the read-back. Expect `mock_tool_call_create_event`
  once and the invite reported as sent.
- "I was arrested and need a defense lawyer." Expect a referral to the lawyer
  referral service and no booking.

## Boundaries

- The firm, practice areas, leads, and calendar data are fictional and come from
  the mock server; no intake is saved and no consultation is booked.
- `store` is `false`; enable persistence deliberately if you need it.
- To use a real CRM or calendar, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
