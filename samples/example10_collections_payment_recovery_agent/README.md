# Collections and Payment Recovery with Handoff

## Conclusion

`agent.json` is a Voice Agent for an outbound collections call from a fictional
lender, Contoso Financial, as a staged handoff graph. It is the same
conversation design that the Microsoft Foundry **Collections and payment
recovery** template creates.

By default, its business tools run on the shared **mock-tool-call** MCP server:
a Salesforce contact search for the billing team's follow-up and a Twilio text
message that confirms the arrangement. The mocks take the same arguments and
return the same fields as the real tools, but results are fictional and no text
is delivered. No payment system is connected, so no payment is taken. To
connect real systems, use **Connect my tools** in the Portal Editor or a Foundry
Toolbox in your own Project; see
[Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try identity checks before disclosure, a required disclosure line,
empathetic hardship handling, and a confirmed arrangement followed by a CRM
lookup and an optional text.

## Workflow

| Stage | Purpose |
| --- | --- |
| `verify` | Confirm the account holder with the sample verification details without reading them aloud. |
| `discuss` | Give the debt-collection disclosure, the balance, and the days past due, and ask whether the holder can pay. |
| `pay` | Capture the arrangement and read it back; after a yes, find the contact record, then text a confirmation if the holder agrees. |
| `hardship` | Explain the hardship program and capture a commitment collected for manual follow-up by the billing team. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `pay` | `mock_tool_call_salesforce_search`, `mock_tool_call_twilio_send_message` |

The other stages have no tools. In `pay`, no tool runs before the holder says
yes to the arrangement read-back. `mock_tool_call_salesforce_search` then runs
once with the email on file, and `mock_tool_call_twilio_send_message` runs once,
only after a second yes to the text. Record fields are never read aloud.

## Sample data

Holder Jordan Lee, account ending 4821, born March 14, 1985, balance $482.16, 47
days past due. Email on file `jordan.lee@example.com`, mobile on file
+14255550123. Options: pay in full; 3 monthly payments of $160.72 or 6 of
$80.36; or the hardship program, $25 a month for up to 6 months or a 30-day
pause. Written disputes go to Contoso Financial Disputes, 1 Contoso Way,
Redmond, Washington, within 30 days.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):

- Jordan Lee, `jordan.lee@example.com`, is an existing CRM contact, so the
  search finds a record.
- A text to any valid E.164 number, including the mobile on file, is `queued`;
  nothing is delivered.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 10: Collections and Payment Recovery**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system.

## Try these turns

- "Yes, this is Jordan Lee. The last four are 4821. I can do three monthly
  payments by debit card starting November 1." Expect the disclosure, no card
  details requested, and the arrangement read back with "Is that correct?".
- "Yes." Expect `mock_tool_call_salesforce_search` once, the arrangement noted
  with the billing team holding the contact record, and an offer to text a
  confirmation without the number read aloud.
- "Yes, text me." Expect `mock_tool_call_twilio_send_message` once and the
  text reported as sent. Say "No thanks" instead and no text tool runs.
- "I lost my job last month and can't pay right now." Expect the hardship
  options and a commitment read back as collected for manual follow-up by the
  billing team, never "approved", "set up", or "saved to the file".
- "No, this is his roommate." Expect no mention of the account or the debt.

## Boundaries

- The account holder, balance, lender, CRM record, and text message are
  fictional and come from the mock server; there is no payment system.
- `store` is `false`; enable persistence deliberately if you need it.
- To use real CRM and SMS systems, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
