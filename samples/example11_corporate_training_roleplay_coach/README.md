# Corporate Training Role-Play Coach with Handoff

## Conclusion

`agent.json` is a Voice Agent that role-plays a tough workplace conversation and
then coaches the trainee, as a staged handoff graph. It is the same conversation
design that the Microsoft Foundry **Corporate training role-play coach**
template creates.

By default, its one business tool runs on the shared **mock-tool-call** MCP
server: a training-record tool that saves the debrief scores and takeaway when
the trainee agrees. Results are fictional and nothing is saved to a real
learning system. To connect real systems, use **Connect my tools** in the Portal Editor or a Foundry Toolbox in your own Project; see
[Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try in-character role-play stages, a clean switch to an
out-of-character debrief, and a consented write of the debrief to a training
record.

## Workflow

| Stage | Purpose |
| --- | --- |
| `select` | Welcome the trainee, describe the scenarios, and wait until they are ready. |
| `customer` | Play the angry customer or the difficult employee in character. |
| `sales` | Play the sales prospect or the negotiation counterpart in character. |
| `debrief` | Step out of character, score Communication, Objection Handling, Empathy, and Resolution from 1 to 5 with one takeaway, and offer to save them. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `debrief` | `mock_tool_call_training_record_session` |

The other stages have no tools. `mock_tool_call_training_record_session` runs
at most once, only after the trainee says yes to saving, with the scenario
name, the four scores, the key takeaway, and their name if given.

## Sample data

Four fictional scenarios: Pat, a Contoso Home Internet customer whose repair
visit was missed twice; Riley, a capable employee who missed three deadlines;
Sam, a Fabrikam finance director evaluating a 40,000 dollar a year analytics
subscription; and Alex, a supplier account manager asking for a 12 percent price
increase.

The mock training record has no fixed data; it records the role-play debrief
with four 1-5 scores (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)).

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 11: Corporate Training Role-Play Coach**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system.

## Try these turns

- "Let's do the angry customer." "Ready." Expect the coach to set the scene and
  play Pat in character.
- "Let's stop, give me feedback." Expect scores from 1 to 5 with reasons, quotes
  of your lines, one takeaway, and a question whether to save them.
- "Yes, save it. I'm Dana Test." Expect
  `mock_tool_call_training_record_session` once and the debrief reported as
  saved only if the result has `ok` true. Say "No" instead and no tool runs.
- "Sales objection handling." Expect Sam to push back on price and ROI until you
  give evidence.

## Boundaries

- All scenarios, people, and companies are fictional; saved debriefs live only
  on the mock server.
- `store` is `false`; enable persistence deliberately if you need it.
- To use a real learning system, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
