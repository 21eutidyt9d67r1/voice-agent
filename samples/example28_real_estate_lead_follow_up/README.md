# Real Estate Lead Follow-Up with Handoff

## Conclusion

`agent.json` is a Voice Agent for a fictional brokerage, Contoso Realty, that
follows up property leads as a staged handoff graph. It is the same
conversation design that the Microsoft Foundry **Real estate lead follow-up**
template creates.

By default, its business tools run on the shared **mock-tool-call** MCP server:
Microsoft 365 calendar tools to find a showing time and send the invite, and
Salesforce tools to look up the buyer and create a lead. The mocks take the
same arguments and return the same fields as the real tools, but results are
fictional and nothing real is booked or sent. To connect real systems, use **Connect my tools** in the Portal Editor or a Foundry Toolbox in your own Project; see
[Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try buyer qualification, listing discussion from sample facts, and a
confirmed showing booking or information request saved to a CRM.

## Workflow

| Stage | Purpose |
| --- | --- |
| `greeting` | Introduce yourself, reference the property they viewed, and thank them. |
| `qualify` | Understand timeline, budget, pre-approval, and what they want. |
| `discuss_properties` | Discuss one to three matching listings from the sample facts only. |
| `book_showing` | Offer returned showing times, send the invite after a yes, then look up or create the lead. |
| `send_info` | Capture which information they want and a follow-up call time, then look up or create the lead after a yes. |
| `wrap_up` | Confirm the next step that actually happened on the call. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `book_showing` | `mock_tool_call_find_meeting_times`, `mock_tool_call_get_user_date_and_time_zone_settings`, `mock_tool_call_create_event`, `mock_tool_call_salesforce_search`, `mock_tool_call_salesforce_get_contact`, `mock_tool_call_salesforce_create_lead` |
| `send_info` | `mock_tool_call_salesforce_search`, `mock_tool_call_salesforce_get_contact`, `mock_tool_call_salesforce_create_lead` |

The other stages have no tools. Each write runs at most once, only after the
buyer says yes to the read-back. The agent never sends floor plans or tours
itself; it saves the request for the agent's team.

## Sample data

14 Maple Court, Redmond: 3 bed, 2 bath craftsman, $849,000. 220 Lakeview Drive,
Kirkland: 2 bed, 2 bath condo, $695,000. 8 Cedar Lane, Bellevue: 4 bed, 3 bath
modern home, $1,450,000. Showings take 45 minutes at the property's front door.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):

- Meeting suggestions come back in UTC; the calendar owner is in Pacific
  Standard Time. About one half-hour start in five is busy.
- Existing CRM contacts include Jordan Lee, `jordan.lee@example.com`. Any other
  email, such as `dana.test20261020@example.com`, is a new prospect, so a Lead
  is created with an ID starting `00QMOCK`.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 28: Real Estate Lead Follow-Up**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system. Microsoft 365 (Work IQ) tools stay on mock data in the shared
Playground because they act as the signed-in user.

## Try these turns

- "We want three bedrooms in Redmond under 900k. Can I see 14 Maple Court
  Saturday?" Expect listed features only, then up to three 45-minute times
  returned by `mock_tool_call_find_meeting_times`.
- Pick a time and give "Dana Test, dana.test20261020@example.com" and a phone
  number. Expect the address, date, time, time zone, and email read back. After
  "yes", expect one `mock_tool_call_create_event` call, the invite reported as
  sent, and a new lead created because the email is not in the CRM.
- "Send me the floor plans for the Kirkland condo," as Jordan Lee,
  `jordan.lee@example.com`. Expect a read-back and, after "yes", a Salesforce
  search that finds the contact, no new lead, and the request noted for Marco.
- "What's the kitchen like at 8 Cedar Lane?" Expect no invented details.
- "No thanks, bye." Expect a short goodbye and the session ending.

## Boundaries

- The brokerage, listings, calendar, and CRM data are fictional and come from
  the mock server; no showing or lead is real.
- `store` is `false`; enable persistence deliberately if you need it.
- To use real calendar and CRM systems, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
