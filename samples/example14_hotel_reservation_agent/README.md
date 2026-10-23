# Hotel Reservations with Handoff

## Conclusion

`agent.json` is a Voice Agent for a fictional hotel, the Grand Hotel, that books,
changes, and cancels stays and answers guest questions as a staged handoff
graph. It is the same conversation design that the Microsoft Foundry **Hotel
reservations** template creates.

By default, its business tools run on the shared **mock-tool-call** MCP server:
reservation tools that check availability and create, look up, and cancel
reservations. The mocks mirror the template's custom reservation tools, but
results are fictional and nothing real is booked, cancelled, or charged. To
connect real systems, use **Connect my tools** in the Portal Editor or a Foundry
Toolbox in your own Project; see
[Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try request routing, availability-based quotes, policy answers, and
read-backs that must get a yes before a reservation is created, changed, or
cancelled.

## Workflow

| Stage | Purpose |
| --- | --- |
| `welcome` | Find out whether the caller wants a new stay, a change or cancellation, or hotel information. |
| `new_booking` | Check availability, quote available rooms with the total before taxes, read the reservation back, and book it after a yes. |
| `manage_existing` | Look up the reservation by confirmation number and last name, then change or cancel it after a read-back and a yes. |
| `general_inquiry` | Answer amenity, dining, parking, check-in, and pet questions from the sample facts. |
| `wrap_up` | Recap only what a tool reported, such as the confirmation number, or the question answered. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `new_booking` | `mock_tool_call_hotel_check_availability`, `mock_tool_call_hotel_create_reservation` |
| `manage_existing` | `mock_tool_call_hotel_get_reservation`, `mock_tool_call_hotel_check_availability`, `mock_tool_call_hotel_create_reservation`, `mock_tool_call_hotel_cancel_reservation` |

The other stages have no tools. Each write runs once, only after the caller
says yes to the read-back. A change creates the new reservation first and
cancels the old one only when that succeeds. No card details are taken.

## Sample data

The Grand Hotel, 100 Example Avenue, Seattle. Check-in from 3 PM, check-out by
11 AM. Classic King $229, Deluxe Double Queen $259, Junior Suite $349 a night
before taxes. Free cancellation until 48 hours before 3 PM on arrival day;
later, one night. Valet parking only, $45 a night; dogs up to 25 kg, $75 a
stay.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):

- The Junior Suite is sold out on Saturday nights; the other rooms are always
  available.
- Existing reservation **A1B2C3**, last name **Test** (Dana Test): Classic King,
  2 nights, arriving 14 days after the first lookup, so cancelling it is free.
- New reservations get a random confirmation number such as `M3K9QZ`. The mock
  keeps nothing callers say, so only `A1B2C3` can be looked up or cancelled.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 14: Hotel Reservations**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system.

## Try these turns

- "I'd like a room for two nights from Friday, two adults, it's our
  anniversary." Expect `mock_tool_call_hotel_check_availability` and only the
  available rooms quoted; the Junior Suite is not offered because Saturday is
  sold out.
- Pick the Classic King and give a name and email. Expect the whole reservation
  read back with the total before taxes and a question whether to book it.
  After "Yes", expect `mock_tool_call_hotel_create_reservation` once and the
  confirmation number read back character by character.
- "Cancel my reservation, confirmation A1B2C3, last name Test." Expect
  `mock_tool_call_hotel_get_reservation`, the stay and the 48-hour policy read
  back, and after "Yes" `mock_tool_call_hotel_cancel_reservation` with no fee.
- "Confirmation ZZZ999, last name Test." Expect that no reservation matches and
  a request to check the details, with no guess.
- "Can I bring my dog, and how does parking work?" Expect the pet fee and
  valet-only parking.

## Boundaries

- The hotel, rates, policies, and reservations are fictional and come from the
  mock server; no stay is real. There is no guest record, payment, or mail
  system.
- `store` is `false`; enable persistence deliberately if you need it.
- To use a real reservation system, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
