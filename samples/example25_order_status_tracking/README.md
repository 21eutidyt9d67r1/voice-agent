# Order Status and Tracking with Handoff

## Conclusion

`agent.json` is a Voice Agent for a fictional online store, Contoso Shop, that
handles order status, returns, and warranty claims as a staged handoff graph.
It is the same conversation design that the Microsoft Foundry **Order status
and tracking** template creates.

By default its business tools run on the shared **mock-tool-call** MCP server:
a mock order lookup, a mock Zendesk comment that logs a return on the caller's
support ticket, and a mock Twilio text with the return details. Results are
fictional, and nothing real is logged, shipped, or sent. To connect real
systems, use **Connect my tools** in the Portal Editor or a Foundry Toolbox in your
own Project; see [Connect real tools](../../docs/05_connect_real_tools.md).

Warranty claims are noted for the warranty team only; no tool files them.

## When to use this example

Use it to try order lookups, return and warranty routing, and a ticket comment
and a text that wait for a yes, before you connect real order, ticketing, or
SMS tools.

## Workflow

| Stage | Purpose |
| --- | --- |
| `greeting` | Capture the order number or account name and what the caller needs. |
| `assess` | Look the order up and give its status, items, carrier, tracking number, and delivery window, or route to a return or warranty claim. |
| `process_return` | Explain the return policy, log the return on the caller's ticket after a yes, and offer to text the details. |
| `process_warranty` | Capture the order, item, defect, photos, and a follow-up contact; the claim is noted only. |
| `confirm` | Confirm the status given, the return logged or noted, the text outcome, or the warranty claim noted. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `assess` | `mock_tool_call_order_lookup` |
| `process_return` | `mock_tool_call_zendesk_add_comment`, `mock_tool_call_twilio_send_message` |

The other stages have no tools. `mock_tool_call_zendesk_add_comment` runs once,
only after the caller says yes to the read-back, and
`mock_tool_call_twilio_send_message` runs once, only after the caller confirms
the number. Without a ticket number, the return is noted for the returns team.

## Sample data

Contoso Shop ships within one business day; standard shipping takes 3 to 5
business days, express 1 to 2. Returns within 30 days of delivery, unused, in
original packaging; final-sale items cannot be returned. The returns team emails
a prepaid label within one business day after a return is logged on the
caller's ticket. Refunds within 5 to 7 business days after the return arrives.
One-year limited warranty; claims reviewed in 3 to 5 business days.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):

| Order | Customer | Status | Items |
| --- | --- | --- | --- |
| 10045 | Dana Test | In transit, standard, Contoso Express `CX100450001` | Rain jacket, size M; wool socks, 3 pack (final sale) |
| 10046 | Jordan Lee | Processing, express, ordered today | Blender, 1.5 L |
| 10047 | Jack Rogers | Delivered 15 days ago | Desk lamp ×2 |

- Existing support tickets: 1, 2, and 3 (open). Use ticket 3 to log a return.
- A text to any valid E.164 number is queued; `+15005550001` fails with error
  code 21211.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 25: Order Status and Tracking**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system.

## Try these turns

- "Where is my order 10045?" Expect `mock_tool_call_order_lookup` and the
  result: in transit, standard shipping, Contoso Express `CX100450001`, and the
  estimated delivery window.
- "I want to return the rain jacket, wrong size. My ticket is 3." Expect the
  policy and a read-back. After "yes", expect
  `mock_tool_call_zendesk_add_comment` on ticket 3 and the promise that the
  returns team emails the prepaid label within one business day.
- "Yes, text me the details at +1 425 555 0123." Expect the number read back,
  then after confirmation `mock_tool_call_twilio_send_message` once and the
  text reported as sent (the mock queues it).
- "Can I return the wool socks too?" Expect that final-sale items cannot be
  returned.
- "My blender stopped working." When asked for the best email or phone for
  follow-up, give `jordan.lee@example.com`. Expect it read back and a warranty
  claim noted for review, never "filed" or "approved".

## Boundaries

- The store, policies, orders, and tickets are fictional and come from the mock
  server; no return label, refund, or text is real.
- `store` is `false`; enable persistence deliberately if you need it.
- To use real order, ticketing, or SMS systems, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
