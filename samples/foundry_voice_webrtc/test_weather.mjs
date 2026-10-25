import test from 'node:test';
import assert from 'node:assert/strict';
import { parseWeather, weatherLabel } from './public/weather.mjs';

const current = {
  temperature_2m: 12, is_day: 1, precipitation: 0,
  weather_code: 0, cloud_cover: 5, wind_speed_10m: 18,
  wind_direction_10m: 240, time: '2026-10-25T09:15',
};

test('Seattle weather uses explicit units and local timestamp', () => {
  const weather = parseWeather({ current });
  assert.equal(weather.cloud, 0.05);
  assert.equal(weather.day, true);
  assert.match(weatherLabel(weather), /Seattle: Sunny, 12 C, wind 18 km\/h.*09:15 Seattle time/);
});

test('rain, snow, fog, cloud cover, and night select appropriate conditions', () => {
  for (const [overrides, label] of [
    [{ precipitation: 1.2, weather_code: 61 }, 'Rain'],
    [{ precipitation: 0.5, weather_code: 73 }, 'Snow'],
    [{ weather_code: 45 }, 'Fog'],
    [{ cloud_cover: 90 }, 'Cloudy'],
    [{ cloud_cover: 40 }, 'Partly cloudy'],
    [{ is_day: 0 }, 'Clear'],
  ]) {
    assert.match(weatherLabel(parseWeather({ current: { ...current, ...overrides } })), new RegExp(`Seattle: ${label}`));
  }
});

test('missing or invalid weather cannot silently become sunny scenery', () => {
  assert.throws(() => parseWeather({}), /missing/);
  for (const key of Object.keys(current).filter(key => key !== 'time')) {
    assert.throws(() => parseWeather({ current: { ...current, [key]: null } }), /missing/);
  }
  for (const overrides of [
    { precipitation: -1 }, { wind_speed_10m: -1 },
    { cloud_cover: 101 }, { is_day: 2 }, { time: '' },
  ]) {
    assert.throws(() => parseWeather({ current: { ...current, ...overrides } }));
  }
});
