# Outbound Sales Representative with Handoff

## Conclusion

`agent.json` is a Voice Agent for an outbound call from a fictional data
platform, CloudSync, as a staged handoff graph. It is the same conversation
design that the Microsoft Foundry **Outbound sales representative** template
creates.

By default, its business tools run on the shared **mock-tool-call** MCP server:
Microsoft 365 calendar tools to find a demo slot and send the invite, and
Salesforce tools to look up the contact and create a lead. The mocks take the
same arguments and return the same fields as the real tools, but results are
fictional and nothing real is booked or sent. To connect real systems, use **Connect my tools** in the Portal Editor or a Foundry Toolbox in your own Project; see
[Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try permission-based openers, concise objection handling, do-not-call
requests, and a confirmed demo booking with a CRM follow-up.

## Workflow

| Stage | Purpose |
| --- | --- |
| `opener` | Ask permission for 30 seconds. |
| `pitch` | Give one value proposition and one qualifying question, then listen. |
| `close` | Wrap up warmly whatever the outcome; mention the invite only when it was created. |
| `book` | Offer returned demo slots, read the invite back, and create it after a yes; then offer an optional CRM save and, only after a separate yes, look up or create the lead. |
| `handle_objection` | Acknowledge the objection, answer with one concrete point, and check it resolved the concern. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `book` | `mock_tool_call_find_meeting_times`, `mock_tool_call_get_user_date_and_time_zone_settings`, `mock_tool_call_create_event`, `mock_tool_call_salesforce_search`, `mock_tool_call_salesforce_get_contact`, `mock_tool_call_salesforce_create_lead` |

The other stages have no tools. `mock_tool_call_create_event` and
`mock_tool_call_salesforce_create_lead` run at most once each, and the invite is
created only after the lead says yes to the read-back. The CRM tools run only
after a separate yes to saving the details read back; consent to the invite is
not consent to the CRM save.

## Sample data

CloudSync keeps data from apps and databases in sync in real time. Demos are
30-minute Teams video calls with an account executive on weekdays. Most teams
start by replacing one pipeline. No prices are quoted.

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
3. Select **Example 26: Outbound Sales Representative**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system. Microsoft 365 (Work IQ) tools stay on mock data in the shared
Playground because they act as the signed-in user.

## Try these turns

- "Sure, I have a minute. That sounds useful, I'd like a demo." Expect a
  question about days and time zone, then two or three slots returned by
  `mock_tool_call_find_meeting_times`.
- Pick a slot and give "Dana Test, Fabrikam, dana.test20261020@example.com".
  Expect the date, time, time zone, and email read back and a question whether
  to send the invite; nothing is created yet.
- "Yes, send it." Expect `mock_tool_call_create_event` once and the invite
  reported as sent, then an offer to save your details as a CRM lead with the
  data read back; no CRM tool runs yet.
- "Yes, save it." Expect a Salesforce search that finds nothing and one
  `mock_tool_call_salesforce_create_lead` call. Use `jrogers@burlington.com`
  instead and no lead is created because the contact exists. Say "No" instead
  and no CRM tool runs; your details are not kept for follow-up.
- "We already built our own pipelines and we're too busy." Expect one concrete
  point from the sample facts.
- "Take me off your list." Expect the request noted for the team, without a
  claim that it was processed, and the call ending.

## Boundaries

- The company, product, calendar, and CRM data are fictional and come from the
  mock server; no invite or lead is real.
- `store` is `false`; enable persistence deliberately if you need it.
- To use real calendar and CRM systems, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
