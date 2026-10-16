import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source = await readFile(new URL('./public/app.js', import.meta.url), 'utf8');

async function setup(transport, overrides = {}) {
  const elements = new Map();
  const makeElement = () => ({
    value: '', disabled: true, hidden: true, textContent: '', children: [],
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    remove() {}, setAttribute() {}, pause() {},
  });
  const element = id => {
    if (!elements.has(id)) elements.set(id, makeElement());
    return elements.get(id);
  };
  const sent = [];
  const session = {
    transport, ready: false, ws: { readyState: 1, send: frame => sent.push(JSON.parse(frame)), close() {} },
    abort: new AbortController(),
  };
  const context = {
    document: { getElementById: element, createElement: makeElement },
    window: { addEventListener() {} }, WebSocket: { OPEN: 1 },
    crypto: webcrypto,
    fetch: async () => ({ ok: true, json: async () => ({ configured: true }) }),
    clearTimeout() {}, clearInterval() {}, setInterval: () => 1,
    validateAudioSession() {},
    session,
    ...overrides,
  };
  // Run the actual UI code with a minimal DOM, without browser audio imports.
  await vm.runInNewContext(`(async () => {
    ${source.replace(/^import .*;\r?\n/, '')}
    call = session;
    return {markReady, handleEvent, updateTextInput, stop, connectWebRtc};
  })()`, context).then(api => context.api = api);
  return { ...context.api, element, session, sent };
}

for (const transport of ['websocket', 'webrtc']) {
  test(`${transport}: sends text and a response request over the bridge socket`, async () => {
    const ui = await setup(transport);
    ui.element('text-input').value = '  Hello <world>  ';
    ui.updateTextInput();
    assert.equal(ui.element('send-text').disabled, true);
    ui.markReady(ui.session);
    assert.equal(ui.element('text-input').disabled, false);
    assert.equal(ui.element('send-text').disabled, false);
    let prevented = false;
    ui.element('text-form').onsubmit({ preventDefault() { prevented = true; } });
    assert.equal(prevented, true);
    const id = ui.sent[0].item.id;
    assert.equal(id.length, 32);
    assert.match(id, /^[a-f0-9]{32}$/);
    assert.deepEqual(ui.sent, [
      { type: 'conversation.item.create', item: {
        id, type: 'message', role: 'user',
        content: [{ type: 'input_text', text: 'Hello <world>' }],
      } },
      { type: 'response.create', response: { output_modalities: ['text'] } },
    ]);
    assert.equal(ui.element('text-input').value, '');
    assert.equal(ui.element('transcript').children[0].children[1].textContent, 'Hello <world>');
    ui.element('text-input').value = 'Next';
    ui.element('text-input').oninput();
    assert.equal(ui.element('send-text').disabled, true);
    ui.element('text-form').onsubmit({ preventDefault() {} });
    assert.equal(ui.sent.length, 2);
    await ui.handleEvent(ui.session, { type: 'response.created', response: { id: 'reply' } });
    await ui.handleEvent(ui.session, { type: 'response.output_text.delta', item_id: 'answer', delta: 'Hello back' });
    await ui.handleEvent(ui.session, { type: 'response.output_text.done', item_id: 'answer', text: 'Hello back' });
    assert.equal(ui.element('transcript').children[1].children[1].textContent, 'Hello back');
    await ui.handleEvent(ui.session, { type: 'response.done', response: { status: 'completed' } });
    assert.equal(ui.element('send-text').disabled, false);
    ui.stop();
    assert.equal(ui.element('text-input').disabled, true);
    assert.equal(ui.element('send-text').disabled, true);
  });

  test(`${transport}: rejects blank, oversized, speaking and disconnected submissions`, async () => {
    const ui = await setup(transport);
    ui.markReady(ui.session);
    for (const text of [' ', 'x'.repeat(4001)]) {
      ui.element('text-input').value = text;
      ui.element('text-form').onsubmit({ preventDefault() {} });
    }
    assert.equal(ui.sent.length, 0);
    assert.equal(ui.element('error').hidden, false);
    ui.element('text-input').value = 'Hello';
    await ui.handleEvent(ui.session, { type: 'input_audio_buffer.speech_started' });
    assert.equal(ui.element('send-text').disabled, true);
    ui.element('text-form').onsubmit({ preventDefault() {} });
    await ui.handleEvent(ui.session, { type: 'input_audio_buffer.speech_stopped' });
    ui.session.ws.readyState = 3;
    ui.updateTextInput();
    assert.equal(ui.element('text-input').disabled, true);
    ui.element('text-form').onsubmit({ preventDefault() {} });
    assert.equal(ui.sent.length, 0);
  });

  test(`${transport}: failed responses surface errors and allow retry`, async () => {
    const ui = await setup(transport);
    ui.markReady(ui.session);
    ui.element('text-input').value = 'Hello';
    await ui.handleEvent(ui.session, { type: 'response.created', response: { id: 'reply' } });
    assert.equal(ui.element('send-text').disabled, true);
    await ui.handleEvent(ui.session, { type: 'response.done', response: { status: 'failed' } });
    assert.equal(ui.element('error').hidden, false);
    assert.equal(ui.element('send-text').disabled, false);
  });

  test(`${transport}: send failures preserve the draft and disable the composer`, async () => {
    const ui = await setup(transport);
    ui.markReady(ui.session);
    ui.element('text-input').value = 'Keep my draft';
    ui.session.ws.send = () => { throw new Error('Socket send failed'); };
    ui.element('text-form').onsubmit({ preventDefault() {} });
    assert.equal(ui.element('text-input').value, 'Keep my draft');
    assert.equal(ui.element('text-input').disabled, true);
    assert.equal(ui.element('error').textContent, 'Socket send failed');
    assert.equal(ui.element('transcript').children.length, 0);
  });
}

async function setupSignaling(overrides = {}) {
  class Socket {
    static OPEN = 1;
    constructor() { this.readyState = 0; this.sent = []; }
    send(frame) { this.sent.push(JSON.parse(frame)); }
    close() { this.readyState = 3; }
    open() { this.readyState = 1; this.onopen(); }
  }
  const ui = await setup('webrtc', {
    WebSocket: Socket, location: { protocol: 'https:', host: 'example.test' },
    setTimeout, clearTimeout, ...overrides,
  });
  const peer = new EventTarget();
  peer.iceGatheringState = 'gathering';
  peer.createOffer = async () => ({type:'offer', sdp:'v=0\r\n'});
  peer.setLocalDescription = async offer => { peer.localDescription = offer; };
  peer.complete = () => {
    peer.localDescription.sdp += 'a=candidate:complete\r\n';
    peer.iceGatheringState = 'complete';
    peer.dispatchEvent(new Event('icegatheringstatechange'));
  };
  peer.close = () => {};
  ui.session.peer = peer;
  return {...ui, peer};
}

test('WebRTC opens signaling before ICE completes and sends the complete offer once', async () => {
  const ui = await setupSignaling();
  const connecting = ui.connectWebRtc(ui.session);
  const ws = ui.session.ws;
  assert.ok(ws, 'Socket must open without waiting for ICE');
  ws.open();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ws.sent.length, 0, 'An incomplete SDP must not be sent');
  ui.peer.complete();
  await connecting;
  assert.deepEqual(ws.sent, [{type:'rtc.call.sdp.create', sdp_offer:ui.peer.localDescription.sdp}]);
  ws.onopen();
  assert.equal(ws.sent.length, 1);
  ui.stop();
});

test('WebRTC waits for socket opening when ICE completes first', async () => {
  const ui = await setupSignaling();
  const connecting = ui.connectWebRtc(ui.session);
  await new Promise(resolve => setImmediate(resolve));
  ui.peer.complete();
  await connecting;
  assert.equal(ui.session.ws.sent.length, 0);
  ui.session.ws.open();
  assert.equal(ui.session.ws.sent.length, 1);
  ui.stop();
});

test('WebRTC cancellation during ICE closes signaling without sending an offer', async () => {
  const ui = await setupSignaling();
  const connecting = ui.connectWebRtc(ui.session);
  ui.session.ws.open();
  await new Promise(resolve => setImmediate(resolve));
  ui.stop();
  await assert.rejects(connecting, /Session cancelled/);
  assert.equal(ui.session.ws.readyState, 3);
  assert.equal(ui.session.ws.sent.length, 0);
});

test('WebRTC reports an ICE timeout and does not send an incomplete offer', async () => {
  let timeout;
  const ui = await setupSignaling({setTimeout: callback => { timeout = callback; return 1; }, clearTimeout() {}});
  const connecting = ui.connectWebRtc(ui.session);
  ui.session.ws.open();
  await new Promise(resolve => setImmediate(resolve));
  timeout();
  await assert.rejects(connecting, /ICE gathering timed out/);
  assert.equal(ui.session.ws.sent.length, 0);
  ui.stop();
});
