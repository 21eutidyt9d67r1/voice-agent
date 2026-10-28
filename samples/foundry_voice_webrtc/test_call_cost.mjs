import assert from 'node:assert/strict';
import test from 'node:test';
import { returnedCallCost } from './public/call-cost.mjs';

const cost = {amount:0.006344, currency:'USD', status:'complete', price_version:'test-catalog', unpriced_components:[]};

test('uses the returned session amount exactly and derives cost per minute', () => {
  const result = returnedCallCost(cost, 30);
  assert.equal(result.total, 0.006344);
  assert.equal(result.perMinute, 0.012688);
  assert.equal(result.status, 'complete');
  assert.equal(result.priceVersion, 'test-catalog');
  assert.equal(returnedCallCost(cost, 120).total, result.total);
  assert.equal(returnedCallCost({...cost, amount:0}, 60).total, 0);
});

test('partial cost preserves the known subtotal and unpriced component names', () => {
  const result = returnedCallCost({...cost, status:'partial', unpriced_components:['byom_model']}, 60);
  assert.equal(result.status, 'partial');
  assert.equal(result.total, cost.amount);
  assert.deepEqual(result.unpriced, ['byom_model']);
});

test('missing, unavailable and malformed costs never become a zero-cost success', () => {
  for (const value of [
    null, undefined, {}, {usage:{total_tokens:1000}},
    {...cost, status:'unavailable'}, {...cost, status:'unknown'}, {...cost, currency:'EUR'},
    ...[null, -1, NaN, Infinity, '0.05'].map(amount=>({...cost, amount})),
  ]) {
    assert.equal(returnedCallCost(value, 60).available, false);
  }
});

test('missing or zero duration still shows returned total without an invented per-minute rate', () => {
  for (const duration of [0, -1, NaN, Infinity, undefined, '60']) {
    const result = returnedCallCost(cost, duration);
    assert.equal(result.total, cost.amount);
    assert.equal(result.perMinute, null);
  }
});
