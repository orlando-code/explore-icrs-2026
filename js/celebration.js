const FIREWORK_COLORS = ["#2d8a4e", "#3aa764", "#5fd68a", "#ffd166", "#ff8c42", "#ffffff", "#1f6f8b"];

function randomColor() {
  return FIREWORK_COLORS[Math.floor(Math.random() * FIREWORK_COLORS.length)];
}

export function createFireworksOverlay(container) {
  const canvas = document.createElement("canvas");
  canvas.className = "celebration-fireworks";
  canvas.setAttribute("aria-hidden", "true");
  container.appendChild(canvas);

  const context = canvas.getContext("2d");
  let particles = [];
  let rockets = [];
  let frameId = null;

  function resize() {
    const width = container.clientWidth;
    const height = container.clientHeight;
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
  }

  function addBurst(x, y, count = 42) {
    for (let index = 0; index < count; index += 1) {
      const angle = Math.random() * Math.PI * 2;
      const speed = 1.5 + Math.random() * 5.5;
      particles.push({
        x,
        y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        life: 1,
        decay: 0.012 + Math.random() * 0.018,
        color: randomColor(),
        size: 1.5 + Math.random() * 2.5,
        sparkle: Math.random() > 0.65,
      });
    }
    start();
  }

  function addRocket(targetX, targetY) {
    const startX = targetX + (Math.random() - 0.5) * 40;
    const startY = canvas.height + 8;
    const dx = targetX - startX;
    const dy = targetY - startY;
    const distance = Math.hypot(dx, dy) || 1;
    const speed = 7 + Math.random() * 2;
    rockets.push({
      x: startX,
      y: startY,
      vx: (dx / distance) * speed,
      vy: (dy / distance) * speed,
      targetX,
      targetY,
      trail: [],
      color: randomColor(),
    });
    start();
  }

  function tick() {
    context.clearRect(0, 0, canvas.width, canvas.height);

    rockets = rockets.filter((rocket) => {
      rocket.trail.push({ x: rocket.x, y: rocket.y });
      if (rocket.trail.length > 8) rocket.trail.shift();
      rocket.x += rocket.vx;
      rocket.y += rocket.vy;

      for (const point of rocket.trail) {
        context.globalAlpha = 0.35;
        context.fillStyle = rocket.color;
        context.beginPath();
        context.arc(point.x, point.y, 2, 0, Math.PI * 2);
        context.fill();
      }

      const reached =
        Math.hypot(rocket.x - rocket.targetX, rocket.y - rocket.targetY) < 12 || rocket.y < rocket.targetY;
      if (reached) {
        addBurst(rocket.targetX, rocket.targetY, 36 + Math.floor(Math.random() * 20));
        return false;
      }
      return true;
    });

    particles = particles.filter((particle) => particle.life > 0);
    for (const particle of particles) {
      particle.x += particle.vx;
      particle.y += particle.vy;
      particle.vy += 0.07;
      particle.vx *= 0.985;
      particle.life -= particle.decay;

      context.globalAlpha = Math.max(0, particle.life);
      context.fillStyle = particle.color;
      const radius = particle.size * (0.4 + particle.life * 0.6);
      context.beginPath();
      context.arc(particle.x, particle.y, radius, 0, Math.PI * 2);
      context.fill();

      if (particle.sparkle && particle.life > 0.35) {
        context.globalAlpha = particle.life * 0.5;
        context.strokeStyle = "#ffffff";
        context.lineWidth = 1;
        context.beginPath();
        context.moveTo(particle.x - radius * 1.8, particle.y);
        context.lineTo(particle.x + radius * 1.8, particle.y);
        context.moveTo(particle.x, particle.y - radius * 1.8);
        context.lineTo(particle.x, particle.y + radius * 1.8);
        context.stroke();
      }
    }

    context.globalAlpha = 1;
    if (rockets.length || particles.length) {
      frameId = window.requestAnimationFrame(tick);
    } else {
      frameId = null;
    }
  }

  function start() {
    if (frameId) return;
    resize();
    frameId = window.requestAnimationFrame(tick);
  }

  function celebrateAt(x, y) {
    resize();
    addRocket(x, y);
    window.setTimeout(() => addRocket(x + 24, y - 18), 180);
    window.setTimeout(() => addBurst(x - 20, y - 12, 28), 520);
    window.setTimeout(() => addBurst(x + 14, y - 36, 32), 760);
  }

  resize();

  return { celebrateAt, resize };
}
