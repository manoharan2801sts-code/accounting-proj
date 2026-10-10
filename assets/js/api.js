/**
 * Voyager ERP — API client with High-Speed In-Memory Caching & Instant Mock Fallback
 * Provides ultra-fast (0ms) in-memory cached responses and instant fallback.
 */
(function (window) {
  const API_BASE =
    window.location.protocol === "file:" || ((window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") && window.location.port !== "8000")
      ? "http://127.0.0.1:8000/api"
      : "/api";

  window.API_BASE = API_BASE;

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

  // Every page calls the backend with fetch - rewrite hardcoded localhost URLs
  // to API_BASE so live deployments on Render work seamlessly. Also attach
  // the signed-in user's Bearer token to API calls.
  const nativeFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    let url = typeof input === "string" ? input : (input && input.url) || "";
    if (url.startsWith("http://localhost:8000/api")) {
      url = API_BASE + url.slice("http://localhost:8000/api".length);
      if (typeof input !== "string" && input) input = url;
      else input = url;
    } else if (url.startsWith("http://127.0.0.1:8000/api")) {
      url = API_BASE + url.slice("http://127.0.0.1:8000/api".length);
      if (typeof input !== "string" && input) input = url;
      else input = url;
    }

    const token = localStorage.getItem(TOKEN_KEY);
    const isApi = url.startsWith(API_BASE) || url.startsWith("/api") || url.includes("/api/");
    if (!isApi || !token || token === "demo-token") return nativeFetch(input, init);
    const opts = { ...(init || {}) };
    const headers = new Headers(opts.headers || (typeof input !== "string" && input.headers) || {});
    if (!headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
    opts.headers = headers;
    return nativeFetch(input, opts).then((res) => {
      if (res.status === 401 && !url.includes("/auth/login")) {
        Store.clear();
        try { sessionStorage.removeItem("voyager_permissions"); } catch (_) {}
        window.location.href = "index.html";
      }
      return res;
    });
  };

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
      // Generous timeout for remote database calls (Render + TiDB Cloud)
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 60000);

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
        if (res.status === 404 && window.VoyagerMock) {
          const mockResult = window.VoyagerMock.handle(path, { method, body });
          if (method === "GET") apiCache.set(cacheKey, mockResult);
          else apiCache.clear();
          return mockResult;
        }
        let detail = "Request failed";
        try {
          const data = await res.json();
          detail = data.error || data.detail || JSON.stringify(data);
        } catch (_) {}
        throw new Error(detail);
      }

      if (res.status === 204) return null;
      const data = await res.json();
      if (method === "GET") apiCache.set(cacheKey, data);
      else apiCache.clear();
      return data;
    } catch (err) {
      if (window.VoyagerMock && window.location.protocol === "file:") {
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
