// Floating summary panel injected into ordinary web pages (selection / page summary).
(() => {
  if (window.__williamPanel) return;
  window.__williamPanel = true;
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function panel() {
    let p = document.getElementById("william-panel");
    if (!p) {
      p = document.createElement("aside");
      p.id = "william-panel";
      document.documentElement.appendChild(p);
    }
    return p;
  }

  function render(res, selection) {
    // spans are computed by the engine (core.js locatePhrase); rebuild the text around them
    const spans = res.topics.map((t, i) => (t.span ? [t.span[0], t.span[1], i] : null)).filter(Boolean).sort((x, y) => x[0] - y[0]);
    let html = "", pos = 0;
    for (const [s0, e0, i] of spans) {
      if (s0 < pos) continue;
      html += esc(res.summary.slice(pos, s0)) + `<a class="wp-topic" data-i="${i}" href="#">${esc(res.summary.slice(s0, e0))}</a>`;
      pos = e0;
    }
    html += esc(res.summary.slice(pos));
    const chips = res.topics.map((t, i) => (t.span ? "" : `<a class="wp-topic" data-i="${i}" href="#">${esc(t.phrase)}</a>`)).filter(Boolean);
    const kp = (res.key_points || []).map((x) => `<li>${esc(x)}</li>`).join("");
    const p = panel();
    p.innerHTML = `<header><b>William</b><span>${selection ? "selection" : "page"} · ${esc(res.language)}</span><button class="wp-x" title="Close">×</button></header>
      <p class="wp-sum">${html}</p>${kp ? `<ul class="wp-kp">${kp}</ul>` : ""}
      ${chips.length ? `<div class="wp-chips">${chips.join(" ")}</div>` : ""}
      <div class="wp-hint">Highlighted topics link to Swiss news. Summary by Apertus — check against the source.</div>
      <div class="wp-news"></div>`;
    p.querySelector(".wp-x").onclick = () => p.remove();
    p.querySelectorAll(".wp-topic").forEach((a) => (a.onclick = (ev) => {
      ev.preventDefault();
      const t = res.topics[+a.dataset.i];
      p.querySelectorAll(".wp-topic.on").forEach((x) => x.classList.remove("on"));
      a.classList.add("on");
      p.querySelector(".wp-news").innerHTML = t.articles?.length
        ? `<div class="wp-nh">Swiss news · ${esc(t.query)}</div><ul>` + t.articles.map((n) =>
          `<li><a href="${/^https?:\/\//.test(n.url) ? esc(n.url) : "#"}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a><span>${esc(n.source)}</span></li>`).join("") + "</ul>"
        : `<div class="wp-nh">No Swiss news found for “${esc(t.query)}”.</div>`;
    }));
  }

  browser.runtime.onMessage.addListener((msg) => {
    if (msg.type === "william-loading") panel().innerHTML = `<header><b>William</b><span>Apertus is reading…</span></header><div class="wp-spin"></div>`;
    else if (msg.type === "william-summary") render(msg.res, msg.selection);
    else if (msg.type === "william-error") {
      const p = panel();
      p.innerHTML = `<header><b>William</b><button class="wp-x">×</button></header><p class="wp-err">${esc(msg.error)}</p>`;
      p.querySelector(".wp-x").onclick = () => p.remove();
    }
  });
})();
