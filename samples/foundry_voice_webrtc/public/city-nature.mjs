const PROFILES = Object.freeze({
  seattle: Object.freeze({ bird: 'gull', tree: 'evergreen', leaf: 'maple', label: 'Gulls, evergreens & maples' }),
  mumbai: Object.freeze({ bird: 'kite', tree: 'palm', leaf: 'palm', label: 'Black kites & palms' }),
  tokyo: Object.freeze({ bird: 'sparrow', tree: 'ginkgo', leaf: 'ginkgo', label: 'Sparrows & ginkgo' }),
  paris: Object.freeze({ bird: 'pigeon', tree: 'plane', leaf: 'plane', label: 'Pigeons & plane trees' }),
  beijing: Object.freeze({ bird: 'magpie', tree: 'cypress', leaf: 'ginkgo', label: 'Magpies, cypresses & ginkgo' }),
  'new-york': Object.freeze({ bird: 'pigeon', tree: 'maple', leaf: 'maple', label: 'Pigeons & maples' }),
});

const monthFormatters = new Map();
const wrap = (value, size) => ((value % size) + size) % size;
const seed = i => ((i * 7919 + 173) % 1009) / 1009;
const smoothstep = (low, high, value) => {
  const t = Math.max(0, Math.min(1, (value - low) / (high - low)));
  return t * t * (3 - 2 * t);
};

export function cityNature(city, date = new Date()) {
  const profile = PROFILES[city.id];
  if (!profile) throw new Error(`Unknown nature profile: ${city.id}`);
  if (!Number.isFinite(date.getTime())) throw new Error('City nature requires a valid date');
  if (!monthFormatters.has(city.timezone)) {
    monthFormatters.set(city.timezone, new Intl.DateTimeFormat('en', { month: 'numeric', timeZone: city.timezone }));
  }
  const month = Number(monthFormatters.get(city.timezone).format(date));
  const season = city.id === 'mumbai' ? 'tropical'
    : month >= 9 && month <= 11 ? 'autumn'
      : month >= 6 && month <= 8 ? 'summer' : month >= 3 && month <= 5 ? 'spring' : 'winter';
  return { ...profile, season };
}

export function foliagePalette(species, season) {
  switch (species) {
    case 'palm': return ['426b4c', '63854d', '3b654b'];
    case 'cypress': return ['284c3f', '3c6250', '355744'];
    case 'evergreen': return ['294c3d', '42634a', '365641'];
    case 'ginkgo': return season === 'autumn' ? ['d3ae3c', 'e9c85d', 'b99c3b'] : ['658d46', '8ca953', '527d42'];
    case 'plane': return season === 'autumn' ? ['ae7b3e', 'c69a50', '99804c'] : ['527244', '7e9255', '466b46'];
    case 'maple': return season === 'autumn' ? ['b5593e', 'd18b42', 'a7753b'] : ['4f7744', '7e9652', '466c43'];
    default: throw new Error(`Unknown foliage species: ${species}`);
  }
}

export function leafCount(nature, weather) {
  if (weather.snow || weather.wind < 6 || nature.season === 'winter') return 0;
  if (nature.leaf === 'palm') return weather.wind < 18 ? 0 : Math.min(3, Math.floor(weather.wind / 12));
  if (nature.season !== 'autumn') return weather.wind < 28 ? 0 : 2;
  return Math.min(14, 2 + Math.floor(weather.wind / 3));
}

export function birdsVisible(weather, light) {
  return weather.day && light.daylight > 0.25 && !weather.fog &&
    !weather.snow && weather.wet < 0.8 && weather.wind < 45;
}

export function gullPose(time, bird = 0) {
  const orbit = time * 0.13 + bird * 2.1;
  const depth = (Math.sin(orbit) + 1) / 2;
  const cycle = (time + bird) % 9;
  const flapping = smoothstep(0, 0.6, cycle) * (1 - smoothstep(2, 3, cycle));
  return {
    x: 0.5 + Math.sin(orbit) * 0.35,
    y: 0.38 + Math.sin(orbit * 2 + bird) * 0.08,
    scale: 0.55 + depth * 0.45,
    bank: Math.cos(orbit) * 0.3,
    wing: -2 + flapping * (Math.sin(time * 5 + bird) * 7 + 2),
  };
}

export function birdPose(species, time, bird = 0) {
  if (species === 'gull') return gullPose(time, bird);
  const orbit = time * (species === 'kite' ? 0.075 : 0.16) + bird * 1.7;
  const depth = (Math.sin(orbit) + 1) / 2;
  const cycle = (time + bird * 0.7) % 14;
  const soaring = smoothstep(0, 0.6, cycle) * (1 - smoothstep(1.7, 2.5, cycle));
  const position = {
    x: 0.5 + Math.sin(orbit) * 0.4,
    y: (species === 'kite' ? 0.29 : 0.49) + Math.sin(orbit * 2 + bird) * 0.055,
    scale: 0.55 + depth * 0.4,
    bank: Math.cos(orbit) * 0.22,
  };
  switch (species) {
    case 'kite': return { ...position, wing: -3 + soaring * Math.sin(time * 3.8 + bird) * 5 };
    case 'sparrow': return { ...position, wing: Math.sin(time * 13 + bird) * 7 };
    case 'pigeon': return { ...position, wing: Math.sin(time * 8 + bird) * 9 };
    case 'magpie': return { ...position, wing: -1 + Math.sin(time * 5.2 + bird) * 8 };
    default: throw new Error(`Unknown bird species: ${species}`);
  }
}

function ellipse(ctx, x, y, rx, ry, fill) {
  ctx.fillStyle = fill;
  ctx.beginPath(); ctx.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2); ctx.fill();
}

function bird(ctx, species, wing, color) {
  const gull = species === 'gull', kite = species === 'kite';
  const sparrow = species === 'sparrow', magpie = species === 'magpie';
  const span = gull || kite ? 23 : sparrow ? 12 : 17;
  const feather = color('334658', gull ? 'e7ece8' : kite ? '68513b' : sparrow ? '8e7154' : magpie ? '243b48' : '83939d');
  const dark = color('1c2b39', kite ? '3a3028' : '30424d');
  const tail = magpie ? 22 : kite ? 12 : sparrow ? 7 : 9;
  ctx.fillStyle = dark;
  ctx.beginPath(); ctx.moveTo(-2, 3); ctx.lineTo(-4, tail);
  if (kite) ctx.lineTo(0, tail - 5);
  ctx.lineTo(4, tail); ctx.lineTo(2, 3); ctx.closePath(); ctx.fill();
  for (const side of [-1, 1]) {
    ctx.fillStyle = feather;
    ctx.beginPath(); ctx.moveTo(0, -3);
    ctx.quadraticCurveTo(side * span * 0.5, wing - 5, side * span, wing);
    ctx.quadraticCurveTo(side * span * 0.66, wing + (kite ? 3 : 7), 0, 4);
    ctx.closePath(); ctx.fill();
    if (gull || kite) {
      ctx.fillStyle = dark;
      for (let finger = 0; finger < (kite ? 4 : 1); finger++) {
        ctx.beginPath(); ctx.moveTo(side * (span - 6 - finger), wing - 1 + finger);
        ctx.lineTo(side * (span + 1 - finger), wing + finger * 1.4);
        ctx.lineTo(side * (span - 6 - finger), wing + 3 + finger); ctx.closePath(); ctx.fill();
      }
    } else if (magpie) {
      ellipse(ctx, side * span * 0.55, wing + 1, 4, 2, color('8c9ca3', 'e9eee7'));
    } else {
      ctx.strokeStyle = dark; ctx.lineWidth = sparrow ? 0.7 : 1.2;
      for (let bar = 0; bar < 2; bar++) {
        ctx.beginPath(); ctx.moveTo(side * (span * 0.4 + bar * 3), wing - 1);
        ctx.lineTo(side * (span * 0.5 + bar * 3), wing + 3); ctx.stroke();
      }
    }
  }
  ellipse(ctx, 0, 0, sparrow ? 2.7 : 3.5, 6, feather);
  if (magpie) ellipse(ctx, 0, 2, 2.2, 3, color('8c9ca3', 'eef1e8'));
  ellipse(ctx, 0, -6, sparrow ? 2.5 : 3, 3, sparrow ? color('483d31', '6c503c') : feather);
  if (species === 'pigeon') ellipse(ctx, 0, -3.4, 2.5, 1.4, color('293c40', '587971'));
  ctx.fillStyle = gull ? color('82775c', 'ccaa62') : dark;
  ctx.beginPath(); ctx.moveTo(-1, -8); ctx.lineTo(0, -11); ctx.lineTo(1, -8); ctx.fill();
}

export function drawCityBirds(ctx, { nature, width, height, weather, light, time, color }) {
  if (!birdsVisible(weather, light)) return;
  const count = nature.bird === 'kite' || nature.bird === 'magpie' ? 2 : nature.bird === 'sparrow' ? 6 : 4;
  for (let i = 0; i < count; i++) {
    const pose = birdPose(nature.bird, time, i);
    const next = birdPose(nature.bird, time + 0.01, i);
    const heading = Math.atan2((next.y - pose.y) * height, (next.x - pose.x) * width) + Math.PI / 2;
    const scale = pose.scale * Math.max(0.6, Math.min(1, width / 1000));
    ctx.save(); ctx.translate(pose.x * width, pose.y * height);
    ctx.rotate(heading + pose.bank); ctx.scale(scale, scale);
    bird(ctx, nature.bird, pose.wing, color);
    ctx.restore();
  }
}

// Paths are shared by tree details and airborne leaves, so city species match.
export function leafPath(ctx, shape, size) {
  ctx.beginPath();
  if (shape === 'ginkgo') {
    ctx.moveTo(0, size * 0.75); ctx.lineTo(-size * 0.12, size * 0.25);
    ctx.bezierCurveTo(-size * 1.1, size * 0.05, -size, -size * 0.75, -size * 0.12, -size * 0.65);
    ctx.lineTo(0, -size * 0.45); ctx.lineTo(size * 0.12, -size * 0.65);
    ctx.bezierCurveTo(size, -size * 0.75, size * 1.1, size * 0.05, size * 0.12, size * 0.25);
  } else if (shape === 'palm') {
    ctx.moveTo(-size, 0);
    ctx.bezierCurveTo(-size * 0.2, -size * 0.35, size * 0.55, -size * 0.12, size, size * 0.1);
    ctx.bezierCurveTo(size * 0.2, size * 0.15, -size * 0.5, size * 0.3, -size, 0);
  } else if (shape === 'maple' || shape === 'plane') {
    const points = shape === 'maple'
      ? [[0, .8], [-.1, .3], [-.65, .35], [-.48, .05], [-.9, -.22], [-.48, -.28],
        [-.58, -.65], [-.17, -.42], [0, -.95], [.17, -.42], [.58, -.65],
        [.48, -.28], [.9, -.22], [.48, .05], [.65, .35], [.1, .3]]
      : [[0, .8], [-.1, .3], [-.65, .3], [-.42, 0], [-.85, -.3], [-.3, -.35],
        [0, -.85], [.3, -.35], [.85, -.3], [.42, 0], [.65, .3], [.1, .3]];
    points.forEach(([x, y], i) => i ? ctx.lineTo(x * size, y * size) : ctx.moveTo(x * size, y * size));
  } else {
    throw new Error(`Unknown leaf shape: ${shape}`);
  }
  ctx.closePath();
}

export function drawCityLeaves(ctx, { nature, width, height, weather, time, drift, horizontal, color }) {
  const count = leafCount(nature, weather);
  const palette = foliagePalette(nature.leaf, nature.season);
  for (let i = 0; i < count; i++) {
    const depth = 0.4 + seed(i * 3) * 0.6;
    const cycle = wrap(seed(i * 7) + time * (0.055 + depth * 0.025), 1);
    const x = wrap(seed(i) * width + drift * depth * 0.8, width + 60) - 30;
    const y = height * (0.52 + cycle * 0.52) + Math.sin(time * 1.2 + i) * 8 * depth;
    ctx.save(); ctx.translate(x, y);
    ctx.rotate(time * (horizontal < 0 ? -1 : 1) * (0.7 + depth) + i);
    ctx.scale(1, 0.35 + Math.abs(Math.sin(time * 1.7 + i)) * 0.65);
    leafPath(ctx, nature.leaf, (nature.leaf === 'palm' ? 8 : 6) * depth);
    ctx.fillStyle = color('384437', palette[i % palette.length], 0.85); ctx.fill();
    ctx.strokeStyle = color('343e30', '6b693b', 0.6); ctx.lineWidth = 0.5;
    ctx.beginPath(); ctx.moveTo(0, depth * 4); ctx.lineTo(0, -depth * 3); ctx.stroke();
    ctx.restore();
  }
}
