# Insurance Advisor with Handoff

## Conclusion

`agent.json` is a Voice Agent for a fictional insurer, Pinnacle Insurance Group,
that explores coverage and starts an application as a staged handoff graph. It
is the same conversation design that the Microsoft Foundry **Insurance
advisor** template creates.

By default its business tools run on the shared `mock-tool-call` MCP server: a
mock Salesforce contact lookup and a mock Microsoft 365 calendar that books the
application review call. Results are fictional, and nothing real is saved,
booked, or sent. To connect real systems, use **Connect my tools** in the Portal Editor or a Foundry Toolbox in your own Project; see
[Connect real tools](../../docs/05_connect_real_tools.md).

The agent never takes a payment and never quotes a premium; only a licensed
agent gives a binding quote.

## When to use this example

Use it to try needs assessment, range-only pricing, a CRM check, and booking a
review call after a read-back, before you connect real CRM and calendar tools.

## Workflow

| Stage | Purpose |
| --- | --- |
| `greeting` | Welcome the caller and find out whether they want coverage or have a claim. |
| `needs_assessment` | Understand the coverage type, what prompted it, and current coverage, one question at a time. |
| `claims_redirect` | Capture the claim basics and give the claims line and hours. |
| `present_options` | Walk through one to three options with typical ranges and honest trade-offs. |
| `wrap_up` | Read back what was captured, and the booked review call or the licensed agent's follow-up. |
| `collect_details` | Capture application details, check the CRM by email, and book a 30-minute Teams review call after a yes. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `collect_details` | `mock_tool_call_salesforce_search`, `mock_tool_call_salesforce_get_contact`, `mock_tool_call_create_event` |

The other stages have no tools. `mock_tool_call_create_event` runs once, only
after the caller says yes to the read-back. No payment tool is connected.

## Sample data

Pinnacle Insurance Group offers homeowners, auto, life, and umbrella insurance.
Typical monthly ranges, never a quote: auto liability $60 to $100; auto full
coverage $120 to $220; homeowners $100 to $200. A licensed agent follows up
within two business days with a binding quote. Application review calls are
30-minute Microsoft Teams calls. Claims line 1 800 555 0142, Monday to Friday,
8 AM to 8 PM Eastern.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):

- Existing CRM contact: Jack Rogers, `jrogers@burlington.com`. Any other email,
  such as `dana.test20261020@example.com`, is a new client.
- The calendar books any requested time and returns an event with a fake Teams
  join link; no invite is delivered.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 17: Insurance Advisor**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system. Microsoft 365 (Work IQ) tools stay on mock data in the shared
Playground because they act as the signed-in user.

## Try these turns

- "I just bought a new car and need auto insurance." Expect ranges only, never a
  premium, and questions one at a time.
- Start an application as Jack Rogers with `jrogers@burlington.com`. Expect
  `mock_tool_call_salesforce_search`, then
  `mock_tool_call_salesforce_get_contact`; the agent notes an existing client
  without reading the record aloud.
- Give a day and time for the review call. Expect a read-back of the summary,
  email, and time, and a question. After "yes", expect one
  `mock_tool_call_create_event` call and "booked, invite sent" only on success.
  If you decline instead, nothing is booked and a licensed agent follows up
  within two business days.
- "I need to file a claim on policy 12345." Expect the claims line and hours.
- "Can I pay by card now?" Expect no payment by phone.

## Boundaries

- The insurer, prices, phone numbers, and mock results are fictional; the mock
  server books and sends nothing real.
- `store` is `false`; enable persistence deliberately if you need it.
- To connect real CRM and calendar systems, follow
  [Connect real tools](../../docs/05_connect_real_tools.md).
- The read-back and "yes" are conversational confirmation, not an authorization
  boundary.
