import test from 'node:test';
import assert from 'node:assert/strict';
import { CITIES, getCity, blendColor, drawCityScene } from './public/city-scenes.mjs';
import {
  cityNature, foliagePalette, leafCount, birdsVisible, birdPose,
  leafPath, drawCityBirds, drawCityLeaves,
} from './public/city-nature.mjs';

const autumn = new Date('2026-10-27T12:00:00Z');
const summer = new Date('2026-07-15T12:00:00Z');
const winter = new Date('2026-01-15T12:00:00Z');
const weather = { day: true, snow: false, fog: false, wet: 0, wind: 18, cloud: 0 };
const light = { daylight: 1, brightness: 1 };
const color = (night, day, alpha = 1) => blendColor(night, day, 1, alpha);

function recorder() {
  const calls = [];
  let depth = 0;
  const context = new Proxy({
    save() { depth++; },
    restore() { assert.ok(depth > 0); depth--; },
    createLinearGradient: () => ({ addColorStop() {} }),
    createRadialGradient: () => ({ addColorStop() {} }),
  }, {
    get(target, key) {
      if (key in target) return target[key];
      return (...args) => {
        assert.ok(args.filter(value => typeof value === 'number').every(Number.isFinite), `${String(key)}: finite coordinates`);
        calls.push([key, ...args]);
      };
    },
    set(target, key, value) {
      target[key] = value;
      calls.push(['set', key, typeof value === 'object' ? 'gradient' : value]);
      return true;
    },
  });
  return { context, calls, balanced: () => assert.equal(depth, 0) };
}

test('city profiles choose local birds, planted trees and corresponding airborne leaves', () => {
  const expected = {
    seattle: ['gull', 'evergreen', 'maple'],
    mumbai: ['kite', 'palm', 'palm'],
    tokyo: ['sparrow', 'ginkgo', 'ginkgo'],
    paris: ['pigeon', 'plane', 'plane'],
    beijing: ['magpie', 'cypress', 'ginkgo'],
    'new-york': ['pigeon', 'maple', 'maple'],
  };
  for (const city of CITIES) {
    const nature = cityNature(city, autumn);
    assert.deepEqual([nature.bird, nature.tree, nature.leaf], expected[city.id]);
  }
  assert.throws(() => cityNature({ id: 'unknown' }), /Unknown nature profile/);
  assert.throws(() => cityNature(CITIES[0], new Date('invalid')), /valid date/);
});

test('local month controls seasons; Mumbai stays tropical instead of inheriting autumn', () => {
  for (const city of CITIES.filter(value => value.id !== 'mumbai')) {
    assert.equal(cityNature(city, autumn).season, 'autumn');
    assert.equal(cityNature(city, summer).season, 'summer');
    assert.equal(cityNature(city, winter).season, 'winter');
  }
  for (const date of [autumn, summer, winter]) {
    assert.equal(cityNature(getCity('mumbai'), date).season, 'tropical');
  }
  const boundary = new Date('2026-09-01T00:30:00Z');
  assert.equal(cityNature(getCity('seattle'), boundary).season, 'summer');
  assert.equal(cityNature(getCity('tokyo'), boundary).season, 'autumn');
  assert.notDeepEqual(foliagePalette('ginkgo', 'autumn'), foliagePalette('ginkgo', 'summer'));
  assert.notDeepEqual(foliagePalette('plane', 'autumn'), foliagePalette('maple', 'autumn'));
  assert.deepEqual(foliagePalette('palm', 'autumn'), foliagePalette('palm', 'summer'));
  assert.throws(() => foliagePalette('unknown', 'autumn'), /Unknown foliage/);
});

test('leaf density depends on local season, snow, and wind rather than a universal brown-leaf storm', () => {
  for (const city of CITIES.filter(value => value.id !== 'mumbai')) {
    assert.ok(leafCount(cityNature(city, autumn), weather) > 0);
    assert.equal(leafCount(cityNature(city, summer), weather), 0);
    assert.equal(leafCount(cityNature(city, winter), weather), 0);
    assert.equal(leafCount(cityNature(city, autumn), { ...weather, wind: 0 }), 0);
    assert.equal(leafCount(cityNature(city, autumn), { ...weather, snow: true }), 0);
  }
  const palm = cityNature(getCity('mumbai'), autumn);
  assert.equal(leafCount(palm, { ...weather, wind: 12 }), 0);
  assert.equal(leafCount(palm, { ...weather, wind: 36 }), 3);
});

test('daytime birds shelter during rain, fog, snow, and strong winds', () => {
  assert.ok(birdsVisible(weather, light));
  assert.equal(birdsVisible(weather, { daylight: 0 }), false);
  assert.equal(birdsVisible({ ...weather, day: false }, light), false);
  for (const changes of [{ snow: true }, { fog: true }, { wet: 1 }, { wind: 45 }]) {
    assert.equal(birdsVisible({ ...weather, ...changes }, light), false);
  }
});

test('species use distinct flight cadences and smooth, bounded paths', () => {
  for (const species of ['gull', 'kite', 'sparrow', 'pigeon', 'magpie']) {
    for (let time = 0; time < 40; time += 0.1) {
      const pose = birdPose(species, time, 1), next = birdPose(species, time + 0.001, 1);
      assert.ok(pose.x >= 0.09 && pose.x <= 0.91);
      assert.ok(pose.y >= 0.2 && pose.y <= 0.55);
      assert.ok(Object.values(pose).every(Number.isFinite));
      assert.ok(Math.abs(next.x - pose.x) < 0.001);
      assert.ok(Math.abs(next.wing - pose.wing) < 0.15);
    }
  }
  assert.equal(birdPose('kite', 4).wing, birdPose('kite', 5).wing);
  assert.notEqual(birdPose('sparrow', 4).wing, birdPose('sparrow', 4.1).wing);
  assert.notEqual(birdPose('pigeon', 4).wing, birdPose('magpie', 4).wing);
  assert.throws(() => birdPose('unknown', 0), /Unknown bird species/);
});

test('palm, ginkgo fan, maple, and plane leaves have different silhouettes', () => {
  const paths = ['palm', 'ginkgo', 'maple', 'plane'].map(shape => {
    const { context, calls } = recorder();
    leafPath(context, shape, 8);
    return JSON.stringify(calls);
  });
  assert.equal(new Set(paths).size, 4);
  assert.throws(() => leafPath(recorder().context, 'unknown', 8), /Unknown leaf/);
});

test('city-specific birds and leaves draw valid balanced paths on mobile and desktop', () => {
  for (const city of CITIES) {
    const nature = cityNature(city, autumn);
    for (const [width, height] of [[390, 844], [1440, 900]]) {
      const { context, calls, balanced } = recorder();
      const args = { nature, width, height, weather, light, time: 12, color, drift: 30, horizontal: 18 };
      drawCityBirds(context, args);
      assert.ok(calls.length > 10);
      if (nature.bird === 'magpie') assert.ok(calls.some(call => call[0] === 'lineTo' && call[2] === 22), 'magpie has its distinctive long tail');
      calls.length = 0;
      drawCityLeaves(context, args);
      assert.ok(calls.length > 10);
      assert.ok(calls.filter(call => call[0] === 'translate').every(call => call[2] >= height * 0.49), 'leaves originate near canopies, not the upper sky');
      balanced();
      calls.length = 0;
      drawCityBirds(context, { ...args, light: { daylight: 0 } });
      assert.equal(calls.length, 0);
      drawCityLeaves(context, { ...args, weather: { ...weather, wind: 0 } });
      assert.equal(calls.length, 0);
    }
  }
});

test('tree rendering follows the selected city profile and sheds deciduous foliage in winter', () => {
  const draw = (city, date) => {
    const { context, calls, balanced } = recorder();
    drawCityScene(context, {
      city, width: 900, height: 700, weather, light, time: 1,
      sway: () => 0, nature: cityNature(city, date),
    });
    balanced();
    return calls;
  };
  for (const id of ['tokyo', 'paris', 'beijing', 'new-york']) {
    const city = getCity(id);
    assert.ok(draw(city, winter).length < draw(city, autumn).length, id);
    assert.notDeepEqual(draw(city, summer), draw(city, autumn), `${id}: seasonal palette`);
  }
  assert.deepEqual(draw(getCity('mumbai'), winter), draw(getCity('mumbai'), autumn));
});
