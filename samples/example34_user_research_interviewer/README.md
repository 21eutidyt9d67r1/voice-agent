# User Research Interviewer with Handoff

## Conclusion

`agent.json` is a Voice Agent that runs a short user research interview as a
staged handoff graph. It is the same conversation design that the Microsoft
Foundry **User research interviewer** template creates.

By default, its one business tool runs on the shared **mock-tool-call** MCP
server: `mock_tool_call_research_save_interview_notes`, which saves a written
recap for the product team, and only when the participant agreed to a recap at
the start. Results are fictional and nothing real is stored; the call is not
recorded. To connect a real research repository, use the Portal's **My MCP
server** option or a Foundry Toolbox in your own Project; see
[Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try neutral probing, time-based branching, and consent-gated note
saving.

## Workflow

| Stage | Purpose |
| --- | --- |
| `consent_intro` | Thank the participant, explain the study, and ask consent for a written recap. |
| `discovery` | Ask the open discovery question and probe neutrally. |
| `depth_branch` | Reflect one point and ask how much time they have left. |
| `deep_dive` | Explore tools, workarounds, and ratings with an engaged participant. |
| `priority_questions` | Ask only the three priority questions when time is short. |
| `polite_close` | Thank a participant who is ready to stop. |
| `submit_notes` | Recap the interview for the participant to correct, then save notes only after a fresh yes to saving that recap. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `submit_notes` | `mock_tool_call_research_save_interview_notes` |

The other stages have no tools. The notes are saved once, with
`consent_given` true, only when the participant agreed to a written recap at
the start, has not withdrawn consent, and explicitly agreed in a later turn to
saving the closing recap. A goodbye or no-contact request ends the call
without a notes write. The two 1 to 5 ratings are sent
when collected, and 0 otherwise.

## Sample data

Study: how small teams plan and track weekly work, 20 to 30 minutes. Discovery
question: "Walk me through how your team plans its work for the week." Three
priority questions cover tracking who does what, the last thing that slipped,
and one thing to change. The call is not recorded and there is no prototype.

The mock saves a recap only when `consent_given` is true; see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md).

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 34: User Research Interviewer**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system.

## Try these turns

- "Sure, I'm happy to help, and a written recap is fine." Then "I have 15
  minutes." Expect the deep dive and ratings with reasons.
- At the close, expect a brief recap and a question whether it is accurate and
  may be saved for the product team. Say "Yes, that's right, save it." Expect
  one `mock_tool_call_research_save_interview_notes` call and the notes
  reported as saved. Say "Don't save it" instead and no tool runs.
- "I only have a few minutes." Expect only the three priority questions, then
  the recap.
- Decline the written recap at the start. Expect the interview as usual, no
  recap request at the close, no tool call, and no claim that notes were saved.
- "I'd rather stop here." Expect a thank-you without another interview
  question, then the optional recap.
- "Goodbye, please don't contact me again." Expect the call to end without a
  notes write.

## Boundaries

- The study and saved notes are fictional and come from the mock server; no
  research repository stores them.
- `store` is `false`; enable persistence deliberately if you need it.
- To use a real research repository, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
