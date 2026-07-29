const SPARK_COLORS = ["#2d8a4e", "#3aa764", "#5fd68a", "#7ef0a8", "#ffffff"];

/** Lightweight map celebration: CSS border glow + a tiny pin spark (no shadows). */
export function createMapCelebration(stageCanvas) {
  const canvas = document.createElement("canvas");
  canvas.className = "celebration-fireworks";
  canvas.setAttribute("aria-hidden", "true");
  stageCanvas.appendChild(canvas);

  const context = canvas.getContext("2d");
  let particles = [];
  let frameId = null;
  let glowTimer = null;

  function resize() {
    const width = stageCanvas.clientWidth;
    const height = stageCanvas.clientHeight;
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
  }

  function pulseMapGlow(durationMs = 2800) {
    stageCanvas.classList.remove("stage-canvas--celebrate");
    void stageCanvas.offsetWidth;
    stageCanvas.classList.add("stage-canvas--celebrate");
    if (glowTimer) window.clearTimeout(glowTimer);
    glowTimer = window.setTimeout(() => {
      stageCanvas.classList.remove("stage-canvas--celebrate");
      glowTimer = null;
    }, durationMs);
  }

  function addSpark(x, y) {
    const count = 14;
    for (let index = 0; index < count; index += 1) {
      const angle = Math.random() * Math.PI * 2;
      const speed = 1 + Math.random() * 2.8;
      particles.push({
        x,
        y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        life: 1,
        decay: 0.06 + Math.random() * 0.04,
        color: SPARK_COLORS[Math.floor(Math.random() * SPARK_COLORS.length)],
        size: 1 + Math.random() * 1.6,
      });
    }
    if (!frameId) {
      resize();
      frameId = window.requestAnimationFrame(tick);
    }
  }

  function tick() {
    context.clearRect(0, 0, canvas.width, canvas.height);
    particles = particles.filter((particle) => particle.life > 0);
    for (const particle of particles) {
      particle.x += particle.vx;
      particle.y += particle.vy;
      particle.vy += 0.05;
      particle.life -= particle.decay;
      context.globalAlpha = Math.max(0, particle.life);
      context.fillStyle = particle.color;
      context.beginPath();
      context.arc(particle.x, particle.y, particle.size * particle.life, 0, Math.PI * 2);
      context.fill();
    }
    context.globalAlpha = 1;
    frameId = particles.length ? window.requestAnimationFrame(tick) : null;
  }

  function celebrateAt(x, y) {
    resize();
    addSpark(x, y);
  }

  resize();

  return { celebrateAt, pulseMapGlow, resize };
}

/** @deprecated Use createMapCelebration */
export const createFireworksOverlay = createMapCelebration;
