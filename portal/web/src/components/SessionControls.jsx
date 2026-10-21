// Copyright (c) Microsoft. All rights reserved.
// Settings here are per-session overrides, never edits to the stored definition.

import { useEffect, useRef, useState } from "react";
import { voiceGroups } from "../config.js";
import { withSelectedAgent, withSessionTransport } from "../lib/agentUrl.mjs";
import { Field, GroupedSelect, Icon } from "./ConfigControls.jsx";
import { SessionAgentPicker } from "./SessionAgentPicker.jsx";

export function SessionControls({
  cfg, session, agent, agents, agentListState, onSelectAgent, onRefreshAgents,
  onLoadMoreAgents, onEditAgent, transport, transportError, transportNotice, onTransportChange,
}) {
  const [voiceOverride, setVoiceOverride] = useState("");
  const [storeOverride, setStoreOverride] = useState("");
  const [structuredInput, setStructuredInput] = useState("");
  const [referenceAudioMode, setReferenceAudioMode] = useState("assistant");
  const [copyUrlState, setCopyUrlState] = useState({ text: "", kind: "", url: "" });
  const [agentQuery, setAgentQuery] = useState(agent?.name || "");
  const [agentSearchState, setAgentSearchState] = useState({
    searching: false,
    error: "",
  });
  const settingsRef = useRef(null);
  const { isConnected, sessionReady, micMuted, status } = session;
  const agentListBusy = agentListState.loading || agentListState.loadingMore;
  const agentQueryMatchesSelection = agentQuery.trim() === (agent?.name || "");

  useEffect(() => {
    const closeOutside = (event) => {
      if (!settingsRef.current?.contains(event.target)) settingsRef.current?.removeAttribute("open");
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, []);

  useEffect(() => {
    // Do not carry an override from one model family (or edited version) into another.
    setVoiceOverride("");
    setStoreOverride(typeof agent?.sessionStoreDefault === "boolean" ? String(agent.sessionStoreDefault) : "");
    setStructuredInput("");
    setCopyUrlState({ text: "", kind: "", url: "" });
  }, [agent?.name, agent?.version, agent?.sessionStoreDefault]);

  useEffect(() => {
    setCopyUrlState({ text: "", kind: "", url: "" });
  }, [transport]);

  useEffect(() => {
    setAgentQuery(agent?.name || "");
    setAgentSearchState({ searching: false, error: "" });
  }, [agent?.name]);

  const searchAgent = async (requestedName = agentQuery) => {
    const name = requestedName.trim();
    if (!name || isConnected || agentListState.loading || agentSearchState.searching) return;
    setAgentQuery(name);
    setAgentSearchState({ searching: true, error: "" });
    try {
      const selectedName = await onSelectAgent(name);
      setAgentQuery(selectedName);
      setAgentSearchState({ searching: false, error: "" });
    } catch (error) {
      setAgentSearchState({
        searching: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  };

  const connect = () => session.connect(
    agent.name, voiceOverride, storeOverride, cfg.apiVersion, transport,
    Boolean(agent.clientReferenceEc), referenceAudioMode, structuredInput,
  );
  const copyAgentUrl = async () => {
    if (!agent?.name) return;
    const url = withSessionTransport(
      withSelectedAgent(window.location.href, agent.name), transport,
    );
    try {
      if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") {
        throw new Error("Clipboard API is unavailable in this browser context");
      }
      await navigator.clipboard.writeText(url);
      setCopyUrlState({ text: "Copied full URL", kind: "ok", url });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setCopyUrlState({ text: `Copy failed: ${message}`, kind: "err", url });
      session.logError(`Copy Agent URL failed: ${message}`);
    }
  };
  const modelSource = agent?.inferenceMode === "hosted_agent"
    ? "Hosted agent"
    : agent?.inferenceMode === "deployment" ? "BYOM" : "Managed";

  return (
    <section className="session-controls" aria-label="Playground connection">
      <div className="playground-heading">
        <div><span className="eyebrow">TRY IT LIVE</span><h2>Playground</h2></div>
        <span className={`connection-status ${status.kind || ""}`} role="status">
          <span className="status-dot" />{status.text === "not connected" ? "Not connected" : status.text}
        </span>
      </div>
      <div className="agent-picker-row">
        <Field label="Session agent">
          <SessionAgentPicker agents={agents} value={agentQuery} selectedName={agent?.name || ""}
            disabled={isConnected || agentListState.loading}
            loading={agentListState.loading} busy={agentSearchState.searching}
            onChange={(value) => {
              setAgentQuery(value);
              setAgentSearchState((current) => ({ ...current, error: "" }));
            }}
            onResolve={searchAgent}
            onReset={() => {
              setAgentQuery(agent?.name || "");
              setAgentSearchState({ searching: false, error: "" });
            }} />
        </Field>
        <button className="definition-button agent-search-button" type="button"
          title="Search for an exact Agent name" aria-label="Search agent"
          disabled={isConnected || agentListState.loading || agentSearchState.searching || !agentQuery.trim()}
          onClick={() => searchAgent()}>
          <Icon name="search" /><span>{agentSearchState.searching ? "Searching…" : "Search"}</span>
        </button>
        <button className="icon-button" type="button" title="Refresh agents" aria-label="Refresh agents"
          disabled={isConnected || agentListBusy} onClick={onRefreshAgents}>
          <Icon name="refresh" className={agentListBusy ? "spin" : ""} />
        </button>
        <button className="definition-button" type="button" title="Edit definition as YAML; save as a new version"
          aria-label="Edit definition"
          disabled={isConnected || agentListState.loading || !agent || !agentQueryMatchesSelection}
          onClick={onEditAgent}>
          <Icon name="code" /><span>YAML</span>
        </button>
        <button className="definition-button" type="button" title="Copy URL to this agent"
          aria-label="Copy URL to this agent"
          disabled={!agent || !agentQueryMatchesSelection || Boolean(transportError)}
          onClick={copyAgentUrl}>
          <Icon name="external" /><span>URL</span>
        </button>
        {agentListState.hasMore || agentListState.loadingMore ? (
          <div className="agent-pagination">
            <span aria-live="polite">{agents.length} loaded</span>
            <button type="button" aria-label="Load more agents" title="Load more agents"
              disabled={agentListState.loadingMore} onClick={onLoadMoreAgents}>
              {agentListState.loadingMore ? "Loading…" : "More"}
            </button>
          </div>
        ) : null}
      </div>
      {!agentQueryMatchesSelection && agentQuery.trim() && !agentSearchState.error ? (
        <p className="agent-search-hint">Press Enter or Search to select this Agent name.</p>
      ) : null}
      {agentSearchState.error ? (
        <div className="form-feedback err" role="alert">{agentSearchState.error}</div>
      ) : null}
      {agentListState.error ? <div className="form-feedback err" role="alert">{agentListState.error}</div> : null}
      {transportError ? (
        <div className="form-feedback err" role="alert" id="session-transport-error">{transportError}</div>
      ) : null}
      {transportNotice ? <p className="field-hint" role="status">{transportNotice}</p> : null}
      {typeof agent?.sessionStoreDefault === "boolean" ? (
        <p className="field-hint" role="status">
          Generated-session storage: {storeOverride === "" ? "use stored agent policy" : storeOverride === "true" ? "save transcript and audio" : "do not save"}.
          {" "}Change it in Session settings. The agent's stored definition is unchanged.
        </p>
      ) : null}
      {copyUrlState.text ? (
        <div className={`copy-agent-url-status ${copyUrlState.kind}`} role="status">
          <strong>{copyUrlState.text}</strong>
          <code>{copyUrlState.url}</code>
        </div>
      ) : null}
      <div className="session-actions">
        <div className="session-action-context">
          {agent ? (
            <div className="selected-agent-meta">
              <span className="subtle-badge">{modelSource}</span>
              <span title={agent.targetAgent?.name || agent.model}>{agent.model || agent.targetAgent?.name}</span>
              <span title={agent.voice}>{agent.voice || "Default voice"}</span>
              <span>v{agent.version || "latest"}</span>
            </div>
          ) : <p className="field-hint picker-hint">{agents.length} voice agent{agents.length === 1 ? "" : "s"} loaded. Creation is optional.</p>}
          <details className="session-settings" ref={settingsRef} onKeyDown={(event) => {
          if (event.key === "Escape") {
            settingsRef.current?.removeAttribute("open");
            settingsRef.current?.querySelector("summary")?.focus();
          }
        }}>
          <summary><Icon name="settings" />Session settings<Icon name="chevron" /></summary>
          <div className="session-settings-body">
            <div className="field-hint">Overrides apply to this connection only. The stored agent is unchanged.</div>
            <div className="field-grid">
              <Field label="Voice override">
                <GroupedSelect value={voiceOverride} disabled={isConnected || !agent}
                  placeholder="Use agent default" groups={voiceGroups(cfg, agent?.cascaded)}
                  onChange={(event) => setVoiceOverride(event.target.value)} />
              </Field>
              <Field label="Conversation storage override">
                <select value={storeOverride} disabled={isConnected || !agent}
                  onChange={(event) => setStoreOverride(event.target.value)}>
                  <option value="">Use agent default{agent ? ` (${agent.store ? "on" : "off"})` : ""}</option>
                  <option value="true">Save transcript & audio</option>
                  <option value="false">Do not save</option>
                </select>
              </Field>
              <Field label="Transport">
                <select value={transport} disabled={isConnected}
                  aria-invalid={Boolean(transportError)}
                  aria-describedby={transportError ? "session-transport-error" : undefined}
                  onChange={(event) => onTransportChange(event.target.value)}>
                  {transportError ? <option value={transport} disabled>Select a supported transport</option> : null}
                  <option value="websocket">WebSocket · PCM audio</option>
                  <option value="webrtc" disabled={Boolean(agent?.clientReferenceEc)}>WebRTC · media</option>
                </select>
              </Field>
              {agent?.clientReferenceEc ? (
                <Field label="Client reference audio">
                  <select value={referenceAudioMode} disabled={isConnected}
                    onChange={(event) => setReferenceAudioMode(event.target.value)}>
                    <option value="assistant">Agent playback only</option>
                    <option value="shared-additive">Agent + shared tab/app audio</option>
                    <option value="shared-system">Shared system mix (includes agent)</option>
                  </select>
                </Field>
              ) : null}
            </div>
            <Field label="Structured input JSON" optional
              hint={`Values apply to this session only. Use a JSON object; do not include secrets.${
                agent?.definition?.structured_inputs
                  ? ` Declared keys: ${Object.keys(agent.definition.structured_inputs).join(", ") || "(none)"}.`
                  : ""
              }`}>
              <textarea value={structuredInput} disabled={isConnected || !agent} rows={3}
                placeholder='{"customer_name":"Grace"}'
                onChange={(event) => setStructuredInput(event.target.value)} />
            </Field>
            {agent?.clientReferenceEc ? <p className="field-hint">
              Live-reference echo cancellation requires WebSocket. Shared audio opens the browser’s share picker;
              enable audio sharing. The system mix replaces the direct agent tap to avoid duplication.
            </p> : transport === "webrtc" ? <p className="field-hint">
              WebRTC carries microphone and agent audio over a peer connection. Avatar is not used in this mode.
              Use localhost or HTTPS.
            </p> : null}
            {agent ? (
              <dl className="agent-facts">
                <div><dt>Greeting</dt><dd>{agent.greeting?.type || "None"}</dd></div>
                <div><dt>Echo cancellation</dt><dd>{agent.clientReferenceEc ? "Live reference" : "Server loopback"}</dd></div>
                <div><dt>Avatar</dt><dd>{agent.avatar ? [agent.avatar.character, agent.avatar.style].filter(Boolean).join(" / ") : "Off"}</dd></div>
                {agent.targetAgent ? <div><dt>Hosted target</dt><dd>{agent.targetAgent.name} · {agent.targetAgent.version || "latest"}</dd></div> : null}
              </dl>
            ) : null}
            <p className="field-hint">Tools and avatar belong to the stored version. Use Edit definition to change them.</p>
          </div>
          </details>
        </div>
        <div className="connection-buttons">
          {isConnected ? (
            <>
              <button type="button" className="icon-button" onClick={session.toggleMute}
                disabled={!sessionReady} title={micMuted ? "Unmute mic" : "Mute mic"}
                aria-label={micMuted ? "Unmute mic" : "Mute mic"}>
                <Icon name={micMuted ? "muted" : "voice"} />
              </button>
              <button type="button" className="danger" onClick={session.stopSession}><Icon name="stop" />Stop session</button>
            </>
          ) : (
            <button type="button" className="primary connect-button"
              disabled={!agent || agentListState.loading || !agentQueryMatchesSelection || Boolean(transportError)}
              onClick={connect}><Icon name="voice" />Connect &amp; start session</button>
          )}
        </div>
      </div>
    </section>
  );
}
