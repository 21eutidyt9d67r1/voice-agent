# Language Practice Tutor with Handoff

## Conclusion

`agent.json` is a Voice Agent for a fictional language studio, Contoso Language
Studio, that runs conversation practice as a staged handoff graph. It is the
same conversation design that the Microsoft Foundry **Language practice tutor**
template creates.

By default its business tools run on the shared **mock-tool-call** MCP server:
mock Microsoft 365 calendar tools that find free times and book the next
30-minute Teams practice session. Results are fictional, and nothing real is
booked or sent. To connect real systems, use **Connect my tools** in the Portal Editor or a Foundry Toolbox in your own Project; see
[Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try level-based branching, recaps in the right language, and booking
the next session after a read-back, before you connect a real calendar.

## Workflow

| Stage | Purpose |
| --- | --- |
| `assess` | Welcome the student, ask which language, and gauge their level. |
| `beginner` | Practice simple phrases slowly with gentle corrections. |
| `advanced` | Hold a natural conversation in the target language with targeted feedback. |
| `summary` | Recap practiced items, new words, strengths, and one area to work on, then offer to book the next session. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `summary` | `mock_tool_call_find_meeting_times`, `mock_tool_call_get_user_date_and_time_zone_settings`, `mock_tool_call_create_event` |

The other stages have no tools. The agent offers only slots that
`mock_tool_call_find_meeting_times` returned, and `mock_tool_call_create_event`
runs once, only after the student says yes to the read-back.

## Sample data

Contoso Language Studio offers 30-minute practice sessions with Lena as
Microsoft Teams video calls. The next session can be booked at the end of a
practice call, and the invite with the Teams link goes to the student's email.

Fixed mock data (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)):

- The calendar owner is in Pacific Standard Time; meeting suggestions come back
  in UTC, and the agent converts them to the student's time zone. About one
  half-hour start in five is busy.
- A booked event returns a fake Teams join link; no invite is delivered.

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 21: Language Practice Tutor**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system. Microsoft 365 (Work IQ) tools stay on mock data in the shared
Playground because they act as the signed-in user.

## Try these turns

- "Let's practice Spanish, I'm a beginner." Expect simple phrases and an English
  recap.
- "I'm intermediate in French." Expect advanced practice and a recap in French.
- "Can you book my next session for Friday? I'm on Pacific time." Expect
  `mock_tool_call_find_meeting_times` and two or three returned slots.
- Pick a slot and give your email. Expect the date, time, time zone, and email
  read back with a question. After "yes", expect `mock_tool_call_create_event`
  once and the booked weekday, date, and time.
- "No, I'll book later." Expect no booking and a brief goodbye.

## Boundaries

- The studio, slots, and invites are fictional and come from the mock server;
  no session is really booked. There is no student record system.
- `store` is `false`; enable persistence deliberately if you need it.
- To use a real calendar, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
