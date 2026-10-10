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
    // preventScroll - this modal is position:fixed and already fully in
    // view regardless of any ancestor's scroll position, but a plain
    // .focus() still triggers the browser's default scroll-into-view
    // walk up every scrollable ancestor, visibly jumping the page/table
    // scroll position underneath the modal for no reason.
    modal.querySelector("#voyager-alert-ok").focus({ preventScroll: true });
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
    // preventScroll - see voyagerAlert's identical comment above.
    modal.querySelector("#voyager-confirm-cancel").focus({ preventScroll: true });
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

  // ============================================================
  // Per-user menu access (User Management). Super Admin sees everything;
  // anyone else sees Home plus only the menus with
  // View ticked for them. Re-fetched on every full page load, so a change
  // by the Super Admin (or deactivating the user) applies on next load.
  // ============================================================
  const PERMS_KEY = "voyager_permissions";
  let currentPerms = null;

  async function loadPermissions() {
    const token = Store.getToken();
    try {
      const res = await fetch(`${window.VoyagerAPI.API_BASE}/auth/my-permissions/`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) {
        Store.clear();
        try { sessionStorage.removeItem(PERMS_KEY); } catch (_) {}
        window.location.href = "index.html";
        return null;
      }
      if (res.ok) {
        const data = await res.json();
        const perms = { is_super_admin: !!data.is_super_admin, menus: data.menus || {} };
        try { sessionStorage.setItem(PERMS_KEY, JSON.stringify(perms)); } catch (_) {}
        if (data.user) Store.setUser(data.user);
        return perms;
      }
    } catch (_) {}
    // Backend unreachable - last known set for this tab, else Home only.
    try {
      const cached = JSON.parse(sessionStorage.getItem(PERMS_KEY) || "null");
      if (cached) return cached;
    } catch (_) {}
    return { is_super_admin: false, menus: {} };
  }

  function canView(key) {
    if (!currentPerms || currentPerms.is_super_admin) return true;
    if (key === "dashboard") return true;
    const m = currentPerms.menus[key];
    return !!(m && m.view);
  }

  function filterNavItems(items) {
    return items
      .map((it) => (it.children && it.children.length ? { ...it, children: filterNavItems(it.children) } : it))
      .filter((it) => (it.children ? it.children.length > 0 : canView(it.key)));
  }

  function visibleSections() {
    if (!currentPerms || currentPerms.is_super_admin) return NAV_SECTIONS;
    return NAV_SECTIONS
      .map((section) => ({ ...section, items: filterNavItems(section.items) }))
      .filter((section) => section.items.length);
  }

  // ------------------------------------------------------------
  // Add / Edit / Delete on each page. Keyed by page file (Booking/
  // Reschedule/Cancellation share ticket-entry.html, Accounts and its
  // ledger screen share the "accounts" key), applied against the user's
  // flags for that page's activeKey. The server enforces the same rules
  // (accounting/permissions.py) - this just keeps the screen honest.
  //   add / edit / delete : hidden when that flag is off
  //   addOrEdit           : hidden when both add and edit are off
  //   save + saveNeeds()  : hidden when the flag the CURRENT mode needs is off
  //   lock                : fields not focusable when the user can't save here
  //   editTriggers        : [selector, event] blocked when edit is off
  // ------------------------------------------------------------
  const savedRecordInUrl = (...params) => () => {
    const q = new URLSearchParams(window.location.search);
    return params.some((p) => q.get(p)) ? "edit" : "add";
  };
  const PAGE_PERMISSION_UI = {
    "ticket-entry.html": {
      add: ["#add-line-btn", "#add-line-btn-bot", "#pax-add-row-btn", ".pax-add-row", "#reschedule-new-btn", "#cancellation-new-btn", "#rs-reschedule-btn", "#cx-cancel-btn", "#proceed-btn"],
      edit: ["#edit-ticket-btn"],
      save: ["#submit-btn", "#cancellation-save-btn", "#modal-save-btn", "#modal-sector-add-btn", "#sector-save-btn", ".pax-remove-btn", ".dom-chip-remove"],
      saveNeeds: savedRecordInUrl("id", "reschedule_saved_id", "cancellation_saved_id"),
      lock: ["#ticket-form", "#fare-breakdown-modal", "#sector-modal"],
    },
    "company-master.html": {
      edit: ["#cm-edit-btn", "#cm-save-btn"],
    },
    "groups.html": {
      add: ["#new-group-btn"],
      edit: [".edit-btn"],
      delete: [".delete-btn"],
      addOrEdit: ["#submit-form-btn"],
      editTriggers: [[".grp-name", "click"]],
    },
    "accounts.html": {
      add: ['a.btn-brand[href="ledger-entry.html"]'],
      delete: [".delete-ledger-btn"],
    },
    "ledger-entry.html": {
      save: ["#submit-btn"],
      saveNeeds: savedRecordInUrl("id"),
      lock: ["#ledger-form"],
    },
    "voucher-type.html": {
      add: ["#vt-new-btn"],
      addOrEdit: ["#vt-save-btn", "#addl-numbering-save-btn"],
      lock: [".vt-card"],
    },
    "supplier-master.html": {
      add: [".sm-rule-save-btn"],
      // Edit removes the rule and re-adds it on save - needs all three.
      edit: [".sm-list-edit-btn"],
      delete: [".sm-list-del-btn", ".sm-list-edit-btn"],
      lockNeeds: "add",
      lock: ["#sm-rule-tbody"],
    },
    "master-mapping.html": {
      edit: [".mm-row-edit-btn"],
      delete: [".mm-row-del-btn"],
      addOrEdit: [".mm-row-save-btn"],
      lock: [".mm-ledger-select", ".mm-effective-from"],
    },
    "fop-master.html": {
      delete: [".fm-btn-minus"],
      addOrEdit: ["#fm-btn-save"],
      editTriggers: [["tr.fm-grid-row", "dblclick"]],
      lock: [".fm-form-card"],
    },
    "pg-master.html": {
      delete: [".pg-btn-minus"],
      addOrEdit: ["#pg-btn-save"],
      editTriggers: [["tr.pg-grid-row", "dblclick"]],
      lock: [".pg-form-card"],
    },
  };
  // supplier-master's Edit also needs add (it re-creates the rule).
  PAGE_PERMISSION_UI["supplier-master.html"].add.push(".sm-list-edit-btn");

  let pagePerm = { view: true, add: true, edit: true, delete: true };
  let pageRule = null;
  let lockedSelectors = [];
  let blockedTriggers = [];

  function permFor(key) {
    if (!currentPerms || currentPerms.is_super_admin) return { view: true, add: true, edit: true, delete: true };
    const m = currentPerms.menus[key] || {};
    return { view: !!m.view, add: !!m.add, edit: !!m.edit, delete: !!m.delete };
  }

  function applyPagePermissions(activeKey) {
    const page = window.location.pathname.split("/").pop() || "dashboard.html";
    pagePerm = permFor(activeKey);
    pageRule = PAGE_PERMISSION_UI[page] || null;
    const hide = [];
    lockedSelectors = [];
    blockedTriggers = [];
    if (pageRule) {
      const p = pagePerm;
      if (!p.add) hide.push(...(pageRule.add || []));
      if (!p.edit) hide.push(...(pageRule.edit || []));
      if (!p.delete) hide.push(...(pageRule.delete || []));
      if (!p.add && !p.edit) hide.push(...(pageRule.addOrEdit || []));
      const canSaveHere = pageRule.saveNeeds ? p[pageRule.saveNeeds()] : (pageRule.lockNeeds ? p[pageRule.lockNeeds] : (p.add || p.edit));
      if (pageRule.save && !canSaveHere) hide.push(...pageRule.save);
      if (pageRule.lock && !canSaveHere) lockedSelectors = pageRule.lock.slice();
      if (!p.edit) blockedTriggers = (pageRule.editTriggers || []).slice();
    }
    let style = document.getElementById("perm-ui-style");
    if (!style) {
      style = document.createElement("style");
      style.id = "perm-ui-style";
      document.head.appendChild(style);
    }
    const lockCss = lockedSelectors.map((s) => `${s} input, ${s} select, ${s} textarea, input${s}, select${s}, textarea${s}`).join(", ");
    style.textContent =
      (hide.length ? `${hide.join(", ")} { display: none !important; }\n` : "") +
      (lockCss ? `${lockCss} { pointer-events: none !important; background-color: var(--color-bg-subtle) !important; }\n` : "");
    watchLockedFields();
  }

  function isLockedField(el) {
    return lockedSelectors.length && el && el.matches && el.matches("input, select, textarea")
      && lockedSelectors.some((s) => el.matches(s) || el.closest(s));
  }

  // Locked text fields get the real readonly attribute (the only thing
  // every input method respects); selects can't be readonly, so they rely
  // on the pointer-events CSS + key blocking below. Re-applied whenever the
  // page re-renders or flips readonly back off (e.g. its own mode changes).
  function enforceLockedFields() {
    if (!lockedSelectors.length) return;
    lockedSelectors.forEach((s) => {
      document.querySelectorAll(`${s} input, ${s} textarea, input${s}, textarea${s}`).forEach((el) => {
        if (!el.readOnly) el.readOnly = true;
      });
    });
  }
  let lockObserver = null;
  function watchLockedFields() {
    if (lockObserver) { lockObserver.disconnect(); lockObserver = null; }
    if (!lockedSelectors.length) return;
    enforceLockedFields();
    let queued = false;
    lockObserver = new MutationObserver(() => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => { queued = false; enforceLockedFields(); });
    });
    lockObserver.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["readonly"] });
  }

  // Registered once; read whatever the current page's rules are. Typing,
  // paste and drop are blocked outright (not just focus), so a field
  // reached with Tab still can't be changed. Tab/Escape keep working.
  document.addEventListener("focusin", (e) => { if (isLockedField(e.target)) e.target.blur(); }, true);
  ["beforeinput", "paste", "drop", "cut"].forEach((evt) => {
    document.addEventListener(evt, (e) => { if (isLockedField(e.target)) e.preventDefault(); }, true);
  });
  document.addEventListener("keydown", (e) => {
    if (isLockedField(e.target) && e.key !== "Tab" && e.key !== "Escape") e.preventDefault();
  }, true);
  ["click", "dblclick"].forEach((evt) => {
    document.addEventListener(evt, (e) => {
      if (!blockedTriggers.length || !e.target.closest) return;
      if (blockedTriggers.some(([sel, ev]) => ev === evt && e.target.closest(sel))) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    }, true);
  });

  function renderAccessDenied() {
    const main = document.querySelector(".app-main");
    if (!main) return;
    main.innerHTML = `
      <div style="max-width:440px; margin:4rem auto; text-align:center; background:var(--color-white); border:1px solid var(--color-border); border-radius:var(--radius-md); padding:2rem 1.5rem;">
        ${icon("M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z")}
        <h1 style="font-size:1.15rem; font-weight:700; margin:0.6rem 0 0.4rem;">403 – Access Denied</h1>
        <p style="font-size:0.85rem; color:var(--color-text-muted); margin:0 0 1.1rem;">You don't have access to this page. Ask your Super Admin to grant it in User Management.</p>
        <a href="dashboard.html" class="dom-nav-btn btn-primary" style="display:inline-flex; text-decoration:none;">Go to Home</a>
      </div>`;
  }

  function renderMenubar(activeKey) {
    const currentBase = window.location.pathname.split("/").pop() || "dashboard.html";
    return visibleSections().map((section) => {
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
        // Sync the class list too, not just style - several pages (e.g.
        // voucher-type.html's "vt-main", company-master.html's "cmx-main",
        // report-dsr-airline-booking.html's "dsr-main") hang their own
        // locked-viewport scroll container's CSS off an extra class on
        // .app-main, same idea as the style sync above. .app-main is a
        // persistent shell element that survives across navigations, so
        // without this the PREVIOUS page's extra class (or none at all)
        // stayed stuck here and the new page's scroll area never got its
        // real overflow/height rules until a full reload re-parsed the
        // actual HTML from scratch.
        currentMain.className = newMain.className;
        currentMain.classList.remove("spa-fade-in");
        void currentMain.offsetWidth; // trigger reflow for animation
        currentMain.classList.add("spa-fade-in");
      }

      // 2a-pre. Update Browser History BEFORE running any inline script
      // below - moved here (2026-10-07) from its old spot after step 4.
      // Those inline scripts (e.g. ticket-entry.html's own title guard)
      // read `window.location.search` directly to tell New Ticket/
      // Reschedule/Cancellation apart, since all three share this one
      // path with only the query string differing. With pushState still
      // happening AFTER them, navigating from one of these three to
      // another left `window.location` pointing at the PREVIOUS page's
      // URL while the guard script ran - e.g. leaving Cancellation
      // (?cancellation_new=1) for a plain New Ticket (no params) would
      // run the just-swapped-in page's own guard script, which re-read
      // the OLD "?cancellation_new=1" still sitting in window.location
      // and set the title right back to "Cancellation". Running pushState
      // first makes window.location already correct by the time any
      // inline script - current or future - reads it.
      if (push) {
        window.history.pushState({ url }, "", url);
      }

      // 2a. Run every INLINE script (no src) immediately, right after the
      // swap above - setting .innerHTML does NOT execute embedded
      // <script> tags (a well-known DOM behavior), which is exactly why
      // step 6 below has to manually re-create/append each one to make it
      // run at all. But step 6 processes every script - inline AND
      // external - in one pass, in document order, and awaits each
      // external <script src> in turn; a page's "guard" inline script
      // (e.g. ticket-entry.html's title-fix-up for Reschedule/
      // Cancellation's blank shell, meant to run before its own heavy
      // page-ticket-entry.js even loads - see that script's own comment)
      // was getting reached only AFTER whatever earlier scripts step 6
      // had already awaited, by which point the browser may have already
      // painted the just-swapped DOM showing the wrong default content -
      // precisely the "New Ticket flashes before Cancellation" bug this
      // fixes. Running all inline scripts here instead, synchronously,
      // with no `await` between the DOM swap and this loop, means the
      // browser has no opportunity to paint in between: whatever an
      // inline script fixes up is correct from the very first rendered
      // frame. External <script src> tags are unaffected - they still
      // load/run in step 6 below, in their original relative order.
      Array.from(doc.querySelectorAll("script")).forEach((s) => {
        if (s.getAttribute("src") || !s.textContent.trim()) return;
        try {
          const inlineScript = document.createElement("script");
          inlineScript.textContent = s.textContent;
          document.body.appendChild(inlineScript);
          inlineScript.remove();
        } catch (e) {
          console.error("Inline script execution error:", e);
        }
      });

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

      // 4. Update Menubar Active State
      updateActiveNav(null, url);

      // 5. Update Browser History - moved to step 2a-pre (before any inline
      // script runs); nothing left to do here.

      window.scrollTo({ top: 0, behavior: "instant" });

      // 6. Execute external (src) scripts from the new page in order -
      // inline scripts already ran in step 2a, immediately after the DOM
      // swap, so they're not reprocessed here.
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

          // Dynamically load page-specific script. Keep the ORIGINAL src
          // (including whatever ?v=N cache-busting query it already has)
          // instead of forcing a fresh "?t="+Date.now() on every single
          // navigation - that made every menu click re-download every
          // page's full JS bundle from the network with no caching at
          // all, which is most of the "menu click feels slow" cost on a
          // plain static file server (no HTTP cache headers to make a
          // repeat fetch cheap). The browser can now cache each script by
          // its own ?v=N, so navigating back to an already-visited page
          // is instant - a real content change still gets picked up the
          // moment its own HTML bumps that ?v=N (the convention already
          // used throughout this app for every edited shared .js file).
          await new Promise((resolve) => {
            const scriptEl = document.createElement("script");
            scriptEl.src = src;
            scriptEl.onload = resolve;
            scriptEl.onerror = resolve;
            document.body.appendChild(scriptEl);
          });
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

    // Not signed in - go to the login page. The returned promise never
    // settles, so the page's own code (awaiting init) stops here.
    if (!Store.getToken() || Store.getToken() === "demo-token") {
      Store.clear();
      window.location.href = "index.html";
      return new Promise(() => {});
    }
    if (!currentPerms) {
      currentPerms = await loadPermissions();
      if (!currentPerms) return new Promise(() => {});
    }
    const user = Store.getUser() || { full_name: "Ananya Krishnan" };

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
        </div>`;
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
        try { sessionStorage.removeItem(PERMS_KEY); } catch (_) {}
        currentPerms = null;
        window.location.href = "index.html";
      });
    }

    // Page guard - typing a page's URL directly is blocked too, not just
    // hidden from the menu. Menu bar + Sign out stay usable.
    if (!canView(activeKey)) {
      renderAccessDenied();
      return new Promise(() => {});
    }
    applyPagePermissions(activeKey);

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
    // Real per-company Country (from Company Master) drives the flag and
    // Financial Year convention - "India" (or blank) is Apr-Mar, anything
    // else (UAE, etc.) is Jan-Dec, matched loosely so "UAE"/"U.A.E"/
    // "United Arab Emirates" all resolve the same way.
    function countryCodeFromText(text) {
      const t = (text || "").trim().toLowerCase();
      return (!t || t === "india" || t === "in" || t === "bharat") ? "IN" : "AE";
    }
    function fyLabelForCountry(countryCode) {
      const today = new Date();
      if (countryCode !== "IN") return `FY ${today.getFullYear()}`;
      const fyStart = today.getMonth() >= 3 ? today.getFullYear() : today.getFullYear() - 1;
      return `FY ${fyStart}-${String(fyStart + 1).slice(-2)}`;
    }
    if (select) {
      // Wraps the WHOLE block, not just the fetch - this used to be a
      // plain mock-data read that could never fail; now it's a real
      // network call plus a bunch of DOM wiring, and ANY exception in
      // here escaping uncaught would reject the whole init() promise,
      // leaving every page's own "Could not load the active company"
      // fallback alert firing even though the rest of init() (menubar,
      // theme, etc.) already succeeded. Falls through to a safe default
      // company further below no matter what goes wrong here.
      try {
      if (!select.dataset.loaded) {
        // Real companies (Company Master), not the old hardcoded mock list -
        // so the flag/FY genuinely reflect whatever Country is actually set
        // there, and a newly-added company shows up here automatically.
        let companies = [];
        try {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 2500);
          const res = await fetch("http://localhost:8000/api/company-master/", { signal: controller.signal });
          clearTimeout(timeoutId);
          const rows = res.ok ? await res.json() : [];
          companies = rows.map((c) => ({ id: c.id, name: c.company_name, country_code: countryCodeFromText(c.country) }));
        } catch (_) { companies = []; }
        if (!companies.length) companies = [{ id: 1, name: "Travel Agency", country_code: "IN" }];

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
          // Looked up fresh rather than captured in an outer closure - the
          // topnav markup that creates #fy-label is only (re)built further
          // up, in a separate block that doesn't share scope with this one.
          const fyLabelEl = document.getElementById("fy-label");
          if (fyLabelEl) fyLabelEl.textContent = fyLabelForCountry(activeCountry);
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
      } catch (err) {
        console.error("Company/flag selector setup failed - falling back to the default company", err);
        if (!select.dataset.loaded) {
          select.innerHTML = `<option value="1" data-country="IN">Travel Agency (IN)</option>`;
          Store.setCompanyId("1");
          select.dataset.loaded = "1";
        }
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

  // ============================================================
  // Project calendar - replaces the browser's own date picker on EVERY
  // <input type="date"> in the app (pages, popups, SPA-loaded pages) with
  // one consistent popup: prev/next arrows + Month/Year dropdowns in a
  // primary-coloured header, weekday row, day grid. The input itself stays
  // a real date input, so .value (yyyy-mm-dd), min/max, typing and the
  // input/change events every page already listens to all work as before.
  // Disabled or read-only (permission-locked) fields never open it.
  // ============================================================
  const CAL_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const CAL_ICON = "data:image/svg+xml," + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#3B6DB5" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>'
  );
  let calEl = null, calInput = null, calView = null; // calView = {year, month}

  function ensureCalendarStyle() {
    if (document.getElementById("vcal-style")) return;
    const style = document.createElement("style");
    style.id = "vcal-style";
    style.textContent = `
      input[type="date"]::-webkit-calendar-picker-indicator { display: none; }
      input[type="date"] {
        background-image: url("${CAL_ICON}") !important; background-repeat: no-repeat !important;
        background-position: right 8px center !important; background-size: 15px 15px !important;
        cursor: pointer;
      }
      input[type="date"]:disabled, input[type="date"][readonly] { cursor: default; }
      .vcal {
        position: fixed; z-index: 2147483600; width: 284px; background: #FFFFFF;
        border: 1px solid var(--color-border, #E2E8F0); border-radius: 0;
        box-shadow: 0 12px 32px rgba(15, 23, 42, 0.18); overflow: hidden;
        font-family: inherit; user-select: none;
      }
      .vcal-head {
        display: flex; align-items: center; gap: 6px; padding: 4px 6px;
        background: var(--color-primary, #3B6DB5);
      }
      .vcal-nav {
        width: 24px; height: 24px; flex-shrink: 0; border: none; background: transparent; color: #FFFFFF;
        font-size: 18px; font-weight: 700; line-height: 1; cursor: pointer; border-radius: 0;
      }
      .vcal-nav:hover:not(:disabled) { background: rgba(255, 255, 255, 0.18); }
      .vcal-nav:disabled { opacity: 0.35; cursor: default; }
      .vcal-select {
        flex: 1; min-width: 0; height: 24px; padding: 0 4px; border: 1px solid transparent; border-radius: 0;
        background: #FFFFFF; color: var(--color-text-dark, #0F172A); font-size: 13px; font-weight: 600;
        font-family: inherit; cursor: pointer;
      }
      .vcal-select:focus { outline: 2px solid rgba(255, 255, 255, 0.6); outline-offset: 0; }
      .vcal-week, .vcal-grid { display: grid; grid-template-columns: repeat(7, 1fr); }
      .vcal-week { background: var(--color-bg-subtle, #F1F5F9); padding: 3px 6px; }
      .vcal-week span { text-align: center; font-size: 12px; font-weight: 700; color: var(--color-text-muted, #475569); }
      .vcal-grid { padding: 6px; gap: 2px; }
      .vcal-day {
        height: 34px; border: none; background: transparent; border-radius: 0; cursor: pointer;
        font-family: inherit; font-size: 13px; color: var(--color-text-dark, #0F172A);
      }
      .vcal-day.vcal-sun { color: var(--color-primary, #3B6DB5); font-weight: 600; }
      .vcal-day:hover:not(:disabled) { background: var(--color-primary-tint, #F0F4FC); }
      .vcal-day.vcal-today { background: var(--color-bg-subtle, #F1F5F9); font-weight: 700; }
      .vcal-day.vcal-selected, .vcal-day.vcal-selected:hover { background: var(--color-primary, #3B6DB5); color: #FFFFFF; font-weight: 700; }
      .vcal-day:disabled { color: #CBD5E1; cursor: default; background: transparent; }
      .vcal-blank { height: 34px; }
    `;
    document.head.appendChild(style);
  }
  ensureCalendarStyle();

  const pad2 = (n) => String(n).padStart(2, "0");
  const toIso = (y, m, d) => `${y}-${pad2(m + 1)}-${pad2(d)}`;
  function parseIso(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || "");
    return m ? { year: +m[1], month: +m[2] - 1, day: +m[3] } : null;
  }

  function calRange(input) {
    const today = new Date();
    const min = parseIso(input.min), max = parseIso(input.max);
    return {
      min, max,
      minYear: min ? min.year : today.getFullYear() - 60,
      maxYear: max ? max.year : today.getFullYear() + 20,
    };
  }

  function renderCalendar() {
    if (!calEl || !calInput) return;
    const { year, month } = calView;
    const range = calRange(calInput);
    const selected = calInput.value;
    const now = new Date();
    const todayIso = toIso(now.getFullYear(), now.getMonth(), now.getDate());
    const minIso = calInput.min || "", maxIso = calInput.max || "";

    const years = [];
    for (let y = range.minYear; y <= range.maxYear; y++) years.push(y);
    if (!years.includes(year)) years.push(year), years.sort((a, b) => a - b);
    const monthOpts = CAL_MONTHS.map((name, i) => {
      const outOfRange = (range.min && year === range.min.year && i < range.min.month)
        || (range.max && year === range.max.year && i > range.max.month);
      return `<option value="${i}" ${i === month ? "selected" : ""} ${outOfRange ? "disabled" : ""}>${name}</option>`;
    }).join("");
    const yearOpts = years.map((y) => `<option value="${y}" ${y === year ? "selected" : ""}>${y}</option>`).join("");

    const firstDow = new Date(year, month, 1).getDay();
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    let cells = "";
    for (let i = 0; i < firstDow; i++) cells += `<span class="vcal-blank"></span>`;
    for (let d = 1; d <= daysInMonth; d++) {
      const iso = toIso(year, month, d);
      const dow = (firstDow + d - 1) % 7;
      const off = (minIso && iso < minIso) || (maxIso && iso > maxIso);
      const cls = ["vcal-day", dow === 0 ? "vcal-sun" : "", iso === todayIso ? "vcal-today" : "", iso === selected ? "vcal-selected" : ""].join(" ");
      cells += `<button type="button" class="${cls}" data-iso="${iso}" ${off ? "disabled" : ""}>${d}</button>`;
    }

    const prevOff = range.min && (year < range.min.year || (year === range.min.year && month <= range.min.month));
    const nextOff = range.max && (year > range.max.year || (year === range.max.year && month >= range.max.month));
    calEl.innerHTML = `
      <div class="vcal-head">
        <button type="button" class="vcal-nav" data-step="-1" ${prevOff ? "disabled" : ""} aria-label="Previous month">&#8249;</button>
        <select class="vcal-select" data-part="month" aria-label="Month">${monthOpts}</select>
        <select class="vcal-select" data-part="year" aria-label="Year">${yearOpts}</select>
        <button type="button" class="vcal-nav" data-step="1" ${nextOff ? "disabled" : ""} aria-label="Next month">&#8250;</button>
      </div>
      <div class="vcal-week"><span>Su</span><span>Mo</span><span>Tu</span><span>We</span><span>Th</span><span>Fr</span><span>Sa</span></div>
      <div class="vcal-grid">${cells}</div>`;
  }

  function positionCalendar() {
    if (!calEl || !calInput) return;
    if (!calInput.isConnected) { closeCalendar(); return; } // page swapped out under it
    const r = calInput.getBoundingClientRect();
    const w = calEl.offsetWidth, h = calEl.offsetHeight;
    let top = r.bottom + 4;
    if (top + h > window.innerHeight - 8 && r.top - h - 4 >= 8) top = r.top - h - 4;
    let left = Math.min(r.left, window.innerWidth - w - 8);
    calEl.style.top = `${Math.max(8, top)}px`;
    calEl.style.left = `${Math.max(8, left)}px`;
  }

  function openCalendar(input) {
    if (input.disabled || input.readOnly) return;
    if (!calEl) {
      calEl = document.createElement("div");
      calEl.className = "vcal";
      calEl.addEventListener("mousedown", (e) => {
        // Keep focus on the date input (and the popup open), except when
        // using the Month/Year dropdowns, which need focus themselves.
        if (!e.target.closest("select")) e.preventDefault();
      });
      calEl.addEventListener("click", (e) => {
        const step = e.target.closest(".vcal-nav");
        if (step && !step.disabled) {
          const d = new Date(calView.year, calView.month + Number(step.dataset.step), 1);
          calView = { year: d.getFullYear(), month: d.getMonth() };
          renderCalendar();
          return;
        }
        const day = e.target.closest(".vcal-day");
        if (day && !day.disabled) pickCalendarDate(day.dataset.iso);
      });
      calEl.addEventListener("change", (e) => {
        const sel = e.target.closest(".vcal-select");
        if (!sel) return;
        if (sel.dataset.part === "month") calView.month = Number(sel.value);
        else calView.year = Number(sel.value);
        // A year whose allowed range doesn't include the current month
        // snaps to the nearest allowed month.
        const range = calRange(calInput);
        if (range.min && calView.year === range.min.year && calView.month < range.min.month) calView.month = range.min.month;
        if (range.max && calView.year === range.max.year && calView.month > range.max.month) calView.month = range.max.month;
        renderCalendar();
      });
      document.body.appendChild(calEl);
    }
    calInput = input;
    const current = parseIso(input.value) || parseIso(input.min && new Date().toISOString().slice(0, 10) < input.min ? input.min : "");
    const now = new Date();
    calView = current ? { year: current.year, month: current.month } : { year: now.getFullYear(), month: now.getMonth() };
    calEl.style.display = "block";
    renderCalendar();
    positionCalendar();
  }

  function closeCalendar() {
    if (calEl) calEl.style.display = "none";
    calInput = null;
  }

  function pickCalendarDate(iso) {
    const input = calInput;
    if (!input) return;
    input.value = iso;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    closeCalendar();
  }

  // Capture phase, so the browser's own picker never opens and page
  // handlers further down still see their usual events afterwards.
  document.addEventListener("mousedown", (e) => {
    const input = e.target.closest && e.target.closest('input[type="date"]');
    if (input) {
      if (input.disabled || input.readOnly) return;
      // No focus on click - focusing highlights the native day/month/year
      // segment as a blue block behind the dd/mm/yyyy label. Keyboard
      // users still Tab into the field and can type a date directly.
      e.preventDefault();
      if (calInput === input) closeCalendar();
      else openCalendar(input);
      return;
    }
    if (calEl && calInput && !calEl.contains(e.target)) closeCalendar();
  }, true);
  document.addEventListener("keydown", (e) => {
    const input = e.target.closest && e.target.closest('input[type="date"]');
    // Escape closes just the calendar - not the modal it sits in.
    if (calInput && e.key === "Escape") { e.preventDefault(); e.stopImmediatePropagation(); closeCalendar(); return; }
    if (input && !input.disabled && !input.readOnly && (e.key === " " || e.key === "F4" || (e.altKey && e.key === "ArrowDown"))) {
      e.preventDefault();
      openCalendar(input);
    }
    if (input && e.key === "Tab") closeCalendar();
  }, true);
  // Typing a date straight into the field keeps the open calendar in step.
  document.addEventListener("input", (e) => {
    if (calInput && e.target === calInput) {
      const d = parseIso(calInput.value);
      if (d) calView = { year: d.year, month: d.month };
      renderCalendar();
    }
  }, true);
  document.addEventListener("scroll", (e) => {
    if (calEl && calInput && !calEl.contains(e.target)) positionCalendar();
  }, true);
  window.addEventListener("resize", () => { if (calInput) positionCalendar(); });

  // can("add" | "edit" | "delete" | "view") for the page currently shown.
  window.VoyagerShell = { init, navigateTo, can: (action) => !!pagePerm[action] };
})(window);
