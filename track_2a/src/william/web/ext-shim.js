// Runs the Firefox extension's pages (batch, viewer) as plain web pages served by William's server.
// Supplies the two browser.* APIs they use, and sends what the extension fetched cross-origin
// (documents, OpenParlData, Google News, Apertus) through the server: a web page can't read other
// origins, and the Apertus key stays on the server.
(() => {
  const realFetch = window.fetch.bind(window);
  const PREFIX = "william.ext.";

  const read = (k) => {
    try { const v = localStorage.getItem(PREFIX + k); return v == null ? undefined : JSON.parse(v); } catch { return undefined; }
  };

  window.browser = {
    runtime: {
      getURL: (p) => new URL("/ext/" + String(p).replace(/^\/+/, ""), location.origin).href,
    },
    storage: {
      local: {
        async get(keys) {
          const list = keys == null ? [] : Array.isArray(keys) ? keys : typeof keys === "string" ? [keys] : Object.keys(keys);
          const out = {};
          for (const k of list) { const v = read(k); if (v !== undefined) out[k] = v; }
          // the server holds the key; engine.js only checks that one is set
          if (list.includes("apiKey")) out.apiKey = "server";
          return out;
        },
        async set(obj) {
          for (const [k, v] of Object.entries(obj || {})) {
            if (k === "apiKey") continue;
            try { localStorage.setItem(PREFIX + k, JSON.stringify(v)); } catch {}
          }
        },
      },
    },
  };

  window.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (url.origin === location.origin) return realFetch(input, init);
    if (url.pathname.endsWith("/chat/completions")) {
      return realFetch("/web/llm", { method: "POST", headers: { "content-type": "application/json" }, body: init.body });
    }
    const r = await realFetch("/web/fetch?url=" + encodeURIComponent(url.href));
    const body = [101, 204, 205, 304].includes(r.status) ? null : await r.arrayBuffer();
    const res = new Response(body, { status: r.status, statusText: r.statusText, headers: r.headers });
    // engine.js records the document's final URL from res.url, so report the real one, not the proxy's
    Object.defineProperty(res, "url", { value: r.headers.get("x-final-url") || url.href });
    return res;
  };
})();
