import assert from 'node:assert/strict';
import test from 'node:test';
import { RetainedHistory } from './public/retained-history.mjs';

const item = (text, field = 'transcript', id = 'answer') =>
  ({id, type:'message', role:'assistant', content:[{type:field === 'text' ? 'text' : 'audio', [field]:text}]});
const cut = (text, end = 500, extra = {}) => ({
  type:'conversation.item.truncated', item_id:'answer', content_index:0, audio_end_ms:end,
  ...(text === undefined ? {} : {item:item(text)}), ...extra,
});
const delta = (text, extra = {}) =>
  ({type:'response.audio_transcript.delta', item_id:'answer', response_id:'response1', delta:text, ...extra});
const retrieved = text => ({type:'conversation.item.retrieved', item:item(text)});

function setup() {
  const rendered = new Map(), requests = [], errors = [], timers = new Map();
  const history = new RetainedHistory({
    render:record => rendered.set(record, {text:record.text, status:record.status, role:record.role}),
    remove:record => rendered.delete(record),
    retrieve:(item_id, event_id) => requests.push({item_id, event_id}),
    error:message => errors.push(message),
    timers:{
      setTimeout:callback => { const id = timers.size + 1; timers.set(id, callback); return id; },
      clearTimeout:id => timers.delete(id),
    },
  });
  return {history, rendered, requests, errors, timers,
    current:() => rendered.get(history.items.get('answer')),
    texts:() => [...rendered.values()].map(record => record.text)};
}

test('normal multi-part text/transcript turns and user text are unchanged', () => {
  const ui = setup();
  ui.history.user('user1', 'Hello <world>');
  ui.history.handle(delta('One'));
  ui.history.handle(delta(' two'));
  ui.history.handle(delta('Three', {content_index:1}));
  assert.deepEqual(ui.texts(), ['Hello <world>', 'One two\nThree']);
  ui.history.handle({type:'response.output_item.done', item:item('Final text', 'text'), response_id:'response1'});
  assert.equal(ui.current().text, 'Final text');
  assert.equal(ui.current().status, 'complete');
});

for (const field of ['text', 'transcript']) {
  for (const retained of ['Heard prefix [Interrupted]', '']) {
    test(`${field}: authoritative ${retained ? 'partial' : 'empty'} cut survives every full-answer event`, () => {
      const ui = setup();
      ui.history.handle(delta('Heard prefix UNHEARD SUFFIX'));
      const record = ui.history.items.get('answer');
      ui.history.handle(cut(retained, 500, {item:item(retained, field)}));
      for (const type of ['audio_transcript', 'output_audio_transcript', 'text', 'output_text']) {
        for (const phase of ['delta', 'done']) {
          ui.history.handle({type:`response.${type}.${phase}`, item_id:'answer', response_id:'response1',
            delta:'UNHEARD', transcript:'UNHEARD', text:'UNHEARD'});
        }
      }
      for (const type of ['response.output_item.added', 'response.output_item.done', 'conversation.item.created',
                          'conversation.item.added', 'conversation.item.done'])
        ui.history.handle({type, item:item('FULL ANSWER'), response_id:'response1'});
      ui.history.handle({type:'response.done', response:{id:'response1', output:[item('FULL ANSWER')]}});
      assert.equal(ui.history.items.get('answer'), record);
      assert.deepEqual(ui.current(), {text:retained, status:'truncated', role:'assistant'});
      assert.equal(ui.rendered.size, 1);
      assert.equal(ui.requests.length, 0);
    });
  }
}

test('a full cut with zero content clears text and keeps its truncation lock', () => {
  const ui = setup();
  ui.history.handle(delta('Full response'));
  ui.history.handle(cut('', 0, {item:{...item(''), content:[]}}));
  ui.history.handle(delta('Late suffix'));
  assert.equal(ui.current().text, '');
  assert.equal(ui.current().status, 'truncated');
});

test('authoritative items include all text and transcript parts, not only content_index', () => {
  const ui = setup();
  ui.history.handle(cut('', 20, {content_index:1, item:{...item(''), content:[
    {type:'text', text:'First'}, {type:'audio', transcript:'Second [Interrupted]'},
  ]}}));
  assert.equal(ui.current().text, 'First\nSecond [Interrupted]');
});

test('repeated and delayed truncations never lengthen an earlier cut', () => {
  const ui = setup();
  ui.history.handle(cut('First second third', 900));
  ui.history.handle(cut('First second', 500));
  ui.history.handle(cut('Duplicate changed content', 500));
  ui.history.handle(cut('Old longer result', 900));
  assert.equal(ui.current().text, 'First second');
  ui.history.handle(cut('', 0));
  ui.history.handle(cut('Late', 500));
  assert.equal(ui.current().text, '');
});

test('missing item immediately hides full text and retrieves by item_id; empty retrieval is valid', () => {
  const ui = setup();
  ui.history.handle(delta('Heard UNHEARD'));
  ui.history.handle(cut(undefined));
  assert.deepEqual(ui.current(), {text:'', status:'pending', role:'assistant'});
  assert.equal(ui.requests[0].item_id, 'answer');
  assert.match(ui.requests[0].event_id, /^[a-f0-9]{32}$/);
  ui.history.handle(delta('UNHEARD'));
  ui.history.handle(retrieved(''));
  assert.deepEqual(ui.current(), {text:'', status:'truncated', role:'assistant'});
  assert.equal(ui.timers.size, 0);
});

test('overlapping missing-item cuts serialize retrieval and discard a stale snapshot', () => {
  const ui = setup();
  ui.history.handle(cut(undefined, 900));
  ui.history.handle(cut(undefined, 900));
  ui.history.handle(cut(undefined, 400));
  assert.equal(ui.requests.length, 1);
  ui.history.handle(retrieved('Snapshot from the first cut'));
  assert.equal(ui.current().text, '');
  assert.equal(ui.requests.length, 2);
  ui.history.handle(retrieved('Latest'));
  assert.equal(ui.current().text, 'Latest');
});

test('enriched truncation wins over a pending retrieval and subsequent full response', () => {
  const ui = setup();
  ui.history.handle(cut(undefined, 900));
  ui.history.handle(cut('Latest', 400));
  ui.history.handle(retrieved('Stale'));
  ui.history.handle({type:'response.done', response:{id:'response1', output:[item('Full')]}});
  assert.equal(ui.current().text, 'Latest');
  assert.equal(ui.requests.length, 1);
  assert.equal(ui.timers.size, 0);
  assert.equal(ui.history.handle({type:'error', error:{event_id:ui.requests[0].event_id, message:'Late retrieval failure'}}), true);
  assert.equal(ui.current().text, 'Latest');
});

test('retrieval service errors are explicit, leave no full answer and do not fail unrelated events', () => {
  const ui = setup();
  ui.history.handle(cut(undefined));
  assert.equal(ui.history.handle({type:'error', error:{event_id:'unrelated'}}), false);
  assert.equal(ui.history.handle({type:'error', error:{event_id:ui.requests[0].event_id, message:'Item not found'}}), true);
  assert.equal(ui.current().text, '');
  assert.equal(ui.current().status, 'unavailable');
  assert.match(ui.errors[0], /Item not found/);
  ui.history.handle(retrieved('Late'));
  ui.history.handle(delta('Late'));
  assert.equal(ui.current().text, '');
  assert.equal(ui.history.handle({type:'error', error:{message:'Session failed'}}), false);
});

test('timeout blocks ambiguous retries and cannot be overwritten by a delayed reply', () => {
  const ui = setup();
  ui.history.handle(cut(undefined, 900));
  [...ui.timers.values()][0]();
  assert.equal(ui.current().status, 'unavailable');
  ui.history.handle(cut(undefined, 400));
  assert.equal(ui.requests.length, 1);
  assert.equal(ui.current().status, 'unavailable');
  ui.history.handle(retrieved('Stale'));
  assert.equal(ui.current().text, '');
  assert.match(ui.errors[0], /timed out/);
  ui.history.handle(cut('Enriched recovery', 200));
  assert.equal(ui.current().text, 'Enriched recovery');
});

test('retrieval send failure and malformed authoritative items are explicit', () => {
  const ui = setup();
  ui.history.retrieve = () => { throw new Error('Socket failed'); };
  ui.history.handle(cut(undefined));
  assert.match(ui.errors[0], /Socket failed/);
  assert.equal(ui.current().status, 'unavailable');
  ui.history.handle(cut('ignored', 200, {item:item('Wrong', 'text', 'wrong_id')}));
  assert.equal(ui.current().text, '');
  assert.match(ui.errors[1], /wrong item ID/);
});

test('multi-item responses lock only the cut item and never keep a response-ID copy', () => {
  const ui = setup();
  ui.history.handle(delta('Draft without item ID', {item_id:undefined, output_index:0}));
  assert.equal(ui.rendered.size, 0);
  ui.history.handle(cut('Retained'));
  ui.history.handle({type:'response.output_item.added', response_id:'response1', output_index:0, item:item('Full')});
  ui.history.handle(delta('Other item', {item_id:'answer2', output_index:1}));
  ui.history.handle({type:'response.done', response:{id:'response1', output:[item('Full'), item('Other completed', 'text', 'answer2')]}});
  ui.history.handle(delta('No-ID late suffix', {item_id:undefined, output_index:0}));
  assert.deepEqual(ui.texts(), ['Retained', 'Other completed']);
});

test('clear preserves tombstones, suppresses later response items and allows new turns', () => {
  const ui = setup();
  ui.history.handle({type:'response.created', response:{id:'response1'}});
  ui.history.handle(delta('Full'));
  ui.history.handle(cut(undefined));
  ui.history.clear();
  ui.rendered.clear();
  ui.history.handle(retrieved('Retained'));
  ui.history.handle(delta('Late'));
  ui.history.handle({type:'response.done', response:{id:'response1', output:[item('Full'), item('Late second', 'text', 'answer2')]}});
  assert.equal(ui.rendered.size, 0);
  ui.history.handle(delta('New turn', {item_id:'answer3', response_id:'response2'}));
  assert.deepEqual(ui.texts(), ['New turn']);
});

test('ending a session resolves pending UI as unavailable and a fresh history has no old locks', () => {
  const ui = setup();
  ui.history.handle(cut(undefined));
  ui.history.dispose();
  assert.equal(ui.current().status, 'unavailable');
  assert.equal(ui.timers.size, 0);
  const fresh = setup();
  fresh.history.handle(delta('New session with reused ID'));
  assert.equal(fresh.current().text, 'New session with reused ID');
});

test('mapping a cleared response draft to a cut item removes any unresolved card', () => {
  const ui = setup();
  ui.history.handle(delta('Draft', {item_id:undefined}));
  ui.history.clear();
  ui.rendered.clear();
  ui.history.handle(cut('Retained'));
  ui.history.handle({type:'response.output_item.done', response_id:'response1', item:item('Full')});
  assert.equal(ui.rendered.size, 0);
});
