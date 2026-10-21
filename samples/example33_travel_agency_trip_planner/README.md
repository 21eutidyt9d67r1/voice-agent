# Travel Agency Trip Planner with Handoff

## Conclusion

`agent.json` is a Voice Agent for a fictional agency, Contoso Travel, that plans
trips as a staged handoff graph. It is the same conversation design that the
Microsoft Foundry **Travel agency trip planner** template creates.

By default, its business tools run on the shared **mock-tool-call** MCP server:
Salesforce tools to look up the traveler and create a lead for the trip
request. The mocks take the same arguments and return the same fields as the
real tools, but results are fictional and nothing real is saved, booked, or
sent. The agent never books a trip, takes payment, or emails an itinerary. To
connect real systems, use **Connect my tools** in the Portal Editor or a Foundry
Toolbox in your own Project; see
[Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try destination discovery, package recommendations from sample facts,
and a confirmed trip request saved to a CRM.

## Workflow

| Stage | Purpose |
| --- | --- |
| `discover` | Greet the traveler and ask about their plans. |
| `destination_details` | Build a trip around a destination the traveler already has in mind. |
| `recommend_destinations` | Recommend sample packages for an undecided traveler. |
| `build_itinerary` | Give ballpark pricing and policies, read back the trip request, and save it after a yes. |
| `booking_wrap` | Confirm the next step from what happened on the call; nothing is booked. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `build_itinerary` | `mock_tool_call_salesforce_search`, `mock_tool_call_salesforce_get_contact`, `mock_tool_call_salesforce_create_lead` |

The other stages have no tools. The search and lead run only after the traveler
says yes to the read-back, and the lead is created at most once.

## Sample data

Packages per person, excluding international flights: 7-day Tuscany tour $2,800;
6-day Amalfi Coast escape $3,100; 8-day Bali wellness retreat $2,100; 10-day
Japan highlights $4,200; 5-day Costa Rica adventure $1,900. Groups of 8 or more
get 10 percent off. Full refund 60 or more days before departure, 50 percent 30
to 59 days, none within 30 days.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):
existing CRM contacts include Jordan Lee, `jordan.lee@example.com`. Any other
email, such as `dana.test20261020@example.com`, is a new prospect, so a Lead is
created with an ID starting `00QMOCK`.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 33: Travel Agency Trip Planner**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system.

## Try these turns

- "Japan in April for two, budget about 10,000 dollars." Expect $4,200 per
  person and flights excluded.
- "Send me a proposal. Dana Test, dana.test20261020@example.com." Expect the
  trip request read back and a question whether to pass it to a travel agent,
  with no tool call yet.
- "Yes." Expect a Salesforce search that finds nothing, one
  `mock_tool_call_salesforce_create_lead` call, and a travel agent following up
  with a proposal. With `jordan.lee@example.com`, the contact is found, no lead
  is created, and the request is noted.
- "Somewhere relaxing, I'm not sure where." Expect a recommendation such as
  Bali.
- "We're a group of 10; what if we cancel 45 days out?" Expect the group
  discount and a 50 percent refund.

## Boundaries

- The agency, packages, prices, and CRM data are fictional and come from the
  mock server; no lead or booking is real.
- `store` is `false`; enable persistence deliberately if you need it.
- To use a real CRM or booking system, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
