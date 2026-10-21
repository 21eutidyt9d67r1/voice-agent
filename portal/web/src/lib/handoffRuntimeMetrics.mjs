// Copyright (c) Microsoft. All rights reserved.

const emptyNode = () => ({
  durationMs: 0,
  userTurns: 0,
  visits: 0,
  completed: false,
  latencySamplesMs: [],
});

export function createHandoffRuntimeMetrics() {
  return {
    activeNodeId: null,
    activeSinceMs: null,
    nodes: {},
  };
}

function closeActiveNode(state, atMs, completed = false) {
  if (!state.activeNodeId || state.activeSinceMs == null) return state.nodes;
  const current = state.nodes[state.activeNodeId] || emptyNode();
  return {
    ...state.nodes,
    [state.activeNodeId]: {
      ...current,
      durationMs: current.durationMs + Math.max(0, atMs - state.activeSinceMs),
      completed,
    },
  };
}

export function activateHandoffNode(state, nodeId, atMs) {
  const id = String(nodeId || "");
  if (!id || state.activeNodeId === id) return state;
  const nodes = closeActiveNode(state, atMs, true);
  const current = nodes[id] || emptyNode();
  return {
    activeNodeId: id,
    activeSinceMs: atMs,
    nodes: {
      ...nodes,
      [id]: {
        ...current,
        visits: current.visits + 1,
        completed: false,
      },
    },
  };
}

export function recordHandoffUserTurn(state, nodeId) {
  const id = String(nodeId || state.activeNodeId || "");
  if (!id) return state;
  const current = state.nodes[id] || emptyNode();
  return {
    ...state,
    nodes: {
      ...state.nodes,
      [id]: {
        ...current,
        userTurns: current.userTurns + 1,
      },
    },
  };
}

export function recordHandoffLatency(state, nodeId, latencyMs) {
  const id = String(nodeId || "");
  if (!id || !Number.isFinite(latencyMs) || latencyMs < 0) return state;
  const current = state.nodes[id] || emptyNode();
  return {
    ...state,
    nodes: {
      ...state.nodes,
      [id]: {
        ...current,
        latencySamplesMs: [...current.latencySamplesMs, latencyMs].slice(-50),
      },
    },
  };
}

export function stopHandoffRuntimeMetrics(state, atMs, { completed = false } = {}) {
  if (!state.activeNodeId) return state;
  return {
    activeNodeId: null,
    activeSinceMs: null,
    nodes: closeActiveNode(state, atMs, completed),
  };
}

export function snapshotHandoffRuntimeMetrics(state, atMs) {
  const nodes = Object.fromEntries(
    Object.entries(state.nodes).map(([id, metric]) => [id, {
      ...metric,
      latency: summarizeLatency(metric.latencySamplesMs),
      active: false,
    }]),
  );
  if (state.activeNodeId) {
    const current = nodes[state.activeNodeId] || {
      ...emptyNode(),
      latency: null,
      active: false,
    };
    nodes[state.activeNodeId] = {
      ...current,
      durationMs: current.durationMs + (
        state.activeSinceMs == null ? 0 : Math.max(0, atMs - state.activeSinceMs)
      ),
      active: true,
    };
  }
  return nodes;
}

function percentile(sorted, value) {
  if (!sorted.length) return null;
  return sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * value) - 1)];
}

export function summarizeLatency(samples) {
  const values = (samples || []).filter(
    (value) => Number.isFinite(value) && value >= 0,
  );
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  return {
    count: sorted.length,
    latestMs: Math.round(values.at(-1)),
    averageMs: Math.round(values.reduce((sum, value) => sum + value, 0) / values.length),
    p50Ms: Math.round(percentile(sorted, 0.5)),
    p95Ms: Math.round(percentile(sorted, 0.95)),
  };
}

export function handoffDurationShares(metrics) {
  const entries = Object.entries(metrics || {});
  const total = entries.reduce(
    (sum, [, metric]) => sum + Math.max(0, metric.durationMs || 0),
    0,
  );
  if (!total) return Object.fromEntries(entries.map(([id]) => [id, 0]));
  const shares = Object.fromEntries(entries.map(([id, metric]) => [
    id,
    Math.round((Math.max(0, metric.durationMs || 0) / total) * 1000) / 10,
  ]));
  const sum = Object.values(shares).reduce((value, share) => value + share, 0);
  const largest = entries.reduce((best, entry) => (
    (entry[1].durationMs || 0) > (best?.[1].durationMs || 0) ? entry : best
  ), null);
  if (largest) {
    shares[largest[0]] = Math.round((shares[largest[0]] + 100 - sum) * 10) / 10;
  }
  return shares;
}

export function formatHandoffDuration(durationMs) {
  const seconds = Math.max(0, durationMs) / 1000;
  if (seconds < 10) return `${seconds.toFixed(1)}s`;
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60);
  return `${minutes}m ${String(remainder).padStart(2, "0")}s`;
}
