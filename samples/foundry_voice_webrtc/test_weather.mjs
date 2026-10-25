import test from 'node:test';
import assert from 'node:assert/strict';
import { parseWeather, weatherLabel, weatherMotion, treeSway, wildlifeMotion, solarPosition, solarLighting, gullPose, shorelineY } from './public/weather.mjs';

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

test('wind motion is continuous, directional, and still in calm weather', () => {
  const calm = weatherMotion({ wind: 0, direction: 270 }, 20);
  assert.equal(calm.drift, 0);
  for (const time of [0, 1, 10, 100]) {
    const west = weatherMotion({ wind: 18, direction: 270 }, time);
    const east = weatherMotion({ wind: 18, direction: 90 }, time);
    assert.ok(west.gust >= 0.74 && west.gust <= 1.26);
    assert.equal(west.drift, -east.drift);
    const next = weatherMotion({ wind: 18, direction: 270 }, time + 0.001);
    assert.ok(next.drift >= west.drift);
    assert.ok(next.drift - west.drift < 0.1);
  }
});

test('trees stay still in calm weather and flex more in stronger wind', () => {
  for (const time of [0, 1, 10, 100]) {
    assert.equal(treeSway({ wind: 0, direction: 270 }, time), 0);
    const gentle = treeSway({ wind: 5, direction: 270 }, time);
    const strong = treeSway({ wind: 30, direction: 270 }, time);
    assert.ok(Math.abs(strong) >= Math.abs(gentle));
    assert.ok(Math.abs(strong) <= 1.26);
  }
  const weather = { wind: 18, direction: 270 };
  assert.notEqual(treeSway(weather, 1), treeSway(weather, 2));
  assert.notEqual(treeSway(weather, 1, 0), treeSway(weather, 1, 2));
});

test('tree roots and wildlife stay on the shared shoreline across viewport sizes', () => {
  for (const [width, height] of [[320, 480], [390, 844], [1280, 800], [1920, 1080]]) {
    for (let i = 0; i < 70; i++) {
      const x = i * width / 69;
      const depth = 0.35 + (0.35 + ((i * 127) % 100) / 100) * 0.4;
      const root = shorelineY(height, x, depth);
      const ground = shorelineY(height, x);
      assert.ok(root > ground + height * 0.02);
      assert.ok(root < height);
      const feet = shorelineY(height, x, 0.9);
      assert.ok(feet > ground && feet < height);
    }
  }
});

test('wildlife walks, stops to graze, and resumes without teleporting', () => {
  assert.ok(wildlifeMotion(10).distance > wildlifeMotion(9).distance);
  assert.equal(wildlifeMotion(25).distance, wildlifeMotion(24).distance);
  assert.equal(wildlifeMotion(25).stride, 0);
  assert.equal(wildlifeMotion(25).grazing, 1);
  assert.equal(wildlifeMotion(10).grazing, 0);
  for (const boundary of [22, 32, 54, 64]) {
    const before = wildlifeMotion(boundary - 0.001);
    const after = wildlifeMotion(boundary + 0.001);
    assert.ok(after.distance >= before.distance);
    assert.ok(after.distance - before.distance < 0.02);
    assert.ok(Math.abs(after.grazing - before.grazing) < 0.01);
  }
  assert.notEqual(wildlifeMotion(10).distance, wildlifeMotion(10, 2).distance);
});

test('seagulls circle smoothly within the scene and alternate wingbeats with gliding', () => {
  for (let bird = 0; bird < 3; bird++) {
    for (let time = 0; time < 100; time++) {
      const pose = gullPose(time, bird);
      const next = gullPose(time + 0.01, bird);
      assert.ok(pose.x >= 0.15 && pose.x <= 0.85);
      assert.ok(pose.y >= 0.3 && pose.y <= 0.46);
      assert.ok(pose.scale >= 0.55 && pose.scale <= 1);
      assert.ok(Math.abs(next.x - pose.x) < 0.001);
      assert.ok(Math.abs(next.y - pose.y) < 0.001);
    }
  }
  assert.notEqual(gullPose(1).wing, gullPose(1.1).wing);
  assert.equal(gullPose(4).wing, gullPose(5).wing);
  assert.notEqual(gullPose(1, 0).x, gullPose(1, 1).x);
  for (const time of [2, 3, 9, 18]) {
    assert.ok(Math.abs(gullPose(time - 0.001).wing - gullPose(time + 0.001).wing) < 0.1);
  }
});

test('Seattle solar position agrees with USNO sunrise, sunset, and civil twilight', () => {
  // USNO one-day data for Seattle, 2026-10-25, UTC-7; geometric sunrise is about -0.833 degrees.
  for (const [timestamp, expected] of [
    ['2026-10-25T14:11:00Z', -6],
    ['2026-10-25T14:43:00Z', -0.833],
    ['2026-10-26T01:03:00Z', -0.833],
    ['2026-10-26T01:35:00Z', -6],
  ]) {
    assert.ok(Math.abs(solarPosition(new Date(timestamp)).altitude - expected) < 0.2, timestamp);
  }
  assert.ok(Math.abs(solarPosition(new Date('2026-10-25T19:53:00Z')).azimuth - 180) < 0.3);
  assert.ok(solarPosition(new Date('2026-10-25T14:43:00Z')).azimuth < 180);
  assert.ok(solarPosition(new Date('2026-10-26T01:03:00Z')).azimuth > 180);
  assert.deepEqual(solarPosition(new Date('2026-10-25T07:43:00-07:00')),
    solarPosition(new Date('2026-10-25T14:43:00Z')));
  assert.throws(() => solarPosition(new Date('invalid')), /valid date/);
});

test('solar lighting follows seasons and blends smoothly through twilight with weather dimming', () => {
  const clear = { cloud: 0, wet: 0 };
  const noon = new Date('2026-10-25T20:00:00Z');
  const night = solarLighting(new Date('2026-10-25T07:00:00Z'), clear);
  const dawn = solarLighting(new Date('2026-10-25T14:40:00Z'), clear);
  const day = solarLighting(noon, clear);
  assert.equal(night.daylight, 0);
  assert.equal(night.sunVisibility, 0);
  assert.ok(dawn.daylight > 0 && dawn.daylight < 1);
  assert.ok(dawn.twilight > 0.8);
  assert.equal(day.daylight, 1);
  assert.ok(solarLighting(noon, { cloud: 1, wet: 0 }).brightness < day.brightness);
  assert.equal(solarLighting(noon, { cloud: 1, wet: 0 }).sunVisibility, 0);
  assert.ok(solarLighting(noon, { cloud: 0, wet: 3 }).brightness < day.brightness);
  assert.ok(solarPosition(new Date('2026-06-21T20:00:00Z')).altitude >
    solarPosition(new Date('2026-12-21T20:00:00Z')).altitude + 40);
  for (let minute = 0; minute < 120; minute++) {
    const t = Date.parse('2026-10-25T14:00:00Z') + minute * 60000;
    const a = solarLighting(new Date(t), clear);
    const b = solarLighting(new Date(t + 60000), clear);
    assert.ok(Math.abs(b.daylight - a.daylight) < 0.03);
    assert.ok(Math.abs(b.twilight - a.twilight) < 0.04);
  }
});
