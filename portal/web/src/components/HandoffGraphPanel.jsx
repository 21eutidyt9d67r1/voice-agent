// Copyright (c) Microsoft. All rights reserved.
// Live handoff diagram for the demo session. It shares the authoring editor's card layout and edge
// routing, then overlays active-node state and per-node runtime metrics.

import { Fragment, useEffect, useId, useMemo, useState } from "react";
import {
  PIPELINE_METRICS_DISCLAIMER,
  estimatePipeline,
  formatPipelineCost,
  formatPipelineLatency,
  layoutHandoffGraph,
  pipelineBrand,
  pipelineTotals,
  sideEdgeAnchors,
  smoothOuterEdgePath,
  smoothVerticalEdgePath,
} from "../../../static/handoff/handoff-core.mjs";
import {
  createHandoffRuntimeMetrics,
  formatHandoffDuration,
  handoffDurationShares,
  snapshotHandoffRuntimeMetrics,
} from "../lib/handoffRuntimeMetrics.mjs";

const CARD_WIDTH = 320;
const CARD_HEIGHT = 149;
const ROW_GAP = 108;

function nowMs() {
  return typeof performance !== "undefined" ? performance.now() : Date.now();
}

function stageLabel(brand, fallback) {
  if (brand === "gpt") return "GPT";
  if (brand === "azure") return "AZ";
  if (brand === "whisper") return "W";
  if (brand === "mai") return "MAI";
  if (brand === "voice") return "TTS";
  if (brand === "speech") return "STT";
  return fallback;
}

function PipelineStage({ kind, value, fallback }) {
  const brand = pipelineBrand(kind, value);
  return (
    <span className={`runtime-pipeline-stage brand-${brand}`} title={`${fallback}: ${value || "inherited"}`}>
      {stageLabel(brand, fallback)}
    </span>
  );
}

function FlipValue({ value }) {
  return (
    <b className="runtime-flip-value">
      <span key={value}>{value}</span>
    </b>
  );
}

function StageEstimate({ label, component }) {
  return (
    <span>
      <em>{label}</em>
      <b>{formatPipelineLatency(component)}</b>
      <small>{formatPipelineCost(component?.costPerMinute)}</small>
    </span>
  );
}

function graphGeometry(graph) {
  const positions = layoutHandoffGraph(
    graph.nodes.map((node) => node.id),
    graph.edges,
    {
      nodeWidth: CARD_WIDTH,
      nodeHeight: CARD_HEIGHT,
      rowGap: ROW_GAP,
      originX: 90,
      originY: 40,
    },
  );
  const boxes = new Map([...positions].map(([id, position]) => [
    id,
    { ...position, width: CARD_WIDTH, height: CARD_HEIGHT },
  ]));
  const values = [...boxes.values()];
  const base = {
    minX: Math.min(...values.map((box) => box.x)),
    maxX: Math.max(...values.map((box) => box.x + box.width)),
    maxY: Math.max(...values.map((box) => box.y + box.height)),
  };
  const graphCenter = (base.minX + base.maxX) / 2;
  let leftLane = 0;
  let rightLane = 0;
  const rawLanes = new Map();
  for (const edge of graph.edges) {
    const source = boxes.get(edge.source);
    const target = boxes.get(edge.target);
    if (!source || !target || target.y > source.y) continue;
    const average = (
      source.x + source.width / 2
      + target.x + target.width / 2
    ) / 2;
    const laneX = average < graphCenter
      ? base.minX - 72 - leftLane++ * 22
      : base.maxX + 72 + rightLane++ * 22;
    rawLanes.set(edge.id, laneX);
  }
  const minVisualX = Math.min(base.minX, ...rawLanes.values());
  const shiftX = Math.max(0, 28 - minVisualX);
  const shiftedBoxes = new Map([...boxes].map(([id, box]) => [
    id,
    { ...box, x: box.x + shiftX },
  ]));
  const lanes = new Map([...rawLanes].map(([id, laneX]) => [id, laneX + shiftX]));
  const edgeGeometry = new Map();
  for (const edge of graph.edges) {
    const source = shiftedBoxes.get(edge.source);
    const target = shiftedBoxes.get(edge.target);
    if (!source || !target) continue;
    const laneX = lanes.get(edge.id);
    if (laneX != null) {
      const anchors = sideEdgeAnchors(source, target, laneX);
      edgeGeometry.set(edge.id, {
        outer: true,
        side: anchors.side,
        path: smoothOuterEdgePath(
          anchors.sourceX,
          anchors.sourceY,
          anchors.targetX,
          anchors.targetY,
          laneX,
        ),
      });
    } else {
      edgeGeometry.set(edge.id, {
        outer: false,
        path: smoothVerticalEdgePath(
          source.x + source.width / 2,
          source.y + source.height,
          target.x + target.width / 2,
          target.y,
        ),
      });
    }
  }
  return {
    boxes: shiftedBoxes,
    edges: edgeGeometry,
    width: Math.ceil(Math.max(
      ...[...shiftedBoxes.values()].map((box) => box.x + box.width),
      ...lanes.values(),
    ) + 32),
    height: Math.ceil(base.maxY + 32),
  };
}

function signature(tool) {
  const params = Object.entries(tool.parameters || {});
  if (params.length) {
    return `(${params.map(([name, schema]) => `${name}: ${schema?.type || "?"}`).join(", ")})`;
  }
  return tool.kind === "function" ? "(no arguments)" : "";
}

/* An MCP tool's declaration cannot tell you whether the server answers: the URL is written by the
 * author, the credential lives in the project connection the service holds, and the allowed_tools
 * list is a claim about what the server exposes. Test calls the server for real and reports which
 * of those three is wrong, because "the agent silently does nothing" usually means one of them is. */
function McpToolCard({ tool, agentName, enableProbe, showServerUrl }) {
  const [result, setResult] = useState(null);
  const [running, setRunning] = useState(false);

  useEffect(() => setResult(null), [agentName, tool.serverLabel]);

  const test = async () => {
    setRunning(true);
    setResult({ state: "running", text: "testing…" });
    const startedAt = performance.now();
    try {
      const resp = await fetch("/api/mcp/probe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent: agentName, server_label: tool.serverLabel }),
      });
      const data = await resp.json();
      const roundTrip = Math.round(performance.now() - startedAt);
      if (data.ok) {
        setResult({
          state: "good",
          text: `ok · ${data.latency_ms} ms (init ${data.initialize_ms} + tools/list ${data.tools_ms})`
            + ` · ${data.tools.length} tools · ${roundTrip} ms round trip`,
          detail: data.server_name ? `${data.server_name} ${data.server_version}` : "",
        });
      } else if (data.connection_only) {
        setResult({
          state: "warn",
          text: "project connection · no direct MCP URL is available to test",
        });
      } else if (data.no_mcp) {
        setResult({
          state: "warn",
          text: "published as a function tool — the agent carries the declaration itself,"
            + " so there is no MCP endpoint to call",
        });
      } else if (data.reached) {
        setResult({
          state: "warn",
          text: `reachable · HTTP ${data.http_status} in ${data.latency_ms} ms · ${data.error}`,
        });
      } else {
        setResult({ state: "bad", text: `unreachable · ${data.error || `HTTP ${resp.status}`}` });
      }
    } catch (error) {
      setResult({ state: "bad", text: `failed · ${error.message}` });
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="tool-card">
      <div className="tool-card-head">
        <span className="kind-chip mcp">MCP</span>
        <code>{tool.serverLabel || "mcp"}</code>
        <span className="tool-count">{tool.allowedTools.length || "all"} tools</span>
        {enableProbe ? (
          <button type="button" className="probe-btn" onClick={test} disabled={running || !agentName}>
            {running ? "testing…" : "Test"}
          </button>
        ) : null}
      </div>
      <div className="tool-card-meta">
        {showServerUrl && tool.serverUrl
          ? <span className="tool-url" title={tool.serverUrl}>{tool.serverUrl}</span>
          : null}
        {tool.projectConnectionId
          ? <span className="tool-conn">connection: {tool.projectConnectionId}</span>
          : null}
        <span className="tool-flag">approval: {tool.requireApproval}</span>
        {tool.responseScheduling
          ? <span className="tool-flag">scheduling: {tool.responseScheduling}</span>
          : null}
      </div>
      {result ? (
        <div className={`probe-status ${result.state}`} title={result.detail || ""}>{result.text}</div>
      ) : enableProbe ? (
        <div className="probe-status">not tested — the server is called live when you press Test</div>
      ) : null}
      {tool.allowedTools.length ? (
        <ul className="tool-name-list">
          {tool.allowedTools.map((name) => <li key={name}><code>{name}</code></li>)}
        </ul>
      ) : null}
    </div>
  );
}

function FunctionToolCard({ tool }) {
  return (
    <div className="tool-card">
      <div className="tool-card-head">
        <span className={`kind-chip ${tool.kind === "toolbox" ? "toolbox" : "fn"}`}>
          {tool.kind === "toolbox" ? "TOOLBOX" : "FUNCTION"}
        </span>
        <code>{tool.label}</code>
        {tool.toolboxVersion ? <span className="tool-count">v{tool.toolboxVersion}</span> : null}
      </div>
      {tool.description ? <p className="tool-desc">{tool.description}</p> : null}
      {signature(tool) ? <div className="tool-params">{signature(tool)}</div> : null}
      {tool.allowedTools?.length ? (
        <ul className="tool-name-list">
          {tool.allowedTools.map((name) => <li key={name}><code>{name}</code></li>)}
        </ul>
      ) : null}
    </div>
  );
}

/* A modal rather than a panel under the diagram: a node's prompt runs to hundreds of words and its
 * tools each need a URL, an allow-list and a test result beside them. In a column that also holds
 * the graph that reads through a slot; over the page it reads as a page. */
function NodeModal({
  node, graph, agentName, enableMcpProbe, showMcpServerUrl, onClose, onOpenNode,
}) {
  const specs = node.toolSpecs || [];
  const mcp = specs.filter((tool) => tool.kind === "mcp");
  const functions = specs.filter((tool) => tool.kind !== "mcp");
  const outgoing = graph.edges.filter((edge) => edge.source === node.id);

  useEffect(() => {
    const onKey = (event) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="node-modal">
      <div className="node-modal-backdrop" onClick={onClose} />
      <div className="node-modal-card" role="dialog" aria-modal="true">
        <header className="node-modal-head">
          <div className="node-modal-title">
            <span className="node-modal-kind">{node.kind}</span>
            <b>{node.label}</b>
            <span className="node-modal-sub">{node.id}</span>
          </div>
          <div className="node-modal-chips">
            <span className="hg-chip">tool_choice: {node.toolChoice}</span>
            <span className="hg-chip">{mcp.length} MCP servers</span>
            {functions.length ? <span className="hg-chip">{functions.length} function tools</span> : null}
            <span className="hg-chip">{outgoing.length} outgoing edges</span>
            {node.voice ? <span className="hg-chip">voice: {node.voice}</span> : null}
            {node.model ? <span className="hg-chip">model: {node.model}</span> : null}
          </div>
          <button type="button" className="node-modal-close" onClick={onClose} aria-label="Close">✕</button>
        </header>

        <div className="node-modal-body">
          <section className="node-modal-section">
            <h4>Instructions</h4>
            {node.description ? <p className="node-modal-desc">{node.description}</p> : null}
            <pre>
              {node.instructions
                || (node.authored
                  ? "(no node instructions — this node inherits the session instructions)"
                  : "(this node was compiled by the service; the agent definition does not describe it)")}
            </pre>
          </section>

          <div className="node-modal-col">
            <section className="node-modal-section">
              <h4>Tools ({specs.length})</h4>
              {specs.length ? null : <p className="node-modal-empty">This node carries no tools.</p>}
              {mcp.map((tool) => (
                <McpToolCard
                  key={tool.serverLabel || tool.label}
                  tool={tool}
                  agentName={agentName}
                  enableProbe={enableMcpProbe}
                  showServerUrl={showMcpServerUrl}
                />
              ))}
              {functions.map((tool) => <FunctionToolCard key={tool.label} tool={tool} />)}
            </section>

            {outgoing.length ? (
              <section className="node-modal-section">
                <h4>Outgoing edges</h4>
                <ul className="node-modal-edges">
                  {outgoing.map((edge) => (
                    <li key={edge.id}>
                      <button type="button" className="edge-jump" onClick={() => onOpenNode(edge.target)}>
                        → {edge.target}
                      </button>
                      <span className="edge-desc">{edge.description}</span>
                      <span className="hg-chip">target_response: {edge.targetResponse}</span>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

export function HandoffGraphPanel({
  graph, activeNodeId, takenEdgeIds, trail, agentName, enableMcpProbe = true,
  showMcpServerUrl = true, runtimeMetrics = createHandoffRuntimeMetrics(),
  debugMode = false,
}) {
  const [selectedId, setSelectedId] = useState(null);
  const [expandedMetricId, setExpandedMetricId] = useState(null);
  const [clock, setClock] = useState(nowMs);
  const markerId = useId().replaceAll(":", "");
  const geometry = useMemo(() => graphGeometry(graph), [graph]);
  const metrics = useMemo(
    () => snapshotHandoffRuntimeMetrics(runtimeMetrics, clock),
    [clock, runtimeMetrics],
  );
  const shares = useMemo(() => handoffDurationShares(metrics), [metrics]);

  useEffect(() => {
    setClock(nowMs());
    if (!runtimeMetrics.activeNodeId) return undefined;
    const timer = window.setInterval(() => setClock(nowMs()), 2000);
    return () => window.clearInterval(timer);
  }, [runtimeMetrics]);

  const taken = new Set(takenEdgeIds || []);
  const available = new Set(
    graph.availableNodeId && graph.availableNodeId === activeNodeId ? graph.availableEdgeIds : [],
  );
  const selected = graph.nodes.find((node) => node.id === selectedId) || null;

  const { stats } = graph;
  let graphStatus = "authored";
  if (graph.source === "session") graphStatus = activeNodeId ? "live" : "ended";
  const badges = [
    graphStatus,
    stats.transferCount
      ? `transfers: ${stats.transferCount}${stats.maxTransfers ? `/${stats.maxTransfers}` : ""}`
      : null,
    stats.pipelineFamily || null,
  ].filter(Boolean);

  return (
    <section className="handoff-graph">
      <div className="handoff-graph-head">
        <h3>Handoff graph</h3>
        <span className="handoff-active">
          active node: <code>
            {activeNodeId || (graph.source === "session" ? "session ended" : graph.entrypoint)}
          </code>
        </span>
        {badges.map((badge) => <span key={badge} className="handoff-badge">{badge}</span>)}
        <span className="handoff-hint">click a node to read its prompt</span>
      </div>

      <div className="handoff-graph-body">
        <div className="graph-wrap runtime-graph-wrap">
          <div
            className="runtime-graph-canvas"
            style={{ width: geometry.width, height: geometry.height }}
          >
            <svg
              className="runtime-edge-layer"
              width={geometry.width}
              height={geometry.height}
              viewBox={`0 0 ${geometry.width} ${geometry.height}`}
              aria-hidden="true"
            >
            <defs>
              <marker id={`${markerId}-arrow`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0 L8,4 L0,8 z" />
              </marker>
              <marker id={`${markerId}-arrow-active`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0 L8,4 L0,8 z" />
              </marker>
            </defs>
              {graph.edges.map((edge) => {
                const edgeView = geometry.edges.get(edge.id);
                if (!edgeView) return null;
                const isTaken = taken.has(edge.id);
                const classes = [
                  "runtime-edge",
                  edgeView.outer ? "outer" : "",
                  isTaken ? "taken" : "",
                  available.has(edge.id) ? "available" : "",
                ];
                return (
                  <path
                    key={edge.id}
                    className={classes.filter(Boolean).join(" ")}
                    d={edgeView.path}
                    markerEnd={`url(#${isTaken ? `${markerId}-arrow-active` : `${markerId}-arrow`})`}
                  >
                    <title>
                      {`${edge.id} (target_response: ${edge.targetResponse})`}
                      {edge.description ? `\n${edge.description}` : ""}
                      {edge.transferMessage ? `\ntransfer message: ${edge.transferMessage}` : ""}
                    </title>
                  </path>
                );
              })}
            </svg>

            {graph.nodes.map((node) => {
              const box = geometry.boxes.get(node.id);
              const nodeMetric = metrics[node.id] || {
                durationMs: 0,
                userTurns: 0,
                visits: 0,
                latency: null,
                active: false,
              };
              const pipelineEstimate = estimatePipeline({
                stt: node.stt,
                model: node.model,
                voice: node.voice,
                voiceType: node.voiceType,
                customSpeech: node.customSpeech,
              }).pipeline;
              const estimatedTotals = pipelineTotals(pipelineEstimate);
              const dwellShare = shares[node.id] || 0;
              const mcpCount = node.toolSpecs.filter((tool) => tool.kind === "mcp").length;
              const toolCount = node.toolSpecs.length - mcpCount;
              const outgoing = graph.edges.filter((edge) => edge.source === node.id).length;
              const nodeCompleted = nodeMetric.completed && !nodeMetric.active;
              const classes = [
                "runtime-node-card",
                node.kind === "entry" ? "entry" : "",
                node.id === activeNodeId ? "active" : "",
                nodeMetric.visits > 0 ? "visited" : "",
                nodeCompleted ? "completed" : "",
                nodeMetric.visits > 0 && !nodeMetric.active && !nodeCompleted ? "stopped" : "",
                nodeMetric.visits === 0 ? "unvisited" : "",
                node.id === selectedId ? "selected" : "",
                debugMode && node.id === expandedMetricId ? "metrics-open" : "",
              ];
              return (
                <article
                  key={node.id}
                  className={classes.filter(Boolean).join(" ")}
                  style={{ left: box.x, top: box.y }}
                  data-node-id={node.id}
                >
                  {nodeMetric.visits ? (
                    <span className={`runtime-node-state ${nodeMetric.active ? "live" : nodeCompleted ? "completed" : "stopped"}`}
                      role="status"
                      title={nodeCompleted ? "This node visit has completed." : nodeMetric.active ? "Currently running." : "Stopped before this node completed."}>
                      <span className="runtime-node-state-icon" aria-hidden="true">
                        {nodeMetric.active ? "●" : nodeCompleted ? "✓" : "■"}
                      </span>
                      {nodeMetric.active ? "LIVE" : nodeCompleted ? "COMPLETED" : "STOPPED"}
                      {nodeMetric.visits > 1 ? ` ×${nodeMetric.visits}` : ""}
                    </span>
                  ) : null}
                  <button
                    type="button"
                    className="runtime-node-open"
                    onClick={() => setSelectedId((current) => (current === node.id ? null : node.id))}
                    aria-label={`Open ${node.label} node details`}
                  >
                    <span className="runtime-node-identity">
                      <span className="runtime-node-icon" aria-hidden="true">{nodeCompleted ? "✓" : "♙"}</span>
                      <span>
                        <b>{node.label}</b>
                        <small>{node.kind === "entry" ? "Starter · fixed name" : node.description || "Voice Agent node"}</small>
                      </span>
                    </span>
                    <span className="runtime-node-pipeline" aria-label="Node speech pipeline">
                      <PipelineStage kind="stt" value={node.stt} fallback="STT" />
                      <PipelineStage kind="model" value={node.model} fallback="LLM" />
                      <PipelineStage kind="voice" value={node.voice} fallback="TTS" />
                    </span>
                  </button>
                  <div className="runtime-node-utility">
                    <span className={mcpCount ? "configured" : ""}>MCP <b>{mcpCount}</b></span>
                    <span><b>{toolCount}</b> tool{toolCount === 1 ? "" : "s"}</span>
                    <span className="routes"><b>{outgoing}</b> route{outgoing === 1 ? "" : "s"}</span>
                  </div>
                  <button
                    type="button"
                    className="runtime-node-metrics"
                    disabled={!debugMode}
                    aria-expanded={debugMode && node.id === expandedMetricId}
                    aria-label={debugMode
                      ? `Show runtime latency and cost for ${node.label}`
                      : `Runtime activity for ${node.label}`}
                    onClick={() => setExpandedMetricId((current) => (
                      current === node.id ? null : node.id
                    ))}
                  >
                    <span>Dwell <FlipValue value={formatHandoffDuration(nodeMetric.durationMs)} /></span>
                    <span>Share <FlipValue value={`${dwellShare.toFixed(1)}%`} /></span>
                    <span>Turns <FlipValue value={String(nodeMetric.userTurns)} /></span>
                  </button>
                  {debugMode && node.id === expandedMetricId ? (
                    <div className="runtime-node-breakdown" role="region" aria-label={`${node.label} runtime metrics`}>
                      <div className="runtime-observed-latency">
                        <strong>Observed turn latency</strong>
                        {nodeMetric.latency ? (
                          <div>
                            <span><em>Average</em><b>{nodeMetric.latency.averageMs} ms</b></span>
                            <span><em>P50</em><b>{nodeMetric.latency.p50Ms} ms</b></span>
                            <span><em>P95</em><b>{nodeMetric.latency.p95Ms} ms</b></span>
                            <span><em>Latest</em><b>{nodeMetric.latency.latestMs} ms</b></span>
                          </div>
                        ) : (
                          <p>No completed user response has been observed in this node yet.</p>
                        )}
                      </div>
                      <div className="runtime-estimate-head">
                        <span>Pipeline</span>
                        <strong>
                          {formatPipelineLatency(estimatedTotals)}
                        </strong>
                        <strong>
                          {formatPipelineCost(estimatedTotals?.costPerMinute)}
                        </strong>
                      </div>
                      <div className="runtime-stage-estimates">
                        <StageEstimate label="STT" component={pipelineEstimate.stt} />
                        <StageEstimate label="LLM" component={pipelineEstimate.model} />
                        <StageEstimate label="TTS" component={pipelineEstimate.voice} />
                      </div>
                      <p className="runtime-estimate-note">
                        Disclaimer: {PIPELINE_METRICS_DISCLAIMER}
                      </p>
                    </div>
                  ) : null}
                  {node.kind === "entry" ? null : <i className="runtime-node-port input" aria-hidden="true" />}
                  <i className="runtime-node-port output" aria-hidden="true" />
                </article>
              );
            })}
          </div>
        </div>

        <ol className="handoff-trail">
          {(trail || []).map((step) => (
            <li key={`${step.at}-${step.nodeId}`}>
              <code>{step.nodeId}</code>
              {step.edgeId ? <span className="handoff-trail-edge">via {step.edgeId}</span> : null}
            </li>
          ))}
          {trail && trail.length ? null : <li className="handoff-trail-empty">no transfer yet</li>}
        </ol>
      </div>

      {selected ? (
        <NodeModal
          node={selected}
          graph={graph}
          agentName={agentName}
          enableMcpProbe={enableMcpProbe}
          showMcpServerUrl={showMcpServerUrl}
          onClose={() => setSelectedId(null)}
          onOpenNode={(id) => setSelectedId(id)}
        />
      ) : null}
    </section>
  );
}
