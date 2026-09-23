(async function () {
  const { Store, get, post, put, del } = window.VoyagerAPI;
  let activeCompanyId, allGroups = [], byParent = {}, editingId = null;

  const form = document.getElementById("group-form-panel");
  const errEl = document.getElementById("form-error");

  function showError(msg) { errEl.textContent = msg; errEl.style.display = "inline-flex"; }
  function hideError() { errEl.style.display = "none"; }

  function openForCreate() {
    editingId = null;
    document.getElementById("form-title").textContent = "New Group";
    document.getElementById("submit-form-btn").textContent = "Save Group";
    document.getElementById("group-name").value = "";
    hideError();
    form.style.display = "block";
    form.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function openForEdit(group) {
    editingId = group.id;
    document.getElementById("form-title").textContent = `Edit "${group.name}"`;
    document.getElementById("submit-form-btn").textContent = "Update Group";
    document.getElementById("group-name").value = group.name;
    document.getElementById("group-parent").value = group.parent_id || "";
    hideError();
    form.style.display = "block";
    form.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function closeForm() {
    form.style.display = "none";
    editingId = null;
  }

  function renderParentOptions(excludeId) {
    const out = [];
    function walk(parentKey, depth) {
      (byParent[parentKey] || []).forEach((g) => {
        if (g.id !== excludeId) {
          out.push(`<option value="${g.id}">${"- ".repeat(depth)}${g.name}${g.is_master ? "" : " (custom)"}</option>`);
        }
        walk(g.id, depth + 1);
      });
    }
    walk("root", 0);
    return out.join("");
  }

  async function refreshGroupList() {
    allGroups = Store.isMockMode()
      ? window.VoyagerMock.getAccountGroups(activeCompanyId)
      : await get(`/accounting/accounts/groups?company_id=${activeCompanyId}`);
    byParent = {};
    allGroups.forEach((g) => { (byParent[g.parent_id || "root"] = byParent[g.parent_id || "root"] || []).push(g); });
    document.getElementById("group-parent").innerHTML = renderParentOptions(editingId);
    render();
  }

  function render() {
    // Count ledgers under each group by checking the full account list (not just groups) -
    // needed so the Delete button can be disabled with an accurate tooltip up front.
    function renderLevel(parentKey, depth) {
      return (byParent[parentKey] || []).map((g) => {
        const indent = 16 + depth * 20;
        const badge = g.is_master
          ? `<span class="pill pill-neutral">System</span>`
          : `<span class="pill pill-success">Custom</span>`;
        const disabledAttr = g.is_master ? "disabled" : "";
        const title = g.is_master ? 'title="System group - cannot be modified"' : "";
        return `
          <div class="grp-row">
            <div class="grp-code">${g.code}</div>
            <div class="grp-name drillable" style="padding-left:${indent}px;" data-id="${g.id}" ${title}>${g.name}</div>
            <div class="grp-badge-wrap">${badge}</div>
            <div class="grp-actions">
              <button type="button" class="edit-btn" data-id="${g.id}" ${disabledAttr} ${title}>Edit</button>
              <button type="button" class="delete-btn" data-id="${g.id}" ${disabledAttr} ${title}>Delete</button>
            </div>
          </div>
          ${renderLevel(g.id, depth + 1)}`;
      }).join("");
    }
    document.getElementById("groups-body").innerHTML = renderLevel("root", 0);

    function handleGroupClick(id) {
      const group = allGroups.find((g) => g.id === id);
      if (group.is_master) { voyagerAlert('"' + group.name + '" is one of the 23 master groups and cannot be modified.'); return; }
      document.getElementById("group-parent").innerHTML = renderParentOptions(group.id);
      openForEdit(group);
    }

    document.querySelectorAll(".grp-name").forEach((el) => {
      el.addEventListener("click", () => handleGroupClick(Number(el.dataset.id)));
    });

    document.querySelectorAll(".edit-btn:not(:disabled)").forEach((btn) => {
      btn.addEventListener("click", () => {
        const group = allGroups.find((g) => g.id === Number(btn.dataset.id));
        document.getElementById("group-parent").innerHTML = renderParentOptions(group.id);
        openForEdit(group);
      });
    });
    document.querySelectorAll(".delete-btn:not(:disabled)").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const group = allGroups.find((g) => g.id === Number(btn.dataset.id));
        const ok = await voyagerConfirm(
          `Delete group "${group.name}"? This only works if no ledgers exist under it.`,
          { title: "Delete Group", confirmLabel: "Delete", icon: "delete" }
        );
        if (!ok) return;
        try {
          if (Store.isMockMode()) {
            const result = window.VoyagerMock.deleteGroup(activeCompanyId, group.id);
            if (result.error) throw new Error(result.error);
          } else {
            await del(`/accounting/accounts/groups/${group.id}?company_id=${activeCompanyId}`);
          }
          await refreshGroupList();
        } catch (err) {
          voyagerAlert(err.message || "Could not delete this group.", { icon: "error" });
        }
      });
    });
  }

  document.getElementById("new-group-btn").addEventListener("click", openForCreate);
  document.getElementById("cancel-form-btn").addEventListener("click", closeForm);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    hideError();
    const name = document.getElementById("group-name").value.trim();
    const parent_id = parseInt(document.getElementById("group-parent").value);
    if (!name || !parent_id) return;

    try {
      if (editingId) {
        if (Store.isMockMode()) {
          const result = window.VoyagerMock.updateGroup(activeCompanyId, { id: editingId, name, parent_id });
          if (result.error) throw new Error(result.error);
        } else {
          await put(`/accounting/accounts/groups/${editingId}?company_id=${activeCompanyId}`, { name, parent_id });
        }
      } else {
        if (Store.isMockMode()) {
          const result = window.VoyagerMock.addGroup(activeCompanyId, { name, parent_id });
          if (result.error) throw new Error(result.error);
        } else {
          await post(`/accounting/accounts/groups?company_id=${activeCompanyId}`, { name, parent_id });
        }
      }
      closeForm();
      await refreshGroupList();
    } catch (err) {
      showError(err.message || "Could not save this group.");
    }
  });

  const active = await VoyagerShell.init({
    activeKey: "groups",
    onCompanyChange: (id) => { activeCompanyId = Number(id); closeForm(); refreshGroupList(); },
  });
  if (active) { activeCompanyId = Number(active.id); refreshGroupList(); }
})();
