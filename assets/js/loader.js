/**
 * Voyager ERP — Bar Chart Loader
 * Usage:
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
        <div class="vloader-bars" aria-hidden="true">
          <span></span><span></span><span></span><span></span><span></span>
        </div>
        <div class="vloader-brand">TRAVEL AGENCY</div>
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
})(window);