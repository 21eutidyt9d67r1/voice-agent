// Copyright (c) Microsoft. All rights reserved.
import assert from "node:assert/strict";
import test from "node:test";

import { debugModeRequested } from "./debugMode.mjs";

test("debug mode is off unless the page is opened with debug=1", () => {
  assert.equal(debugModeRequested(""), false);
  assert.equal(debugModeRequested("?agent=x"), false);
  assert.equal(debugModeRequested("?debug=0"), false);
  assert.equal(debugModeRequested("?debug=true"), false);
  assert.equal(debugModeRequested("?debug=1"), true);
  assert.equal(debugModeRequested("?agent=x&debug=1"), true);
});
