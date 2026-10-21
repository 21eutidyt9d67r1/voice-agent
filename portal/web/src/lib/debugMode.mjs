// Copyright (c) Microsoft. All rights reserved.

// Debug mode (latency/cost estimates, protocol events) has no visible toggle;
// open a page with ?debug=1 to turn it on for that page load.
export function debugModeRequested(search = globalThis.location?.search || "") {
  return new URLSearchParams(search).get("debug") === "1";
}
