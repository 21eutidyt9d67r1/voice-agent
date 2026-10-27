import { CITIES, getCity, weatherUrl, blendColor, drawCityScene } from './city-scenes.mjs';
import { cityNature, foliagePalette, leafPath, drawCityBirds, drawCityLeaves } from './city-nature.mjs';
export { gullPose } from './city-nature.mjs';

const radians = Math.PI / 180;
const smoothstep = (low, high, value) => {
  const t = Math.max(0, Math.min(1, (value - low) / (high - low)));
  return t * t * (3 - 2 * t);
};

// NOAA-style geometric solar coordinates; UTC avoids browser timezone and DST offsets.
export function solarPosition(date, city = CITIES[0]) {
  const timestamp = date.getTime();
  if (!Number.isFinite(timestamp)) throw new Error('Solar position requires a valid date');
  if (!Number.isFinite(city.latitude) || Math.abs(city.latitude) > 90 ||
      !Number.isFinite(city.longitude) || Math.abs(city.longitude) > 180) {
    throw new Error('Solar position requires valid city coordinates');
  }
  const centuries = (timestamp / 86400000 + 2440587.5 - 2451545) / 36525;
  const longitude = (280.46646 + centuries * (36000.76983 + centuries * 0.0003032)) % 360;
  const anomaly = (357.52911 + centuries * (35999.05029 - 0.0001537 * centuries)) * radians;
  const eccentricity = 0.016708634 - centuries * (0.000042037 + 0.0000001267 * centuries);
  const center = Math.sin(anomaly) * (1.914602 - centuries * (0.004817 + 0.000014 * centuries)) +
    Math.sin(2 * anomaly) * (0.019993 - 0.000101 * centuries) + Math.sin(3 * anomaly) * 0.000289;
  const omega = (125.04 - 1934.136 * centuries) * radians;
  const apparent = (longitude + center - 0.00569 - 0.00478 * Math.sin(omega)) * radians;
  const obliquity = (23 + (26 + (21.448 - centuries * (46.815 + centuries *
    (0.00059 - centuries * 0.001813))) / 60) / 60 + 0.00256 * Math.cos(omega)) * radians;
  const declination = Math.asin(Math.sin(obliquity) * Math.sin(apparent));
  const y = Math.tan(obliquity / 2) ** 2, l = longitude * radians;
  const equation = 4 / radians * (y * Math.sin(2 * l) - 2 * eccentricity * Math.sin(anomaly) +
    4 * eccentricity * y * Math.sin(anomaly) * Math.cos(2 * l) -
    0.5 * y * y * Math.sin(4 * l) - 1.25 * eccentricity ** 2 * Math.sin(2 * anomaly));
  const utcMinutes = date.getUTCHours() * 60 + date.getUTCMinutes() +
    date.getUTCSeconds() / 60 + date.getUTCMilliseconds() / 60000;
  const solarMinutes = ((utcMinutes + equation + 4 * city.longitude) % 1440 + 1440) % 1440;
  const hourAngle = (solarMinutes / 4 - 180) * radians, latitude = city.latitude * radians;
  const altitude = Math.asin(Math.max(-1, Math.min(1, Math.sin(latitude) * Math.sin(declination) +
    Math.cos(latitude) * Math.cos(declination) * Math.cos(hourAngle)))) / radians;
  const azimuth = (Math.atan2(Math.sin(hourAngle),
    Math.cos(hourAngle) * Math.sin(latitude) - Math.tan(declination) * Math.cos(latitude)) / radians + 180) % 360;
  return { altitude, azimuth };
}

export function solarLighting(date, weather, city = CITIES[0]) {
  const sun = solarPosition(date, city);
  const daylight = smoothstep(-9, 6, sun.altitude);
  return {
    ...sun, daylight,
    brightness: daylight * (1 - weather.cloud * 0.3) * (1 - Math.min(weather.wet / 25, 0.2)),
    twilight: smoothstep(-10, -1, sun.altitude) * (1 - smoothstep(0, 14, sun.altitude)),
    sunVisibility: smoothstep(-0.9, -0.1, sun.altitude) * (1 - weather.cloud) ** 2,
  };
}

export function parseWeather(data) {
  const c = data?.current;
  for (const key of ['temperature_2m', 'is_day', 'precipitation', 'weather_code', 'cloud_cover', 'wind_speed_10m', 'wind_direction_10m']) {
    if (!Number.isFinite(c?.[key])) throw new Error(`Weather response missing ${key}`);
  }
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(c.time || '')) throw new Error('Weather timestamp missing');
  if (c.precipitation < 0 || c.wind_speed_10m < 0 || c.cloud_cover < 0 || c.cloud_cover > 100 || ![0, 1].includes(c.is_day)) {
    throw new Error('Weather values out of range');
  }
  return {
    temperature: c.temperature_2m, day: c.is_day === 1, cloud: c.cloud_cover / 100,
    wet: c.precipitation, wind: c.wind_speed_10m, direction: c.wind_direction_10m,
    snow: [71, 73, 75, 77, 85, 86].includes(c.weather_code),
    fog: [45, 48].includes(c.weather_code), time: c.time,
  };
}

export function weatherLabel(w, city = CITIES[0]) {
  const condition = w.snow ? 'Snow' : w.wet > 0 ? 'Rain' : w.fog ? 'Fog' : w.cloud > 0.65 ? 'Cloudy' : w.cloud > 0.2 ? 'Partly cloudy' : w.day ? 'Sunny' : 'Clear';
  return `${city.name}: ${condition}, ${Math.round(w.temperature)} C, wind ${Math.round(w.wind)} km/h · ${w.time.slice(11)} ${city.name} time`;
}

export class CityWeather {
  constructor(onState, fetcher = (url, options) => globalThis.fetch(url, options)) {
    this.onState = onState;
    this.fetcher = fetcher;
    this.city = CITIES[0];
    this.weather = null;
    this.request = null;
  }

  select(id) {
    const city = getCity(id);
    if (city.id !== this.city.id) this.weather = null;
    this.city = city;
    return this.refresh();
  }

  cancel() {
    const request = this.request;
    this.request = null;
    request?.abort();
  }

  async refresh() {
    this.cancel();
    const city = this.city, request = new AbortController();
    this.request = request;
    this.onState({ city, weather: this.weather, loading: true, error: null });
    const timeout = setTimeout(() => request.abort(), 10000);
    try {
      const response = await this.fetcher(weatherUrl(city), {
        signal: request.signal, credentials: 'omit', referrerPolicy: 'no-referrer',
      });
      if (!response.ok) throw new Error(`Weather service returned HTTP ${response.status}`);
      const weather = parseWeather(await response.json());
      if (this.request !== request) return;
      if (request.signal.aborted) throw new Error('Weather request timed out');
      this.weather = weather;
      this.onState({ city, weather, loading: false, error: null });
    } catch (error) {
      if (this.request !== request) return;
      this.onState({ city, weather: this.weather, loading: false, error });
    } finally {
      clearTimeout(timeout);
      if (this.request === request) this.request = null;
    }
  }
}

export function weatherMotion(w, time) {
  const gust = 1 + 0.18 * Math.sin(time * 0.43) + 0.08 * Math.sin(time * 1.17);
  const horizontal = -Math.sin(w.direction * Math.PI / 180) * Math.min(w.wind * 3, 120);
  // Integrate the gust so motion stays continuous instead of jumping as wind changes.
  const elapsed = time + 0.18 * (1 - Math.cos(time * 0.43)) / 0.43 +
    0.08 * (1 - Math.cos(time * 1.17)) / 1.17;
  return { horizontal, gust, drift: horizontal * elapsed };
}

export function treeSway(w, time, phase = 0) {
  const strength = Math.sqrt(Math.min(w.wind / 35, 1));
  const { horizontal, gust } = weatherMotion(w, time);
  return strength * gust * (horizontal / 120 * 0.5 +
    Math.sin(time * 0.9 + phase) * 0.35 + Math.sin(time * 1.7 + phase * 0.7) * 0.15);
}

export function wildlifeMotion(time, phase = 0) {
  const elapsed = time + phase;
  const cycle = elapsed % 32;
  const walking = Math.floor(elapsed / 32) * 22 + Math.min(cycle, 22);
  const ease = value => {
    const t = Math.max(0, Math.min(1, value));
    return t * t * (3 - 2 * t);
  };
  return {
    distance: walking * 9,
    stride: cycle < 22 ? Math.sin(cycle * Math.PI * 2) : 0,
    grazing: ease((cycle - 22) / 2) * ease((32 - cycle) / 2),
  };
}

export function shorelineY(height, x, depth = 0) {
  return height * (0.94 + depth * 0.045) + Math.sin(x * 0.008) * Math.min(3, height * 0.003);
}

function startWeather() {
  const canvas = document.getElementById('weather-scene');
  const ctx = canvas.getContext('2d');
  const status = document.getElementById('weather-status');
  const button = document.getElementById('weather-motion');
  const viewButton = document.getElementById('scenery-toggle');
  const selector = document.getElementById('scene-city');
  const caption = document.getElementById('scene-landmark');
  const sceneStatus = document.getElementById('scenery-weather');
  let panelScroll = 0;
  function sceneryView(showScenery) {
    if (showScenery) panelScroll = window.scrollY;
    document.body.classList.toggle('scenery-only', showScenery);
    viewButton.textContent = showScenery ? 'Show panels' : 'Scenery only';
    viewButton.title = `${viewButton.textContent}. Active calls continue.`;
    viewButton.setAttribute('aria-label', viewButton.textContent);
    viewButton.setAttribute('aria-pressed', String(showScenery));
    window.scrollTo({ top: showScenery ? 0 : panelScroll, behavior: 'instant' });
    viewButton.focus({ preventScroll: true });
  }
  viewButton.addEventListener('click', () => sceneryView(!document.body.classList.contains('scenery-only')));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && document.body.classList.contains('scenery-only')) sceneryView(false);
  });
  if (!ctx) {
    status.textContent = 'City scenery unavailable: canvas is not supported.';
    sceneStatus.textContent = status.textContent;
    button.disabled = true;
    viewButton.disabled = true;
    selector.disabled = true;
    return;
  }
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  let paused = motion.matches, weather = null, width = 0, height = 0, frame = 0, last = 0, time = 0;
  let city = CITIES[0], refresh;
  // Fixed seeds keep particles and cloud layers stable across redraws and resizes.
  const particles = Array.from({ length: 160 }, (_, i) => ({
    x: ((i * 7919 + 37) % 1009) / 1009,
    y: ((i * 3571 + 83) % 1013) / 1013,
    depth: 0.35 + ((i * 127) % 100) / 100,
  }));
  const wrap = (value, size) => ((value % size) + size) % size;

  function render(ctx, width, height) {
    ctx.clearRect(0, 0, width, height);
    if (!weather) return;
    const now = new Date();
    const light = solarLighting(now, weather, city);
    const nature = cityNature(city, now);
    const w = { ...weather, day: light.altitude > -0.833 };
    const brightness = light.brightness;
    const color = (night, day, alpha = 1) => blendColor(night, day, brightness, alpha);
    const sky = ctx.createLinearGradient(0, 0, 0, height);
    sky.addColorStop(0, blendColor('0b182d', '8fbacc', brightness));
    sky.addColorStop(0.65, blendColor('243b55', 'dce5df', brightness));
    sky.addColorStop(1, blendColor('394c61', 'edf0df', brightness));
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, width, height);

    const sunX = width * ((light.azimuth - 70) / 220);
    const sunY = height * (0.74 - 0.68 * Math.sin(Math.max(0, light.altitude) * radians));
    const dusk = ctx.createRadialGradient(sunX, height * 0.74, 0, sunX, height * 0.74, width * 0.7);
    dusk.addColorStop(0, `rgba(239,143,93,${light.twilight * (1 - w.cloud * 0.7) * 0.65})`);
    dusk.addColorStop(1, 'rgba(239,143,93,0)');
    ctx.fillStyle = dusk; ctx.fillRect(0, 0, width, height);
    if (light.daylight < 0.4) {
      ctx.fillStyle = `rgba(226,237,250,${(1 - light.daylight / 0.4) * (1 - w.cloud) * 0.65})`;
      for (let star = 0; star < 45; star++) {
        const p = particles[star];
        ctx.beginPath(); ctx.arc(p.x * width, p.y * height * 0.58, 0.6 + p.depth * 0.4, 0, Math.PI * 2); ctx.fill();
      }
    }
    const halo = ctx.createRadialGradient(sunX, sunY, 0, sunX, sunY, width * 0.48);
    halo.addColorStop(0, `rgba(255,223,166,${light.sunVisibility * 0.65})`);
    halo.addColorStop(1, 'rgba(255,241,190,0)');
    ctx.fillStyle = halo; ctx.fillRect(0, 0, width, height);
    if (light.sunVisibility > 0) {
      ctx.fillStyle = blendColor('f4ac73', 'fff5d5', smoothstep(0, 18, light.altitude), light.sunVisibility);
      ctx.beginPath(); ctx.arc(sunX, sunY, 15, 0, Math.PI * 2); ctx.fill();
    }
    const { horizontal, drift } = weatherMotion(w, time);
    for (let layer = 0; layer < 3; layer++) {
      const depth = 0.35 + layer * 0.3;
      for (let i = 0; i < 5; i++) {
        const seed = particles[layer * 5 + i];
        const x = wrap(seed.x * (width + 700) + drift * depth * 0.22, width + 700) - 350;
        const y = height * (0.06 + seed.y * 0.32);
        ctx.save(); ctx.translate(x, y); ctx.scale(1.6 + depth, 0.35 + depth * 0.25);
        for (let puff = 0; puff < 5; puff++) {
          const px = (puff - 2) * 48, py = Math.sin(puff * 2.3 + i) * 22;
          const radius = 65 + particles[i + puff].depth * 30;
          const cloud = ctx.createRadialGradient(px, py - 12, 0, px, py, radius);
          const alpha = w.cloud * (0.12 + depth * 0.12);
          cloud.addColorStop(0, blendColor('56677f', 'f8f8ef', brightness, alpha));
          cloud.addColorStop(0.55, blendColor('2e405a', 'b7c6c9', brightness, alpha * 0.7));
          cloud.addColorStop(1, 'rgba(150,170,181,0)');
          ctx.fillStyle = cloud; ctx.fillRect(px - radius, py - radius, radius * 2, radius * 2);
        }
        ctx.restore();
      }
    }
    drawCityBirds(ctx, { nature, width, height, weather: w, light, time, color });
    if (city.id !== 'seattle') {
      drawCityScene(ctx, {
        city, width, height, weather: w, light, time, nature,
        sway: phase => treeSway(w, time, phase),
      });
    } else {
      // A broad volcanic summit and glacier fingers suggest distant Mount Rainier.
      ctx.save();
      ctx.translate(width * 0.7, height * 0.61);
      ctx.scale(Math.min(width * 0.32, 430), Math.min(height * 0.25, 230));
      ctx.globalAlpha = w.fog ? 0.18 : 0.78 - w.cloud * 0.25;
      ctx.fillStyle = blendColor('34485f', '819da7', brightness);
      ctx.beginPath(); ctx.moveTo(-1, 1);
      ctx.lineTo(-0.64, 0.72); ctx.lineTo(-0.35, 0.36); ctx.lineTo(-0.19, 0.2);
      ctx.bezierCurveTo(-0.14, 0.02, -0.07, 0.08, -0.04, 0.04);
      ctx.bezierCurveTo(0.03, -0.02, 0.13, 0.04, 0.19, 0.13);
      ctx.lineTo(0.36, 0.34); ctx.lineTo(0.56, 0.57); ctx.lineTo(1, 1);
      ctx.closePath(); ctx.fill();
      ctx.fillStyle = blendColor('71849c', 'e1e9e7', brightness);
      ctx.beginPath(); ctx.moveTo(-0.35, 0.36); ctx.lineTo(-0.19, 0.2);
      ctx.bezierCurveTo(-0.14, 0.02, -0.07, 0.08, -0.04, 0.04);
      ctx.bezierCurveTo(0.03, -0.02, 0.13, 0.04, 0.19, 0.13);
      ctx.lineTo(0.36, 0.34); ctx.lineTo(0.53, 0.55); ctx.lineTo(0.25, 0.4);
      ctx.lineTo(0.32, 0.65); ctx.lineTo(0.12, 0.42); ctx.lineTo(0.06, 0.71);
      ctx.lineTo(-0.04, 0.42); ctx.lineTo(-0.22, 0.62); ctx.lineTo(-0.17, 0.39);
      ctx.lineTo(-0.45, 0.58); ctx.closePath(); ctx.fill();
      ctx.strokeStyle = blendColor('455f7a', '9fb6c0', brightness); ctx.lineWidth = 0.012;
      for (let glacier = 0; glacier < 4; glacier++) {
        const x = -0.12 + glacier * 0.07;
        ctx.beginPath(); ctx.moveTo(x, 0.17);
        ctx.quadraticCurveTo(x - 0.04, 0.3, x * 2, 0.43); ctx.stroke();
      }
      ctx.restore();
      // Hazy mountain ridges and a darker evergreen shoreline give the scene depth.
      for (let layer = 0; layer < 3; layer++) {
        ctx.fillStyle = blendColor(['304154', '263f46', '19362f'][layer],
          ['789496', '62877c', '345c4b'][layer], brightness, 0.4 + layer * 0.08);
        ctx.beginPath(); ctx.moveTo(0, height);
        for (let x = 0; x <= width + 4; x += 4) {
          const y = height * (0.76 + layer * 0.065) +
            Math.sin(x * 0.003 + layer * 2) * 38 + Math.sin(x * 0.009 + layer) * 17 +
            Math.sin(x * 0.031 + layer) * 5 + Math.sin(x * 0.071) * 2;
          ctx.lineTo(x, y);
        }
        ctx.lineTo(width, height); ctx.closePath(); ctx.fill();
      }
      ctx.save();
      ctx.translate(width * 0.2, height * 0.86);
      const landmarkScale = Math.min(height * 0.2, width * 0.25, 160);
      ctx.scale(landmarkScale, landmarkScale);
      ctx.globalAlpha = w.fog ? 0.3 : 0.7;
      ctx.fillStyle = blendColor('263a50', '536e76', brightness);
      ctx.strokeStyle = ctx.fillStyle;
      ctx.lineWidth = 0.018;
      // The Space Needle's tapered supports, saucer deck, and antenna stay small on the horizon.
      for (const foot of [-0.07, 0, 0.07]) {
        ctx.beginPath(); ctx.moveTo(foot, 0);
        ctx.bezierCurveTo(foot * 0.6, -0.3, -foot * 0.2, -0.5, foot * 0.55, -0.76);
        ctx.stroke();
      }
      ctx.beginPath(); ctx.ellipse(0, -0.77, 0.115, 0.022, 0, 0, Math.PI * 2); ctx.fill();
      ctx.fillRect(-0.065, -0.82, 0.13, 0.04);
      ctx.beginPath(); ctx.moveTo(-0.13, -0.82);
      ctx.quadraticCurveTo(0, -0.94, 0.13, -0.82); ctx.closePath(); ctx.fill();
      ctx.lineWidth = 0.009;
      ctx.beginPath(); ctx.moveTo(0, -0.88); ctx.lineTo(0, -1); ctx.stroke();
      ctx.restore();
      const waterline = height * 0.86;
      const water = ctx.createLinearGradient(0, waterline, 0, height);
      water.addColorStop(0, blendColor('263e55', '9bb5b5', brightness));
      water.addColorStop(1, blendColor('142b3c', '526f73', brightness));
      ctx.fillStyle = water; ctx.fillRect(0, waterline, width, height - waterline);
      for (let i = 0; i < 65; i++) {
        const p = particles[i], depth = (i + 1) / 65;
        const x = p.x * width + Math.sin(time * (0.4 + depth) + i) * (1 + w.wind * 0.08);
        const y = waterline + depth * (height - waterline);
        const reflection = Math.max(0, 1 - Math.abs(x - sunX) / (width * 0.3));
        ctx.strokeStyle = `rgba(224,235,226,${(0.025 + reflection * 0.16) * (0.2 + light.sunVisibility * 0.8)})`;
        ctx.lineWidth = 0.5 + depth;
        ctx.beginPath(); ctx.moveTo(x, y);
        ctx.lineTo(x + 6 + depth * 32, y); ctx.stroke();
      }
      if (!w.fog && w.wet < 2 && !w.snow) {
        for (let duck = 0; duck < 3; duck++) {
          const x = wrap(width * 0.28 + time * 5 - duck * 21, width + 80) - 40;
          const y = height * 0.905 + duck * 3 + Math.sin(time * 1.2 + duck) * 0.8;
          ctx.fillStyle = blendColor('1c333c', '344b49', brightness, 0.73);
          ctx.beginPath(); ctx.ellipse(x, y, 6, 2.6, 0, 0, Math.PI * 2); ctx.fill();
          ctx.beginPath(); ctx.arc(x + 4, y - 3.5, 2, 0, Math.PI * 2); ctx.fill();
          ctx.beginPath(); ctx.moveTo(x + 5, y - 4);
          ctx.lineTo(x + 9, y - 3); ctx.lineTo(x + 5, y - 2); ctx.fill();
          ctx.strokeStyle = '#cfddd64a'; ctx.lineWidth = 0.7;
          ctx.beginPath(); ctx.ellipse(x - 7, y + 2, 12, 2.4, 0, 0.3, Math.PI - 0.3); ctx.stroke();
        }
      }
      const bank = ctx.createLinearGradient(0, height * 0.94, 0, height);
      bank.addColorStop(0, blendColor('35453d', '7a8061', brightness));
      bank.addColorStop(0.2, blendColor('22362d', '536446', brightness));
      bank.addColorStop(1, blendColor('172c29', '405442', brightness));
      ctx.fillStyle = bank;
      ctx.beginPath(); ctx.moveTo(0, height);
      for (let x = 0; x <= width + 8; x += 8) {
        ctx.lineTo(x, shorelineY(height, x));
      }
      ctx.lineTo(width, height); ctx.closePath(); ctx.fill();
      ctx.strokeStyle = blendColor('334a49', '9ca68a', brightness, 0.6);
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(0, shorelineY(height, 0));
      for (let x = 8; x <= width + 8; x += 8) ctx.lineTo(x, shorelineY(height, x));
      ctx.stroke();
      for (let i = 0; i < 70; i++) {
        const x = i * width / 69;
        const y = shorelineY(height, x, 0.35 + particles[i].depth * 0.4);
        const size = 18 + particles[i].depth * 38;
        const sway = treeSway(w, time, i * 0.2) * size * 0.14;
        ctx.fillStyle = blendColor('142923', '2c3e2d', brightness, 0.35);
        ctx.beginPath(); ctx.ellipse(x, y, size * 0.12, 1.5, 0, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = blendColor('162e29', '294c3d', brightness, 0.65);
        ctx.strokeStyle = blendColor('1c332d', '345044', brightness, 0.65); ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + sway, y - size); ctx.stroke();
        for (let branch = 1; branch <= 9; branch++) {
          const top = y - size + branch * size / 11;
          const spread = branch * size / 33;
          const center = x + sway * (1 - branch / 11);
          ctx.beginPath(); ctx.moveTo(center, top - size * 0.12);
          ctx.lineTo(center - spread, top + size * 0.12);
          ctx.lineTo(center - spread * 0.3, top + size * 0.08);
          ctx.lineTo(center, top + size * 0.17);
          ctx.lineTo(center + spread, top + size * 0.12);
          ctx.closePath(); ctx.fill();
        }
      }
      // Foreground branches flex from fixed roots; leaf flutter is faster than trunk sway.
      for (let tree = 0; tree < 2; tree++) {
        const side = tree ? -1 : 1;
        const root = tree ? width + 12 : -12;
        const size = Math.min(height * 0.38, 320);
        const bend = treeSway(w, time, tree * 1.6) * size * 0.16;
        const tipX = root + side * size * 0.2 + bend;
        const tipY = height - size;
        ctx.strokeStyle = blendColor('1b302d', '394b3c', brightness, 0.85);
        ctx.lineWidth = 7;
        ctx.beginPath(); ctx.moveTo(root, height);
        ctx.bezierCurveTo(root, height - size * 0.45, tipX - bend * 0.4, tipY + size * 0.25, tipX, tipY);
        ctx.stroke();
        for (let branch = 0; branch < 7; branch++) {
          const level = (branch + 2) / 10;
          const baseX = root + (tipX - root) * level * level;
          const baseY = height - size * level;
          const reach = size * (0.2 + particles[branch + tree * 7].x * 0.25);
          const endX = baseX + side * reach + bend * level * 0.4;
          const endY = baseY - size * 0.13;
          ctx.lineWidth = 1.2 + (1 - level) * 2;
          ctx.beginPath(); ctx.moveTo(baseX, baseY);
          ctx.quadraticCurveTo(baseX + side * reach * 0.5, baseY, endX, endY); ctx.stroke();
          for (let leaf = 0; leaf < 6; leaf++) {
            if (nature.season === 'winter') continue;
            const t = (leaf + 1) / 6;
            const seed = particles[tree * 42 + branch * 6 + leaf];
            const flutter = Math.sin(time * 3.2 + seed.x * 20) * Math.min(w.wind / 12, 1);
            const x = baseX + (endX - baseX) * t;
            const y = baseY + (endY - baseY) * t * t + (leaf % 2 ? -7 : 7);
            ctx.save(); ctx.translate(x, y);
            ctx.rotate(side * -0.5 + flutter * 0.55);
            ctx.scale(1, 0.65 + flutter * 0.25);
            ctx.fillStyle = color('344c3e', foliagePalette(nature.leaf, nature.season)[leaf % 3], 0.85);
            leafPath(ctx, nature.leaf, 5 + seed.depth * 3); ctx.fill();
            ctx.restore();
          }
        }
      }
      if (!w.fog && w.wet < 2 && !w.snow) {
        for (let deer = 0; deer < 2; deer++) {
          const pose = wildlifeMotion(time, deer ? 0 : 2);
          const scale = deer ? 0.62 : 0.95;
          const x = wrap(width * 0.12 + pose.distance - deer * 50, width + 160) - 80;
          ctx.save(); ctx.translate(x, shorelineY(height, x, 0.9)); ctx.scale(scale, scale);
          ctx.fillStyle = blendColor('203530', '4b4b36', brightness, 0.9);
          ctx.strokeStyle = ctx.fillStyle; ctx.lineCap = 'round';
          for (let leg = 0; leg < 4; leg++) {
            const hip = leg < 2 ? -10 : 10;
            const swing = pose.stride * (leg % 2 ? -1 : 1) * 5;
            ctx.lineWidth = leg % 2 ? 1.7 : 2.2;
            ctx.beginPath(); ctx.moveTo(hip, -20);
            ctx.lineTo(hip + swing * 0.4, -10); ctx.lineTo(hip + swing, -1); ctx.stroke();
          }
          ctx.beginPath(); ctx.ellipse(0, -23, 15, 7, -0.08, 0, Math.PI * 2); ctx.fill();
          ctx.lineWidth = 5;
          ctx.beginPath(); ctx.moveTo(10, -25);
          ctx.quadraticCurveTo(15, -30 + pose.grazing * 18, 18, -39 + pose.grazing * 29); ctx.stroke();
          const headY = -40 + pose.grazing * 29;
          ctx.beginPath(); ctx.ellipse(21, headY, 6, 3, pose.grazing * 0.7, 0, Math.PI * 2); ctx.fill();
          ctx.beginPath(); ctx.ellipse(18, headY - 5, 1.8, 5, -0.4, 0, Math.PI * 2); ctx.fill();
          ctx.beginPath(); ctx.ellipse(22, headY - 5, 1.5, 4, 0.3, 0, Math.PI * 2); ctx.fill();
          ctx.lineWidth = 2.5;
          ctx.beginPath(); ctx.moveTo(-13, -25); ctx.lineTo(-18, -28); ctx.stroke();
          ctx.restore();
        }
      }
    }
    if (w.fog) {
      const fog = ctx.createLinearGradient(0, height * 0.4, 0, height);
      fog.addColorStop(0, '#e4e9e600');
      fog.addColorStop(1, blendColor('4c6073', 'e4e9e6', brightness, 0.8));
      ctx.fillStyle = fog; ctx.fillRect(0, 0, width, height);
    }
    if (w.wet > 0 || w.snow) {
      const count = w.snow ? 65 : Math.min(160, 45 + w.wet * 22);
      for (let i = 0; i < count; i++) {
        const p = particles[i], speed = (w.snow ? 22 : 410) * p.depth;
        const flutter = w.snow ? Math.sin(time * 0.8 + i) * 14 * p.depth : 0;
        const x = wrap(p.x * width + drift * p.depth + flutter, width + 40) - 20;
        const y = wrap(p.y * height + time * speed, height + 40) - 20;
        ctx.strokeStyle = `rgba(224,239,245,${0.22 + p.depth * 0.2})`;
        ctx.lineWidth = p.depth;
        ctx.beginPath();
        if (w.snow) {
          ctx.fillStyle = `rgba(245,250,251,${0.4 + p.depth * 0.3})`;
          ctx.arc(x, y, p.depth * 2, 0, Math.PI * 2); ctx.fill();
        } else {
          ctx.moveTo(x, y); ctx.lineTo(x + horizontal * 0.035, y + 16 * p.depth); ctx.stroke();
        }
      }
    }
    drawCityLeaves(ctx, { nature, width, height, weather: w, time, drift, horizontal, color });
  }

  function paint() {
    render(ctx, width, height);
  }

  function tick(now) {
    frame = 0;
    if (paused || document.hidden || !weather) return;
    if (now - last >= 33) {
      time += Math.min((now - (last || now)) / 1000, 0.1);
      last = now; paint();
    }
    frame = requestAnimationFrame(tick);
  }
  function animate() {
    cancelAnimationFrame(frame); frame = 0; last = 0;
    paint();
    if (!paused && !document.hidden && weather) frame = requestAnimationFrame(tick);
    button.textContent = paused ? 'Play scenery' : 'Pause scenery';
    button.title = button.textContent;
    button.setAttribute('aria-label', button.textContent);
    button.setAttribute('aria-pressed', String(paused));
  }
  function resize() {
    width = innerWidth; height = innerHeight;
    const ratio = Math.min(devicePixelRatio || 1, 2);
    canvas.width = width * ratio; canvas.height = height * ratio;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    paint();
  }
  const source = new CityWeather(state => {
    city = state.city; weather = state.weather;
    caption.textContent = `${city.landmark} · ${city.country}`;
    caption.title = cityNature(city).label;
    canvas.dataset.city = city.id;
    canvas.setAttribute('aria-label', `${city.name}: ${city.landmark}. Weather-reactive illustrated scenery.`);
    const label = weather ? weatherLabel(weather, city) : `Loading ${city.name} weather...`;
    status.textContent = state.error
      ? weather
        ? `${label} (refresh failed; showing last update)`
        : `${city.name} weather unavailable. Scenery will appear when the weather service reconnects.`
      : state.loading && weather ? `${label} (refreshing)` : label;
    sceneStatus.textContent = status.textContent;
    sceneStatus.title = status.textContent;
    selector.title = `${city.name}, ${city.country}: ${city.landmark}`;
    selector.setAttribute('aria-busy', String(state.loading));
    if (state.error) console.warn(`${city.name} weather update failed:`, state.error);
    animate();
  });
  let initialCity = 'seattle';
  try {
    const saved = localStorage.getItem('voice-scene-city');
    if (saved) initialCity = getCity(saved).id;
  } catch (error) {
    console.warn('Could not restore city scenery preference:', error);
  }
  selector.value = initialCity;
  selector.addEventListener('change', () => {
    const id = getCity(selector.value).id;
    try { localStorage.setItem('voice-scene-city', id); }
    catch (error) { console.warn('Could not save city scenery preference:', error); }
    time = 0;
    source.select(id);
  });
  const update = () => source.refresh();
  button.addEventListener('click', () => { paused = !paused; animate(); });
  motion.addEventListener('change', () => { paused = motion.matches; animate(); });
  document.addEventListener('visibilitychange', animate);
  window.addEventListener('resize', resize);
  window.addEventListener('pagehide', () => { clearInterval(refresh); source.cancel(); cancelAnimationFrame(frame); });
  window.addEventListener('pageshow', event => {
    if (event.persisted) { update(); refresh = setInterval(update, 15 * 60 * 1000); }
  });
  resize(); animate(); source.select(initialCity);
  refresh = setInterval(update, 15 * 60 * 1000);
}

if (typeof document !== 'undefined') startWeather();
