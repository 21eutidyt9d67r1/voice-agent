import assert from "node:assert/strict";
import test from "node:test";

import {
  ENTRYPOINT_ID,
  PIPELINE_COMPONENTS,
  PIPELINE_COST_USAGE,
  PIPELINE_LLM_ESTIMATE_DIVISOR,
  PIPELINE_RETAIL_RATES_PER_MILLION,
  createSampleDefinition,
  deterministicYaml,
  estimatePipeline,
  ensureEditableDefinition,
  extractLatestAgent,
  formatPipelineCost,
  formatPipelineLatency,
  layoutHandoffGraph,
  mergeServiceProblems,
  matchesAgentSearch,
  modelEstimate,
  pipelineBrand,
  pipelineComponentOptions,
  pipelineComponentProvider,
  pipelineMetricMinimum,
  pipelineTotals,
  publicationFeatures,
  sideEdgeAnchors,
  smoothOuterEdgePath,
  smoothVerticalEdgePath,
  sortPipelineComponents,
  stableJson,
  validateDefinition,
} from "../../../static/handoff/handoff-core.mjs";

test("pipeline metrics show compact cents and complete latency ranges", () => {
  assert.equal(formatPipelineCost(.019654), "1.97¢/min");
  assert.equal(formatPipelineCost(.000154), "0.02¢/min");
  assert.equal(formatPipelineCost(.00001), "0.01¢/min");
  assert.equal(formatPipelineCost(.019651), "1.97¢/min");
  assert.equal(formatPipelineCost(.019701), "1.98¢/min");
  assert.equal(formatPipelineCost(.0102), "1.02¢/min");
  assert.equal(formatPipelineCost(Number.MIN_VALUE), "0.01¢/min");
  assert.equal(formatPipelineCost(0), "0¢/min");
  for (const value of [null, undefined, NaN, Infinity, Number.MAX_VALUE, -1]) {
    assert.equal(formatPipelineCost(value), "Not available");
  }
  assert.equal(
    formatPipelineLatency({ latencyMinMs: 800, latencyMaxMs: 3200 }),
    "800 ms – 3.2 s",
  );
  assert.equal(
    formatPipelineLatency({ latencyMinMs: 1300, latencyMaxMs: 3625 }),
    "1.3 s – 3.7 s",
  );
  assert.equal(formatPipelineLatency({ latencyMs: 307 }), "307 ms");
  assert.equal(formatPipelineLatency({ latencyMinMs: 800 }), "Not available");
  assert.equal(formatPipelineLatency(null), "Not available");
});

test("displayed cost never rounds a positive budget down or to zero", () => {
  for (let millionths = 1; millionths <= 100_000; millionths += 17) {
    const usd = millionths / 1_000_000;
    const displayed = Number(formatPipelineCost(usd).replaceAll(",", "").replace("¢/min", ""));
    assert.ok(displayed > 0);
    assert.ok(displayed + 1e-12 >= usd * 100, `${usd} rounded down to ${displayed} cents`);
    assert.ok(displayed - usd * 100 < .010000000001);
  }
});

test("uses full audio minutes and budgets for repeated history and reasoning without cache discounts", () => {
  assert.deepEqual(PIPELINE_COST_USAGE, {
    userAudioSeconds: 60,
    agentAudioSeconds: 60,
    inputAudioTokensPerSecond: 10,
    outputAudioTokensPerSecond: 20,
    modelRequestsPerMinute: 10,
    textInputTokensPerRequest: 64_000,
    textOutputTokensPerRequest: 2_000,
    nativeAudioInputTokensPerRequest: 6_000,
    nativeAudioInputTokens: 60_000,
    textInputTokens: 640_000,
    textOutputTokens: 20_000,
  });
  assert.equal(PIPELINE_RETAIL_RATES_PER_MILLION.lite.nativeAudioOutput, 12);
  assert.deepEqual(
    ["pro", "standard", "lite"].map((tier) => {
      const rates = PIPELINE_RETAIL_RATES_PER_MILLION[tier];
      return [
        rates.textInput, rates.textOutput, rates.nativeAudioInput, rates.nativeAudioOutput,
        rates.speechInput, rates.speechOutput, rates.customSpeechInput, rates.customSpeechOutput,
      ];
    }),
    [
      [4, 16, 32, 64, 17, 31, 40, 55],
      [.66, 2.64, 11, 22, 15, 26, 39, 50],
      [.11, .44, 4, 12, 15, 25, 38, 50],
    ],
  );
});

test("divides only the prior model budget by the approved factor and preserves full speech minutes", () => {
  assert.equal(PIPELINE_LLM_ESTIMATE_DIVISOR, 150);
  const usage = PIPELINE_COST_USAGE;
  assert.equal(usage.textInputTokens, usage.modelRequestsPerMinute * usage.textInputTokensPerRequest);
  assert.equal(usage.textOutputTokens, usage.modelRequestsPerMinute * usage.textOutputTokensPerRequest);
  assert.equal(usage.nativeAudioInputTokens, usage.modelRequestsPerMinute * usage.nativeAudioInputTokensPerRequest);
  const realtime = estimatePipeline({ model: "gpt-realtime", stt: "azure-speech", voice: "alloy" }).pipeline;
  const rates = PIPELINE_RETAIL_RATES_PER_MILLION.pro;
  const perRequest = (
    64_000 * rates.textInput + 2_000 * rates.textOutput + 6_000 * rates.nativeAudioInput
  ) / 1_000_000;
  assert.ok(Math.abs(realtime.model.costPerMinute - 10 * perRequest / 150) < 1e-12);
  assert.match(realtime.model.costSource, /Temporary model budget \/150; workload revision pending approval/);
  assert.equal(realtime.stt.costPerMinute, 60 * 10 * rates.speechInput / 1_000_000);
  assert.equal(realtime.voice.costPerMinute, 60 * 20 * rates.nativeAudioOutput / 1_000_000);
});

test("reduces every model budget exactly 150-fold without changing its retail-rate certainty", () => {
  const expected = {
    "gpt-realtime-2.1": [4.96, false],
    "azure-realtime": [4.96, true],
    "gpt-realtime-1.5": [4.96, true],
    "gpt-realtime-2.1-mini": [1.1352, false],
    "gpt-realtime": [4.8, false],
    "gpt-realtime-mini": [1.1352, false],
    "gpt-realtime-2": [4.96, false],
    "gpt-5.4": [3.04, true],
    "gpt-5.6-terra": [3.04, true],
    "gpt-5.6-luna": [.4752, false],
    "gpt-6-sol": [4.44, true],
    "gpt-6.1-sol": [4.44, true],
    "gpt-6-luna": [4.44, true],
    "gpt-oss-120b": [4.44, true],
  };
  const models = pipelineComponentOptions("model");
  assert.equal(models.length, Object.keys(expected).length);
  for (const model of models) {
    const [amount, allowance] = expected[model.id];
    assert.ok(Math.abs(model.costPerMinute * 150 - amount) < 1e-12, model.id);
    assert.equal(model.costIsAllowance, allowance, model.id);
    if (allowance) {
      assert.equal(model.publicRateLabel, "");
      assert.match(model.costSource, /Conservative/);
    } else {
      assert.match(model.publicRateLabel, /1M tokens/);
    }
  }
});

test("shares pipeline estimates between authoring and runtime cards", () => {
  const { preset, pipeline } = estimatePipeline({
    model: "gpt-realtime-2.1",
    voice: "alloy",
    stt: "whisper-1",
  });
  assert.equal(preset.id, "balanced");
  const balancedTotals = pipelineTotals(pipeline);
  assert.ok(Math.abs(balancedTotals.costPerMinute - (.02 + 4.96 / 150 + .0768)) < 1e-12);
  assert.deepEqual({
    latencyMinMs: balancedTotals.latencyMinMs,
    latencyMaxMs: balancedTotals.latencyMaxMs,
    latencyMs: balancedTotals.latencyMs,
  }, {
    latencyMinMs: 1300,
    latencyMaxMs: 3626,
    latencyMs: 2463,
  });

  const fallback = estimatePipeline({
    model: "custom-model",
    voice: "custom-voice",
    stt: "whisper-1",
  }).pipeline;
  assert.equal(pipelineTotals(fallback), null);
  assert.equal(fallback.model.estimateUnavailable, true);
});

test("keeps current Realtime versions distinct and couples compatible speech stages", () => {
  const realtime = estimatePipeline({
    model: "gpt-realtime",
    voice: "alloy",
    stt: "whisper-1",
  }).pipeline;
  assert.equal(realtime.model.id, "gpt-realtime");
  assert.equal(realtime.stt.id, "whisper-1");
  const realtimeTotals = pipelineTotals(realtime);
  assert.ok(Math.abs(realtimeTotals.costPerMinute - .1288) < 1e-12);
  assert.deepEqual({
    latencyMinMs: realtimeTotals.latencyMinMs,
    latencyMaxMs: realtimeTotals.latencyMaxMs,
    latencyMs: realtimeTotals.latencyMs,
  }, {
    latencyMinMs: 800,
    latencyMaxMs: 3126,
    latencyMs: 1963,
  });

  const realtimeModels = pipelineComponentOptions("model")
    .filter((item) => item.architecture === "realtime")
    .map((item) => item.id);
  assert.deepEqual(realtimeModels, [
    "gpt-realtime-2.1",
    "azure-realtime",
    "gpt-realtime-1.5",
    "gpt-realtime-2.1-mini",
    "gpt-realtime",
    "gpt-realtime-mini",
    "gpt-realtime-2",
  ]);
  const realtimeStt = pipelineComponentOptions("stt", {
    model: "gpt-realtime-2.1",
    voice: "alloy",
    stt: "whisper-1",
  });
  assert.equal(realtimeStt.length, 12);
  assert.ok(realtimeStt.every((item) => item.compatible));
  assert.ok(realtimeStt.some((item) => item.id === "whisper-1"));
  assert.ok(realtimeStt.some((item) => item.id === "native-realtime-audio"));
  assert.ok(
    pipelineTotals(estimatePipeline({
      model: "gpt-realtime-2.1",
      voice: "alloy",
      stt: "native-realtime-audio",
    }).pipeline),
  );
  assert.ok(
    pipelineComponentOptions("voice", {
      model: "azure-realtime",
      voice: "ava",
      stt: "azure-speech",
    }).some((item) => item.id === "ava" && item.compatible),
  );
  assert.ok(
    pipelineComponentOptions("voice", {
      model: "azure-realtime",
      voice: "ava",
      stt: "azure-speech",
    }).some((item) => item.id === "alloy" && !item.compatible),
  );
});

test("offers current cascaded models and Voice Live transcription choices", () => {
  const cascadedModels = pipelineComponentOptions("model")
    .filter((item) => item.architecture === "cascaded")
    .map((item) => item.id);
  assert.deepEqual(cascadedModels, [
    "gpt-5.4",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-6-sol",
    "gpt-6.1-sol",
    "gpt-6-luna",
    "gpt-oss-120b",
  ]);
  const transcribers = pipelineComponentOptions("stt", {
    model: "gpt-5.4",
    voice: "en-US-Ava:DragonHDLatestNeural",
    stt: "mai-transcribe-2",
  });

  assert.ok(transcribers.some((item) => item.id === "azure-speech" && item.compatible));
  assert.ok(transcribers.some((item) => item.id === "mai-transcribe-2-streaming" && item.compatible));
  assert.ok(transcribers.some((item) => item.id === "gpt-4o-transcribe-diarize" && !item.compatible));
  assert.ok(transcribers.some((item) => item.id === "whisper-1" && !item.compatible));
});

test("separates verified speech meters from unverified auxiliary transcription allowances", () => {
  const realtimeStt = pipelineComponentOptions("stt", {
    model: "gpt-realtime",
    voice: "alloy",
    stt: "whisper-1",
  });
  assert.equal(realtimeStt.find((item) => item.id === "azure-speech").latencyMs, 1016);
  assert.equal(realtimeStt.find((item) => item.id === "mai-transcribe-2-streaming").latencyMs, 130);
  assert.equal(realtimeStt.find((item) => item.id === "gpt-realtime-whisper").latencyMs, 740);
  assert.equal(realtimeStt.find((item) => item.id === "gpt-4o-transcribe").latencyMs, 637);
  assert.equal(realtimeStt.find((item) => item.id === "whisper-1").latencyMs, 1507);
  for (const model of ["gpt-realtime", "gpt-realtime-mini"]) {
    const choices = pipelineComponentOptions("stt", { model, voice: "alloy" });
    assert.equal(choices.length, 12);
    for (const choice of choices) {
      if (choice.id === "native-realtime-audio") {
        assert.equal(choice.costPerMinute, 0);
      } else if (["azure-speech", "mai-transcribe", "mai-transcribe-2", "mai-transcribe-2-streaming"].includes(choice.id)) {
        assert.equal(choice.costPerMinute, model === "gpt-realtime" ? .0102 : .009);
        assert.equal(choice.costIsAllowance, false);
      } else {
        assert.equal(choice.costPerMinute, .02, choice.id);
        assert.equal(choice.costIsAllowance, true);
        assert.equal(choice.publicRateLabel, "");
        assert.match(choice.costSource, /unverified/);
      }
    }
  }
  assert.equal(
    realtimeStt.find((item) => item.id === "mai-transcribe-2-streaming").publicRateLabel,
    "$17 / 1M Voice Live speech-input tokens",
  );
  assert.equal(
    realtimeStt.find((item) => item.id === "mai-transcribe-2").costPerMinute,
    0.0102,
  );

  const realtimeVoices = pipelineComponentOptions("voice", {
    model: "gpt-realtime",
    voice: "alloy",
    stt: "whisper-1",
  });
  const alloy = realtimeVoices.find((item) => item.id === "alloy");
  assert.equal(alloy.latencyMs, null);
  assert.equal(alloy.latencyIncludedInModel, true);
  assert.equal(
    realtimeVoices.find((item) => item.id === "en-US-Ava:DragonHDLatestNeural").latencyMs,
    307,
  );
  const realtime = estimatePipeline({
    model: "gpt-realtime",
    stt: "whisper-1",
    voice: "alloy",
  }).pipeline;
  assert.equal(realtime.stt.costPerMinute, 0.02);
  assert.equal(realtime.stt.noAdditionalCost, undefined);
  assert.ok(Math.abs(realtime.model.costPerMinute - .032) < 1e-12);
  assert.equal(
    realtime.model.publicRateLabel,
    "$32 audio input + $4 text input + $16 text output / 1M tokens",
  );
  assert.equal(realtime.voice.costPerMinute, 0.0768);
  assert.equal(
    realtime.voice.publicRateLabel,
    "$64 / 1M native audio-output tokens",
  );
  assert.ok(Math.abs(pipelineTotals(realtime).costPerMinute - .1288) < 1e-12);

  const noTranscript = estimatePipeline({
    model: "gpt-realtime",
    stt: "native-realtime-audio",
    voice: "alloy",
  }).pipeline;
  assert.equal(noTranscript.stt.costPerMinute, 0);
  assert.equal(noTranscript.stt.noAdditionalCost, true);
  assert.ok(Math.abs(pipelineTotals(noTranscript).costPerMinute - .1088) < 1e-12);
});

test("does not assign publicly unverified models bargain rates based on their names", () => {
  const standard = estimatePipeline({
    model: "gpt-5.6-luna",
    stt: "azure-speech",
    voice: "en-US-Ava:DragonHDLatestNeural",
  }).pipeline;
  assert.deepEqual(
    [standard.stt.costPerMinute, standard.model.costPerMinute, standard.voice.costPerMinute],
    [0.009, 0.4752 / 150, 0.0312],
  );
  assert.ok(Math.abs(pipelineTotals(standard).costPerMinute - .043368) < 1e-12);

  const lite = estimatePipeline({
    model: "gpt-6-luna",
    stt: "azure-speech",
    voice: "en-US-Ava:DragonHDLatestNeural",
  }).pipeline;
  assert.deepEqual(
    [lite.stt.costPerMinute, lite.model.costPerMinute, lite.voice.costPerMinute],
    [0.0102, 4.44 / 150, 0.0372],
  );
  for (const component of [lite.stt, lite.model, lite.voice]) {
    assert.equal(component.publicRateLabel, "");
    assert.equal(component.costIsAllowance, true);
  }
  assert.ok(Math.abs(pipelineTotals(lite).costPerMinute - .077) < 1e-12);
  assert.ok(Math.abs(
    pipelineTotals(lite).costPerMinute
      - (lite.stt.costPerMinute + lite.model.costPerMinute + lite.voice.costPerMinute),
  ) < 1e-12);
});

test("prices every compatible catalog combination without omitting or double-counting components", () => {
  assert.equal(PIPELINE_COMPONENTS.model.length, 14);
  assert.equal(PIPELINE_COMPONENTS.stt.length, 12);
  assert.equal(PIPELINE_COMPONENTS.voice.length, 46);
  let checked = 0;
  for (const model of PIPELINE_COMPONENTS.model) {
    for (const voice of pipelineComponentOptions("voice", { model: model.id }).filter((item) => item.compatible)) {
      for (const stt of pipelineComponentOptions("stt", { model: model.id, voice: voice.id }).filter((item) => item.compatible)) {
        const pipeline = estimatePipeline({ model: model.id, voice: voice.id, stt: stt.id }).pipeline;
        const components = [pipeline.stt, pipeline.model, pipeline.voice];
        assert.ok(components.every((component) => Number.isFinite(component.costPerMinute)));
        assert.ok(pipeline.model.costPerMinute > 0);
        assert.ok(pipeline.voice.costPerMinute > 0);
        if (stt.id !== "native-realtime-audio") assert.ok(pipeline.stt.costPerMinute > 0);
        assert.ok(Math.abs(
          pipelineTotals(pipeline).costPerMinute
            - components.reduce((total, component) => total + component.costPerMinute, 0),
        ) < 1e-12);
        checked += 1;
      }
    }
  }
  assert.ok(checked > 1_000);
});

test("does not price configured Custom Speech recognition at the lower Standard Speech rate", () => {
  for (const [model, expected] of [
    ["gpt-5.4", .024],
    ["gpt-5.6-luna", .0234],
    ["gpt-6-luna", .024],
  ]) {
    const selection = {
      model, stt: "azure-speech", voice: "en-US-Ava:DragonHDLatestNeural", customSpeech: true,
    };
    const pipeline = estimatePipeline(selection).pipeline;
    assert.equal(pipeline.stt.costPerMinute, expected);
    assert.match(pipeline.stt.costSource, /Custom Speech|Conservative/);
    const row = pipelineComponentOptions("stt", selection).find((item) => item.id === "azure-speech");
    assert.equal(row.costPerMinute, expected);
    assert.equal(row.costSource, pipeline.stt.costSource);
  }
});

test("uses the declared voice family for standard, custom and personal output costs", () => {
  const selection = { model: "gpt-realtime", stt: "native-realtime-audio" };
  for (const [voice, voiceType, amount, allowance] of [
    ["en-US-AvaNeural", "azure-standard", .0372, false],
    ["customer-voice", "azure-custom", .066, false],
    ["customer-voice", "azure-personal", .066, true],
    ["en-US-Ava:DragonHDLatestNeural", "azure-custom", .066, false],
  ]) {
    const pipeline = estimatePipeline({ ...selection, voice, voiceType }).pipeline;
    assert.equal(pipeline.voice.type, voiceType);
    assert.equal(pipeline.voice.costPerMinute, amount);
    assert.equal(pipeline.voice.costIsAllowance, allowance);
    assert.ok(pipelineTotals(pipeline));
  }
  assert.equal(
    estimatePipeline({ ...selection, voice: "en-US-AvaNeural" }).pipeline.voice.costPerMinute,
    .0372,
  );
  assert.equal(
    pipelineTotals(estimatePipeline({ ...selection, voice: "unknown-voice" }).pipeline),
    null,
  );
});

test("does not report a partial or nonfinite pipeline cost as a valid total", () => {
  for (const costPerMinute of [null, undefined, NaN, Infinity, -1]) {
    assert.equal(pipelineTotals({
      stt: { costPerMinute: .01 },
      model: { costPerMinute },
      voice: { costPerMinute: .03 },
    }), null);
  }
});

test("labels providers and sorts table metrics by the minimum estimate", () => {
  const models = pipelineComponentOptions("model");
  assert.equal(
    pipelineComponentProvider(
      "voice",
      pipelineComponentOptions("voice", {
        model: "gpt-realtime",
        voice: "alloy",
        stt: "whisper-1",
      }).find((item) => item.id === "en-US-Ava:DragonHDLatestNeural"),
    ),
    "Azure Speech",
  );
  assert.equal(
    pipelineComponentProvider(
      "voice",
      pipelineComponentOptions("voice", {
        model: "gpt-realtime",
        voice: "alloy",
        stt: "whisper-1",
      }).find((item) => item.id === "alloy"),
    ),
    "GPT native",
  );
  const realtime = models.find((item) => item.id === "gpt-realtime");
  assert.equal(pipelineMetricMinimum(realtime, "latency"), realtime.latencyMinMs);
  assert.deepEqual(
    sortPipelineComponents("model", models, { key: "latency", direction: "asc" })
      .slice(0, 3)
      .map((item) => item.id),
    ["gpt-realtime-mini", "azure-realtime", "gpt-realtime-1.5"],
  );
  assert.equal(
    sortPipelineComponents("model", models, { key: "cost", direction: "desc" })[0]
      .costPerMinute,
    Math.max(...models.map((item) => item.costPerMinute)),
  );
});

test("limits Agent-level STT to the intersection of every graph model", () => {
  const transcribers = pipelineComponentOptions("stt", {
    model: "gpt-realtime-2.1",
    models: ["gpt-realtime-2.1", "gpt-5.6-luna"],
    voice: "alloy",
    stt: "whisper-1",
  });
  assert.deepEqual(
    transcribers.filter((item) => item.compatible).map((item) => item.id),
    ["azure-speech", "mai-transcribe", "mai-transcribe-2", "mai-transcribe-2-streaming"],
  );
  assert.match(
    transcribers.find((item) => item.id === "whisper-1").incompatibility,
    /GPT-5\.6 Luna/,
  );
});

test("reports imported model, STT, and voice combinations that capabilities reject", () => {
  const definition = createSampleDefinition();
  definition.handoff.nodes[0].config.model = "gpt-5.6-luna";
  definition.handoff.nodes[0].config.voice = "alloy";
  const problems = validateDefinition(definition);
  assert.ok(problems.some((item) => (
    item.code === "incompatible_transcription_model" && item.objectId === "support"
  )));
  assert.ok(problems.some((item) => (
    item.code === "incompatible_voice" && item.objectId === "support"
  )));
});

test("matches Agent names by case-insensitive partial terms", () => {
  assert.equal(matchesAgentSearch("frontdesk-fluency-v12-baseline", "FLU v12"), true);
  assert.equal(matchesAgentSearch("frontdesk-fluency-v12-baseline", "front base"), true);
  assert.equal(matchesAgentSearch("frontdesk-fluency-v12-baseline", "finance"), false);
  assert.equal(matchesAgentSearch("frontdesk-fluency-v12-baseline", "  "), true);
});

test("anchors reverse edges to the selected left or right node sides", () => {
  const from = { x: 300, y: 500, width: 320, height: 160 };
  const to = { x: 100, y: 100, width: 320, height: 160 };

  assert.deepEqual(sideEdgeAnchors(from, to, -80), {
    side: "left",
    sourceX: 300,
    sourceY: 580,
    targetX: 100,
    targetY: 180,
  });
  assert.deepEqual(sideEdgeAnchors(from, to, 900), {
    side: "right",
    sourceX: 620,
    sourceY: 580,
    targetX: 420,
    targetY: 180,
  });
});

test("classifies prominent node pipeline brands", () => {
  assert.equal(pipelineBrand("stt", "mai-transcribe-2"), "mai");
  assert.equal(pipelineBrand("stt", "whisper-1"), "whisper");
  assert.equal(pipelineBrand("stt", "azure-speech"), "azure");
  assert.equal(pipelineBrand("model", "gpt-realtime-2.1"), "gpt");
  assert.equal(pipelineBrand("voice", "en-US-Ava:DragonHDLatestNeural"), "azure");
});

test("draws every edge as a smooth curve between the exact handle centers", () => {
  const adjacent = smoothVerticalEdgePath(140, 246, 326, 445);
  const jump = smoothOuterEdgePath(140, 246, 326, 1145, 620);
  const feedback = smoothOuterEdgePath(326, 1145, 140, 246, -120);

  assert.equal(adjacent, "M140,246 C140,345.5 326,345.5 326,445");
  assert.doesNotMatch(adjacent, /\bL\b/);
  assert.equal(jump, "M140,246 C620,246 620,1145 326,1145");
  assert.doesNotMatch(jump, /\bL\b/);
  assert.equal(feedback, "M326,1145 C-120,1145 -120,246 140,246");
  assert.doesNotMatch(feedback, /\bL\b/);
});

test("lays out the handoff graph from top to bottom with readable layer gaps", () => {
  const positions = layoutHandoffGraph(
    [ENTRYPOINT_ID, "identify", "billing", "support", "done"],
    [
      { id: "start", source: ENTRYPOINT_ID, target: "identify" },
      { id: "identify_billing", source: "identify", target: "billing" },
      { id: "identify_support", source: "identify", target: "support" },
      { id: "billing_done", source: "billing", target: "done" },
      { id: "support_done", source: "support", target: "done" },
    ],
  );

  assert.ok(positions.get(ENTRYPOINT_ID).y < positions.get("identify").y);
  assert.equal(positions.get("billing").y, positions.get("support").y);
  assert.ok(Math.abs(positions.get("billing").x - positions.get("support").x) >= 372);
  assert.ok(positions.get("billing").y < positions.get("done").y);
  assert.equal(positions.get(ENTRYPOINT_ID).x, positions.get("identify").x);
});

test("keeps cycles finite and places disconnected nodes after the reachable graph", () => {
  const positions = layoutHandoffGraph(
    [ENTRYPOINT_ID, "one", "two", "orphan"],
    [
      { id: "start", source: ENTRYPOINT_ID, target: "one" },
      { id: "forward", source: "one", target: "two" },
      { id: "back", source: "two", target: "one" },
    ],
  );

  assert.ok(positions.get(ENTRYPOINT_ID).y < positions.get("one").y);
  assert.ok(positions.get("one").y < positions.get("two").y);
  assert.ok(positions.get("two").y < positions.get("orphan").y);
  for (const position of positions.values()) {
    assert.ok(Number.isFinite(position.x));
    assert.ok(Number.isFinite(position.y));
  }
});

test("keeps unknown root fields while adding an editable handoff graph", () => {
  const source = {
    kind: "voice",
    instructions: "Root",
    future_capability: { enabled: true, settings: ["one", "two"] },
  };

  const editable = ensureEditableDefinition(source);
  editable.handoff.nodes.push({
    id: "specialist",
    description: "Handle specialist requests.",
    config: { instructions: "Help.", tools: [], tool_choice: "auto" },
  });
  editable.handoff.edges.push({
    id: "start_to_specialist",
    source: ENTRYPOINT_ID,
    target: "specialist",
    description: "Use for specialist requests.",
  });

  assert.deepEqual(editable.future_capability, source.future_capability);
  assert.equal(source.handoff, undefined);
  assert.equal(validateDefinition(editable).filter((item) => item.severity === "error").length, 0);
});

test("JSON and YAML serializers are deterministic over one canonical state", () => {
  const definition = createSampleDefinition();
  const firstJson = stableJson(definition);
  const firstYaml = deterministicYaml(definition);

  assert.equal(stableJson(definition), firstJson);
  assert.equal(deterministicYaml(definition), firstYaml);
  assert.match(firstYaml, /^audio:/);
  assert.match(firstYaml, /handoff:/);
  assert.ok(firstYaml.includes('source: "$entrypoint"'));
});

test("validation returns field and object scoped blocking problems", () => {
  const definition = createSampleDefinition();
  definition.handoff.max_attempts = 1;
  definition.handoff.edges[0].target = "missing";
  definition.handoff.nodes.push({
    id: "orphan",
    description: "",
    config: { instructions: "", tools: {} },
  });

  const problems = validateDefinition(definition);

  assert.ok(problems.some((item) => item.field === "max_attempts" && item.objectKind === "graph"));
  assert.ok(problems.some((item) => item.objectId === "start_to_support" && item.field === "target"));
  assert.ok(problems.some((item) => item.objectId === "orphan" && item.code === "unreachable_node"));
  assert.ok(problems.some((item) => item.objectId === "orphan" && item.field === "tools"));
});

test("validates managed runtime and interim-response fields", () => {
  const definition = createSampleDefinition();
  definition.store = true;
  definition.output_modalities = ["text", "audio"];
  definition.greeting = {
    type: "llm_generated",
    prompt: "Say hello.",
    fallback_text: "Hello.",
  };
  definition.audio = {
    input: {
      format: { type: "audio/pcm", rate: 24000 },
      turn_detection: { type: "azure_semantic_vad", threshold: 0.5 },
    },
    output: {
      format: { type: "audio/pcm", rate: 24000 },
      voice: "en-US-AvaNeural",
      voice_type: "azure-standard",
    },
  };
  definition.handoff.nodes[0].config.interim_response = {
    type: "static_interim_response",
    triggers: ["tool"],
    texts: ["One moment."],
  };
  definition.handoff.nodes[1].config.interim_response = null;
  assert.equal(validateDefinition(definition).filter((item) => item.severity === "error").length, 0);

  definition.greeting.prompt = "";
  definition.audio.input.format.rate = 0;
  definition.audio.input.turn_detection.threshold = 1.2;
  definition.handoff.nodes[0].config.interim_response.texts = [];
  const codes = new Set(validateDefinition(definition).map((item) => item.code));
  assert.ok(codes.has("greeting_prompt"));
  assert.ok(codes.has("audio_rate"));
  assert.ok(codes.has("turn_threshold"));
  assert.ok(codes.has("interim_response_texts"));
});

test("model indicators identify catalog estimates and unknown values honestly", () => {
  assert.deepEqual(modelEstimate("gpt-realtime-mini"), {
    latency: "Low",
    cost: "Low",
    source: "Estimated from Voice Live guidance and public retail tier",
    available: true,
  });
  assert.deepEqual(modelEstimate("custom-deployment"), {
    latency: "Not available",
    cost: "Not available",
    source: "No estimate for custom or unknown values",
    available: false,
  });
});

test("draft publication adds the required preview feature without duplicates", () => {
  assert.equal(
    publicationFeatures("VoiceAgents=V1Preview", false),
    "VoiceAgents=V1Preview",
  );
  assert.equal(
    publicationFeatures("VoiceAgents=V1Preview", true),
    "VoiceAgents=V1Preview,DraftAgents=V1Preview",
  );
  assert.equal(
    publicationFeatures(
      "VoiceAgents=V1Preview,DraftAgents=V1Preview",
      true,
    ),
    "VoiceAgents=V1Preview,DraftAgents=V1Preview",
  );
});

test("extracts latest complete definition and maps service validation details", () => {
  const definition = createSampleDefinition();
  definition.unknown_root = "preserved";
  const agent = extractLatestAgent({
    name: "handoff-agent",
    versions: {
      latest: {
        version: "12",
        draft: false,
        definition,
        metadata: { owner: "voice" },
      },
    },
  });

  assert.equal(agent.version, "12");
  assert.equal(agent.definition.unknown_root, "preserved");
  const problems = mergeServiceProblems([], {
    error: {
      details: [{
        code: "handoff_unknown_node",
        object_kind: "edge",
        object_id: "edge-a",
        field: "target",
        message: "Target does not exist.",
      }],
    },
  });
  assert.deepEqual(problems[0], {
    severity: "error",
    message: "Target does not exist.",
    objectKind: "edge",
    objectId: "edge-a",
    field: "target",
    code: "handoff_unknown_node",
    server: true,
  });
});
