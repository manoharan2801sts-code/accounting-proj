/**
 * User Management (Control Panel > User Management).
 * Users CRUD + a per-user Menu Access modal (View/Add/Edit/Delete per menu).
 * View flags drive which menus each user sees (shell.js); Add/Edit/Delete
 * are stored but not yet enforced on individual screens.
 */
(async function () {
  const API = "http://localhost:8000/api/user-management/";
  const MODULE_ORDER = ["Masters", "Transactions", "Reports", "Control Panel"];
  const MODULE_LABEL = { Transactions: "Transactions › Airline" };
  const FLAGS = ["can_view", "can_add", "can_edit", "can_delete"];

  let users = [];
  let editingUserId = null;
  let accessUser = null;
  let accessRows = [];

  const tbody = document.getElementById("user-tbody");
  const searchInput = document.getElementById("um-search");
  const userModal = document.getElementById("um-user-modal");
  const accessModal = document.getElementById("um-access-modal");
  const uaTbody = document.getElementById("ua-tbody");

  const f = {
    fullName: document.getElementById("um-full-name"),
    email: document.getElementById("um-email"),
    password: document.getElementById("um-password"),
    role: document.getElementById("um-role"),
    branch: document.getElementById("um-branch"),
    isSuperAdmin: document.getElementById("um-is-super-admin"),
    isActive: document.getElementById("um-is-active"),
  };

  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  const ICONS = {
    edit: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 3a2.85 2.85 0 114 4L7.5 20.5 2 22l1.5-5.5z"/></svg>`,
    lock: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>`,
    deactivate: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><line x1="8" y1="8" x2="16" y2="16"/></svg>`,
    activate: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>`,
    trash: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18"/><path d="M8 6V4a1 1 0 011-1h6a1 1 0 011 1v2"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>`,
  };

  function accessBadge(u) {
    if (u.is_super_admin) return `<span class="status-badge badge-info">Super Admin</span>`;
    if (u.menu_count > 0) return `<span class="status-badge badge-success">${u.menu_count} menu${u.menu_count === 1 ? "" : "s"}</span>`;
    return `<span class="status-badge badge-danger">No access</span>`;
  }

  // ---------------------------------------------------------------- grid
  async function loadUsers() {
    try {
      const res = await fetch(`${API}users/`);
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      users = await res.json();
    } catch (err) {
      console.error("Could not load users - is the Django backend running?", err);
      users = [];
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:2rem; color:var(--color-text-muted);">Could not load users. Is the Django backend running on localhost:8000?</td></tr>`;
      return;
    }
    renderUsers();
  }

  function renderUsers() {
    const q = searchInput.value.trim().toLowerCase();
    const rows = users.filter((u) =>
      !q || [u.full_name, u.email, u.role, u.branch_name].some((v) => (v || "").toLowerCase().includes(q))
    );
    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:2rem; color:var(--color-text-muted);">${users.length ? "No users match your search." : "No users yet - use Add User to create one."}</td></tr>`;
      return;
    }
    tbody.innerHTML = rows.map((u) => `
      <tr data-id="${u.id}">
        <td style="font-weight:600; color:var(--color-text-dark);">${esc(u.full_name)}</td>
        <td>${esc(u.email)}</td>
        <td>${esc(u.role)}</td>
        <td>${esc(u.branch_name || "-")}</td>
        <td>${accessBadge(u)}</td>
        <td><span class="status-badge ${u.is_active ? "badge-active" : "badge-inactive"}">${u.is_active ? "Active" : "Inactive"}</span></td>
        <td class="row-actions">
          <button type="button" class="um-edit-btn" title="Edit">${ICONS.edit}</button>
          <button type="button" class="um-access-btn" title="Menu Access">${ICONS.lock}</button>
          <button type="button" class="um-toggle-btn" title="${u.is_active ? "Deactivate" : "Activate"}">${u.is_active ? ICONS.deactivate : ICONS.activate}</button>
          <button type="button" class="um-delete-btn" title="Delete">${ICONS.trash}</button>
        </td>
      </tr>`).join("");
  }

  tbody.addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    const row = e.target.closest("tr[data-id]");
    if (!btn || !row) return;
    const user = users.find((u) => u.id === Number(row.dataset.id));
    if (!user) return;
    if (btn.classList.contains("um-edit-btn")) openUserModal(user);
    else if (btn.classList.contains("um-access-btn")) openAccessModal(user);
    else if (btn.classList.contains("um-toggle-btn")) toggleActive(user);
    else if (btn.classList.contains("um-delete-btn")) deleteUser(user);
  });

  searchInput.addEventListener("input", renderUsers);

  // ---------------------------------------------------------- user modal
  function openUserModal(user) {
    editingUserId = user ? user.id : null;
    document.getElementById("um-user-modal-title").textContent = user ? "Edit User" : "Add User";
    f.fullName.value = user ? user.full_name : "";
    f.email.value = user ? user.email : "";
    f.password.value = "";
    f.password.placeholder = user ? "Leave blank to keep current password" : "At least 6 characters";
    document.getElementById("um-password-req").style.display = user ? "none" : "";
    f.role.value = user ? user.role : "";
    f.branch.value = user ? (user.branch_name || "") : "";
    f.isSuperAdmin.checked = user ? user.is_super_admin : false;
    f.isActive.checked = user ? user.is_active : true;
    userModal.classList.add("open");
    setTimeout(() => f.fullName.focus(), 50);
  }

  function closeUserModal() {
    userModal.classList.remove("open");
    editingUserId = null;
  }

  async function saveUser(payload) {
    const res = await fetch(`${API}users/save/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Save failed (${res.status})`);
    return data;
  }

  function userPayload(user, overrides) {
    return {
      id: user.id, full_name: user.full_name, email: user.email, role: user.role,
      branch_name: user.branch_name, is_super_admin: user.is_super_admin, is_active: user.is_active,
      ...overrides,
    };
  }

  document.getElementById("um-user-save-btn").addEventListener("click", async () => {
    const fullName = f.fullName.value.trim();
    const email = f.email.value.trim();
    if (!fullName) { voyagerAlert("Full Name is required.", { focusId: "um-full-name" }); return; }
    if (!email) { voyagerAlert("Email is required.", { focusId: "um-email" }); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { voyagerAlert("Enter a valid Email address.", { focusId: "um-email" }); return; }
    const password = f.password.value;
    if (!editingUserId && !password) { voyagerAlert("Password is required.", { focusId: "um-password" }); return; }
    if (password && password.length < 6) { voyagerAlert("Password must be at least 6 characters.", { focusId: "um-password" }); return; }

    const existing = editingUserId ? users.find((u) => u.id === editingUserId) : null;
    const promoting = f.isSuperAdmin.checked && !(existing && existing.is_super_admin);
    const demoting = !f.isSuperAdmin.checked && existing && existing.is_super_admin;
    if (promoting || demoting) {
      const ok = await voyagerConfirm(
        promoting
          ? `Make ${fullName} a Super Admin? Super Admins have full access to every menu.`
          : `Remove Super Admin from ${fullName}? They will only keep the menus ticked in Menu Access.`,
        { title: "Change Role", confirmLabel: promoting ? "Promote" : "Remove", icon: "warning" }
      );
      if (!ok) return;
    }

    try {
      await saveUser({
        id: editingUserId, full_name: fullName, email, password,
        role: f.role.value.trim() || "User", branch_name: f.branch.value.trim(),
        is_super_admin: f.isSuperAdmin.checked, is_active: f.isActive.checked,
      });
      closeUserModal();
      await loadUsers();
      voyagerAlert(existing ? "User updated." : "User created.", { icon: "success" });
    } catch (err) {
      console.error("Could not save user", err);
      voyagerAlert(err.message || "Could not save this user.", { icon: "error" });
    }
  });

  document.getElementById("add-user-btn").addEventListener("click", () => openUserModal(null));
  document.getElementById("um-user-cancel-btn").addEventListener("click", closeUserModal);
  document.getElementById("um-user-close-btn").addEventListener("click", closeUserModal);

  async function toggleActive(user) {
    const deactivating = user.is_active;
    const ok = await voyagerConfirm(
      deactivating ? `Deactivate ${user.full_name}?` : `Activate ${user.full_name}?`,
      { title: deactivating ? "Deactivate User" : "Activate User", confirmLabel: deactivating ? "Deactivate" : "Activate", icon: "warning" }
    );
    if (!ok) return;
    try {
      await saveUser(userPayload(user, { is_active: !user.is_active }));
      await loadUsers();
    } catch (err) {
      voyagerAlert(err.message || "Could not update this user.", { icon: "error" });
    }
  }

  async function deleteUser(user) {
    const ok = await voyagerConfirm(`Are you sure you want to delete ${user.full_name}? This cannot be undone.`, { icon: "delete" });
    if (!ok) return;
    try {
      const res = await fetch(`${API}users/${user.id}/delete/`, { method: "DELETE" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `Delete failed (${res.status})`);
      await loadUsers();
    } catch (err) {
      voyagerAlert(err.message || "Could not delete this user.", { icon: "error" });
    }
  }

  // -------------------------------------------------------- access modal
  async function openAccessModal(user) {
    try {
      const res = await fetch(`${API}users/${user.id}/access/`);
      const data = await res.json().catch(() => []);
      if (!res.ok) throw new Error(data.error || `Could not load access (${res.status})`);
      accessRows = data;
    } catch (err) {
      voyagerAlert(err.message || "Could not load this user's access.", { icon: "error" });
      return;
    }
    accessUser = user;
    document.getElementById("ua-user-name").textContent = user.full_name;
    document.getElementById("ua-user-sub").textContent =
      [user.is_super_admin ? "Super Admin" : user.role, user.branch_name].filter(Boolean).join(" · ");
    document.getElementById("ua-super-note").style.display = user.is_super_admin ? "block" : "none";
    renderAccess();
    accessModal.classList.add("open");
  }

  function closeAccessModal() {
    accessModal.classList.remove("open");
    accessUser = null;
    accessRows = [];
  }

  function cb(attrs, label) {
    return `<label class="ua-cell"><input type="checkbox" ${attrs} aria-label="${esc(label)}" /></label>`;
  }

  function renderAccess() {
    const locked = accessUser && accessUser.is_super_admin;
    const dis = locked ? "disabled" : "";
    const modules = MODULE_ORDER.filter((m) => accessRows.some((r) => r.module === m));
    uaTbody.innerHTML = modules.map((m) => {
      const rows = accessRows.filter((r) => r.module === m);
      const header = `<tr class="ua-module-row"><td>${esc(MODULE_LABEL[m] || m)}</td>${FLAGS.map((fl) => {
        const all = rows.every((r) => locked || r[fl]);
        return `<td>${cb(`data-module="${esc(m)}" data-flag="${fl}" ${all ? "checked" : ""} ${dis}`, `${m} - all ${fl.replace("can_", "")}`)}</td>`;
      }).join("")}</tr>`;
      const body = rows.map((r) => `<tr><td>${esc(r.title)}<span class="ua-menu-key">${esc(r.menu_key)}</span></td>${FLAGS.map((fl) =>
        `<td>${cb(`data-key="${esc(r.menu_key)}" data-flag="${fl}" ${locked || r[fl] ? "checked" : ""} ${dis}`, `${r.title} - ${fl.replace("can_", "")}`)}</td>`
      ).join("")}</tr>`).join("");
      return header + body;
    }).join("");
  }

  // Add/Edit/Delete implies View; clearing View clears the rest.
  function setFlag(row, flag, value) {
    row[flag] = value;
    if (value && flag !== "can_view") row.can_view = true;
    if (!value && flag === "can_view") { row.can_add = false; row.can_edit = false; row.can_delete = false; }
  }

  uaTbody.addEventListener("change", (e) => {
    const input = e.target;
    if (input.type !== "checkbox") return;
    const flag = input.dataset.flag;
    if (input.dataset.key) {
      const row = accessRows.find((r) => r.menu_key === input.dataset.key);
      if (row) setFlag(row, flag, input.checked);
    } else if (input.dataset.module) {
      accessRows.filter((r) => r.module === input.dataset.module).forEach((r) => setFlag(r, flag, input.checked));
    }
    renderAccess();
  });

  function setAll(value) {
    if (accessUser && accessUser.is_super_admin) return;
    accessRows.forEach((r) => FLAGS.forEach((fl) => { r[fl] = value; }));
    renderAccess();
  }

  document.getElementById("ua-select-all-btn").addEventListener("click", () => setAll(true));
  document.getElementById("ua-clear-all-btn").addEventListener("click", () => setAll(false));
  document.getElementById("um-access-cancel-btn").addEventListener("click", closeAccessModal);
  document.getElementById("um-access-close-btn").addEventListener("click", closeAccessModal);

  document.getElementById("um-access-save-btn").addEventListener("click", async () => {
    if (!accessUser) return;
    if (accessUser.is_super_admin) { closeAccessModal(); return; }
    const signedIn = window.VoyagerAPI.Store.getUser();
    try {
      const res = await fetch(`${API}users/${accessUser.id}/access/save/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          created_by: signedIn && signedIn.id ? signedIn.id : null,
          access: accessRows.map((r) => ({
            menu_key: r.menu_key, can_view: r.can_view, can_add: r.can_add, can_edit: r.can_edit, can_delete: r.can_delete,
          })),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `Save failed (${res.status})`);
      closeAccessModal();
      await loadUsers();
      voyagerAlert("Menu access saved.", { icon: "success" });
    } catch (err) {
      console.error("Could not save menu access", err);
      voyagerAlert(err.message || "Could not save menu access.", { icon: "error" });
    }
  });

  // ---------------------------------------------------------------- init
  try {
    await VoyagerShell.init({ activeKey: "user-management" });
  } catch (err) {
    console.error("Shell init failed", err);
  }
  await loadUsers();
})();
