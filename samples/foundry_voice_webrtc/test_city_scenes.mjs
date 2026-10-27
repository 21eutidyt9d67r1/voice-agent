import test from 'node:test';
import assert from 'node:assert/strict';
import { CITIES, getCity, weatherUrl, drawCityScene } from './public/city-scenes.mjs';
import { CityWeather, parseWeather, solarLighting, solarPosition, treeSway, weatherLabel } from './public/weather.mjs';
import { cityNature } from './public/city-nature.mjs';

const current = {
  temperature_2m: 23, is_day: 1, precipitation: 0,
  weather_code: 0, cloud_cover: 10, wind_speed_10m: 12,
  wind_direction_10m: 220, time: '2026-10-27T12:15',
};
const result = (overrides = {}) => ({ ok: true, json: async () => ({ current: { ...current, ...overrides } }) });
const deferred = () => {
  let resolve;
  const promise = new Promise(complete => { resolve = complete; });
  return { promise, resolve };
};

test('all requested cities have fixed coordinates, IANA timezones and recognizable landmarks', () => {
  assert.deepEqual(CITIES.map(city => city.id), ['seattle', 'mumbai', 'tokyo', 'paris', 'beijing', 'new-york']);
  const landmarks = ['Space Needle', 'Gateway of India', 'Tokyo Tower', 'Eiffel Tower', 'Temple of Heaven', 'Brooklyn Bridge'];
  for (const [index, city] of CITIES.entries()) {
    assert.ok(Object.isFrozen(city));
    assert.ok(Math.abs(city.latitude) <= 90 && Math.abs(city.longitude) <= 180);
    assert.doesNotThrow(() => new Intl.DateTimeFormat('en', { timeZone: city.timezone }).format(new Date()));
    assert.ok(city.landmark.includes(landmarks[index]));
    assert.equal(getCity(city.id), city);
  }
  assert.throws(() => getCity('shanghai'), /Unknown scenery city/);
});

test('weather requests use the selected city and explicit measurement units', () => {
  for (const city of CITIES) {
    const url = new URL(weatherUrl(city));
    assert.equal(url.origin, 'https://api.open-meteo.com');
    assert.equal(Number(url.searchParams.get('latitude')), city.latitude);
    assert.equal(Number(url.searchParams.get('longitude')), city.longitude);
    assert.equal(url.searchParams.get('timezone'), city.timezone);
    assert.equal(url.searchParams.get('wind_speed_unit'), 'kmh');
    assert.equal(url.searchParams.get('temperature_unit'), 'celsius');
    assert.equal(url.searchParams.get('precipitation_unit'), 'mm');
    assert.match(weatherLabel(parseWeather({ current }), city), new RegExp(`^${city.name}:.*12:15 ${city.name} time$`));
  }
});

test('solar lighting uses each city rather than Seattle or the browser timezone', () => {
  for (const city of CITIES) {
    const localNoon = new Date(Date.UTC(2026, 5, 21, 12) - city.longitude * 4 * 60000);
    const noon = solarLighting(localNoon, { cloud: 0, wet: 0 }, city);
    const midnight = solarLighting(new Date(localNoon.getTime() + 12 * 3600000), { cloud: 0, wet: 0 }, city);
    assert.ok(noon.altitude > 50, city.name);
    assert.equal(noon.daylight, 1, city.name);
    assert.equal(midnight.sunVisibility, 0, city.name);
    const overcast = solarLighting(localNoon, { cloud: 1, wet: 4 }, city);
    assert.ok(overcast.brightness < noon.brightness);
    assert.equal(overcast.sunVisibility, 0);
  }
  const now = new Date('2026-10-27T03:00:00Z');
  assert.ok(solarPosition(now, getCity('tokyo')).altitude > 20);
  assert.ok(solarPosition(now, getCity('new-york')).altitude < 0);
  assert.throws(() => solarPosition(now, { latitude: NaN, longitude: 0 }), /coordinates/);
});

test('switching cities aborts the old request and never applies a late response from it', async () => {
  const mumbai = deferred(), tokyo = deferred(), requests = [], states = [];
  const source = new CityWeather(state => states.push(state), (url, options) => {
    requests.push({ url, ...options });
    return requests.length === 1 ? mumbai.promise : tokyo.promise;
  });
  const first = source.select('mumbai');
  const second = source.select('tokyo');
  assert.ok(requests[0].signal.aborted);
  tokyo.resolve(result({ temperature_2m: 18 }));
  await second;
  const stateCount = states.length;
  mumbai.resolve(result({ temperature_2m: 35 }));
  await first;
  assert.equal(states.length, stateCount);
  assert.equal(states.at(-1).city.id, 'tokyo');
  assert.equal(states.at(-1).weather.temperature, 18);
  assert.equal(source.weather.temperature, 18);
});

test('default fetch keeps the browser global receiver instead of binding to CityWeather', async t => {
  const states = [];
  t.mock.method(globalThis, 'fetch', function () {
    assert.equal(this, globalThis);
    return Promise.resolve(result());
  });
  const source = new CityWeather(state => states.push(state));
  await source.select('mumbai');
  assert.equal(states.at(-1).error, null);
  assert.equal(states.at(-1).weather.temperature, 23);
});

test('only a same-city refresh can keep previously observed weather after an error', async () => {
  const states = [];
  let response = result();
  const source = new CityWeather(state => states.push(state), async () => response);
  await source.select('mumbai');
  const previous = source.weather;
  response = { ok: false, status: 503 };
  await source.refresh();
  assert.equal(states.at(-1).weather, previous);
  assert.match(states.at(-1).error.message, /503/);
  await source.select('beijing');
  assert.equal(states.at(-1).city.id, 'beijing');
  assert.equal(states.at(-1).weather, null);
  assert.match(states.at(-1).error.message, /503/);
});

test('malformed weather, cancellation and timeout do not fabricate sunny conditions', async t => {
  const states = [];
  const source = new CityWeather(state => states.push(state), async () => ({ ok: true, json: async () => ({}) }));
  await source.select('paris');
  assert.equal(states.at(-1).weather, null);
  assert.match(states.at(-1).error.message, /missing/);

  const pending = deferred();
  source.fetcher = () => pending.promise;
  const load = source.select('new-york');
  source.cancel();
  const count = states.length;
  pending.resolve(result());
  await load;
  assert.equal(states.length, count);

  t.mock.timers.enable({ apis: ['setTimeout'] });
  source.fetcher = (_url, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(new Error('Weather request timed out')), { once: true });
  });
  const timed = source.refresh();
  t.mock.timers.tick(10001);
  await timed;
  assert.match(states.at(-1).error.message, /timed out/);
  assert.equal(states.at(-1).loading, false);
  t.mock.timers.reset();
});

function canvasRecorder() {
  const calls = [];
  let depth = 0;
  const target = {
    save() { depth++; },
    restore() { assert.ok(depth > 0, 'unbalanced canvas restore'); depth--; },
    createLinearGradient: () => ({ addColorStop() {} }),
    createRadialGradient: () => ({ addColorStop() {} }),
  };
  const context = new Proxy(target, {
    get(object, property) {
      if (property in object) return object[property];
      return (...args) => {
        assert.ok(args.filter(value => typeof value === 'number').every(Number.isFinite), `${String(property)} uses invalid coordinates`);
        if (property === 'ellipse') assert.ok(args[2] >= 0 && args[3] >= 0);
        calls.push([property, ...args]);
      };
    },
  });
  return { context, calls, balanced: () => assert.equal(depth, 0) };
}

test('every city renders finite, balanced geometry on mobile and desktop in all weather states', () => {
  const conditions = [
    {}, { cloud_cover: 100 }, { precipitation: 5, weather_code: 63 },
    { precipitation: 1, weather_code: 73 }, { weather_code: 45 },
    { wind_speed_10m: 60 },
  ];
  for (const city of CITIES.filter(value => value.id !== 'seattle')) {
    for (const [width, height] of [[320, 568], [390, 844], [1440, 900]]) {
      for (const changes of conditions) {
        for (const hour of [0, 12]) {
          const weather = parseWeather({ current: { ...current, ...changes } });
          const date = new Date(Date.UTC(2026, 5, 21, hour) - city.longitude * 4 * 60000);
          const light = solarLighting(date, weather, city);
          const { context, calls, balanced } = canvasRecorder();
          drawCityScene(context, {
            city, width, height, weather, light, time: 12, nature: cityNature(city, date),
            sway: phase => treeSway(weather, 12, phase),
          });
          balanced();
          assert.ok(calls.length > 200, `${city.name} should draw detailed architecture`);
        }
      }
    }
  }
});

test('wind and animation time change scene geometry, while identical inputs are stable', () => {
  for (const id of ['mumbai', 'tokyo', 'paris', 'beijing', 'new-york']) {
    const city = getCity(id);
    const draw = (wind, time) => {
      const { context, calls } = canvasRecorder();
      const weather = parseWeather({ current: { ...current, wind_speed_10m: wind } });
      const date = new Date('2026-10-27T12:00:00Z');
      drawCityScene(context, {
        city, width: 1200, height: 800, weather, time, nature: cityNature(city, date),
        light: solarLighting(date, weather, city),
        sway: phase => treeSway(weather, time, phase),
      });
      return calls;
    };
    assert.deepEqual(draw(12, 1), draw(12, 1), `${id}: no randomized frame jitter`);
    assert.notDeepEqual(draw(0, 1), draw(50, 1), `${id}: wind affects vegetation/water`);
    assert.notDeepEqual(draw(12, 1), draw(12, 2), `${id}: animation affects the scene`);
  }
});
