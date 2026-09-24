/**
 * TRAVEL AGENCY - shared shell & SPA Navigation Engine
 * Renders the top nav (logo/company/search/profile) into #shell-topnav and
 * a horizontal dropdown menu bar (built fresh each load, no sidebar), wires
 * common behaviors (dropdown open/close, logout, company selector,
 * light/dark theme toggle), and provides seamless Single-Page-Application
 * (SPA) client-side routing.
 *
 * Clicking any navigation link or internal page link dynamically loads
 * the view and data without a full page reload!
 */
(function (window) {
  // Apply saved theme immediately on load to prevent flicker
  const savedTheme = localStorage.getItem("voyager-theme") || "light";
  document.documentElement.setAttribute("data-theme", savedTheme);

  // Tag any existing <style> tags in <head> so SPA navigation can swap them cleanly
  document.querySelectorAll("head style:not([data-page-style])").forEach((s) => {
    s.setAttribute("data-page-style", "1");
  });

  const { Store, get } = window.VoyagerAPI;
  const NAV_SECTIONS = window.VoyagerHardcode.NAV_SECTIONS;

  let currentOnCompanyChange = null;
  let isNavigating = false;
  let isShellInitialized = false;

  function icon(path) {
    return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${path}"/></svg>`;
  }

  function initials(name) {
    return name.split(" ").filter(Boolean).slice(0, 2).map((p) => p[0]).join("").toUpperCase();
  }

  // TRAVEL AGENCY brand mark - flag-topped "T" with an ascending-bars chart
  // badge at the bottom right, blue gradient, no background box, matching
  // the real logo icon.
  const TESEPR_MARK_SVG = `<svg width="26" height="26" viewBox="0 0 100 100" fill="none">
    <defs>
      <linearGradient id="tesepr-mark-grad" x1="8" y1="8" x2="92" y2="88" gradientUnits="userSpaceOnUse">
        <stop offset="0" stop-color="#4D81CD"/>
        <stop offset="1" stop-color="#2F5994"/>
      </linearGradient>
    </defs>
    <path d="M6 8H80L94 21L80 34H6Z" fill="url(#tesepr-mark-grad)"/>
    <rect x="28" y="8" width="17" height="80" rx="2" fill="url(#tesepr-mark-grad)"/>
    <rect x="51" y="53" width="41" height="35" rx="8" fill="#FFFFFF" stroke="url(#tesepr-mark-grad)" stroke-width="4"/>
    <rect x="58" y="72" width="7" height="10" rx="1.5" fill="url(#tesepr-mark-grad)"/>
    <rect x="68" y="65" width="7" height="17" rx="1.5" fill="url(#tesepr-mark-grad)"/>
    <rect x="78" y="59" width="7" height="23" rx="1.5" fill="url(#tesepr-mark-grad)"/>
  </svg>`;

  // ============================================================
  // Shared alert popup - replaces the browser's native voyagerAlert() with an
  // on-brand modal (reuses .dom-modal-backdrop/.dom-modal-window/
  // .dom-modal-titlebar so it looks identical to every other modal in the
  // app, no new visual language). Available on every page as
  // window.voyagerAlert(message) the moment shell.js loads.
  // ============================================================
  // Icon matches the message content, passed via voyagerAlert(message,
  // {icon: "..."}): "success" (green check) for save-confirmation style
  // messages ("X saved.", "Y updated."), "error" (red X) for a hard
  // failure (backend unreachable, request rejected), "info" (blue) for a
  // neutral notice. "warning" (amber triangle) is the default since most
  // unlabelled calls are validation/business-rule blocks ("X is
  // required.", "This voucher is unbalanced.", ...).
  const ALERT_ICONS = {
    info: `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#3B6DB5" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16.5"/><circle cx="12" cy="7.5" r="0.75" fill="#3B6DB5" stroke="none"/></svg>`,
    success: `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#16A34A" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.5 2.5L16 9.5"/></svg>`,
    warning: `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#D97706" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l10 18H2L12 3z"/><line x1="12" y1="10" x2="12" y2="14.5"/><circle cx="12" cy="17.5" r="0.75" fill="#D97706" stroke="none"/></svg>`,
    error: `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#DC2626" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><line x1="9" y1="9" x2="15" y2="15"/><line x1="15" y1="9" x2="9" y2="15"/></svg>`,
  };
  let alertModalEl = null;
  let alertResolve = null;
  function ensureAlertModal() {
    if (alertModalEl) return alertModalEl;
    const modal = document.createElement("div");
    modal.className = "dom-modal-backdrop";
    modal.id = "voyager-alert-modal";
    modal.innerHTML = `
      <div class="dom-modal-window">
        <div class="dom-modal-titlebar">
          <div>Notice</div>
          <button type="button" class="dom-titlebar-btn btn-close" id="voyager-alert-close-x">&times;</button>
        </div>
        <div class="voyager-alert-body">
          <span class="voyager-alert-icon" id="voyager-alert-icon" aria-hidden="true"></span>
          <span class="voyager-alert-text" id="voyager-alert-message"></span>
        </div>
        <div class="voyager-alert-actions">
          <button type="button" class="dom-nav-btn btn-primary" id="voyager-alert-ok">OK</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    const close = () => {
      modal.classList.remove("open");
      if (alertResolve) { const r = alertResolve; alertResolve = null; r(); }
    };
    modal.querySelector("#voyager-alert-ok").addEventListener("click", close);
    modal.querySelector("#voyager-alert-close-x").addEventListener("click", close);
    modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && modal.classList.contains("open")) close();
    });
    alertModalEl = modal;
    return modal;
  }
  window.voyagerAlert = function (message, opts) {
    const modal = ensureAlertModal();
    modal.querySelector("#voyager-alert-message").textContent = message;
    modal.querySelector("#voyager-alert-icon").innerHTML = ALERT_ICONS[(opts && opts.icon) || "warning"];
    modal.classList.add("open");
    modal.querySelector("#voyager-alert-ok").focus();
    return new Promise((resolve) => {
      alertResolve = () => {
        // Once closed (OK, X, backdrop or Escape), move the cursor straight
        // into whatever field the message was actually complaining about -
        // e.g. "Xyz is required" alerts pass {focusId} (or {focusEl} for a
        // field with no static id, like a date-group's inner input) so the
        // user doesn't have to go hunting for the field themselves.
        const focusEl = (opts && opts.focusEl) || (opts && opts.focusId && document.getElementById(opts.focusId));
        if (focusEl) setTimeout(() => focusEl.focus(), 0);
        resolve();
      };
    });
  };

  // ============================================================
  // Shared confirm popup - Cancel/Confirm variant of the same modal, for
  // "Are you sure?" prompts (delete, discard, etc.) instead of the
  // browser's native confirm(). window.voyagerConfirm(message, opts) on
  // every page, resolves to true/false.
  // ============================================================
  // Icon per confirm "flavor" - a delete gets a trash can, a discard/exit
  // gets an amber warning triangle (not destructive to data already
  // saved, just "you'll lose what you typed"), a generic confirm gets a
  // neutral blue question mark. Passed via voyagerConfirm(message, {icon}).
  const CONFIRM_ICONS = {
    delete: `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#DC2626" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>`,
    warning: `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#D97706" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l10 18H2L12 3z"/><line x1="12" y1="10" x2="12" y2="14.5"/><circle cx="12" cy="17.5" r="0.75" fill="#D97706" stroke="none"/></svg>`,
    exit: `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#D97706" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>`,
    question: `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#3B6DB5" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 0 1 4.6 1.4c0 1.5-2.1 1.9-2.1 3.4"/><circle cx="12" cy="17" r="0.75" fill="#3B6DB5" stroke="none"/></svg>`,
  };
  let confirmModalEl = null;
  let confirmResolve = null;
  function ensureConfirmModal() {
    if (confirmModalEl) return confirmModalEl;
    const modal = document.createElement("div");
    modal.className = "dom-modal-backdrop";
    modal.id = "voyager-confirm-modal";
    modal.innerHTML = `
      <div class="dom-modal-window">
        <div class="dom-modal-titlebar">
          <div id="voyager-confirm-title">Please Confirm</div>
          <button type="button" class="dom-titlebar-btn btn-close" id="voyager-confirm-close-x">&times;</button>
        </div>
        <div class="voyager-alert-body">
          <span class="voyager-alert-icon voyager-confirm-icon" id="voyager-confirm-icon" aria-hidden="true"></span>
          <span class="voyager-alert-text" id="voyager-confirm-message"></span>
        </div>
        <div class="voyager-alert-actions">
          <button type="button" class="dom-nav-btn" id="voyager-confirm-cancel">Cancel</button>
          <button type="button" class="dom-nav-btn btn-danger" id="voyager-confirm-ok">Delete</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    const settle = (result) => {
      modal.classList.remove("open");
      if (confirmResolve) { const r = confirmResolve; confirmResolve = null; r(result); }
    };
    modal.querySelector("#voyager-confirm-ok").addEventListener("click", () => settle(true));
    modal.querySelector("#voyager-confirm-cancel").addEventListener("click", () => settle(false));
    modal.querySelector("#voyager-confirm-close-x").addEventListener("click", () => settle(false));
    modal.addEventListener("click", (e) => { if (e.target === modal) settle(false); });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && modal.classList.contains("open")) settle(false);
    });
    confirmModalEl = modal;
    return modal;
  }
  window.voyagerConfirm = function (message, opts) {
    const modal = ensureConfirmModal();
    modal.querySelector("#voyager-confirm-message").textContent = message;
    modal.querySelector("#voyager-confirm-title").textContent = (opts && opts.title) || "Please Confirm";
    modal.querySelector("#voyager-confirm-ok").textContent = (opts && opts.confirmLabel) || "Delete";
    modal.querySelector("#voyager-confirm-icon").innerHTML = CONFIRM_ICONS[(opts && opts.icon) || "warning"];
    modal.classList.add("open");
    modal.querySelector("#voyager-confirm-cancel").focus();
    return new Promise((resolve) => { confirmResolve = resolve; });
  };

  // Each NAV_SECTIONS entry becomes one top-level menubar item: a plain link
  // when it has exactly one item AND isn't marked forceDropdown (e.g.
  // "Overview" -> CFO Dashboard shows as "CFO Dashboard" directly, "Admin"
  // -> "Users & Roles" directly), a dropdown trigger otherwise (Sales,
  // Accounting, Reports & Compliance, Masters).
  function isItemActive(item, activeKey, baseName) {
    if (!item) return false;
    if (activeKey && item.key === activeKey) return true;
    if (baseName && item.href && item.href.split("?")[0] === baseName) return true;
    if (item.children && item.children.length) {
      return item.children.some((c) => isItemActive(c, activeKey, baseName));
    }
    return false;
  }

  function renderDropdownItem(item, activeKey, level = 2) {
    if (item.children && item.children.length) {
      const active = isItemActive(item, activeKey);
      return `<div class="menubar-submenu level-${level} ${active ? "has-active" : ""}">
        <button type="button" class="menubar-submenu-trigger ${active ? "active" : ""}">
          ${item.icon ? icon(item.icon) : ""}
          <span class="menubar-item-label">${item.label}</span>
          <svg class="menubar-subcaret" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M9 18l6-6-6-6"/></svg>
        </button>
        <div class="menubar-subdropdown">
          ${item.children.map((child) => renderDropdownItem(child, activeKey, level + 1)).join("")}
        </div>
      </div>`;
    }
    return `<a class="${item.key === activeKey ? "active" : ""}" href="${item.href || "#"}" data-key="${item.key || ""}" ${item.phase2 ? 'data-phase2="1"' : ""}>
      ${item.icon ? icon(item.icon) : ""}
      <span class="menubar-item-label">${item.label}</span>
      ${item.phase2 ? '<span class="nav-badge">Phase 2</span>' : ""}
    </a>`;
  }

  function renderMenubar(activeKey) {
    const currentBase = window.location.pathname.split("/").pop() || "dashboard.html";
    return NAV_SECTIONS.map((section) => {
      if (section.items.length === 1 && !section.forceDropdown && (!section.items[0].children || !section.items[0].children.length)) {
        const item = section.items[0];
        const active = isItemActive(item, activeKey, currentBase);
        return `<div class="menubar-item">
          <a class="menubar-link ${active ? "active" : ""}" href="${item.href}" data-key="${item.key}" ${item.phase2 ? 'data-phase2="1"' : ""}>
            ${item.label}
          </a>
        </div>`;
      }
      const hasActive = section.items.some((item) => isItemActive(item, activeKey, currentBase));
      return `<div class="menubar-item">
        <button type="button" class="menubar-link menubar-trigger ${hasActive ? "active" : ""}">
          ${section.label}
          <svg class="menubar-caret" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M6 9l6 6 6-6"/></svg>
        </button>
        <div class="menubar-dropdown">
          ${section.items.map((item) => renderDropdownItem(item, activeKey, 2)).join("")}
        </div>
      </div>`;
    }).join("") + `
      <div class="menubar-item" style="margin-left:auto;">
        <a class="menubar-link" href="#" id="logout-link">
          ${icon("M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9")}
          Sign out
        </a>
      </div>`;
  }

  function wireMenubarDropdowns() {
    document.querySelectorAll(".menubar-item").forEach((item) => {
      const trigger = item.querySelector(".menubar-trigger");
      if (!trigger) return;
      trigger.addEventListener("click", (e) => {
        e.stopPropagation();
        const wasOpen = item.classList.contains("open");
        document.querySelectorAll(".menubar-item.open").forEach((o) => {
          if (o !== item) o.classList.remove("open");
        });
        item.classList.toggle("open", !wasOpen);
      });
    });

    document.querySelectorAll(".menubar-submenu-trigger").forEach((subTrigger) => {
      const sub = subTrigger.closest(".menubar-submenu");
      if (!sub) return;

      subTrigger.addEventListener("click", (e) => {
        e.stopPropagation();
        const wasOpen = sub.classList.contains("open");
        const parentDropdown = sub.parentElement;
        if (parentDropdown) {
          parentDropdown.querySelectorAll(":scope > .menubar-submenu.open").forEach((s) => {
            if (s !== sub) s.classList.remove("open");
          });
        }
        sub.classList.toggle("open", !wasOpen);
      });

      sub.addEventListener("mouseenter", () => {
        if (window.innerWidth > 900) {
          const parentDropdown = sub.parentElement;
          if (parentDropdown) {
            parentDropdown.querySelectorAll(":scope > .menubar-submenu.open").forEach((s) => {
              if (s !== sub) s.classList.remove("open");
            });
          }
          sub.classList.add("open");
        }
      });
      sub.addEventListener("mouseleave", () => {
        if (window.innerWidth > 900) {
          sub.classList.remove("open");
        }
      });
    });

    document.addEventListener("click", () => {
      document.querySelectorAll(".menubar-item.open").forEach((o) => o.classList.remove("open"));
      document.querySelectorAll(".menubar-submenu.open").forEach((s) => s.classList.remove("open"));
    });

    document.querySelectorAll(".menubar-dropdown a, .menubar-subdropdown a").forEach((link) => {
      link.addEventListener("click", () => {
        document.querySelectorAll(".menubar-item.open").forEach((o) => o.classList.remove("open"));
        document.querySelectorAll(".menubar-submenu.open").forEach((s) => s.classList.remove("open"));
      });
    });
  }

  function updateActiveNav(activeKey, url) {
    const baseName = url ? url.split("?")[0].replace(/^.*[\\/]/, "") : (window.location.pathname.split("/").pop() || "dashboard.html");
    document.querySelectorAll(".menubar-link, .menubar-dropdown a, .menubar-subdropdown a, .menubar-trigger, .menubar-submenu-trigger").forEach((el) => {
      el.classList.remove("active");
    });
    document.querySelectorAll(".menubar-submenu").forEach((s) => s.classList.remove("has-active"));

    document.querySelectorAll(".menubar-link[href], .menubar-dropdown a[href], .menubar-subdropdown a[href]").forEach((item) => {
      const itemHref = item.getAttribute("href") || "";
      const itemKey = item.getAttribute("data-key");
      const isMatch = (activeKey && itemKey === activeKey) || (baseName && itemHref.split("?")[0] === baseName);
      if (isMatch) {
        item.classList.add("active");
        let parent = item.parentElement;
        while (parent && !parent.classList.contains("app-menubar")) {
          if (parent.classList.contains("menubar-submenu")) {
            parent.classList.add("has-active");
            const subTrig = parent.querySelector(":scope > .menubar-submenu-trigger");
            if (subTrig) subTrig.classList.add("active");
          }
          if (parent.classList.contains("menubar-item")) {
            const topTrig = parent.querySelector(":scope > .menubar-trigger");
            if (topTrig) topTrig.classList.add("active");
          }
          parent = parent.parentElement;
        }
      }
    });
  }

  async function navigateTo(url, push = true) {
    if (!url || url === "#" || url.startsWith("javascript:") || isNavigating) return;
    if (url === "index.html" || url.endsWith("/index.html")) {
      window.location.href = "index.html";
      return;
    }

    isNavigating = true;
    try {
      // Close any modal left open on the outgoing page - these live outside
      // .app-main (siblings of .app-body), so swapping .app-main's innerHTML
      // alone doesn't remove/hide them and they'd otherwise bleed through
      // on top of the newly routed page.
      document.querySelectorAll(".dom-modal-backdrop.open").forEach((m) => m.classList.remove("open"));

      const res = await fetch(url);
      if (!res.ok) {
        window.location.href = url;
        return;
      }
      const html = await res.text();
      const parser = new DOMParser();
      const doc = parser.parseFromString(html, "text/html");

      // 1. Update Document Title
      if (doc.title) {
        document.title = doc.title;
      }

      // 1b. Sync .app-body's own inline style (height/overflow-y) - several
      // pages (master-mapping.html, fop-master.html, pg-master.html,
      // ticket-entry.html) rely on this for their locked-viewport scroll
      // container, but .app-body itself is a persistent shell element that
      // never gets replaced across SPA navigations - only swapping
      // .app-main below left it stuck with whatever style the PREVIOUS
      // page had (often none), so the new page's content had no scrollbar
      // until a full reload re-parsed its real inline style from scratch.
      const newBody = doc.querySelector(".app-body");
      const currentBody = document.querySelector(".app-body");
      if (newBody && currentBody) {
        if (newBody.getAttribute("style")) {
          currentBody.setAttribute("style", newBody.getAttribute("style"));
        } else {
          currentBody.removeAttribute("style");
        }
      }

      // 2. Swap Main View
      const newMain = doc.querySelector(".app-main");
      const currentMain = document.querySelector(".app-main");
      if (newMain && currentMain) {
        currentMain.innerHTML = newMain.innerHTML;
        if (newMain.getAttribute("style")) {
          currentMain.setAttribute("style", newMain.getAttribute("style"));
        } else {
          currentMain.removeAttribute("style");
        }
        currentMain.classList.remove("spa-fade-in");
        void currentMain.offsetWidth; // trigger reflow for animation
        currentMain.classList.add("spa-fade-in");
      }

      // 2b. Sync page-specific markup that lives OUTSIDE .app-main (e.g.
      // ticket-entry.html's modals, which are siblings of .app-body, not
      // descendants of .app-main) - swapping .app-main's innerHTML alone
      // never brings these over, so any script that does
      // document.getElementById() on them gets null and buttons silently
      // do nothing until a full page reload re-parses the whole file.
      document.querySelectorAll(".spa-extra-content").forEach((el) => el.remove());
      Array.from(doc.body.children).forEach((el) => {
        const tag = el.tagName.toLowerCase();
        if (tag === "script" || tag === "style" || tag === "link") return;
        if (el.id === "shell-topnav" || el.id === "shell-menubar" || el.classList.contains("app-body")) return;
        el.classList.add("spa-extra-content");
        document.body.appendChild(document.importNode(el, true));
      });

      // 3. Update Page Styles
      const existingPageStyles = document.querySelectorAll("style[data-page-style]");
      existingPageStyles.forEach((s) => s.remove());
      const newPageStyles = doc.querySelectorAll("head style");
      newPageStyles.forEach((s) => {
        const cloned = document.createElement("style");
        cloned.setAttribute("data-page-style", "1");
        cloned.textContent = s.textContent;
        document.head.appendChild(cloned);
      });

      // 3b. Reset html and body inline styles so no previous page locks scrolling
      document.documentElement.style.overflow = "";
      document.documentElement.style.overflowY = "";
      document.documentElement.style.height = "";
      document.body.style.overflow = "";
      document.body.style.overflowY = "";
      document.body.style.height = "";

      // 4. Update Menubar Active State
      updateActiveNav(null, url);

      // 5. Update Browser History
      if (push) {
        window.history.pushState({ url }, "", url);
      }

      window.scrollTo({ top: 0, behavior: "instant" });

      // 6. Execute scripts from the new page in order
      const scripts = Array.from(doc.querySelectorAll("script"));
      for (const s of scripts) {
        const src = s.getAttribute("src");
        if (src) {
          // Skip shared base libraries that are already loaded in memory
          if (
            src.includes("hardcode.js") ||
            src.includes("mock-data.js") ||
            src.includes("api.js") ||
            src.includes("util.js") ||
            src.includes("entry-common.js") ||
            src.includes("drilldown.js") ||
            src.includes("shell.js") ||
            src.includes("auth.js")
          ) {
            continue;
          }

          // Check if external CDN library is already loaded
          if (src.includes("chart.umd") && window.Chart) continue;
          if (src.includes("jquery") && window.jQuery) continue;
          if (src.includes("dataTables") && window.jQuery && window.jQuery.fn && window.jQuery.fn.DataTable) continue;

          // Dynamically load page-specific script
          await new Promise((resolve) => {
            const scriptEl = document.createElement("script");
            scriptEl.src = src.split("?")[0] + "?t=" + Date.now();
            scriptEl.onload = resolve;
            scriptEl.onerror = resolve;
            document.body.appendChild(scriptEl);
          });
        } else if (s.textContent.trim()) {
          try {
            const inlineScript = document.createElement("script");
            inlineScript.textContent = s.textContent;
            document.body.appendChild(inlineScript);
            inlineScript.remove();
          } catch (e) {
            console.error("Inline script execution error:", e);
          }
        }
      }
    } catch (err) {
      console.error("SPA routing error:", err);
      window.location.href = url;
    } finally {
      isNavigating = false;
    }
  }

  // Intercept all clicks globally for instant SPA navigation without full page reload
  document.addEventListener("click", (e) => {
    const link = e.target.closest("a");
    if (!link) return;

    const href = link.getAttribute("href");
    if (
      !href ||
      href === "#" ||
      href.startsWith("javascript:") ||
      href.startsWith("mailto:") ||
      href.startsWith("tel:") ||
      link.hasAttribute("data-phase2") ||
      link.id === "logout-link"
    ) {
      return;
    }

    // Allow opening in new tab / window with Ctrl/Cmd/Shift
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;

    // Check if link is internal
    if (link.hostname && link.hostname !== window.location.hostname) return;

    // Only route to html pages
    const isHtmlTarget = href.includes(".html") || !href.includes(".");
    if (!isHtmlTarget) return;

    e.preventDefault();
    navigateTo(href, true);
  });

  // Handle Browser Back and Forward buttons seamlessly
  window.addEventListener("popstate", (e) => {
    if (e.state && e.state.url) {
      navigateTo(e.state.url, false);
    } else {
      navigateTo(window.location.pathname + window.location.search, false);
    }
  });

  async function init({ activeKey, onCompanyChange }) {
    currentOnCompanyChange = onCompanyChange;

    if (!Store.getToken() || Store.getToken() === "demo-token") {
      Store.setToken("session-token");
      Store.setRefresh("session-refresh");
      Store.setUser(Store.getUser() || { full_name: "Ananya Krishnan" });
      localStorage.removeItem("voyager_mock_mode");
    }
    const user = Store.getUser() || { full_name: "Ananya Krishnan" };
    const currentTheme = document.documentElement.getAttribute("data-theme") || "light";

    // Build Topnav only once if not already rendered
    const topnav = document.getElementById("shell-topnav");
    if (topnav && (!isShellInitialized || !topnav.innerHTML.trim())) {
      topnav.innerHTML = `
        <a class="app-logo" href="dashboard.html" title="TRAVEL AGENCY" style="display:flex; align-items:center;">
          <img class="logo-img" src="assets/img/travel-agency-logo.png" alt="TRAVEL AGENCY" style="height:34px; width:auto; display:block;" />
        </a>
        <select class="form-control-custom company-selector" id="company-selector" style="display:none;"></select>
        <div class="topnav-actions">
          <!-- -1. Financial Year label — sits just left of the country
               flag switcher, shows the current accounting year only -->
          <span class="fy-label" id="fy-label" title="Accounting Financial Year" style="display:inline-flex; align-items:center; height:32px; padding:0 0.6rem; font-size:0.8rem; font-weight:700; color:var(--color-text-dark); background:var(--color-primary-tint); border:1px solid var(--color-border); border-radius:var(--radius-sm); white-space:nowrap;"></span>

          <!-- 0. Country Flag — shows only the active company's flag; click
               opens a small dropdown to switch. Sits right before the
               profile pill -->
          <div class="country-flags" id="country-flags">
            <button type="button" class="flag-current-btn" id="flag-current-btn" aria-label="Switch company/country">
              <span class="flag-current-icon" id="flag-current-icon"></span>
              <span class="flag-caret">&#9662;</span>
            </button>
            <div class="flag-dropdown" id="flag-dropdown"></div>
          </div>

          <!-- 1. Profile Pill First -->
          <div class="user-chip" id="user-profile-chip" title="Logged in as ${user ? user.full_name : ''}">
            <span class="user-avatar">${user ? initials(user.full_name) : "--"}</span>
            <span style="font-size:0.85rem; font-weight:600;">${user ? user.full_name.split(" (")[0] : "..."}</span>
          </div>

          <!-- 2. Notification Bell Next -->
          <button class="icon-btn" id="notif-btn" aria-label="Notifications" title="Notifications">
            ${icon("M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9")}
            <span class="dot"></span>
          </button>

          <!-- 3. Theme Toggle Button Next (Light/Dark Mode) -->
          <button class="icon-btn theme-toggle-btn" id="theme-toggle-btn" aria-label="Toggle Theme" title="Toggle Light / Dark Mode">
            <span class="theme-icon-sun" style="display:${currentTheme === 'dark' ? 'inline-flex' : 'none'};">${icon("M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z")}</span>
            <span class="theme-icon-moon" style="display:${currentTheme === 'dark' ? 'none' : 'inline-flex'};">${icon("M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z")}</span>
          </button>
        </div>`;

      // Theme Toggle Handler
      const themeBtn = document.getElementById("theme-toggle-btn");
      if (themeBtn) {
        themeBtn.addEventListener("click", () => {
          const activeTheme = document.documentElement.getAttribute("data-theme") || "light";
          const newTheme = activeTheme === "dark" ? "light" : "dark";
          document.documentElement.setAttribute("data-theme", newTheme);
          localStorage.setItem("voyager-theme", newTheme);

          const sun = themeBtn.querySelector(".theme-icon-sun");
          const moon = themeBtn.querySelector(".theme-icon-moon");
          if (sun && moon) {
            sun.style.display = newTheme === "dark" ? "inline-flex" : "none";
            moon.style.display = newTheme === "dark" ? "none" : "inline-flex";
          }
        });
      }

      // Financial Year label (Apr-Mar accounting year) - current year only,
      // no switching.
      const fyLabel = document.getElementById("fy-label");
      if (fyLabel) {
        const today = new Date();
        const currentFyStart = today.getMonth() >= 3 ? today.getFullYear() : today.getFullYear() - 1;
        fyLabel.textContent = `FY ${currentFyStart}-${String(currentFyStart + 1).slice(-2)}`;
      }
    }

    // Build the horizontal dropdown menu bar - created fresh each load, no
    // sidebar. Inserted as a sibling right after #shell-topnav so it doesn't
    // need to exist in every page's own HTML.
    let menubar = document.getElementById("shell-menubar");
    if (!menubar) {
      menubar = document.createElement("nav");
      menubar.id = "shell-menubar";
      menubar.className = "app-menubar";
      topnav.insertAdjacentElement("afterend", menubar);
    }
    if (!isShellInitialized || !menubar.innerHTML.trim()) {
      menubar.innerHTML = renderMenubar(activeKey);
      wireMenubarDropdowns();
    } else {
      updateActiveNav(activeKey, window.location.pathname);
    }

    // Old sidebar markup, if a page's HTML still has it - remove outright,
    // menubar replaces it entirely.
    const staleSidebar = document.getElementById("shell-sidebar");
    if (staleSidebar) staleSidebar.remove();

    document.querySelectorAll("[data-phase2]").forEach((el) => {
      el.addEventListener("click", (e) => {
        e.preventDefault();
        voyagerAlert("This module is part of the Phase 2 build.", { icon: "info" });
      });
    });

    const logoutLink = document.getElementById("logout-link");
    if (logoutLink && !logoutLink.dataset.bound) {
      logoutLink.dataset.bound = "1";
      logoutLink.addEventListener("click", async (e) => {
        e.preventDefault();
        try { await window.VoyagerAPI.post("/auth/logout"); } catch (_) {}
        Store.clear();
        window.location.href = "index.html";
      });
    }

    // Company Selector Setup (hidden <select> stays the source of truth;
    // the single current-flag button + its dropdown are what the user
    // actually clicks to switch company/country)
    const FLAG_SVG = {
      IN: '<svg viewBox="0 0 24 16" width="20" height="14"><rect width="24" height="16" fill="#F1F5F9"/><rect width="24" height="5.33" fill="#FF9933"/><rect y="10.67" width="24" height="5.33" fill="#138808"/><circle cx="12" cy="8" r="2.2" fill="none" stroke="#000080" stroke-width="0.4"/><circle cx="12" cy="8" r="0.35" fill="#000080"/></svg>',
      AE: '<svg viewBox="0 0 24 16" width="20" height="14"><rect width="24" height="16" fill="#FFFFFF"/><rect y="0" width="24" height="5.33" fill="#00732F"/><rect y="10.67" width="24" height="5.33" fill="#000000"/><rect width="7" height="16" fill="#FF0000"/></svg>',
    };
    const select = document.getElementById("company-selector");
    const flagBtn = document.getElementById("flag-current-btn");
    const flagIcon = document.getElementById("flag-current-icon");
    const flagDropdown = document.getElementById("flag-dropdown");
    if (select) {
      if (!select.dataset.loaded) {
        const COUNTRY_CODE = { India: "IN", "United Arab Emirates": "AE" };
        const rawCompanies = await get("/company-master/");
        const companies = rawCompanies.map((c) => ({
          id: c.id,
          name: c.name || c.company_name,
          country_code: c.country_code || COUNTRY_CODE[c.country] || "IN",
        }));
        select.innerHTML = companies.map((c) =>
          `<option value="${c.id}" data-country="${c.country_code}">${c.name} (${c.country_code})</option>`).join("");
        const savedId = Store.getCompanyId();
        if (savedId && companies.some((c) => String(c.id) === savedId)) select.value = savedId;
        else Store.setCompanyId(select.value);
        select.dataset.loaded = "1";

        const closeFlagDropdown = () => flagDropdown.classList.remove("open");
        const syncFlagUI = () => {
          const activeOpt = select.selectedOptions[0];
          const activeCountry = activeOpt ? activeOpt.dataset.country : "IN";
          if (flagIcon) flagIcon.innerHTML = FLAG_SVG[activeCountry] || FLAG_SVG.IN;
          flagDropdown.querySelectorAll(".flag-dropdown-item").forEach((item) => {
            item.classList.toggle("active", item.dataset.value === select.value);
          });
        };

        flagDropdown.innerHTML = companies.map((c) => `
          <button type="button" class="flag-dropdown-item" data-value="${c.id}" data-country="${c.country_code}">
            <span class="flag-dropdown-icon">${FLAG_SVG[c.country_code] || ""}</span>
            <span>${c.name} (${c.country_code})</span>
          </button>`).join("");

        select.addEventListener("change", () => {
          Store.setCompanyId(select.value);
          const activeOpt = select.selectedOptions[0];
          syncFlagUI();
          if (currentOnCompanyChange) {
            currentOnCompanyChange(select.value, activeOpt ? activeOpt.dataset.country : "IN");
          }
        });

        if (flagBtn) {
          flagBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            flagDropdown.classList.toggle("open");
          });
        }
        flagDropdown.querySelectorAll(".flag-dropdown-item").forEach((item) => {
          item.addEventListener("click", () => {
            if (select.value !== item.dataset.value) {
              select.value = item.dataset.value;
              select.dispatchEvent(new Event("change"));
            }
            closeFlagDropdown();
          });
        });
        document.addEventListener("click", (e) => {
          if (!flagDropdown.contains(e.target) && e.target !== flagBtn) closeFlagDropdown();
        });

        syncFlagUI();
      }
    }

    isShellInitialized = true;
    const active = select && select.selectedOptions[0];
    return {
      id: select ? select.value : "1",
      country: active ? active.dataset.country : "IN"
    };
  }

  // ============================================================
  // Force every native <input type="date"> to DISPLAY dd/mm/yyyy.
  // Setting <html lang="en-GB"> alone isn't reliable - modern Chromium
  // formats the closed date field using the OS/browser locale, not the
  // page's lang attribute, so it can still show mm/dd/yyyy regardless.
  // Fix: keep the native input untouched functionally (calendar picker,
  // value, form submission all still work exactly as before) but make
  // its own text transparent and draw a floating dd/mm/yyyy label
  // exactly on top of it. The label is `pointer-events:none`, so every
  // click still reaches the real input beneath it.
  //
  // Runs from shell.js (loaded on every page) instead of per-page code,
  // and re-scans on a short interval instead of hooking DOMContentLoaded
  // or navigateTo() - this app's SPA navigation swaps page content in
  // without shell.js re-running, and date inputs also appear later
  // inside modals/popups (Add Sector, Company Master, filter popups...),
  // so polling is what reliably catches all of those without needing
  // every single page/modal to remember to call an init function.
  // ============================================================
  const dateOverlays = new Map(); // input element -> its floating label span

  function ensureDateOverlayStyle() {
    if (document.getElementById("dd-date-overlay-style")) return;
    const style = document.createElement("style");
    style.id = "dd-date-overlay-style";
    style.textContent = `
      input[type="date"].dd-date-formatted { color: transparent !important; -webkit-text-fill-color: transparent !important; }
      .dd-date-overlay {
        position: fixed; pointer-events: none; white-space: nowrap; overflow: hidden;
        display: flex; align-items: center; z-index: 2147483000; box-sizing: border-box;
      }
    `;
    document.head.appendChild(style);
  }

  function fmtDDMMYYYY(iso) {
    if (!iso) return "";
    const parts = iso.split("-");
    if (parts.length !== 3) return "";
    const [y, m, d] = parts;
    return `${d}/${m}/${y}`;
  }

  function getOrCreateDateOverlay(input) {
    let span = dateOverlays.get(input);
    if (span) return span;
    ensureDateOverlayStyle();
    span = document.createElement("span");
    span.className = "dd-date-overlay";
    document.body.appendChild(span);
    input.classList.add("dd-date-formatted");
    // Some pages style disabled inputs with their own `!important` color
    // rule (e.g. master-mapping.html's ".mm-table input:disabled"), which
    // can tie in specificity with the stylesheet rule above and win on
    // source order - leaving the native mm/dd/yyyy text visible UNDER our
    // overlay (the garbled double-text look). An inline `!important`
    // always outranks any external stylesheet rule, disabled or not, so
    // set it directly on the element instead of relying on the class alone.
    input.style.setProperty("color", "transparent", "important");
    input.style.setProperty("-webkit-text-fill-color", "transparent", "important");
    input.addEventListener("input", () => syncDateOverlay(input, span));
    input.addEventListener("change", () => syncDateOverlay(input, span));
    dateOverlays.set(input, span);
    return span;
  }

  function syncDateOverlay(input, span) {
    const rect = input.getBoundingClientRect();
    const hidden = rect.width === 0 && rect.height === 0;
    if (hidden) {
      span.style.display = "none";
      return;
    }
    // The overlay's z-index has to be high enough to sit above this
    // page's own modals/popups, but that also means it would otherwise
    // paint over an unrelated dropdown menu (nav submenu, ledger picker,
    // etc.) that happens to open above this input's on-screen position
    // even though the input itself is now covered and behind it. Only
    // draw the label when the input (or its own icon) is genuinely the
    // topmost thing at its own location - sampling just one point (e.g.
    // near the left edge) missed dropdowns that only cover PART of the
    // input's box, so this checks several points across it instead.
    const sampleY = rect.top + rect.height / 2;
    const sampleXs = [
      Math.min(rect.left + 4, rect.right - 1),
      rect.left + rect.width * 0.25,
      rect.left + rect.width * 0.5,
      rect.left + rect.width * 0.75,
      Math.max(rect.right - 30, rect.left),
    ];
    const covered = sampleXs.some((x) => {
      const el = document.elementFromPoint(x, sampleY);
      return el && el !== input && !input.contains(el);
    });
    if (covered) {
      span.style.display = "none";
      return;
    }
    span.style.display = "flex";

    const cs = getComputedStyle(input);
    span.style.left = `${rect.left}px`;
    span.style.top = `${rect.top}px`;
    // Leave room on the right for the native calendar icon, which stays
    // visible since only the input's own text is made transparent.
    span.style.width = `${Math.max(rect.width - 26, 0)}px`;
    span.style.height = `${rect.height}px`;
    span.style.font = cs.font;
    span.style.paddingLeft = cs.paddingLeft;
    span.style.textAlign = cs.textAlign;
    span.style.color = input.disabled
      ? "#94A3B8"
      : (cs.color === "rgba(0, 0, 0, 0)" || cs.color === "transparent" ? "#0F172A" : cs.color);

    span.textContent = fmtDDMMYYYY(input.value);
  }

  function syncAllDateOverlays() {
    document.querySelectorAll('input[type="date"]').forEach((input) => {
      syncDateOverlay(input, getOrCreateDateOverlay(input));
    });
    dateOverlays.forEach((span, input) => {
      if (!input.isConnected) {
        span.remove();
        dateOverlays.delete(input);
      }
    });
  }

  window.addEventListener("resize", syncAllDateOverlays);
  document.addEventListener("scroll", syncAllDateOverlays, true);
  setInterval(syncAllDateOverlays, 400);
  syncAllDateOverlays();

  window.VoyagerShell = { init, navigateTo };
})(window);
