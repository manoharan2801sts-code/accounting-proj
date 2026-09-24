/**
 * TRAVEL AGENCY — Branded Loading Screen
 * Auto-runs the moment this script executes: since its <script> tag sits
 * as the very first thing right after <body> on every page, document.body
 * already exists (the parser creates it as soon as it sees the opening tag)
 * but has no children yet — so the overlay covers the page before anything
 * else has a chance to paint, then removes itself once the page finishes
 * loading (with a safety-net timeout in case "load" never fires).
 *
 * Also exposed as window.VoyagerLoader for any page that wants to show it
 * again for a specific action:
 *   VoyagerLoader.show("Loading dashboard…");
 *   VoyagerLoader.hide();
 *   VoyagerLoader.showFor(800); // auto-hide after ms
 */
(function (window) {
  let overlayEl = null;

  function build(message) {
    const overlay = document.createElement("div");
    overlay.className = "vloader-overlay";
    overlay.id = "vloaderOverlay";
    overlay.innerHTML = `
      <div class="vloader-box">
        <div class="vloader-logo-wrap">
          <img src="assets/img/travel-agency-logo.png" alt="TRAVEL AGENCY" class="vloader-logo" />
          <span class="vloader-plane-orbit" aria-hidden="true">
            <svg class="vloader-plane" width="15" height="15" viewBox="0 0 24 24" fill="currentColor">
              <path d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2.5 1.8V22l3.5-1 3.5 1v-1.2L13 19v-5.5l8 2.5z"/>
            </svg>
          </span>
        </div>
        <div class="vloader-bars" aria-hidden="true">
          <span></span><span></span><span></span><span></span><span></span>
        </div>
        <div class="vloader-label" id="vloaderLabel">${message || "Loading…"}</div>
      </div>
    `;
    return overlay;
  }

  const VoyagerLoader = {
    show(message) {
      if (overlayEl) { this.setMessage(message); return; }
      overlayEl = build(message);
      document.body.appendChild(overlayEl);
    },
    setMessage(message) {
      if (!message) return;
      const label = document.getElementById("vloaderLabel");
      if (label) label.textContent = message;
    },
    hide() {
      if (!overlayEl) return;
      overlayEl.classList.add("vloader-hidden");
      const el = overlayEl;
      overlayEl = null;
      setTimeout(() => el.remove(), 240);
    },
    showFor(ms, message) {
      this.show(message);
      setTimeout(() => this.hide(), ms || 700);
    },
  };

  window.VoyagerLoader = VoyagerLoader;

  if (document.body && !document.getElementById("vloaderOverlay")) {
    overlayEl = build();
    document.body.appendChild(overlayEl);
    const hideNow = () => VoyagerLoader.hide();
    window.addEventListener("load", hideNow);
    setTimeout(hideNow, 6000);
  }
})(window);
