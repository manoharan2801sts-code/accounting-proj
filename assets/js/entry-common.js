(function (window) {
  function showToast(message, redirectTo) {
    const el = document.createElement("div");
    el.className = "toast-success";
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(() => {
      if (redirectTo) {
        if (window.VoyagerShell && window.VoyagerShell.navigateTo) {
          window.VoyagerShell.navigateTo(redirectTo);
        } else {
          window.location.href = redirectTo;
        }
      }
      el.remove();
    }, 900);
  }

  function fillSelect(selectEl, items, valueFn, labelFn, placeholder) {
    selectEl.innerHTML =
      (placeholder ? `<option value="">${placeholder}</option>` : "") +
      items.map((item) => `<option value="${valueFn(item)}">${labelFn(item)}</option>`).join("");
  }

  function todayISO() {
    return new Date().toISOString().slice(0, 10);
  }

  /**
   * Saves a record - creates a new one, or updates an existing one when editId
   * is passed (the "correction" step of a Tally-style zoom-in / zoom-out flow).
   * In demo mode this writes directly into the in-memory mock store. Outside
   * demo mode, only the endpoints actually built on the backend will work -
   * we surface that clearly instead of pretending everything is wired up.
   */
  async function saveRecord({ mockAdd, mockUpdate, apiPath, companyId, payload, successMessage, redirectTo, editId }) {
    const { Store } = window.VoyagerAPI;
    if (Store.isMockMode()) {
      if (editId && mockUpdate) {
        const result = mockUpdate(companyId, Number(editId), payload);
        if (result && result.error) { voyagerAlert(result.error); return false; }
      } else {
        mockAdd(companyId, payload);
      }
      showToast(successMessage, redirectTo);
      return true;
    }
    try {
      if (editId) {
        await window.VoyagerAPI.put(`${apiPath}/${editId}`, payload);
      } else {
        await window.VoyagerAPI.post(apiPath, payload);
      }
      showToast(successMessage, redirectTo);
      return true;
    } catch (err) {
      voyagerAlert(
        "This entity's " + (editId ? "update" : "create") + " endpoint isn't wired up on the live backend yet (Phase 1 shipped the read/reporting APIs). " +
        "Switch to Demo Mode from the login screen to try the full flow, or add the corresponding route to enable this for real.",
        { icon: "error" }
      );
      return false;
    }
  }

  function getEditId() {
    return new URLSearchParams(window.location.search).get("id");
  }

  function getReturnTo(defaultPage) {
    return new URLSearchParams(window.location.search).get("returnTo") || defaultPage;
  }

  function zoomInUrl(entryPage, id, returnTo) {
    return `${entryPage}?id=${id}&returnTo=${encodeURIComponent(returnTo)}`;
  }

  window.VoyagerEntry = { showToast, fillSelect, todayISO, saveRecord, getEditId, getReturnTo, zoomInUrl };
})(window);
