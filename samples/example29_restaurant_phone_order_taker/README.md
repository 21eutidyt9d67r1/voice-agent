# Restaurant Phone Order Taker with Handoff

## Conclusion

`agent.json` is a Voice Agent for a fictional restaurant, Contoso Kitchen, that
prepares unsubmitted phone order summaries as a staged handoff graph. It is the same conversation
design that the Microsoft Foundry **Restaurant phone order taker** template
creates.

By default, its one business tool runs on the shared **mock-tool-call** MCP
server: a Twilio SMS tool that texts the order summary when the caller asks
for it. The mock takes the same arguments and returns the same fields as the
real tool, but results are fictional and no text is delivered. The call cannot
place an order: the agent says the summary is unsubmitted and has not been sent
to or accepted by the kitchen, and no payment is taken. To connect real systems, use **Connect my tools** in the Portal Editor or a
Foundry Toolbox in your own Project; see
[Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try menu-grounded ordering, arithmetic on totals, zone checks, and a
confirmed SMS summary with a failure path.

## Workflow

| Stage | Purpose |
| --- | --- |
| `greeting` | Explain that the call prepares an unsubmitted order summary, then find out whether it is for pickup or delivery. |
| `pickup` | Take the pickup order item by item, asking about allergies. |
| `delivery` | Check the delivery ZIP, minimum, and fee, then take the order. |
| `review` | Read back each item and the total as an unsubmitted summary, then offer to text it. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `review` | `mock_tool_call_twilio_send_message` |

The other stages have no tools. The text is sent at most once, only after the
caller says yes to the separate "May I text this unsubmitted order summary to
that number?" question. The text begins "Unsubmitted order summary; not sent to
the kitchen." and gives no ready-by time.

## Sample data

Contoso Kitchen, 200 Contoso Avenue, Redmond, daily 11 AM to 10 PM. Menu
includes pepperoni pizza (12 inch $15, 16 inch $19), Pad Thai $13.95, spring
rolls $6.50, and fresh lemonade $3.50. Delivery covers ZIP codes 98052, 98053,
and 98033 with a $15 minimum and a $4.99 fee. Payment at pickup or on delivery
only.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):
any valid E.164 number, such as +14255550123, is queued. Texting
**+15005550001** fails with error code `21211`, and a number without a country
code also fails.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 29: Restaurant Phone Order Taker**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system.

## Try these turns

- "Pickup. One 16-inch pepperoni and a fresh lemonade." Expect an allergy
  question and a total of $22.50, read back as an unsubmitted order summary
  that has not been sent to the kitchen.
- Confirm the summary, ask for a text, give your name and "+1 425 555 0123",
  then say "yes" to the text question. Expect one
  `mock_tool_call_twilio_send_message` call and the text reported as sent, with
  a reminder that sending it does not place the order.
- Repeat with "+1 500 555 0001". Expect the text reported as not sent with the
  reason from the error, then an offer to read the summary back.
- "Delivery to 1 Main Street, 98052. Pad Thai, medium, and spring rolls." Expect
  $20.45 plus the $4.99 fee.
- "Delivery to ZIP 98101." Expect outside the zone and a pickup offer.

## Boundaries

- The restaurant, menu, and SMS results are fictional and come from the mock
  server; no order is submitted or accepted and no text is delivered.
- `store` is `false`; enable persistence deliberately if you need it.
- To use a real SMS or ordering system, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
