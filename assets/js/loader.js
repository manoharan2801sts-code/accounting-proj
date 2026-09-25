/**
 * TRAVEL AGENCY — Ultra-Realistic Cinematic 3D Flight Orbit Loader
 * The official brand airplane takes off from the swoosh tip,
 * flies a majestic 3D banked orbital trajectory around the globe with a luminous jet contrail,
 * decelerates smoothly back to its docking position, and triggers a crystalline sheen sweep.
 */
(function (window) {
  let overlayEl = null;
  let animId = null;

  function build() {
    const overlay = document.createElement("div");
    overlay.className = "vloader-overlay";
    overlay.id = "vloaderOverlay";
    overlay.innerHTML = `
      <div class="vloader-box">
        <!-- Volumetric Ambient Light Aura -->
        <div class="vloader-ambient-aura" aria-hidden="true"></div>

        <!-- Main Stage Container -->
        <div class="vloader-stage">
          <!-- SVG Orbit Path & Luminous Jet Contrail Layer -->
          <svg class="vloader-flight-svg" viewBox="0 0 320 110" aria-hidden="true">
            <defs>
              <linearGradient id="vloaderContrailGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="#38bdf8" stop-opacity="0" />
                <stop offset="60%" stop-color="#38bdf8" stop-opacity="0.55" />
                <stop offset="90%" stop-color="#60a5fa" stop-opacity="0.95" />
                <stop offset="100%" stop-color="#ffffff" stop-opacity="1" />
              </linearGradient>
              <filter id="vloaderGlow" x="-30%" y="-30%" width="160%" height="160%">
                <feGaussianBlur stdDeviation="2.2" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>

            <!-- Mathematical Closed Orbit Path around Globe -->
            <path id="vloaderOrbitPath"
              d="M 94 42 C 103 33, 97 20, 73 15 C 53 11, 31 24, 27 46 C 23 62, 31 74, 49 74 C 67 74, 81 64, 87 54 C 90 48, 92 44, 94 42 Z"
              fill="none" stroke="none" />

            <!-- Dynamic Jet Contrail -->
            <path id="vloaderJetContrail"
              d="M 94 42 C 103 33, 97 20, 73 15 C 53 11, 31 24, 27 46 C 23 62, 31 74, 49 74 C 67 74, 81 64, 87 54 C 90 48, 92 44, 94 42 Z"
              fill="none"
              stroke="url(#vloaderContrailGrad)"
              stroke-width="2.6"
              stroke-linecap="round"
              filter="url(#vloaderGlow)" />
          </svg>

          <!-- Official Base Brand Logo (Globe, Swoosh & Typography) -->
          <div class="vloader-base-wrap">
            <img src="assets/img/travel-agency-base.png"
                 srcset="assets/img/travel-agency-base.png 1x, assets/img/travel-agency-base@2x.png 2x"
                 alt="TRAVEL AGENCY"
                 class="vloader-base-img" />
            <div class="vloader-sheen-line" id="vloaderSheen" aria-hidden="true"></div>
          </div>

          <!-- Flying Airplane Sprite with 3D Banking & Perspective -->
          <div id="vloaderPlaneCarrier" class="vloader-plane-carrier">
            <img src="assets/img/travel-agency-plane.png"
                 srcset="assets/img/travel-agency-plane.png 1x, assets/img/travel-agency-plane@2x.png 2x"
                 alt=""
                 class="vloader-plane-sprite" />
          </div>

          <!-- Touchdown / Takeoff Diamond Lens Glint -->
          <div id="vloaderTouchdownSpark" class="vloader-touchdown-spark" aria-hidden="true"></div>
        </div>

        <!-- Sleek Hairline Loading Progress -->
        <div class="vloader-progress-track" aria-hidden="true">
          <div class="vloader-progress-bar"></div>
        </div>
      </div>
    `;
    return overlay;
  }

  function startFlightAnimation(overlay) {
    const path = overlay.querySelector("#vloaderOrbitPath");
    const contrail = overlay.querySelector("#vloaderJetContrail");
    const carrier = overlay.querySelector("#vloaderPlaneCarrier");
    const spark = overlay.querySelector("#vloaderTouchdownSpark");
    const sheen = overlay.querySelector("#vloaderSheen");

    if (!path || !carrier || !contrail) return;

    let totalLength = 205.8;
    try {
      totalLength = path.getTotalLength() || 205.8;
    } catch (e) {
      totalLength = 205.8;
    }

    const cycleDuration = 4200; // 4.2s per full flight cycle
    const restDuration = 1000;  // 1.0s docked in place
    const flightDuration = cycleDuration - restDuration; // 3.2s flight
    const contrailMaxLen = 52; // glowing jet trail length

    contrail.style.strokeDasharray = `${contrailMaxLen} ${totalLength * 2}`;
    contrail.style.strokeDashoffset = `${contrailMaxLen}`;
    contrail.style.opacity = "0";

    // Set initial resting position
    const p0 = path.getPointAtLength(0);
    carrier.style.transform = `translate(${p0.x - 14}px, ${p0.y - 10}px) rotate(0deg) scale(1)`;

    let startTime = null;

    function frame(timestamp) {
      if (!startTime) startTime = timestamp;
      const elapsed = (timestamp - startTime) % cycleDuration;

      if (elapsed < restDuration) {
        // ==========================================
        // PHASE 1: DOCKED AT REST (0 to 1000ms)
        // ==========================================
        carrier.style.transform = `translate(${p0.x - 14}px, ${p0.y - 10}px) rotate(0deg) scale(1)`;
        carrier.style.filter = "drop-shadow(0 2px 5px rgba(22, 85, 174, 0.28))";
        contrail.style.opacity = "0";

        // Touchdown diamond glint (first 260ms of rest)
        if (elapsed < 260) {
          const sparkProgress = Math.sin((elapsed / 260) * Math.PI);
          if (spark) {
            spark.style.opacity = `${sparkProgress}`;
            spark.style.transform = `translate(${p0.x}px, ${p0.y}px) scale(${sparkProgress * 1.5})`;
          }
        } else if (spark) {
          spark.style.opacity = "0";
        }

        // Crystalline liquid sheen sweep across "TRAVEL AGENCY" (250ms to 850ms)
        if (sheen) {
          if (elapsed >= 250 && elapsed < 850) {
            sheen.classList.add("vloader-sheen-active");
          } else {
            sheen.classList.remove("vloader-sheen-active");
          }
        }
      } else {
        // ==========================================
        // PHASE 2: REALISTIC 3D ORBIT FLIGHT
        // ==========================================
        if (spark) spark.style.opacity = "0";
        if (sheen) sheen.classList.remove("vloader-sheen-active");

        const flightTime = elapsed - restDuration;
        const progress = flightTime / flightDuration; // 0.0 to 1.0

        // Aerodynamic smooth easing curve (cubic-bezier ease-in-out)
        const eased =
          progress < 0.5
            ? 4 * progress * progress * progress
            : 1 - Math.pow(-2 * progress + 2, 3) / 2;

        const currentDist = eased * totalLength;
        const pt = path.getPointAtLength(currentDist);
        const nextDist = Math.min(totalLength, currentDist + 1.2);
        const nextPt = path.getPointAtLength(nextDist);

        const dx = nextPt.x - pt.x;
        const dy = nextPt.y - pt.y;
        const heading = Math.atan2(dy, dx) * (180 / Math.PI);
        const rotation = heading + 45; // compensate for base sprite resting angle

        // Realistic 3D Depth & Aerodynamic Banking:
        // - High orbit (behind globe): scales down to 0.86x for distance perspective
        // - Foreground swoop (along swoosh): scales up to 1.14x, closer to viewer
        let scale = 1.0;
        let shadowStyle = "";
        if (progress < 0.45) {
          const tHigh = progress / 0.45;
          scale = 1.0 - 0.14 * Math.sin(tHigh * Math.PI);
          shadowStyle = "drop-shadow(0 2px 4px rgba(22, 85, 174, 0.2))";
        } else {
          const tFore = (progress - 0.45) / 0.55;
          scale = 1.0 + 0.14 * Math.sin(tFore * Math.PI);
          shadowStyle = "drop-shadow(0 6px 14px rgba(22, 85, 174, 0.42))";
        }

        // Aerodynamic wing banking roll
        const bankRoll = Math.sin(progress * Math.PI * 2) * 14;

        carrier.style.transform = `translate(${pt.x - 14}px, ${pt.y - 10}px) rotate(${rotation}deg) rotateY(${bankRoll}deg) scale(${scale})`;
        carrier.style.filter = shadowStyle;

        // Glowing jet contrail trailing behind the aircraft
        let contrailAlpha = 1.0;
        if (progress < 0.08) {
          contrailAlpha = progress / 0.08;
        } else if (progress > 0.88) {
          contrailAlpha = (1.0 - progress) / 0.12;
        }
        contrail.style.opacity = `${contrailAlpha * 0.95}`;
        contrail.style.strokeDashoffset = `${-currentDist + contrailMaxLen}`;
      }

      animId = requestAnimationFrame(frame);
    }

    animId = requestAnimationFrame(frame);
  }

  function stopFlightAnimation() {
    if (animId) {
      cancelAnimationFrame(animId);
      animId = null;
    }
  }

  const VoyagerLoader = {
    show() {
      if (overlayEl) return;
      overlayEl = build();
      document.body.appendChild(overlayEl);
      startFlightAnimation(overlayEl);
    },
    hide() {
      if (!overlayEl) return;
      overlayEl.classList.add("vloader-hidden");
      const el = overlayEl;
      overlayEl = null;
      stopFlightAnimation();
      setTimeout(() => el.remove(), 260);
    },
    showFor(ms) {
      this.show();
      setTimeout(() => this.hide(), ms || 800);
    },
  };

  window.VoyagerLoader = VoyagerLoader;

  // Initial page load trigger
  if (document.body && !document.getElementById("vloaderOverlay")) {
    overlayEl = build();
    document.body.appendChild(overlayEl);
    startFlightAnimation(overlayEl);
    const hideNow = () => VoyagerLoader.hide();
    window.addEventListener("load", hideNow);
    setTimeout(hideNow, 6000);
  }
})(window);
