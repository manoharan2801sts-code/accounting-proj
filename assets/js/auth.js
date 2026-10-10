(function () {
  const { Store, post } = window.VoyagerAPI;

  // Already signed in? Skip straight to the dashboard. A leftover demo
  // session no longer counts as signed in - clear it and show the form.
  if (Store.getToken() === "demo-token") {
    Store.clear();
  } else if (Store.getToken()) {
    window.location.href = "dashboard.html";
    return;
  }

  const stepCredentials = document.getElementById("step-credentials");
  const stepOtp = document.getElementById("step-otp");
  const loginForm = document.getElementById("login-form");
  const otpForm = document.getElementById("otp-form");
  const loginError = document.getElementById("login-error");
  const otpError = document.getElementById("otp-error");
  const otpHint = document.getElementById("otp-hint");
  const loginBtn = document.getElementById("login-btn");

  let pendingEmail = "";

  function showError(el, message) {
    el.textContent = message;
    el.style.display = "inline-flex";
  }
  function hideError(el) {
    el.style.display = "none";
  }

  function completeSession(data) {
    Store.setToken(data.access_token);
    Store.setRefresh(data.refresh_token);
    Store.setUser(data.user);
    // Data layer stays exactly as before (pages read real data via their
    // own fetch calls; VoyagerAPI.get keeps serving mock data) - only the
    // token + permissions are new.
    Store.setMockMode(true);
    try {
      sessionStorage.setItem("voyager_permissions", JSON.stringify({ is_super_admin: data.is_super_admin, menus: data.menus || {} }));
    } catch (_) {}
    window.location.href = "dashboard.html";
  }

  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    hideError(loginError);
    loginBtn.disabled = true;
    loginBtn.textContent = "Signing in...";

    const email = document.getElementById("email").value.trim();
    const password = document.getElementById("password").value;
    pendingEmail = email;

    try {
      // Straight to the backend, not VoyagerAPI.post - that one answers from
      // mock data whenever nobody is signed in yet, so it never reached here.
      const res = await fetch(`${window.VoyagerAPI.API_BASE}/auth/login/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Unable to sign in");
      completeSession(data);
    } catch (err) {
      showError(loginError, err.message === "Failed to fetch"
        ? "Cannot reach the server. Is the Django backend running on localhost:8000?"
        : (err.message || "Unable to sign in"));
    } finally {
      loginBtn.disabled = false;
      loginBtn.textContent = "Sign in";
    }
  });

  otpForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    hideError(otpError);
    const otp_code = document.getElementById("otp-code").value.trim();
    try {
      const data = await post("/auth/verify-otp", { email: pendingEmail, otp_code }, { auth: false });
      completeSession(data);
    } catch (err) {
      showError(otpError, err.message || "Invalid code");
    }
  });

  document.getElementById("back-to-login").addEventListener("click", () => {
    stepOtp.style.display = "none";
    stepCredentials.style.display = "block";
  });

  document.getElementById("forgot-link").addEventListener("click", async (e) => {
    e.preventDefault();
    const email = prompt("Enter your work email to receive a password reset code:");
    if (!email) return;
    try {
      const data = await post("/auth/forgot-password", { email }, { auth: false });
      voyagerAlert(data.dev_otp_hint
        ? `Dev mode - reset OTP is ${data.dev_otp_hint}`
        : "If that email exists, a reset code has been sent.", { icon: "info" });
    } catch (err) {
      voyagerAlert(err.message || "Something went wrong", { icon: "error" });
    }
  });
})();
