# Assessment and Quiz with Handoff

## Conclusion

`agent.json` is a Voice Agent that proctors a spoken 10-question security
awareness quiz as a staged handoff graph. It is the same conversation design
that the Microsoft Foundry **Assessment and quiz** template creates.

By default, its one business tool runs on the shared **mock-tool-call** MCP
server: a learning-record tool that saves the final score when the student
agrees. The mock returns a record ID and whether the score passed, but results
are fictional and nothing is saved to a real learning system. To connect real
systems, use **Connect my tools** in the Portal Editor or a Foundry Toolbox in your
own Project; see [Connect real tools](../../docs/05_connect_real_tools.md).

## When to use this example

Use it to try strict turn-by-turn questioning, neutral acknowledgements, a
branch on the final score, and a consented write of the result.

## Workflow

| Stage | Purpose |
| --- | --- |
| `intro` | Set expectations: the topic, 10 questions, about 15 minutes, one point each, and 7 of 10 to pass. |
| `questions` | Ask the questions in order, exactly one per turn, with neutral acknowledgements and no hints. |
| `pass_node` | Confirm the pass, review any missed question, give the exact score, suggest next topics, and offer to save the score. |
| `fail_node` | Review each missed question, give the score constructively, suggest what to study, and offer to save the score. |
| `end` | Say a short goodbye and call `end_conversation`. |

Every stage can route to `end` as soon as the caller says goodbye or asks to
stop. Handoffs are silent: no edge carries a `transfer_message`.

Each stage repeats the persona, tone, conversation rules, and the sample facts
because a handoff node's instructions replace the session instructions. Without
the facts in every stage, the agent would invent details.

### Mock tools by stage

| Stage | Tools |
| --- | --- |
| `pass_node` | `mock_tool_call_quiz_record_result` |
| `fail_node` | `mock_tool_call_quiz_record_result` |

The other stages have no tools. `mock_tool_call_quiz_record_result` runs at most
once, only after the student says yes to saving, with the quiz name, score,
total 10, passing score 7, and the missed question numbers.

## Sample data

Security awareness basics: 10 questions on passwords, phishing, data handling,
physical security, devices, and software updates; one point each, no penalty for
guessing, and 7 of 10 to pass. Answers with the same meaning are accepted.

The mock learning record has no fixed data; each save returns a new
`record_id` and `passed` (see the
[mock-tool-call README](../../shared_mcp/app/shared_mcp/mock_tool_call/README.md)).

## Run in the portal

1. Start the portal as described in [portal/README.md](../../portal/README.md).
2. In **Editor**, choose **Load from templates**.
3. Select **Example 9: Assessment and Quiz**.
4. Choose **Try it now**, then connect in AgentRuntime.

The Template's tools run on the shared no-auth mock MCP service; there is
nothing to start locally. After loading, a banner says the Agent uses mock
tools; choose **Connect my tools** to connect your own public HTTPS MCP server
for each system.

## Try these turns

- "I'm ready." Then answer "No, one breach exposes both" to the first question.
  Expect one question per turn and no hints.
- Answer "I don't know" to four or more questions. Expect the needs-work debrief
  with each missed answer explained, then a question whether to save the score.
- "Yes, save it, my name is Dana Test." Expect `mock_tool_call_quiz_record_result`
  once and the score reported as saved only if the result has `ok` true.
- On another run, answer the save question with "No thanks." Expect no tool
  call and no claim that the score was saved.
- After the score, "Question 5 should count." Expect the reasoning, with the
  score unchanged.

## Boundaries

- The quiz content and the learning record are fictional; saved scores live
  only on the mock server.
- `store` is `false`; enable persistence deliberately if you need it.
- To use a real learning system, follow
  [Connect real tools](../../docs/05_connect_real_tools.md); conversational
  confirmation is not an authorization boundary.
