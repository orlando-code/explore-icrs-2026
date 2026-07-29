const FIREWORK_COLORS = [
  "#2d8a4e",
  "#3aa764",
  "#5fd68a",
  "#7ef0a8",
  "#ffd166",
  "#ffba3b",
  "#ff8c42",
  "#ffffff",
  "#1f6f8b",
  "#4ecdc4",
];

function randomColor() {
  return FIREWORK_COLORS[Math.floor(Math.random() * FIREWORK_COLORS.length)];
}

function randomBetween(min, max) {
  return min + Math.random() * (max - min);
}

export function createFireworksOverlay(container) {
  const canvas = document.createElement("canvas");
  canvas.className = "celebration-fireworks";
  canvas.setAttribute("aria-hidden", "true");
  container.appendChild(canvas);

  const context = canvas.getContext("2d");
  let particles = [];
  let rockets = [];
  let rings = [];
  let frameId = null;
  let lastFrameTime = 0;

  function resize() {
    const width = container.clientWidth;
    const height = container.clientHeight;
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
  }

  function addBurst(x, y, options = {}) {
    const {
      count = 88,
      speedMin = 2.8,
      speedMax = 10.5,
      sizeMin = 2.2,
      sizeMax = 6.2,
      decayMin = 0.006,
      decayMax = 0.018,
      gravity = 0.052,
      drag = 0.986,
      sparkleChance = 0.42,
      ring = true,
    } = options;

    for (let index = 0; index < count; index += 1) {
      const angle = Math.random() * Math.PI * 2;
      const speed = randomBetween(speedMin, speedMax);
      const kind = Math.random() > 0.78 ? "willow" : "burst";
      particles.push({
        x,
        y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        life: 1,
        decay: randomBetween(decayMin, decayMax),
        color: randomColor(),
        size: randomBetween(sizeMin, sizeMax),
        sparkle: Math.random() < sparkleChance,
        gravity,
        drag,
        kind,
        trail: kind === "willow" ? [] : null,
      });
    }

    if (ring) {
      rings.push({
        x,
        y,
        radius: 4,
        maxRadius: randomBetween(52, 92),
        life: 1,
        decay: 0.028,
        color: randomColor(),
        width: randomBetween(2.4, 4.2),
      });
    }

    start();
  }

  function addRocket(targetX, targetY, options = {}) {
    const spread = options.spread ?? 70;
    const startX = targetX + randomBetween(-spread, spread);
    const startY = canvas.height + randomBetween(4, 28);
    const dx = targetX - startX;
    const dy = targetY - startY;
    const distance = Math.hypot(dx, dy) || 1;
    const speed = randomBetween(9, 13);
    rockets.push({
      x: startX,
      y: startY,
      vx: (dx / distance) * speed,
      vy: (dy / distance) * speed,
      targetX,
      targetY,
      trail: [],
      color: options.color || randomColor(),
      size: randomBetween(2.4, 3.6),
    });
    start();
  }

  function drawRocket(rocket) {
    rocket.trail.push({ x: rocket.x, y: rocket.y, life: 1 });
    if (rocket.trail.length > 14) rocket.trail.shift();

    for (let index = 0; index < rocket.trail.length; index += 1) {
      const point = rocket.trail[index];
      const trailLife = (index + 1) / rocket.trail.length;
      context.globalAlpha = trailLife * 0.55;
      context.fillStyle = rocket.color;
      context.shadowBlur = 10 * trailLife;
      context.shadowColor = rocket.color;
      context.beginPath();
      context.arc(point.x, point.y, rocket.size * (0.45 + trailLife * 0.7), 0, Math.PI * 2);
      context.fill();
    }

    context.shadowBlur = 16;
    context.shadowColor = "#ffffff";
    context.globalAlpha = 1;
    context.fillStyle = "#ffffff";
    context.beginPath();
    context.arc(rocket.x, rocket.y, rocket.size, 0, Math.PI * 2);
    context.fill();
    context.shadowBlur = 0;
  }

  function drawParticle(particle) {
    if (particle.trail) {
      particle.trail.push({ x: particle.x, y: particle.y });
      if (particle.trail.length > 6) particle.trail.shift();
      for (let index = 0; index < particle.trail.length; index += 1) {
        const point = particle.trail[index];
        const trailLife = (index + 1) / particle.trail.length;
        context.globalAlpha = particle.life * trailLife * 0.45;
        context.fillStyle = particle.color;
        context.beginPath();
        context.arc(point.x, point.y, particle.size * 0.35 * trailLife, 0, Math.PI * 2);
        context.fill();
      }
    }

    context.globalAlpha = Math.max(0, particle.life);
    context.fillStyle = particle.color;
    const radius = particle.size * (0.35 + particle.life * 0.75);
    context.shadowBlur = particle.sparkle ? 14 * particle.life : 8 * particle.life;
    context.shadowColor = particle.color;
    context.beginPath();
    context.arc(particle.x, particle.y, radius, 0, Math.PI * 2);
    context.fill();

    if (particle.sparkle && particle.life > 0.25) {
      const sparkleSize = radius * (1.4 + (1 - particle.life) * 0.8);
      context.globalAlpha = particle.life * 0.75;
      context.strokeStyle = "#ffffff";
      context.lineWidth = 1.4;
      context.shadowBlur = 10;
      context.shadowColor = "#ffffff";
      context.beginPath();
      context.moveTo(particle.x - sparkleSize, particle.y);
      context.lineTo(particle.x + sparkleSize, particle.y);
      context.moveTo(particle.x, particle.y - sparkleSize);
      context.lineTo(particle.x, particle.y + sparkleSize);
      context.stroke();
    }

    context.shadowBlur = 0;
  }

  function drawRing(ring) {
    context.globalAlpha = ring.life * 0.85;
    context.strokeStyle = ring.color;
    context.lineWidth = ring.width * ring.life;
    context.shadowBlur = 18 * ring.life;
    context.shadowColor = ring.color;
    context.beginPath();
    context.arc(ring.x, ring.y, ring.radius, 0, Math.PI * 2);
    context.stroke();
    context.shadowBlur = 0;
  }

  function tick(timestamp) {
    const delta = lastFrameTime ? Math.min(32, timestamp - lastFrameTime) / 16.67 : 1;
    lastFrameTime = timestamp;

    context.clearRect(0, 0, canvas.width, canvas.height);
    context.globalCompositeOperation = "lighter";

    rockets = rockets.filter((rocket) => {
      drawRocket(rocket);
      rocket.x += rocket.vx * delta;
      rocket.y += rocket.vy * delta;
      rocket.vy -= 0.04 * delta;

      const reached =
        Math.hypot(rocket.x - rocket.targetX, rocket.y - rocket.targetY) < 16 ||
        rocket.y < rocket.targetY;
      if (reached) {
        addBurst(rocket.targetX, rocket.targetY, {
          count: 72 + Math.floor(Math.random() * 36),
          speedMax: 11.5,
          sizeMax: 6.8,
        });
        return false;
      }
      return true;
    });

    rings = rings.filter((ring) => ring.life > 0);
    for (const ring of rings) {
      ring.radius += (ring.maxRadius - ring.radius) * 0.14 * delta;
      ring.life -= ring.decay * delta;
      drawRing(ring);
    }

    particles = particles.filter((particle) => particle.life > 0);
    for (const particle of particles) {
      particle.x += particle.vx * delta;
      particle.y += particle.vy * delta;
      particle.vy += particle.gravity * delta;
      particle.vx *= particle.drag ** delta;
      particle.vy *= particle.drag ** delta;
      particle.life -= particle.decay * delta;
      drawParticle(particle);
    }

    context.globalCompositeOperation = "source-over";
    context.globalAlpha = 1;

    if (rockets.length || particles.length || rings.length) {
      frameId = window.requestAnimationFrame(tick);
    } else {
      frameId = null;
      lastFrameTime = 0;
    }
  }

  function start() {
    if (frameId) return;
    resize();
    frameId = window.requestAnimationFrame(tick);
  }

  function celebrateAt(x, y) {
    resize();
    const centerX = x;
    const centerY = y;

    addRocket(centerX, centerY, { spread: 90 });
    window.setTimeout(() => addRocket(centerX - 36, centerY - 24, { spread: 110, color: "#5fd68a" }), 140);
    window.setTimeout(() => addRocket(centerX + 42, centerY - 18, { spread: 95, color: "#ffd166" }), 280);
    window.setTimeout(
      () =>
        addBurst(centerX, centerY - 8, {
          count: 110,
          speedMax: 12,
          sizeMax: 7.2,
        }),
      520
    );
    window.setTimeout(
      () =>
        addBurst(centerX - 48, centerY - 28, {
          count: 64,
          speedMin: 2,
          speedMax: 8,
          ring: false,
        }),
      760
    );
    window.setTimeout(
      () =>
        addBurst(centerX + 36, centerY - 44, {
          count: 78,
          speedMax: 10.5,
          sparkleChance: 0.55,
        }),
      980
    );
    window.setTimeout(
      () =>
        addBurst(centerX, centerY - 12, {
          count: 130,
          speedMin: 1.5,
          speedMax: 13,
          sizeMax: 7.8,
          decayMin: 0.004,
          decayMax: 0.012,
        }),
      1240
    );
  }

  resize();

  return { celebrateAt, resize };
}
