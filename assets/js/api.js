/**
 * Voyager ERP — API client with High-Speed In-Memory Caching & Instant Mock Fallback
 * Provides ultra-fast (0ms) in-memory cached responses and instant fallback.
 */
(function (window) {
    const API_BASE =
    window.location.protocol === "file:" || (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") && window.location.port !== "8000"
      ? "http://127.0.0.1:8000/api"
      : "/api";

  const TOKEN_KEY = "voyager_access_token";
  const REFRESH_KEY = "voyager_refresh_token";
  const USER_KEY = "voyager_user";
  const COMPANY_KEY = "voyager_active_company_id";
  const MOCK_KEY = "voyager_mock_mode";

  const Store = {
    getToken: () => localStorage.getItem(TOKEN_KEY),
    setToken: (t) => localStorage.setItem(TOKEN_KEY, t),
    getRefresh: () => localStorage.getItem(REFRESH_KEY),
    setRefresh: (t) => localStorage.setItem(REFRESH_KEY, t),
    getUser: () => JSON.parse(localStorage.getItem(USER_KEY) || "null"),
    setUser: (u) => localStorage.setItem(USER_KEY, JSON.stringify(u)),
    getCompanyId: () => localStorage.getItem(COMPANY_KEY),
    setCompanyId: (id) => localStorage.setItem(COMPANY_KEY, id),
    isMockMode: () => localStorage.getItem(MOCK_KEY) === "1" || localStorage.getItem(TOKEN_KEY) === "demo-token" || !localStorage.getItem(TOKEN_KEY),
    setMockMode: (on) => (on ? localStorage.setItem(MOCK_KEY, "1") : localStorage.removeItem(MOCK_KEY)),
    clear: () => {
      [TOKEN_KEY, REFRESH_KEY, USER_KEY, MOCK_KEY].forEach((k) => localStorage.removeItem(k));
      apiCache.clear();
    },
  };

  // Every page calls the backend with plain fetch("http://127.0.0.1:8000/api/...")
  // - attach the signed-in user's token to those calls here, once, instead
  // of in every page script. The server rejects API calls without it
  // (accounting/permissions.py). A 401 means the session ended or the user
  // was deactivated: back to the login page.
  const nativeFetch = window.fetch.bind(window);
  const API_PREFIXES = [API_BASE, "http://127.0.0.1:8000/api", "http://localhost:8000/api"];
  window.fetch = function (input, init) {
    let url = typeof input === "string" ? input : (input && input.url) || "";
    if (API_BASE !== "http://127.0.0.1:8000/api" && API_BASE !== "http://localhost:8000/api") {
      if (url.startsWith("http://127.0.0.1:8000/api")) {
        url = url.replace("http://127.0.0.1:8000/api", API_BASE);
      } else if (url.startsWith("http://localhost:8000/api")) {
        url = url.replace("http://localhost:8000/api", API_BASE);
      }
    }
    const token = localStorage.getItem(TOKEN_KEY);
    const isApi = API_PREFIXES.some((p) => url.startsWith(p)) || url.startsWith("/api");
    const reqInput = typeof input === "string" ? url : (input && input.url ? new Request(url, input) : url);
    if (!isApi || !token || token === "demo-token") return nativeFetch(reqInput, init);
    const opts = { ...(init || {}) };
    const headers = new Headers(opts.headers || (typeof input !== "string" && input.headers) || {});
    if (!headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
    opts.headers = headers;
    const method = String(opts.method || (typeof input !== "string" && input.method) || "GET").toUpperCase();
    // Any save / edit / delete may change report figures - forget them all.
    if (method !== "GET") reportCache.clear();
    const cacheable = method === "GET" && REPORT_CACHE_PATTERN.test(url);
    if (cacheable) {
      const hit = reportCache.get(url);
      if (hit && Date.now() - hit.at < REPORT_CACHE_TTL_MS) {
        return Promise.resolve(new Response(hit.body, { status: hit.status, headers: { "Content-Type": "application/json" } }));
      }
    }
    return nativeFetch(input, opts).then((res) => {
      if (res.status === 401 && !url.includes("/auth/login")) {
        Store.clear();
        try { sessionStorage.removeItem("voyager_permissions"); } catch (_) {}
        window.location.href = "index.html";
      }
      if (cacheable && res.ok) {
        res.clone().text().then((body) => reportCache.set(url, { at: Date.now(), status: res.status, body })).catch(() => {});
      }
      return res;
    });
  };

  // Report data cache - a report screen already seen (Trial Balance / P&L /
  // Balance Sheet and their group drill-downs, Day Book, Ledger, Cash / Bank
  // Book, Receivables / Payables) opens instantly when you come back to it,
  // instead of loading again. Same URL (same dates / filters / group) only.
  // Kept in memory for this browser tab: cleared by any save / edit / delete
  // (non-GET call), after REPORT_CACHE_TTL_MS, and on a full page reload.
  const REPORT_CACHE_PATTERN = /\/api\/(trial-balance|profit-loss|balance-sheet|day-book|ledger-book|cash-bank-book|receivables|payables)\//;
  const REPORT_CACHE_TTL_MS = 5 * 60 * 1000;
  const reportCache = new Map();

  // Ultra-fast in-memory cache for instant GET requests
  const apiCache = new Map();

  async function request(path, { method = "GET", body, auth = true, retry = true } = {}) {
    const cacheKey = `${method}:${path}:${body ? JSON.stringify(body) : ""}`;

    // Return instant cached data for GET requests
    if (method === "GET" && apiCache.has(cacheKey)) {
      return apiCache.get(cacheKey);
    }

    // In mock/demo mode or standalone frontend
    if (Store.isMockMode() || (window.VoyagerMock && Store.getToken() === "demo-token")) {
      const result = window.VoyagerMock.handle(path, { method, body });
      if (method === "GET") apiCache.set(cacheKey, result);
      else apiCache.clear();
      return result;
    }

    const headers = { "Content-Type": "application/json" };
    if (auth) {
      const token = Store.getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;
    }

    try {
      // Abort controller with fast 2.5s timeout to prevent hanging on unreachable backends
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2500);

      const res = await fetch(`${API_BASE}${path}`, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      if (res.status === 401 && auth && retry) {
        const refreshed = await tryRefresh();
        if (refreshed) return request(path, { method, body, auth, retry: false });
        Store.clear();
        window.location.href = "index.html";
        return Promise.reject(new Error("Session expired"));
      }

      if (!res.ok) {
        // If backend route not found or error, fallback to mock data if available
        if (window.VoyagerMock) {
          const mockResult = window.VoyagerMock.handle(path, { method, body });
          if (method === "GET") apiCache.set(cacheKey, mockResult);
          else apiCache.clear();
          return mockResult;
        }
        let detail = "Request failed";
        try {
          const data = await res.json();
          detail = data.detail || JSON.stringify(data);
        } catch (_) {}
        throw new Error(detail);
      }

      if (res.status === 204) return null;
      const data = await res.json();
      if (method === "GET") apiCache.set(cacheKey, data);
      else apiCache.clear();
      return data;
    } catch (err) {
      // Graceful instant fallback to mock data on network error or timeout
      if (window.VoyagerMock) {
        const mockResult = window.VoyagerMock.handle(path, { method, body });
        if (method === "GET") apiCache.set(cacheKey, mockResult);
        else apiCache.clear();
        return mockResult;
      }
      throw err;
    }
  }

  async function tryRefresh() {
    const refresh_token = Store.getRefresh();
    if (!refresh_token) return false;
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token }),
      });
      if (!res.ok) return false;
      const data = await res.json();
      Store.setToken(data.access_token);
      return true;
    } catch (_) {
      return false;
    }
  }

  window.VoyagerAPI = {
    API_BASE,
    Store,
    apiCache,
    get: (path) => request(path),
    post: (path, body, opts = {}) => request(path, { method: "POST", body, ...opts }),
    put: (path, body, opts = {}) => request(path, { method: "PUT", body, ...opts }),
    del: (path, opts = {}) => request(path, { method: "DELETE", ...opts }),
  };
})(window);
