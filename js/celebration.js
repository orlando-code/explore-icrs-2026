const SPARK_COLORS = [
  "#7ef0a8",
  "#5fd68a",
  "#b8ffd4",
  "#ffffff",
  "#ffe566",
  "#ffc857",
  "#ff9f43",
];

function randomBetween(min, max) {
  return min + Math.random() * (max - min);
}

/** Lightweight map celebration: CSS border glow + smooth triple bursts at the pin. */
export function createMapCelebration(stageCanvas) {
  const canvas = document.createElement("canvas");
  canvas.className = "celebration-fireworks";
  canvas.setAttribute("aria-hidden", "true");
  stageCanvas.appendChild(canvas);

  const context = canvas.getContext("2d");
  let particles = [];
  let frameId = null;
  let glowTimer = null;
  let lastFrameTime = 0;

  function resize() {
    const width = stageCanvas.clientWidth;
    const height = stageCanvas.clientHeight;
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
  }

  function pulseMapGlow(durationMs = 3600) {
    stageCanvas.classList.remove("stage-canvas--celebrate");
    void stageCanvas.offsetWidth;
    stageCanvas.classList.add("stage-canvas--celebrate");
    if (glowTimer) window.clearTimeout(glowTimer);
    glowTimer = window.setTimeout(() => {
      stageCanvas.classList.remove("stage-canvas--celebrate");
      glowTimer = null;
    }, durationMs);
  }

  function addBurst(x, y, burstIndex = 0) {
    const spread = 0.65 + burstIndex * 0.18;
    const count = 22;
    for (let index = 0; index < count; index += 1) {
      const angle = Math.random() * Math.PI * 2;
      const speed = (1.6 + Math.random() * 3.4) * spread;
      particles.push({
        x: x + randomBetween(-4, 4),
        y: y + randomBetween(-4, 4),
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        life: 1,
        decay: randomBetween(0.018, 0.028),
        color: SPARK_COLORS[Math.floor(Math.random() * SPARK_COLORS.length)],
        size: randomBetween(2.8, 5.4),
        drag: 0.988,
      });
    }
    startLoop();
  }

  function drawParticle(particle) {
    const fade = particle.life * particle.life;
    context.globalAlpha = fade;
    context.fillStyle = particle.color;
    const radius = particle.size * (0.55 + fade * 0.55);
    context.beginPath();
    context.arc(particle.x, particle.y, radius, 0, Math.PI * 2);
    context.fill();

    if (fade > 0.45) {
      context.globalAlpha = fade * 0.35;
      context.fillStyle = "#ffffff";
      context.beginPath();
      context.arc(particle.x, particle.y, radius * 0.42, 0, Math.PI * 2);
      context.fill();
    }
  }

  function tick(timestamp) {
    const delta = lastFrameTime ? Math.min(24, timestamp - lastFrameTime) / 16.67 : 1;
    lastFrameTime = timestamp;

    context.clearRect(0, 0, canvas.width, canvas.height);
    particles = particles.filter((particle) => particle.life > 0);

    for (const particle of particles) {
      particle.x += particle.vx * delta;
      particle.y += particle.vy * delta;
      particle.vy += 0.028 * delta;
      particle.vx *= particle.drag ** delta;
      particle.vy *= particle.drag ** delta;
      particle.life -= particle.decay * delta;
      drawParticle(particle);
    }

    context.globalAlpha = 1;

    if (particles.length) {
      frameId = window.requestAnimationFrame(tick);
    } else {
      frameId = null;
      lastFrameTime = 0;
    }
  }

  function startLoop() {
    if (frameId) return;
    resize();
    frameId = window.requestAnimationFrame(tick);
  }

  function celebrateAt(x, y) {
    resize();
    addBurst(x, y, 0);
    window.setTimeout(() => addBurst(x, y, 1), 240);
    window.setTimeout(() => addBurst(x, y, 2), 480);
  }

  resize();

  return { celebrateAt, pulseMapGlow, resize };
}

/** @deprecated Use createMapCelebration */
export const createFireworksOverlay = createMapCelebration;
