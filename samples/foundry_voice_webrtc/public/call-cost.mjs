export function returnedCallCost(cost, seconds) {
  if (!cost) {
    return { available: false, reason: 'The Agent API did not return a finalized session cost. This is not a zero-cost call.' };
  }
  if (!['complete', 'partial', 'unavailable'].includes(cost.status) || cost.currency !== 'USD') {
    return { available: false, reason: 'The Agent API returned an unsupported cost format.' };
  }
  if (cost.status === 'unavailable' || cost.amount === null) {
    return { available: false, reason: 'Session cost is unavailable from the Agent API.' };
  }
  if (typeof cost.amount !== 'number' || !Number.isFinite(cost.amount) || cost.amount < 0) {
    return { available: false, reason: 'The Agent API returned an invalid session cost.' };
  }
  const perMinute = Number.isFinite(seconds) && seconds > 0 ? cost.amount / (seconds / 60) : null;
  return {
    available: true, total: cost.amount, status: cost.status,
    perMinute: Number.isFinite(perMinute) ? perMinute : null,
    priceVersion: typeof cost.price_version === 'string' ? cost.price_version : 'Not supplied',
    unpriced: Array.isArray(cost.unpriced_components) ? cost.unpriced_components.filter(value => typeof value === 'string') : [],
  };
}
