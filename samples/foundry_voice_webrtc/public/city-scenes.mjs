import { cityNature, foliagePalette, leafPath } from './city-nature.mjs';

export const CITIES = Object.freeze([
  { id: 'seattle', name: 'Seattle', country: 'United States', latitude: 47.6062, longitude: -122.3321, timezone: 'America/Los_Angeles', landmark: 'Space Needle & Mount Rainier' },
  { id: 'mumbai', name: 'Mumbai', country: 'India', latitude: 19.076, longitude: 72.8777, timezone: 'Asia/Kolkata', landmark: 'Gateway of India & the waterfront' },
  { id: 'tokyo', name: 'Tokyo', country: 'Japan', latitude: 35.6762, longitude: 139.6503, timezone: 'Asia/Tokyo', landmark: 'Tokyo Tower' },
  { id: 'paris', name: 'Paris', country: 'France', latitude: 48.8566, longitude: 2.3522, timezone: 'Europe/Paris', landmark: 'Eiffel Tower & the Seine' },
  { id: 'beijing', name: 'Beijing', country: 'China', latitude: 39.9042, longitude: 116.4074, timezone: 'Asia/Shanghai', landmark: 'Temple of Heaven' },
  { id: 'new-york', name: 'New York', country: 'United States', latitude: 40.7128, longitude: -74.006, timezone: 'America/New_York', landmark: 'Brooklyn Bridge & Manhattan' },
].map(city => Object.freeze(city)));

export function getCity(id) {
  const city = CITIES.find(value => value.id === id);
  if (!city) throw new Error(`Unknown scenery city: ${id}`);
  return city;
}

export function weatherUrl(city) {
  return `https://api.open-meteo.com/v1/forecast?${new URLSearchParams({
    latitude: city.latitude, longitude: city.longitude, timezone: city.timezone,
    current: 'temperature_2m,is_day,precipitation,weather_code,cloud_cover,wind_speed_10m,wind_direction_10m',
    temperature_unit: 'celsius', wind_speed_unit: 'kmh', precipitation_unit: 'mm',
  })}`;
}

export function blendColor(night, day, amount, alpha = 1) {
  const channels = [0, 2, 4].map(offset => {
    const a = parseInt(night.slice(offset, offset + 2), 16);
    const b = parseInt(day.slice(offset, offset + 2), 16);
    return Math.round(a + (b - a) * amount);
  });
  return `rgba(${channels.join(',')},${alpha})`;
}

const wrap = (value, size) => ((value % size) + size) % size;
const seed = i => ((i * 7919 + 173) % 1009) / 1009;

function polygon(ctx, points, fill, stroke = null) {
  ctx.beginPath();
  points.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
  ctx.closePath();
  if (fill) { ctx.fillStyle = fill; ctx.fill(); }
  if (stroke) { ctx.strokeStyle = stroke; ctx.stroke(); }
}

function ellipse(ctx, x, y, rx, ry, fill) {
  ctx.fillStyle = fill;
  ctx.beginPath(); ctx.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2); ctx.fill();
}

function line(ctx, points, color, width = 1) {
  ctx.strokeStyle = color; ctx.lineWidth = width;
  ctx.beginPath();
  points.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
  ctx.stroke();
}

function glow(ctx, x, y, radius, alpha = 1) {
  const gradient = ctx.createRadialGradient(x, y, 0, x, y, radius);
  gradient.addColorStop(0, `rgba(255,215,145,${alpha * 0.65})`);
  gradient.addColorStop(0.12, `rgba(255,210,125,${alpha * 0.28})`);
  gradient.addColorStop(1, 'rgba(255,198,110,0)');
  ctx.fillStyle = gradient; ctx.fillRect(x - radius, y - radius, radius * 2, radius * 2);
}

function building(ctx, x, ground, width, height, index, s, warm = false) {
  const top = ground - height;
  const depth = Math.min(7, width * 0.16);
  polygon(ctx, [[x + width, top], [x + width + depth, top - depth * 0.4],
    [x + width + depth, ground], [x + width, ground]],
    s.color('10202e', warm ? '777365' : '50616c'));
  const face = ctx.createLinearGradient(x, top, x + width, ground);
  face.addColorStop(0, s.color('172535', warm ? 'b8a694' : '8298a7'));
  face.addColorStop(1, s.color('0d1b2a', warm ? '847d75' : '4d6576'));
  ctx.fillStyle = face; ctx.fillRect(x, top, width, height);
  ctx.fillStyle = s.color('0a1726', warm ? '716b66' : '43596b', 0.65);
  ctx.fillRect(x + width * 0.78, top, width * 0.22, height);
  ctx.fillStyle = s.color('3b4450', 'b5bdba');
  ctx.fillRect(x, top, width, 2);
  polygon(ctx, [[x, top], [x + depth, top - depth * 0.4],
    [x + width + depth, top - depth * 0.4], [x + width, top]],
    s.weather.snow ? s.color('8a99a7', 'eef3ed') : s.color('4a5966', warm ? 'd2c1a6' : 'a1b0b4'));
  if (index % 4 === 0) {
    ctx.fillStyle = s.color('2c3c4b', '7b8d95');
    ctx.fillRect(x + width * 0.2, top - 4, width * 0.25, 4);
    line(ctx, [[x + width * 0.68, top], [x + width * 0.68, top - 9]], s.color('5a6c77', 'b3c2c0'), 0.6);
  }
  const step = Math.max(5, width / 7);
  for (let row = 0; row < Math.floor(height / 9); row++) {
    for (let column = 0; column < Math.floor((width - 4) / step); column++) {
      const lit = seed(index * 31 + row * 7 + column * 17) > 0.48;
      ctx.fillStyle = lit && s.night > 0.1
        ? `rgba(255,215,151,${s.night * (0.25 + seed(row + column) * 0.6)})`
        : s.color('203248', warm ? '65777b' : 'b1ced2', 0.45);
      ctx.fillRect(x + 3 + column * step, top + 5 + row * 9, step * 0.45, 3.5);
      if (warm) line(ctx, [[x + 2, top + 10 + row * 9], [x + width * 0.76, top + 10 + row * 9]],
        s.color('53616a', 'e0d1b3', 0.22), 0.6);
    }
  }
  if (!warm) {
    ctx.fillStyle = s.color('a4bfce', 'e4f0e9', 0.07);
    ctx.fillRect(x + width * 0.26, top + 2, width * 0.12, height - 2);
    ctx.fillRect(x + width * 0.58, top + 2, width * 0.05, height - 2);
  }
}

function skyline(ctx, s, warm = false) {
  for (let layer = 0; layer < 2; layer++) {
    ctx.save(); ctx.globalAlpha = layer ? 0.87 : 0.45;
    const count = layer ? 30 : 43, step = s.width / count;
    for (let i = 0; i < count; i++) {
      const height = s.height * (0.035 + seed(i + layer * 97) * (layer ? 0.13 : 0.18));
      const width = step * (0.7 + seed(i * 3) * 0.45);
      building(ctx, i * step - 8, s.horizon + layer * 8, width, height, i + layer * 41, s, warm);
    }
    ctx.restore();
  }
}

function water(ctx, s, top, bottom = s.height) {
  const gradient = ctx.createLinearGradient(0, top, 0, bottom);
  gradient.addColorStop(0, s.color('1b344c', '8caeb5'));
  gradient.addColorStop(1, s.color('0a2033', '3d6c7d'));
  ctx.fillStyle = gradient; ctx.fillRect(0, top, s.width, bottom - top);
  for (let i = 0; i < 145; i++) {
    const depth = seed(i * 7), y = top + depth * (bottom - top);
    const x = wrap(seed(i) * s.width + Math.sin(s.time * (0.45 + depth) + i) * (3 + s.weather.wind * 0.12), s.width);
    const light = s.night * (i % 7 === 0 ? 0.38 : 0.05);
    line(ctx, [[x, y], [x + 5 + depth * 40, y]],
      i % 7 === 0 ? `rgba(244,192,109,${light})` : s.color('6993ac', 'd4e5e3', 0.08 + depth * 0.09),
      0.5 + depth * (1 + s.weather.wind / 45));
  }
}

function lamps(ctx, s, count, y, height, start = 0, end = s.width) {
  for (let i = 0; i < count; i++) {
    const x = start + (end - start) * i / Math.max(1, count - 1);
    line(ctx, [[x, y], [x, y - height], [x + 6, y - height - 3]], s.color('273743', '58636a'), 1.5);
    ellipse(ctx, x + 7, y - height - 2, 3, 1.7, s.color('e4b976', 'd6d2b7'));
    if (s.night > 0.1) {
      glow(ctx, x + 7, y - height - 2, 25, s.night);
      if (s.weather.wet > 0) {
        ellipse(ctx, x + 7, y + 4, 3, 14, `rgba(243,193,111,${s.night * 0.12})`);
      }
    }
  }
}

function tree(ctx, s, x, y, size, index, species = s.nature.tree) {
  const palm = species === 'palm';
  const palette = foliagePalette(species, s.nature.season);
  const bare = s.nature.season === 'winter' && ['ginkgo', 'plane', 'maple'].includes(species);
  const bend = s.sway(index * 1.3) * size * 0.12;
  ctx.save(); ctx.translate(x, y);
  ctx.strokeStyle = s.color('1d2c2d', palm ? '685e4a' : species === 'plane' ? 'a5a58f' : '555b43');
  ctx.lineWidth = Math.max(2, size * 0.035);
  ctx.beginPath(); ctx.moveTo(0, 0);
  ctx.bezierCurveTo(bend * 0.1, -size * 0.4, bend * 0.7, -size * 0.8, bend, -size);
  ctx.stroke();
  if (palm) {
    for (let i = 0; i < 9; i++) {
      const angle = -Math.PI + i * Math.PI / 8;
      const reach = size * (0.34 + seed(i + index) * 0.14);
      const endX = bend + Math.cos(angle) * reach;
      const endY = -size + Math.sin(angle) * reach * 0.4 + size * 0.12;
      ctx.strokeStyle = s.color('1d3632', palette[i % palette.length]);
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(bend, -size);
      ctx.quadraticCurveTo(bend + Math.cos(angle) * reach * 0.65, -size - reach * 0.3, endX, endY); ctx.stroke();
      for (let leaf = 1; leaf < 9; leaf++) {
        const t = leaf / 9;
        const px = bend + (endX - bend) * t;
        const py = -size + (endY + size) * t - Math.sin(t * Math.PI) * reach * 0.35;
        line(ctx, [[px - 4, py + reach * 0.11], [px, py], [px + 4, py + reach * 0.11]], ctx.strokeStyle, 1);
      }
    }
  } else if (species === 'cypress' || species === 'evergreen') {
    for (let tier = 0; tier < 10; tier++) {
      const t = (tier + 1) / 11;
      const spread = size * t * (species === 'cypress' ? 0.16 : 0.23);
      const center = bend * (1 - t * 0.7), top = -size + size * t * 0.72;
      ctx.fillStyle = s.color('17352d', palette[tier % palette.length]);
      ctx.beginPath(); ctx.moveTo(center, top - size * 0.12);
      ctx.quadraticCurveTo(center - spread * 0.4, top, center - spread, top + size * 0.12);
      ctx.lineTo(center - spread * 0.35, top + size * 0.1);
      ctx.lineTo(center, top + size * 0.15);
      ctx.lineTo(center + spread, top + size * 0.12);
      ctx.quadraticCurveTo(center + spread * 0.4, top, center, top - size * 0.12);
      ctx.closePath(); ctx.fill();
      if (s.weather.snow) {
        line(ctx, [[center - spread * 0.75, top + size * 0.07], [center, top - size * 0.04],
          [center + spread * 0.75, top + size * 0.07]], s.color('9aaeb8', 'e1e9e3'), size * 0.015);
      }
    }
  } else {
    for (let branch = 0; branch < 5; branch++) {
      const direction = branch % 2 ? 1 : -1;
      line(ctx, [[bend * 0.4, -size * 0.5],
        [bend + direction * size * 0.19, -size * (0.8 + branch * 0.04)]],
      s.color('24382e', '596346'), Math.max(1, size * 0.012));
      if (bare) {
        const bx = bend + direction * size * 0.19, by = -size * (0.8 + branch * 0.04);
        for (let twig = 0; twig < 3; twig++) {
          line(ctx, [[bx, by], [bx + direction * size * (0.04 + twig * 0.025), by - size * (0.05 + twig * 0.035)]],
            s.color('324234', '6b6b56'), 0.7);
        }
      }
    }
    if (bare) { ctx.restore(); return; }
    const clusters = size > 90 ? 20 : 12;
    for (let i = 0; i < clusters; i++) {
      const dx = (seed(i + index * 13) - 0.5) * size * (species === 'ginkgo' ? 0.58 : 0.8);
      const dy = -size * (0.65 + seed(i * 11) * 0.45);
      const radius = size * (0.09 + seed(i) * 0.07);
      ctx.beginPath();
      for (let j = 0; j < 15; j++) {
        const angle = j * Math.PI * 2 / 15;
        const r = radius * (0.72 + seed(i * 17 + j) * 0.4);
        const px = bend + dx + Math.cos(angle) * r, py = dy + Math.sin(angle) * r * 0.8;
        if (j === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      }
      ctx.closePath();
      ctx.fillStyle = s.color('132f2c', palette[i % palette.length], 0.95);
      ctx.fill();
      for (let leaf = 0; leaf < (size > 90 ? 6 : 2); leaf++) {
        const lx = bend + dx + (seed(i * 7 + leaf) - 0.5) * radius * 1.6;
        const ly = dy + (seed(i * 19 + leaf) - 0.65) * radius;
        ctx.save(); ctx.translate(lx, ly); ctx.rotate(seed(i + leaf) * 2);
        leafPath(ctx, species, Math.max(1, size * 0.025));
        ctx.fillStyle = s.weather.snow && leaf < 3 ? s.color('b5c3cc', 'eaf0e7', 0.8)
          : s.color('355145', palette[(leaf + 1) % palette.length], 0.7);
        ctx.fill(); ctx.restore();
      }
    }
  }
  ctx.restore();
}

function boat(ctx, s, x, y, size = 1) {
  ctx.save(); ctx.translate(x, y); ctx.scale(size, size);
  polygon(ctx, [[-22, -6], [25, -6], [16, 2], [-14, 2]], s.color('192f3e', 'e4e6d9'));
  ctx.fillStyle = s.color('35475b', 'f3f1e5'); ctx.fillRect(-10, -15, 25, 9);
  ctx.fillStyle = s.color('e8c78b', '668d9f'); ctx.fillRect(-7, -13, 19, 3);
  line(ctx, [[-28, 4], [-48, 6]], s.color('7394a6', 'e1ece6', 0.5), 1);
  ctx.restore();
}

function road(ctx, s, top, bottom, taxi = false) {
  const gradient = ctx.createLinearGradient(0, top, 0, bottom);
  gradient.addColorStop(0, s.color('1d2c3b', '747c7c'));
  gradient.addColorStop(1, s.color('101f2e', s.weather.wet > 0 ? '475e69' : '4d5b62'));
  ctx.fillStyle = gradient; ctx.fillRect(0, top, s.width, bottom - top);
  for (let x = -20; x < s.width; x += 38) {
    line(ctx, [[x, (top + bottom) / 2], [x + 16, (top + bottom) / 2]], s.color('a1997c', 'd4cdb0', 0.65), 1);
  }
  if (s.weather.wet > 0) {
    for (let i = 0; i < 35; i++) {
      const y = top + seed(i * 3) * (bottom - top);
      line(ctx, [[seed(i) * s.width, y], [seed(i) * s.width + 12 + seed(i) * 40, y]],
        s.color('718596', 'b6cbd0', 0.16), 0.8);
    }
  }
  for (let i = 0; i < 10; i++) {
    const direction = i % 2 ? 1 : -1;
    const x = wrap(seed(i + 11) * s.width + s.time * (14 + seed(i) * 12) * direction, s.width + 50) - 25;
    const y = top + (bottom - top) * (direction > 0 ? 0.34 : 0.72);
    ctx.fillStyle = taxi && i % 3 === 0 ? s.color('8a7136', 'cba94b') : s.color('2c3949', i % 2 ? 'bfc5bd' : '526b7a');
    ctx.fillRect(x, y - 4, 17, 5);
    ctx.fillRect(x + 4, y - 7, 9, 3);
    ctx.fillStyle = s.color('516474', '90afb6');
    ctx.fillRect(x + 5, y - 6, 6, 2);
    ellipse(ctx, x + 3, y + 1, 1.6, 1.3, '#202d32');
    ellipse(ctx, x + 13, y + 1, 1.6, 1.3, '#202d32');
    if (s.night > 0.1 || s.weather.wet > 0) {
      const front = direction > 0 ? x + 17 : x;
      ellipse(ctx, front, y - 2, 2, 1, '#fff0bd');
      ellipse(ctx, direction > 0 ? x : x + 17, y - 2, 1.5, 1, '#dd7863');
      if (s.weather.wet > 0) ellipse(ctx, front, y + 6, 8, 2, '#f2d89a25');
    }
  }
}

function mumbai(ctx, s) {
  skyline(ctx, s, true);
  water(ctx, s, s.horizon);
  const shore = s.height * 0.88;
  polygon(ctx, [[0, shore - 25], [s.width * 0.55, shore - 12], [s.width, shore + 8], [s.width, s.height], [0, s.height]],
    s.color('263742', 'b6ad96'));
  // A composed waterfront view, not a literal sightline between Marine Drive and the Gateway.
  road(ctx, s, shore + 28, s.height * 0.985, true);
  line(ctx, [[0, shore - 25], [s.width * 0.55, shore - 12], [s.width, shore + 8]], s.color('647079', 'e2d9be'), 5);
  lamps(ctx, s, 18, shore + 16, s.height * 0.045);
  ctx.save(); ctx.translate(s.heroX, shore - 4); ctx.scale(s.heroSize, s.heroSize);
  const stone = ctx.createLinearGradient(-0.4, -0.8, 0.4, 0);
  stone.addColorStop(0, s.color('625744', 'd4ba82'));
  stone.addColorStop(0.6, s.color('453d32', 'b59a68'));
  stone.addColorStop(1, s.color('35352f', '8b7b5b'));
  const dark = s.color('13232a', '665d49');
  for (const x of [-0.19, 0.19]) {
    ctx.fillStyle = stone; ctx.fillRect(x - 0.035, -0.8, 0.07, 0.18);
    ctx.beginPath(); ctx.moveTo(x - 0.045, -0.81);
    ctx.quadraticCurveTo(x, -0.92, x + 0.045, -0.81); ctx.closePath(); ctx.fill();
    line(ctx, [[x - 0.045, -0.81], [x + 0.045, -0.81]], s.color('a48c60', 'e7d19c'), 0.009);
  }
  ctx.fillStyle = stone; ctx.fillRect(-0.38, -0.62, 0.76, 0.59);
  ctx.fillRect(-0.42, -0.12, 0.84, 0.12);
  ctx.fillRect(-0.4, -0.67, 0.8, 0.06);
  // Deep, pointed central arch with an inset sandstone rim.
  ctx.fillStyle = dark;
  ctx.beginPath(); ctx.moveTo(-0.135, -0.03); ctx.lineTo(-0.135, -0.32);
  ctx.quadraticCurveTo(-0.135, -0.44, 0, -0.51);
  ctx.quadraticCurveTo(0.135, -0.44, 0.135, -0.32);
  ctx.lineTo(0.135, -0.03); ctx.closePath(); ctx.fill();
  ctx.strokeStyle = s.color('9e8a65', 'ead4a2'); ctx.lineWidth = 0.012;
  ctx.beginPath(); ctx.moveTo(-0.15, -0.03); ctx.lineTo(-0.15, -0.32);
  ctx.quadraticCurveTo(-0.15, -0.45, 0, -0.53);
  ctx.quadraticCurveTo(0.15, -0.45, 0.15, -0.32); ctx.lineTo(0.15, -0.03); ctx.stroke();
  for (const side of [-1, 1]) {
    const x = side * 0.23;
    ctx.fillStyle = s.color('323931', '82704d');
    ctx.beginPath(); ctx.moveTo(x - 0.025, -0.13); ctx.lineTo(x - 0.025, -0.34);
    ctx.quadraticCurveTo(x, -0.4, x + 0.025, -0.34);
    ctx.lineTo(x + 0.025, -0.13); ctx.closePath(); ctx.fill();
  }
  for (const side of [-1, 1]) {
    ctx.fillStyle = stone; ctx.fillRect(side * 0.29 - 0.055, -0.8, 0.11, 0.73);
    ellipse(ctx, side * 0.29, -0.81, 0.078, 0.018, s.color('806d4d', 'dec593'));
    ctx.beginPath(); ctx.moveTo(side * 0.29 - 0.06, -0.82);
    ctx.quadraticCurveTo(side * 0.29, -0.98, side * 0.29 + 0.06, -0.82); ctx.closePath();
    ctx.fillStyle = stone; ctx.fill();
    line(ctx, [[side * 0.29, -0.92], [side * 0.29, -0.98]], s.color('867651', 'd4b779'), 0.009);
    ctx.fillStyle = dark;
    for (let i = 0; i < 3; i++) ctx.fillRect(side * 0.23 + (i - 1) * 0.026 - 0.009, -0.57, 0.015, 0.07);
  }
  for (let row = 0; row < 22; row++) {
    const y = -0.58 + row * 0.025;
    for (const [left, right] of y < -0.53 ? [[-0.37, 0.37]] : [[-0.37, -0.16], [0.16, 0.37]]) {
      line(ctx, [[left, y], [right, y]], s.color('b6a281', 'ecdbad', 0.12), 0.001);
    }
    for (let block = 0; block < 8; block++) {
      const x = -0.37 + block * 0.1 + (row % 2) * 0.05;
      if (Math.abs(x) > 0.16 || y < -0.53) line(ctx, [[x, y], [x, y + 0.025]],
        s.color('71664c', '847351', 0.23), 0.001);
    }
  }
  ctx.fillStyle = stone; ctx.fillRect(-0.17, -0.76, 0.34, 0.09);
  for (let i = 0; i < 38; i++) {
    ctx.fillStyle = s.color('877552', 'e0ca96'); ctx.fillRect(-0.38 + i * 0.02, -0.685, 0.009, 0.02);
  }
  ctx.fillStyle = s.color('8c7852', 'cfb27a'); ctx.fillRect(-0.38, -0.7, 0.76, 0.013);
  for (let i = 0; i < 12; i++) {
    ctx.fillStyle = s.color('655a42', '9c855c'); ctx.fillRect(-0.13 + i * 0.022, -0.72, 0.012, 0.004);
  }
  if (s.night > 0.1) {
    for (const side of [-1, 1]) glow(ctx, side * 0.28, -0.1, 0.34, s.night * 0.65);
  }
  ctx.restore();
  for (let i = 0; i < 5; i++) tree(ctx, s, s.width * (0.04 + i * 0.09), shore - 18, s.height * (0.1 + seed(i) * 0.08), i);
  if (s.weather.wet < 2 && !s.weather.fog) {
    boat(ctx, s, wrap(s.width * 0.25 + s.time * 6, s.width), s.horizon + (shore - s.horizon) * 0.55, 0.8);
  }
}

function latticeTower(ctx, s, tokyo) {
  ctx.save(); ctx.translate(s.heroX, s.horizon + 6); ctx.scale(s.heroSize, s.heroSize);
  const steel = tokyo ? s.color('a75039', 'c96340') : s.color('625c49', '777261');
  const white = s.color('9e9385', 'eee6d4');
  const levels = [
    { y: 0, half: 0.28 }, { y: -0.26, half: 0.15 },
    { y: -0.49, half: 0.073 }, { y: -0.76, half: 0.031 }, { y: -0.94, half: 0.006 },
  ];
  // Open lattice legs and recognizable viewing platforms, not a filled triangle.
  for (let i = 0; i < levels.length - 1; i++) {
    const a = levels[i], b = levels[i + 1];
    for (const side of [-1, 1]) {
      polygon(ctx, [[side * a.half, a.y], [side * (a.half - 0.035), a.y],
        [side * Math.max(0, b.half - 0.013), b.y], [side * b.half, b.y]], tokyo && i % 2 ? white : steel);
    }
    const count = i === 0 ? 6 : 5;
    for (let j = 0; j < count; j++) {
      const t = j / count, next = (j + 1) / count;
      const y = a.y + (b.y - a.y) * t, ny = a.y + (b.y - a.y) * next;
      const half = a.half + (b.half - a.half) * t, nh = a.half + (b.half - a.half) * next;
      const color = tokyo && (i + j) % 4 === 2 ? white : steel;
      if (i === 0 && !tokyo) {
        for (const side of [-1, 1]) {
          line(ctx, [[side * half, y], [side * (nh - 0.04), ny]], color, 0.003);
          line(ctx, [[side * (half - 0.05), y], [side * nh, ny]], color, 0.003);
        }
      } else {
        line(ctx, [[-half, y], [nh, ny]], color, 0.003);
        line(ctx, [[half, y], [-nh, ny]], color, 0.003);
        line(ctx, [[-half, y], [half, y]], color, 0.003);
      }
    }
  }
  if (!tokyo) {
    ctx.strokeStyle = steel; ctx.lineWidth = 0.022;
    ctx.beginPath(); ctx.moveTo(-0.23, -0.02);
    ctx.bezierCurveTo(-0.16, -0.3, 0.16, -0.3, 0.23, -0.02); ctx.stroke();
  }
  for (const [y, half] of tokyo ? [[-0.46, 0.105], [-0.74, 0.055]] : [[-0.25, 0.17], [-0.49, 0.09], [-0.79, 0.04]]) {
    ctx.fillStyle = tokyo ? white : steel;
    ctx.fillRect(-half, y - 0.015, half * 2, 0.025);
    if (s.weather.snow) line(ctx, [[-half, y - 0.015], [half, y - 0.015]], s.color('abb9c5', 'edf2ee'), 0.006);
    ctx.fillStyle = s.color('353e47', 'a6bdc2'); ctx.fillRect(-half * 0.8, y - 0.01, half * 1.6, 0.008);
    if (s.night > 0.05) line(ctx, [[-half, y], [half, y]], `rgba(255,198,108,${s.night})`, 0.008);
  }
  line(ctx, [[0, -0.92], [0, -1.05]], tokyo ? white : steel, 0.006);
  ellipse(ctx, 0, -1.05, 0.006, 0.006, '#dc9a75');
  if (s.night > 0.05) {
    ctx.globalAlpha = s.night * 0.75;
    for (let i = 0; i < 24; i++) {
      const t = i / 24, y = -t * 0.94, half = 0.27 * (1 - t) ** 2 + 0.006;
      for (const side of [-1, 1]) ellipse(ctx, side * half, y, 0.003, 0.004, '#ffd48c');
    }
  }
  ctx.restore();
}

function tokyo(ctx, s) {
  skyline(ctx, s);
  ctx.fillStyle = s.color('1c302c', '466c4e');
  ctx.fillRect(0, s.horizon, s.width, s.height - s.horizon);
  latticeTower(ctx, s, true);
  for (let i = 0; i < 12; i++) tree(ctx, s, i * s.width / 11, s.horizon + 22, s.height * 0.045, i);
  road(ctx, s, s.height * 0.81, s.height * 0.87);
  ctx.fillStyle = s.color('20303e', 'b0b3a5'); ctx.fillRect(0, s.height * 0.87, s.width, s.height * 0.13);
  // Nearer office facades, roof equipment, and restrained signs frame the tower.
  for (let i = 0; i < 5; i++) {
    const x = s.width * (i < 3 ? i * 0.075 : 0.82 + (i - 3) * 0.1);
    const h = s.height * (0.18 + seed(i * 3) * 0.08);
    building(ctx, x, s.height * 0.91, s.width * 0.067, h, i + 71, s);
    ctx.fillStyle = s.color('425260', 'bbc2ba');
    ctx.fillRect(x + 4, s.height * 0.91 - h - 4, 12, 4);
    if (s.night > 0.1) {
      ctx.fillStyle = `rgba(${i % 2 ? '228,124,111' : '117,190,204'},${s.night * 0.7})`;
      ctx.fillRect(x + 6, s.height * 0.91 - h + 12, 4, h * 0.35);
    }
  }
  lamps(ctx, s, 12, s.height * 0.89, s.height * 0.045);
  for (const x of [s.width * 0.06, s.width * 0.94]) tree(ctx, s, x, s.height, s.height * 0.19, x);
}

function paris(ctx, s) {
  // Low limestone blocks and mansard roofs preserve the tower's silhouette.
  for (let i = 0; i < 22; i++) {
    const x = i * s.width / 21 - 20, w = s.width / 21;
    const h = s.height * (0.05 + seed(i) * 0.045);
    building(ctx, x, s.horizon, w, h, i, s, true);
    polygon(ctx, [[x - 2, s.horizon - h], [x + 5, s.horizon - h - 10],
      [x + w - 5, s.horizon - h - 10], [x + w + 2, s.horizon - h]], s.color('273445', '67757f'));
    ctx.fillStyle = s.color('3c3a39', 'b8a691'); ctx.fillRect(x + w * 0.7, s.horizon - h - 15, 4, 8);
  }
  latticeTower(ctx, s, false);
  water(ctx, s, s.horizon + 10);
  const bridgeY = s.height * 0.81;
  ctx.fillStyle = s.color('4b4c49', 'b1a58e');
  ctx.fillRect(0, bridgeY, s.width, 12);
  for (let i = 0; i < 7; i++) {
    const x = i * s.width / 6, span = s.width / 6;
    ctx.lineWidth = 9; ctx.strokeStyle = s.color('3d4447', 'a39780');
    ctx.beginPath(); ctx.moveTo(x, bridgeY + 36);
    ctx.quadraticCurveTo(x + span / 2, bridgeY - 6, x + span, bridgeY + 36); ctx.stroke();
    ctx.fillRect(x - 5, bridgeY + 10, 10, 33);
  }
  line(ctx, [[0, bridgeY - 8], [s.width, bridgeY - 8]], s.color('646a65', 'd2c8ae'), 2);
  for (let x = 0; x < s.width; x += 13) line(ctx, [[x, bridgeY - 8], [x, bridgeY]], s.color('455458', '8f9b94'), 1);
  lamps(ctx, s, 11, bridgeY, s.height * 0.035);
  polygon(ctx, [[0, s.height * 0.94], [s.width, s.height * 0.9], [s.width, s.height], [0, s.height]], s.color('273b41', 'ada78e'));
  for (let i = 0; i < 8; i++) tree(ctx, s, i * s.width / 7, s.height * 0.95, s.height * (0.06 + seed(i) * 0.05), i);
  if (s.weather.wet < 2 && !s.weather.fog) boat(ctx, s, wrap(s.width * 0.4 + s.time * 7, s.width + 100) - 50, s.height * 0.88, 1.2);
}

function temple(ctx, s) {
  ctx.save(); ctx.translate(s.heroX, s.horizon + s.height * 0.07); ctx.scale(s.heroSize, s.heroSize);
  for (let tier = 0; tier < 3; tier++) {
    const half = 0.47 - tier * 0.045, y = -tier * 0.035;
    ellipse(ctx, 0, y, half, half * 0.14, s.color('6c7278', 'e4dfcd'));
    ctx.fillStyle = s.color('626b76', 'c9c8b9'); ctx.fillRect(-half, y - 0.035, half * 2, 0.035);
    for (let i = 0; i < 27; i++) {
      const x = -half + i * half * 2 / 26;
      line(ctx, [[x, y - 0.04], [x, y - 0.065]], s.color('91969a', 'f3edda'), 0.006);
    }
    ellipse(ctx, 0, y - 0.035, half, half * 0.12, s.color('858b91', 'f3edda'));
  }
  // Red colonnades and three separate blue glazed circular roofs.
  for (let tier = 0; tier < 3; tier++) {
    const y = -0.16 - tier * 0.205, half = 0.32 - tier * 0.064;
    ctx.fillStyle = s.color('5b2c2c', '9c3e30');
    ctx.fillRect(-half * 0.72, y - 0.14, half * 1.44, 0.17);
    ellipse(ctx, 0, y + 0.03, half * 0.74, 0.02, s.color('603331', 'ba5640'));
    for (let col = -3; col <= 3; col++) {
      const x = col * half * 0.2;
      ctx.fillStyle = s.color('a16040', 'e19464'); ctx.fillRect(x - 0.008, y - 0.14, 0.012, 0.17);
      if (col > -3 && col < 3) {
        ctx.fillStyle = s.color('292e38', '5c4d43');
        ctx.fillRect(x + 0.01, y - 0.09, half * 0.12, 0.085);
        line(ctx, [[x + 0.013, y - 0.07], [x + half * 0.12, y - 0.07]],
          s.color('866a49', 'cdb674'), 0.003);
        for (let bar = 0; bar < 3; bar++) {
          const bx = x + 0.017 + bar * half * 0.033;
          line(ctx, [[bx, y - 0.085], [bx, y - 0.015]], s.color('6f4739', 'b48b5e'), 0.002);
        }
      }
    }
    const roof = ctx.createLinearGradient(0, y - 0.31, 0, y - 0.1);
    roof.addColorStop(0, s.color('29435d', '3e7890'));
    roof.addColorStop(0.55, s.color('173652', '285771'));
    roof.addColorStop(1, s.color('102c47', '173f58'));
    ctx.beginPath(); ctx.moveTo(-half * 1.16, y - 0.1);
    ctx.bezierCurveTo(-half * 0.65, y - 0.1, -half * 0.3, y - 0.27, 0, y - 0.29);
    ctx.bezierCurveTo(half * 0.3, y - 0.27, half * 0.65, y - 0.1, half * 1.16, y - 0.1);
    ctx.quadraticCurveTo(0, y - 0.04, -half * 1.16, y - 0.1);
    ctx.closePath(); ctx.fillStyle = roof; ctx.fill();
    for (let tile = -10; tile <= 10; tile++) {
      const x = tile * half * 0.105;
      ctx.strokeStyle = s.color('547083', '72a4ad', 0.45); ctx.lineWidth = 0.002;
      ctx.beginPath(); ctx.moveTo(x * 0.15, y - 0.275);
      ctx.quadraticCurveTo(x * 0.5, y - 0.16, x, y - 0.095); ctx.stroke();
    }
    ctx.strokeStyle = s.weather.snow ? s.color('acbdc9', 'edf4ee') : s.color('8b875c', 'd0bb76');
    ctx.lineWidth = s.weather.snow ? 0.012 : 0.006;
    ctx.beginPath(); ctx.ellipse(0, y - 0.1, half * 1.16, half * 0.11, 0, 0, Math.PI); ctx.stroke();
    for (let detail = -10; detail <= 10; detail++) {
      const x = detail * half * 0.105;
      ellipse(ctx, x, y - 0.1 + half * 0.09 * Math.sqrt(Math.max(0, 1 - (x / (half * 1.16)) ** 2)),
        0.004, 0.003, s.color('9f986b', 'dec889'));
    }
    if (s.night > 0.1) glow(ctx, 0, y + 0.015, half, s.night * 0.32);
  }
  ellipse(ctx, 0, -0.9, 0.022, 0.027, s.color('bca25a', 'e5c365'));
  line(ctx, [[0, -0.9], [0, -0.97]], s.color('c6ab65', 'f3d577'), 0.008);
  polygon(ctx, [[-0.1, -0.015], [0.1, -0.015], [0.2, 0.1], [-0.2, 0.1]], s.color('828991', 'e1dfd0'));
  for (let i = 0; i < 5; i++) line(ctx, [[-0.12 - i * 0.015, 0.005 + i * 0.02], [0.12 + i * 0.015, 0.005 + i * 0.02]],
    s.color('666f7c', 'b9bfba'), 0.004);
  ctx.restore();
}

function beijing(ctx, s) {
  ctx.fillStyle = s.color('182f2c', '486b4d');
  ctx.fillRect(0, s.horizon - s.height * 0.035, s.width, s.height);
  for (let i = 0; i < 35; i++) {
    const x = i * s.width / 34;
    tree(ctx, s, x, s.horizon + 15, s.height * (0.055 + seed(i) * 0.04), i);
  }
  const courtyard = ctx.createLinearGradient(0, s.horizon, 0, s.height);
  courtyard.addColorStop(0, s.color('485461', 'c6c6b5'));
  courtyard.addColorStop(1, s.color('293e4d', s.weather.wet > 0 ? '788e94' : 'a6ada5'));
  ctx.fillStyle = courtyard; ctx.fillRect(0, s.horizon, s.width, s.height - s.horizon);
  for (let i = -10; i <= 10; i++) {
    line(ctx, [[s.heroX + i * 14, s.horizon], [s.heroX + i * s.width * 0.11, s.height]],
      s.color('687784', 'e2e0cd', 0.3), 1);
  }
  for (let i = 0; i < 10; i++) {
    const y = s.horizon + (s.height - s.horizon) * (i / 9) ** 1.8;
    line(ctx, [[0, y], [s.width, y]], s.color('687784', 'e2e0cd', 0.3), 1);
  }
  temple(ctx, s);
  for (const side of [0.04, 0.94]) tree(ctx, s, s.width * side, s.height * 0.99, s.height * 0.23, side * 17, 'ginkgo');
  if (s.weather.wet > 0) {
    const rainReflection = ctx.createLinearGradient(0, s.horizon, 0, s.height);
    rainReflection.addColorStop(0, s.color('6d808d', 'd1dce0', 0.02));
    rainReflection.addColorStop(1, s.color('6d808d', 'd1dce0', 0.13));
    ctx.fillStyle = rainReflection; ctx.fillRect(s.width * 0.2, s.height * 0.9, s.width * 0.6, s.height * 0.1);
  }
}

function newYork(ctx, s) {
  skyline(ctx, s);
  // Stepped Art Deco silhouette and a slender downtown spire anchor Manhattan.
  for (const [ratio, tall] of [[0.18, 0.28], [0.36, 0.23]]) {
    const x = s.width * ratio, h = s.height * tall, w = Math.min(42, s.width * 0.045);
    building(ctx, x, s.horizon, w, h, ratio * 100, s);
    for (let step = 0; step < 3; step++) {
      ctx.fillStyle = s.color('2d4055', '8a9ca5');
      ctx.fillRect(x + step * w * 0.1, s.horizon - h - step * 9, w * (1 - step * 0.2), 10);
    }
    line(ctx, [[x + w / 2, s.horizon - h - 18], [x + w / 2, s.horizon - h - 55]],
      s.color('73808e', 'bcc7c6'), 2);
  }
  water(ctx, s, s.horizon + 8);
  const deck = s.height * 0.84;
  const towerHeight = Math.min(s.height * 0.3, s.width * 0.42);
  const left = s.width * (s.width < 700 ? 0.18 : 0.57);
  const right = s.width * (s.width < 700 ? 0.8 : 0.86);
  ctx.fillStyle = s.color('383e46', '9c9587'); ctx.fillRect(0, deck, s.width, 10);
  line(ctx, [[0, deck - 8], [s.width, deck - 8]], s.color('79818a', 'd2c6ad'), 1.5);
  for (const x of [left, right]) {
    const w = Math.min(56, s.width * 0.1);
    const top = deck - towerHeight;
    ctx.fillStyle = s.color('625b50', 'b2a083');
    ctx.fillRect(x - w / 2, top, w, towerHeight + 20);
    ctx.fillStyle = s.color('8e7c61', 'd3bc94');
    ctx.fillRect(x - w * 0.57, top - 8, w * 1.14, 9);
    ctx.fillRect(x - w * 0.55, top + 14, w * 1.1, 5);
    for (const side of [-1, 1]) {
      const center = x + side * w * 0.23;
      ctx.fillStyle = s.color('162e42', '7798a5');
      ctx.beginPath(); ctx.moveTo(center - w * 0.13, deck - 5);
      ctx.lineTo(center - w * 0.13, top + 44);
      ctx.lineTo(center, top + 26); ctx.lineTo(center + w * 0.13, top + 44);
      ctx.lineTo(center + w * 0.13, deck - 5); ctx.closePath(); ctx.fill();
    }
    for (let y = top + 22; y < deck; y += 9) line(ctx, [[x - w / 2, y], [x + w / 2, y]], s.color('b4a07c', 'ecdbb5', 0.18), 0.8);
    if (s.night > 0.1) glow(ctx, x, top + 10, w * 1.2, s.night * 0.6);
  }
  const anchors = [[-s.width * 0.12, deck], [left, deck - towerHeight], [right, deck - towerHeight], [s.width * 1.15, deck]];
  for (let segment = 0; segment < anchors.length - 1; segment++) {
    const [ax, ay] = anchors[segment], [bx, by] = anchors[segment + 1];
    const midY = segment === 1 ? deck - towerHeight * 0.16 : (ay + by) / 2 + towerHeight * 0.15;
    ctx.strokeStyle = s.color('8e989e', 'e0d7bc'); ctx.lineWidth = 1.6;
    ctx.beginPath(); ctx.moveTo(ax, ay); ctx.quadraticCurveTo((ax + bx) / 2, midY, bx, by); ctx.stroke();
    for (let i = 0; i <= 22; i++) {
      const t = i / 22, x = ax + (bx - ax) * t;
      const y = (1 - t) ** 2 * ay + 2 * (1 - t) * t * midY + t ** 2 * by;
      line(ctx, [[x, y], [x, deck]], s.color('84939b', 'bcc4bc', 0.7), 0.65);
    }
  }
  road(ctx, s, deck + 2, deck + 10, true);
  if (s.weather.wet < 2 && !s.weather.fog) boat(ctx, s, wrap(s.width * 0.2 + s.time * 9, s.width + 80) - 40, s.height * 0.92, 1.25);
  ctx.fillStyle = s.color('1c3439', '667977'); ctx.fillRect(0, s.height * 0.975, s.width, s.height * 0.025);
  for (let i = 0; i < 5; i++) tree(ctx, s, i * s.width / 4, s.height, s.height * 0.09, i);
}

const renderers = { mumbai, tokyo, paris, beijing, 'new-york': newYork };

export function drawCityScene(ctx, { city, width, height, weather, light, time, sway, nature = cityNature(city) }) {
  const render = renderers[city.id];
  if (!render) throw new Error(`No city renderer for ${city.id}`);
  const portrait = width < 700;
  const scene = {
    city, width, height, weather, light, time, sway, nature,
    horizon: height * 0.73,
    heroX: width * (portrait ? 0.53 : city.id === 'paris' ? 0.27 : 0.66),
    heroSize: Math.min(height * 0.48, width * (portrait ? 0.82 : 0.36)),
    night: Math.min(1, 1 - light.daylight + weather.cloud * 0.08),
    color: (night, day, alpha = 1) => blendColor(night, day, light.brightness, alpha),
  };
  ctx.save();
  ctx.globalAlpha = weather.fog ? 0.65 : 1;
  render(ctx, scene);
  ctx.restore();
}
