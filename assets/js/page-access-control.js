/**
 * Access Control (Control Panel > Access Control).
 * Full-page version of User Management's Menu Access modal: users on the
 * left, the selected user's View/Add/Edit/Delete/Print/Export Excel per
 * menu on the right.
 * Same API as the modal (/api/user-management/ - Super Admin only).
 */
(async function () {
  const API = "/api/user-management/";
  const MODULE_ORDER = ["Masters", "Transactions", "Reports", "Control Panel"];
  const MODULE_LABEL = { Transactions: "Transactions › Airline" };
  const FLAGS = ["can_view", "can_add", "can_edit", "can_delete", "can_print", "can_export"];

  let users = [];
  let currentUser = null;
  let accessRows = [];
  let savedSnapshot = "";

  const userList = document.getElementById("ac-user-list");
  const userSearch = document.getElementById("ac-user-search");
  const menuSearch = document.getElementById("ac-menu-search");
  const tbody = document.getElementById("ac-tbody");
  const dirtyMark = document.getElementById("ac-dirty");

  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function initials(name) {
    const parts = String(name || "?").trim().split(/\s+/);
    return ((parts[0] || "?")[0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
  }

  function accessBadge(u) {
    if (!u.is_active) return `<span class="status-badge badge-muted">Inactive</span>`;
    if (u.is_super_admin) return `<span class="status-badge badge-info">Super Admin</span>`;
    if (u.menu_count > 0) return `<span class="status-badge badge-success">${u.menu_count} menu${u.menu_count === 1 ? "" : "s"}</span>`;
    return `<span class="status-badge badge-danger">No access</span>`;
  }

  const snapshot = () => JSON.stringify(accessRows.map((r) => FLAGS.map((fl) => !!r[fl])));
  const isDirty = () => !!currentUser && !currentUser.is_super_admin && snapshot() !== savedSnapshot;

  function refreshDirty() {
    dirtyMark.hidden = !isDirty();
  }

  // ---------------------------------------------------------------- users
  async function loadUsers() {
    try {
      const res = await fetch(`${API}users/`);
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      users = await res.json();
    } catch (err) {
      console.error("Could not load users - is the Django backend running?", err);
      users = [];
      userList.innerHTML = `<div class="ac-empty">Could not load users. Is the Django backend running on 127.0.0.1:8000?</div>`;
      return;
    }
    renderUsers();
  }

  function renderUsers() {
    const q = userSearch.value.trim().toLowerCase();
    const rows = users.filter((u) =>
      !q || [u.full_name, u.email, u.role].some((v) => (v || "").toLowerCase().includes(q))
    );
    document.getElementById("ac-user-count").textContent = `${users.length} user${users.length === 1 ? "" : "s"}`;
    if (!rows.length) {
      userList.innerHTML = `<div class="ac-empty">${users.length ? "No users match your search." : "No users yet - add them in User Management."}</div>`;
      return;
    }
    userList.innerHTML = rows.map((u) => `
      <button type="button" class="ac-user${currentUser && currentUser.id === u.id ? " active" : ""}${u.is_active ? "" : " inactive"}" data-id="${u.id}">
        <span class="ac-avatar">${esc(initials(u.full_name))}</span>
        <span class="ac-user-text">
          <span class="ac-user-name" style="display:block;">${esc(u.full_name)}</span>
          <span class="ac-user-sub" style="display:block;">${esc([u.role, u.email].filter(Boolean).join(" · "))}</span>
        </span>
        ${accessBadge(u)}
      </button>`).join("");
  }

  userList.addEventListener("click", async (e) => {
    const btn = e.target.closest(".ac-user");
    if (!btn) return;
    const user = users.find((u) => u.id === Number(btn.dataset.id));
    if (!user || (currentUser && currentUser.id === user.id)) return;
    if (isDirty()) {
      const ok = await voyagerConfirm(`Discard the unsaved access changes for ${currentUser.full_name}?`,
        { title: "Unsaved Changes", confirmLabel: "Discard", icon: "warning" });
      if (!ok) return;
    }
    selectUser(user);
  });

  userSearch.addEventListener("input", renderUsers);

  // --------------------------------------------------------------- access
  async function selectUser(user) {
    let rows;
    try {
      const res = await fetch(`${API}users/${user.id}/access/`);
      const data = await res.json().catch(() => []);
      if (!res.ok) throw new Error(data.error || `Could not load access (${res.status})`);
      rows = data;
    } catch (err) {
      voyagerAlert(err.message || "Could not load this user's access.", { icon: "error" });
      return;
    }
    currentUser = user;
    accessRows = rows;
    savedSnapshot = snapshot();
    menuSearch.value = "";

    document.getElementById("ac-placeholder").style.display = "none";
    ["ac-access-head", "ac-grid-scroll", "ac-foot"].forEach((id) => { document.getElementById(id).style.display = ""; });
    document.getElementById("ac-user-name").textContent = user.full_name;
    document.getElementById("ac-user-sub").textContent =
      [user.is_super_admin ? "Super Admin" : user.role, user.email, user.is_active ? "" : "Inactive"].filter(Boolean).join(" · ");
    document.getElementById("ac-super-note").style.display = user.is_super_admin ? "block" : "none";
    ["ac-select-all-btn", "ac-clear-all-btn", "ac-reset-btn", "ac-save-btn"].forEach((id) => {
      document.getElementById(id).disabled = !!user.is_super_admin;
    });
    renderUsers();
    renderAccess();
  }

  function cb(attrs, label) {
    return `<label class="ua-cell"><input type="checkbox" ${attrs} aria-label="${esc(label)}" /></label>`;
  }

  function renderAccess() {
    const locked = currentUser && currentUser.is_super_admin;
    const dis = locked ? "disabled" : "";
    const q = menuSearch.value.trim().toLowerCase();
    const shown = accessRows.filter((r) => !q || `${r.title} ${r.menu_key} ${r.module}`.toLowerCase().includes(q));
    const modules = MODULE_ORDER.concat([...new Set(accessRows.map((r) => r.module))].filter((m) => !MODULE_ORDER.includes(m)))
      .filter((m) => shown.some((r) => r.module === m));
    if (!modules.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="ac-empty">${accessRows.length ? "No menus match your search." : "No menus found."}</td></tr>`;
      refreshDirty();
      return;
    }
    tbody.innerHTML = modules.map((m) => {
      const rows = shown.filter((r) => r.module === m);
      const viewing = rows.filter((r) => locked || r.can_view).length;
      const header = `<tr class="ua-module-row"><td>${esc(MODULE_LABEL[m] || m)}<span class="ua-module-count">${viewing} / ${rows.length}</span></td>${FLAGS.map((fl) => {
        const all = rows.every((r) => locked || r[fl]);
        return `<td>${cb(`data-module="${esc(m)}" data-flag="${fl}" ${all ? "checked" : ""} ${dis}`, `${m} - all ${fl.replace("can_", "")}`)}</td>`;
      }).join("")}</tr>`;
      const body = rows.map((r) => `<tr><td>${esc(r.title)}<span class="ua-menu-key">${esc(r.menu_key)}</span></td>${FLAGS.map((fl) =>
        `<td>${cb(`data-key="${esc(r.menu_key)}" data-flag="${fl}" ${locked || r[fl] ? "checked" : ""} ${dis}`, `${r.title} - ${fl.replace("can_", "")}`)}</td>`
      ).join("")}</tr>`).join("");
      return header + body;
    }).join("");
    refreshDirty();
  }

  // Add/Edit/Delete/Print/Export implies View; clearing View clears the rest.
  function setFlag(row, flag, value) {
    row[flag] = value;
    if (value && flag !== "can_view") row.can_view = true;
    if (!value && flag === "can_view") FLAGS.forEach((fl) => { row[fl] = false; });
  }

  function visibleRows() {
    const q = menuSearch.value.trim().toLowerCase();
    return accessRows.filter((r) => !q || `${r.title} ${r.menu_key} ${r.module}`.toLowerCase().includes(q));
  }

  tbody.addEventListener("change", (e) => {
    const input = e.target;
    if (input.type !== "checkbox") return;
    const flag = input.dataset.flag;
    if (input.dataset.key) {
      const row = accessRows.find((r) => r.menu_key === input.dataset.key);
      if (row) setFlag(row, flag, input.checked);
    } else if (input.dataset.module) {
      // A module tick covers only the menus the search is showing.
      visibleRows().filter((r) => r.module === input.dataset.module).forEach((r) => setFlag(r, flag, input.checked));
    }
    renderAccess();
  });

  menuSearch.addEventListener("input", renderAccess);

  function setAll(value) {
    if (!currentUser || currentUser.is_super_admin) return;
    visibleRows().forEach((r) => FLAGS.forEach((fl) => { r[fl] = value; }));
    renderAccess();
  }

  document.getElementById("ac-select-all-btn").addEventListener("click", () => setAll(true));
  document.getElementById("ac-clear-all-btn").addEventListener("click", () => setAll(false));

  document.getElementById("ac-reset-btn").addEventListener("click", () => {
    if (!currentUser || currentUser.is_super_admin) return;
    const flags = JSON.parse(savedSnapshot);
    accessRows.forEach((r, i) => FLAGS.forEach((fl, j) => { r[fl] = flags[i][j]; }));
    renderAccess();
  });

  document.getElementById("ac-save-btn").addEventListener("click", async () => {
    if (!currentUser || currentUser.is_super_admin) return;
    const signedIn = window.VoyagerAPI.Store.getUser();
    try {
      const res = await fetch(`${API}users/${currentUser.id}/access/save/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          created_by: signedIn && signedIn.id ? signedIn.id : null,
          access: accessRows.map((r) => ({
            menu_key: r.menu_key, can_view: r.can_view, can_add: r.can_add, can_edit: r.can_edit, can_delete: r.can_delete,
            can_print: r.can_print, can_export: r.can_export,
          })),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `Save failed (${res.status})`);
      savedSnapshot = snapshot();
      const id = currentUser.id;
      await loadUsers();
      currentUser = users.find((u) => u.id === id) || currentUser;
      renderUsers();
      refreshDirty();
      voyagerAlert(`Menu access saved for ${currentUser.full_name}.`, { icon: "success" });
    } catch (err) {
      console.error("Could not save menu access", err);
      voyagerAlert(err.message || "Could not save menu access.", { icon: "error" });
    }
  });

  window.addEventListener("beforeunload", (e) => {
    if (isDirty()) { e.preventDefault(); e.returnValue = ""; }
  });

  // ---------------------------------------------------------------- init
  try {
    await VoyagerShell.init({ activeKey: "access-control" });
  } catch (err) {
    console.error("Shell init failed", err);
  }
  await loadUsers();
  // ?user=<id> opens that user straight away (User Management's lock button).
  const preset = Number(new URLSearchParams(window.location.search).get("user"));
  const first = users.find((u) => u.id === preset) || users.find((u) => !u.is_super_admin && u.is_active);
  if (first) selectUser(first);
})();
