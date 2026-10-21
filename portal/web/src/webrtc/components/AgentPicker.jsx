// Copyright (c) Microsoft. All rights reserved.
// Setup phase: pick one agent from the shared catalog and start a WebRTC session.
// Intentionally minimal — no agent authoring here (that stays in the integrated demo);
// this standalone experience is about running + reviewing a single voice session.

import { useState } from "react";

export function AgentPicker({ agents, state, onLoadMore, onResolveAgent, onStart }) {
  const [selectedName, setSelectedName] = useState("");
  const [startState, setStartState] = useState({ resolving: false, error: "" });
  const initialFailure = Boolean(state.error) && agents.length === 0;
  const optionsId = "wrtc-agent-options";

  const startSelected = async () => {
    if (!selectedName.trim() || startState.resolving) return;
    setStartState({ resolving: true, error: "" });
    try {
      onStart(await onResolveAgent(selectedName));
    } catch (error) {
      setStartState({
        resolving: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  };

  return (
    <section className="wrtc-setup">
      <h1>Start a voice session</h1>
      <p className="wrtc-sub">Pick an agent, then talk to it over WebRTC. When you end the
        session, the persisted conversation is shown right here.</p>

      {state.loading ? <div className="wrtc-loading">Loading agents…</div> : null}
      {state.error ? <div className="wrtc-error">Could not list agents: {state.error}</div> : null}

      {!state.loading && !initialFailure ? (
        <>
          <div className="wrtc-picker">
            <label className="wrtc-field">
              <span>Agent</span>
              <input type="search" value={selectedName} list={optionsId}
                placeholder="Select or enter an exact agent name…"
                autoComplete="off" disabled={startState.resolving}
                onChange={(event) => {
                  setSelectedName(event.target.value);
                  setStartState((current) => ({ ...current, error: "" }));
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    startSelected();
                  } else if (event.key === "Escape") {
                    setSelectedName("");
                    setStartState({ resolving: false, error: "" });
                  }
                }} />
              <datalist id={optionsId}>
                {agents.map((a) => (
                  <option key={a.name} value={a.name} label={a.model || "Voice Agent"} />
                ))}
              </datalist>
            </label>
            <button className="wrtc-start" disabled={!selectedName.trim() || startState.resolving}
              onClick={startSelected}>
              {startState.resolving ? "Finding agent…" : "Start WebRTC session"}
            </button>
          </div>
          {startState.error ? (
            <div className="wrtc-error" role="alert">Could not select agent: {startState.error}</div>
          ) : null}
          {state.hasMore || state.loadingMore ? (
            <div className="wrtc-pagination">
              <span aria-live="polite">{agents.length} voice agents loaded</span>
              <button type="button" disabled={state.loadingMore} onClick={onLoadMore}>
                {state.loadingMore ? "Loading more…" : "Load more agents"}
              </button>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
