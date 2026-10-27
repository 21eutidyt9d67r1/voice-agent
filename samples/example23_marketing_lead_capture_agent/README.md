# Marketing Lead Capture with Handoff

## Conclusion

`agent.json` is a Voice Agent for a fictional workflow automation product,
Contoso Flow, that captures leads as a staged handoff graph. It is the same
conversation design that the Microsoft Foundry **Marketing lead capture**
template creates.

By default its business tools run on the shared **mock-tool-call** MCP server:
mock Microsoft 365 calendar tools that book a 30-minute sales call, and mock
Salesforce tools that check for a contact and create a lead. Results are
fictional, and nothing real is booked, saved, or sent. To connect real systems,
use **Connect my tools** in the Portal Editor or a Foundry Toolbox in your own
Project; see [Connect real tools](../../docs/05_connect_real_tools.md).

No mail tool is connected: the agent never sends a case study or pricing
overview itself; the team follows up.

## When to use this example

Use it to try conversational lead capture, hot or nurture routing, and calendar
and CRM writes that wait for a yes, before you connect real calendar and CRM
tools.

## Workflow

| Stage | Purpose |
| --- | --- |
| `greeting` | Welcome the visitor and ask what brought them here. |
| `collect` | Collect name, email, company, role, the problem, timeline, and any budget signal. |
| `hot` | Offer returned slots and book the sales call after a yes; then offer an optional CRM save and, only after a separate yes, create a lead when no contact exists. |
| `nurture` | Capture the resource they want and a follow-up preference, and create a lead after a yes. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `hot` | `mock_tool_call_find_meeting_times`, `mock_tool_call_get_user_date_and_time_zone_settings`, `mock_tool_call_create_event`, `mock_tool_call_salesforce_search`, `mock_tool_call_salesforce_create_lead` |
| `nurture` | `mock_tool_call_salesforce_search`, `mock_tool_call_salesforce_create_lead` |

The other stages have no tools. Each write runs once, only after the visitor
says yes to the read-back. In `hot`, consent to the invite is not consent to
the CRM save: the agent reads back what would be stored and asks separately.
When the email matches an existing contact, no lead is created.

## Sample data

Contoso Flow is a no-code workflow automation platform with Starter, Business,
and Enterprise tiers; sales shares exact prices. A free 14-day trial is
available. Resources: a case study, a pricing overview, and a demo video. Sales
calls are 30-minute Teams video calls on weekdays.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):

- Existing CRM contacts include Jack Rogers, `jrogers@burlington.com`, and Rose
  Gonzalez, `rose@edge.com`. Any other email, such as
  `dana.test20261020@example.com`, is a new prospect, and a lead is created with
  an id starting `00QMOCK`.
- The calendar owner is in Pacific Standard Time; meeting suggestions come back
  in UTC, and the agent converts them to the visitor's time zone.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 23: Marketing Lead Capture**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system. Microsoft 365 (Work IQ) tools stay on mock data in the shared
Playground because they act as the signed-in user.

## Try these turns

- "I run operations at Fabrikam and we need to automate approvals this month;
  can we schedule a call? I'm on Pacific time." Expect
  `mock_tool_call_find_meeting_times` and two or three returned slots.
- Pick a slot and give `dana.test20261020@example.com`. Expect the date, time,
  time zone, and email read back. After "yes", expect
  `mock_tool_call_create_event` once and the invite result, then an offer to
  save your details as a CRM lead with the data read back; no CRM tool runs
  yet.
- "Yes, save it." Expect `mock_tool_call_salesforce_search` and
  `mock_tool_call_salesforce_create_lead`, each once, and the lead reported as
  saved. Say "No" instead: expect no CRM call and that your details will not be
  kept for follow-up; the booking stands.
- "Just browsing; send me the pricing overview. Dana Test, Fabrikam,
  dana.test20261020@example.com." Expect your details read back,
  and after "yes" a lead and "the team will follow up", never "sent".
- Use `rose@edge.com` in the nurture path. Expect the contact found and no new
  lead.
- "How much is Business?" Expect that sales shares exact prices, and the trial.

## Boundaries

- The product, tiers, leads, and calendar data are fictional and come from the
  mock server; no call is booked and no resource is sent.
- `store` is `false`; enable persistence deliberately if you need it.
- To use a real calendar or CRM, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
