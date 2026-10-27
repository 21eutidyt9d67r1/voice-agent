# `mock-tool-call` pack

Mock business tools for the Voice Agent Template catalog. Each Template card can run
on these tools (the default in the Playground) or on a real MCP server. The mocks
take the same arguments as the real tools and return the same fields, plus
`mock: true` and `tool`, so a Template's stage instructions work unchanged on either.
Nothing real is booked, sent, or charged.

Route: `/mcp/mock-tool-call` on the public no-auth MCP service that the default Portal
Templates use (see [`portal/templates.config.json`](../../../../portal/templates.config.json)).
Every tool name starts with `mock_tool_call_`.

## Result shape

Business tools return the real tool's fields with `ok` and `error`:

```json
{"mock": true, "tool": "mock_tool_call_zendesk_create_ticket", "ok": true,
 "source": "zendesk", "ticket_id": 1001, "status": "new", "priority": "high", "error": null}
```

A business failure (unknown ticket, invalid phone, sold-out room) is a normal result
with `ok: false` and `error: {"code", "message"}`; the MCP result is not `isError`.
Invalid arguments (missing required field, wrong enum, text too long) are rejected by
schema validation as MCP errors.

`mock_tool_call_echo` is the protocol self-test. It follows the shared MCP contract:
`request_id` (1-128 characters, not blank), `text` (up to 4096), `mode` (`success` or
`business_error`), and returns `{mock, tool, request_id, status, data, error}` with
`status` `succeeded` or `failed`. It is stateless and deterministic.

## Tools

| Mock tool | Mirrors | Notes |
| --- | --- | --- |
| `mock_tool_call_find_meeting_times` | Work IQ `FindMeetingTimes` | Suggestions in UTC with `end` listed before `start`, like the real tool. Same arguments (`meetingDuration`, `startDateTime`, `endDateTime`, `timeZone`, `attendeeEmails`, `maxCandidates`, `returnSuggestionReasons`). |
| `mock_tool_call_get_user_date_and_time_zone_settings` | Work IQ `GetUserDateAndTimeZoneSettings` | Today's date and time in Pacific Standard Time. |
| `mock_tool_call_create_event` | Work IQ `CreateEvent` | Returns `id`, times, attendees, and a fake Teams `joinUrl` for online meetings. |
| `mock_tool_call_list_calendar_view` | Work IQ `ListCalendarView` | Events overlapping the range whose subject contains `subject`. |
| `mock_tool_call_update_event` | Work IQ `UpdateEvent` | Moves or renames an event. |
| `mock_tool_call_cancel_event` | Work IQ `CancelEvent` | Returns `cancelled`; nothing is stored, so the event still lists for the next caller. |
| `mock_tool_call_get_user_presence` | Work IQ Teams `GetUserPresence` | Argument `userEmail`. |
| `mock_tool_call_send_email_with_attachments` | Work IQ Mail `SendEmailWithAttachments` | Reports `sent`; no email leaves the service. |
| `mock_tool_call_salesforce_search` | `salesforce_search` | Contacts by exact email or partial name. |
| `mock_tool_call_salesforce_get_contact` | `salesforce_get_contact` | By Contact Id or email; `found`. |
| `mock_tool_call_salesforce_create_lead` | `salesforce_create_lead` | Returns `lead_id` `00QMOCK…`. |
| `mock_tool_call_zendesk_search` | `zendesk_search` | `type=articles` (default) searches the articles below; `type=tickets` searches tickets, a number reads one ticket. |
| `mock_tool_call_zendesk_add_comment` | `zendesk_add_comment` | Tickets 1 to 3, or a four-digit number from `zendesk_create_ticket`; reports the ticket reopened. |
| `mock_tool_call_zendesk_create_ticket` | `zendesk_create_ticket` | Returns a random four-digit ticket number; the ticket is not stored. |
| `mock_tool_call_twilio_send_message` | `twilio_send_message` | Any valid E.164 number is `queued`; no text is delivered. |
| `mock_tool_call_order_lookup` | Order lookup (custom tool) | By order number or account email. |
| `mock_tool_call_hotel_check_availability` | Hotel reservation tools (custom) | Rooms, availability, and total before taxes. |
| `mock_tool_call_hotel_create_reservation` | | Returns a random confirmation number such as `M3K9QZ`; the reservation is not stored. |
| `mock_tool_call_hotel_get_reservation` | | By confirmation number and last name. |
| `mock_tool_call_hotel_cancel_reservation` | | Reports a one-night `cancellation_fee` inside 48 hours of the 3 PM arrival. |
| `mock_tool_call_quiz_record_result` | | Records a quiz score; returns `record_id` and `passed`. |
| `mock_tool_call_training_record_session` | | Records a role-play debrief with four 1-5 scores. |
| `mock_tool_call_research_save_interview_notes` | | Saves a recap only when `consent_given` is true. |
| `mock_tool_call_echo` | | Protocol self-test. |

## Fixed test data

All values are in [`fixtures.json`](fixtures.json) and match the Template try-it
guide. The service is stateless: write tools validate their arguments and return
a generated ID, but nothing a caller says is stored or shown to another caller.
Reads return only these fixtures, so a booked slot stays free and a new ticket
or reservation cannot be looked up later.

### CRM contacts

| Name | Email | Phone | Title | Account |
| --- | --- | --- | --- | --- |
| Jack Rogers | `jrogers@burlington.com` | +13362227000 | VP, Facilities | Burlington Textiles Corp of America |
| Jordan Lee | `jordan.lee@example.com` | +14255550123 | Customer | Individual |
| Rose Gonzalez | `rose@edge.com` | +15124575000 | SVP, Procurement | Edge Communications |
| Tim Barr | `barr_tim@grandhotels.com` | +13125963300 | SVP, Administration and Finance | Grand Hotels and Resorts Ltd |

Any other email, such as `dana.test20261020@example.com`, is a new prospect: search
finds nothing and a Lead can be created.

### Help desk

Existing tickets: **1** (solved, sign-in after password change), **2** (pending,
invoice address), **3** (open, API returns 401; Jack Rogers). Use ticket **3** to add
a comment. Articles match keywords such as: password, MFA, locked out; VPN,
GlobalProtect, authentication failed; sync failure; API 401 or token; install
software, Company Portal; monitor flicker; expense report; PTO or time off; Wi-Fi.

### Calendar

The calendar owner's time zone is Pacific Standard Time. Two events exist from the
first calendar call, on the next Thursday and Friday after that day (Pacific):

| Event | When | Use |
| --- | --- | --- |
| Follow-up visit with Dana Test | Thursday 10:00-10:30 AM | Reschedule or cancel by the name "Dana Test" |
| Initial consultation with Jordan Lee | Friday 2:00-3:00 PM | Reschedule or cancel by the name "Jordan Lee" |

Free slots are fixed for a given day and duration: about one half-hour start in five
is busy, and booked events block their time. Every time zone listed in `service.py`
(Windows names such as China Standard Time) or any IANA name works.

### Directory presence

| Person | Email | Presence |
| --- | --- | --- |
| Alex Wilber | `alexw@contoso.com` | Available |
| Megan Bowen | `meganb@contoso.com` | Busy, in a meeting |
| Adele Vance | `adelev@contoso.com` | Away |
| Isaiah Langer | `isaiahl@contoso.com` | Offline |

### Text messages

Every valid E.164 number succeeds, including the sample directory numbers. To see the
failure path, text **+15005550001**: the result is `ok: false` with error code `21211`.
A number without a country code also fails.

### Orders (Contoso Shop)

| Order | Customer | Status | Items |
| --- | --- | --- | --- |
| 10045 | Dana Test | In transit, standard shipping, Contoso Express `CX100450001`, ordered 6 days ago, shipped 5 days ago | Rain jacket, size M; wool socks, 3 pack (final sale) |
| 10046 | Jordan Lee | Processing, express, ordered today | Blender, 1.5 L |
| 10047 | Jack Rogers | Delivered 15 days ago | Desk lamp ×2 |

Dates are relative to the day of the call; the estimated delivery window is 3-5
business days after shipping for standard and 1-2 for express.

### Hotel (The Grand Hotel)

| Room | Sleeps | Nightly rate | Availability |
| --- | --- | --- | --- |
| Classic King | 2 | $229 | Always |
| Deluxe Double Queen | 4 | $259 | Always |
| Junior Suite | 3 | $349 | Sold out on Saturday nights |

Existing reservation: **A1B2C3**, last name **Test** (Dana Test), Classic King, 2
nights, arriving 14 days after the first lookup. Cancelling it is free; a reservation
whose arrival is within 48 hours reports a one-night fee.
