# Inbound Lead Qualifier with Handoff

## Conclusion

`agent.json` is a Voice Agent for a fictional software company, Contoso, that
qualifies inbound prospects as a staged handoff graph. It is the same
conversation design that the Microsoft Foundry **Inbound lead qualifier**
template creates.

By default, its business tools run on the shared **mock-tool-call** MCP server:
Microsoft 365 calendar tools to find a slot and send a meeting invite, and
Salesforce tools to look up the contact and create a lead. The mocks take the
same arguments and return the same fields as the real tools, but results are
fictional and nothing real is booked or sent. To connect real systems, use **Connect my tools** in the Portal Editor or a Foundry Toolbox in your own Project; see
[Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try BANT qualification, hot or nurture routing, a confirmed
account-executive meeting, and a CRM lead created only for new prospects.

## Workflow

| Stage | Purpose |
| --- | --- |
| `greeting` | Thank the caller and ask what prompted the call. |
| `identify_needs` | Understand the core problem, what success looks like, and what they have tried. |
| `qualify_bant` | Collect budget, authority, need, and timeline conversationally. |
| `route_hot` | Offer returned meeting slots, send the invite after a yes, then look up the contact and create a lead if none exists. |
| `route_nurture` | Capture contact details and a follow-up preference, then look up the contact and create a lead if none exists. |
| `wrap_up` | Confirm the next step from what a tool reported: the invite sent, the follow-up saved, or details noted. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `route_hot` | `mock_tool_call_find_meeting_times`, `mock_tool_call_get_user_date_and_time_zone_settings`, `mock_tool_call_create_event`, `mock_tool_call_salesforce_search`, `mock_tool_call_salesforce_get_contact`, `mock_tool_call_salesforce_create_lead` |
| `route_nurture` | `mock_tool_call_salesforce_search`, `mock_tool_call_salesforce_get_contact`, `mock_tool_call_salesforce_create_lead` |

The other stages have no tools. `mock_tool_call_create_event` runs once, only
after the prospect says yes to the read-back. `mock_tool_call_salesforce_create_lead`
runs at most once, and only when `mock_tool_call_salesforce_search` finds no
contact for the prospect's email. Live transfer is not available.

## Sample data

Contoso sells a cloud collaboration platform for mid-size and enterprise teams.
Account-executive meetings are 30-minute Teams video calls on weekdays covering
pricing, case studies, and a walkthrough. The agent quotes no prices or
discounts.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):

- Meeting suggestions come back in UTC; the calendar owner is in Pacific
  Standard Time. About one half-hour start in five is busy.
- Existing CRM contacts include Jack Rogers, `jrogers@burlington.com`
  (Burlington Textiles Corp of America). Any other email, such as
  `dana.test20261020@example.com`, is a new prospect, so a Lead is created
  with an ID starting `00QMOCK`.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 15: Inbound Lead Qualifier**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system. Microsoft 365 (Work IQ) tools stay on mock data in the shared
Playground because they act as the signed-in user.

## Try these turns

- "I'm Dana from Fabrikam. Budget is approved, I decide, and we need it within
  two months." Expect an offer of a 30-minute Teams meeting, a question about
  days and timezone, then two or three slots returned by
  `mock_tool_call_find_meeting_times`.
- Pick a slot and give `dana.test20261020@example.com`. Expect the email spelled
  back and the date, time, timezone, and email read back with a question
  whether to send the invite; nothing is created yet.
- "Yes, send it." Expect `mock_tool_call_create_event` once and the invite
  reported as sent, then a Salesforce search that finds nothing and one
  `mock_tool_call_salesforce_create_lead` call.
- "I'm Jack Rogers from Burlington Textiles. We're just exploring, no budget
  yet." Expect a nurture follow-up; with `jrogers@burlington.com` the search
  finds the contact and no lead is created.
- "How much does it cost?" Expect no price; the account executive covers
  pricing.

## Boundaries

- The company, product, calendar, and CRM data are fictional and come from the
  mock server; no invite or lead is real. There is no mail system.
- `store` is `false`; enable persistence deliberately if you need it.
- To use real calendar and CRM systems, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
