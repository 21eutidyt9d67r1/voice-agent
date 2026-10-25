const WEATHER_URL = 'https://api.open-meteo.com/v1/forecast?latitude=47.6062&longitude=-122.3321&current=temperature_2m,is_day,precipitation,weather_code,cloud_cover,wind_speed_10m,wind_direction_10m&timezone=America%2FLos_Angeles';

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

export function weatherLabel(w) {
  const condition = w.snow ? 'Snow' : w.wet > 0 ? 'Rain' : w.fog ? 'Fog' : w.cloud > 0.65 ? 'Cloudy' : w.cloud > 0.2 ? 'Partly cloudy' : w.day ? 'Sunny' : 'Clear';
  return `Seattle: ${condition}, ${Math.round(w.temperature)} C, wind ${Math.round(w.wind)} km/h · ${w.time.slice(11)} Seattle time`;
}

function startWeather() {
  const canvas = document.getElementById('weather-scene');
  const ctx = canvas.getContext('2d');
  const status = document.getElementById('weather-status');
  const button = document.getElementById('weather-motion');
  if (!ctx) {
    status.textContent = 'Seattle scenery unavailable: canvas is not supported.';
    button.disabled = true;
    return;
  }
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  let paused = motion.matches, weather = null, width = 0, height = 0, frame = 0, last = 0, time = 0;
  let request = null, refresh;
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
    const w = weather;
    const sky = ctx.createLinearGradient(0, 0, 0, height);
    sky.addColorStop(0, w.day ? (w.cloud > 0.65 ? '#718b98' : '#8fbacc') : '#182c40');
    sky.addColorStop(0.65, w.day ? '#dce5df' : '#536773');
    sky.addColorStop(1, w.day ? '#edf0df' : '#a0afa7');
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, width, height);

    const sunX = width * 0.77, sunY = height * 0.16;
    const halo = ctx.createRadialGradient(sunX, sunY, 0, sunX, sunY, width * 0.48);
    halo.addColorStop(0, `rgba(255,241,190,${w.day ? (1 - w.cloud) * 0.75 : 0.08})`);
    halo.addColorStop(1, 'rgba(255,241,190,0)');
    ctx.fillStyle = halo; ctx.fillRect(0, 0, width, height);
    if (w.cloud < 0.8) {
      ctx.fillStyle = w.day ? '#fff5d5' : '#e0e6e1';
      ctx.beginPath(); ctx.arc(sunX, sunY, w.day ? 27 : 16, 0, Math.PI * 2); ctx.fill();
    }
    const horizontal = Math.sin(w.direction * Math.PI / 180) * -Math.min(w.wind * 3, 120);
    const drift = time * (12 + w.wind * 1.2) * (horizontal < 0 ? -1 : 1);
    for (let i = 0; i < 9; i++) {
      const x = wrap(i * width / 4 + drift * (i % 2 ? 0.6 : 1), width + 600) - 300;
      const y = height * (0.03 + (i % 4) * 0.095);
      ctx.save(); ctx.translate(x, y); ctx.scale(2.9, 0.65);
      const cloud = ctx.createRadialGradient(0, 0, 0, 0, 0, 130);
      cloud.addColorStop(0, `rgba(236,242,240,${0.25 + w.cloud * 0.55})`);
      cloud.addColorStop(1, 'rgba(236,242,240,0)');
      ctx.fillStyle = cloud; ctx.fillRect(-130, -130, 260, 260); ctx.restore();
    }
    // Hazy mountain ridges and a darker evergreen shoreline give the scene depth.
    for (let layer = 0; layer < 3; layer++) {
      ctx.fillStyle = ['#78949650', '#62877c60', '#345c4b65'][layer];
      ctx.beginPath(); ctx.moveTo(0, height);
      for (let x = 0; x <= width + 4; x += 4) {
        const y = height * (0.76 + layer * 0.065) +
          Math.sin(x * 0.003 + layer * 2) * 38 + Math.sin(x * 0.009 + layer) * 17 +
          Math.sin(x * 0.031 + layer) * 5 + Math.sin(x * 0.071) * 2;
        ctx.lineTo(x, y);
      }
      ctx.lineTo(width, height); ctx.closePath(); ctx.fill();
    }
    for (let i = 0; i < 70; i++) {
      const x = i * width / 69, y = height * 0.96 + Math.sin(i * 1.7) * 14;
      const size = 18 + particles[i].depth * 38;
      const sway = Math.sin(time * 0.7 + i) * Math.min(w.wind / 12, 3);
      ctx.fillStyle = '#294c3d70'; ctx.strokeStyle = '#34504465'; ctx.lineWidth = 1;
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
    if (w.fog) {
      const fog = ctx.createLinearGradient(0, height * 0.4, 0, height);
      fog.addColorStop(0, '#e4e9e600'); fog.addColorStop(1, '#e4e9e6ca');
      ctx.fillStyle = fog; ctx.fillRect(0, 0, width, height);
    }
    if (w.wet > 0 || w.snow) {
      const count = w.snow ? 65 : Math.min(160, 45 + w.wet * 22);
      for (let i = 0; i < count; i++) {
        const p = particles[i], speed = (w.snow ? 22 : 410) * p.depth;
        const x = wrap(p.x * width + time * horizontal * p.depth, width + 40) - 20;
        const y = wrap(p.y * height + time * speed, height + 40) - 20;
        ctx.strokeStyle = `rgba(224,239,245,${0.22 + p.depth * 0.2})`;
        ctx.lineWidth = p.depth;
        ctx.beginPath();
        if (w.snow) {
          ctx.fillStyle = '#f5fafbd0'; ctx.arc(x, y, p.depth * 2, 0, Math.PI * 2); ctx.fill();
        } else {
          ctx.moveTo(x, y); ctx.lineTo(x + horizontal * 0.035, y + 16 * p.depth); ctx.stroke();
        }
      }
    }
    if (w.wind >= 5 && !w.snow) {
      for (let i = 0; i < Math.min(22, 4 + Math.floor(w.wind / 2)); i++) {
        const p = particles[i], direction = horizontal < 0 ? -1 : 1;
        const x = wrap(p.x * width + time * direction * (35 + w.wind * 4) * p.depth, width + 80) - 40;
        const y = wrap(p.y * height + time * 20 + Math.sin(time * 1.4 + i) * 25, height + 80) - 40;
        ctx.save(); ctx.translate(x, y); ctx.rotate(time * 2 + i);
        ctx.scale(1, 0.35 + Math.abs(Math.sin(time + i)) * 0.65);
        ctx.fillStyle = ['#997344aa', '#b18a45aa', '#6b784eaa'][i % 3];
        ctx.beginPath(); ctx.ellipse(0, 0, 7 * p.depth, 3 * p.depth, 0, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = '#514a36aa'; ctx.lineWidth = 0.6;
        ctx.beginPath(); ctx.moveTo(-6 * p.depth, 0); ctx.lineTo(9 * p.depth, 0); ctx.stroke(); ctx.restore();
      }
    }
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
    button.setAttribute('aria-pressed', String(paused));
  }
  function resize() {
    width = innerWidth; height = innerHeight;
    const ratio = Math.min(devicePixelRatio || 1, 2);
    canvas.width = width * ratio; canvas.height = height * ratio;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    paint();
  }
  async function update() {
    request?.abort(); request = new AbortController();
    const timeout = setTimeout(() => request.abort(), 10000);
    try {
      const response = await fetch(WEATHER_URL, { signal: request.signal, credentials: 'omit', referrerPolicy: 'no-referrer' });
      if (!response.ok) throw new Error(`Weather service returned HTTP ${response.status}`);
      weather = parseWeather(await response.json());
      status.textContent = weatherLabel(weather); animate();
    } catch (error) {
      status.textContent = weather
        ? `${weatherLabel(weather)} (refresh failed; showing last update)`
        : 'Seattle weather unavailable. Scenery will appear when the weather service reconnects.';
      console.warn('Seattle weather update failed:', error);
    } finally {
      clearTimeout(timeout);
    }
  }
  button.addEventListener('click', () => { paused = !paused; animate(); });
  motion.addEventListener('change', () => { paused = motion.matches; animate(); });
  document.addEventListener('visibilitychange', animate);
  window.addEventListener('resize', resize);
  window.addEventListener('pagehide', () => { clearInterval(refresh); request?.abort(); cancelAnimationFrame(frame); });
  window.addEventListener('pageshow', event => {
    if (event.persisted) { update(); refresh = setInterval(update, 15 * 60 * 1000); }
  });
  resize(); animate(); update();
  refresh = setInterval(update, 15 * 60 * 1000);
}

if (typeof document !== 'undefined') startWeather();
