(function () {
  const { Store, post } = window.VoyagerAPI;

  // Already signed in? Skip straight to the dashboard.
  if (Store.getToken()) {
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
      const data = await post("/auth/login", { email, password }, { auth: false });
      if (data.requires_otp) {
        stepCredentials.style.display = "none";
        stepOtp.style.display = "block";
        if (data.dev_otp_hint) {
          otpHint.style.display = "inline-flex";
          otpHint.textContent = `Dev mode - OTP is ${data.dev_otp_hint} (no SMS/email provider configured)`;
        }
      } else {
        completeSession(data);
      }
    } catch (err) {
      showError(loginError, err.message || "Unable to sign in");
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

  document.getElementById("demo-link").addEventListener("click", (e) => {
    e.preventDefault();
    Store.setMockMode(true);
    Store.setToken("demo-token");
    Store.setRefresh("demo-refresh");
    Store.setUser(window.VoyagerMock.USER);
    window.location.href = "dashboard.html";
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
