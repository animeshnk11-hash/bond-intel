// Bond Intel dashboard: tooltips on chart marks, drawers, expandable rows, confirmations. No data is stored in
// the browser; every page is rendered by the server.
(function () {
  const tip = document.createElement("div");
  tip.id = "tip";
  document.body.appendChild(tip);

  function showTip(el, x, y) {
    let d;
    try { d = JSON.parse(el.getAttribute("data-tip")); } catch (e) { return; }
    tip.replaceChildren();
    if (d.t) { const t = document.createElement("div"); t.className = "tt"; t.textContent = d.t; tip.appendChild(t); }
    (d.r || []).forEach(function (r) {
      const row = document.createElement("div"); row.className = "tr";
      const left = document.createElement("span");
      if (r[1]) { const k = document.createElement("i"); k.className = "key"; k.style.background = r[1]; left.appendChild(k); left.append(" "); }
      left.append(r[0] || "");
      const v = document.createElement("b"); v.textContent = r[2];
      row.appendChild(left); row.appendChild(v); tip.appendChild(row);
    });
    if (d.f) { const f = document.createElement("div"); f.className = "tf"; f.textContent = d.f; tip.appendChild(f); }
    tip.style.display = "block";
    const w = tip.offsetWidth, h = tip.offsetHeight;
    let left = x + 14, top = y + 14;
    if (left + w > window.innerWidth - 8) left = x - w - 14;
    if (top + h > window.innerHeight - 8) top = y - h - 14;
    tip.style.left = left + "px"; tip.style.top = top + "px";
  }
  function hideTip() { tip.style.display = "none"; }
  document.addEventListener("pointermove", function (e) {
    const el = e.target.closest && e.target.closest("[data-tip]");
    if (el) showTip(el, e.clientX, e.clientY); else hideTip();
  });
  document.addEventListener("focusin", function (e) {
    const el = e.target.closest && e.target.closest("[data-tip]");
    if (el) { const r = el.getBoundingClientRect(); showTip(el, r.right, r.top); }
  });
  document.addEventListener("focusout", hideTip);

  // drawers: <a data-drawer="id"> opens #id; [data-close] or the backdrop closes. An open drawer is a modal
  // dialog: the page behind is inert, focus moves into the drawer and goes back to the opener on close.
  let opener = null;
  function openDrawer(id, from) {
    const d = document.getElementById(id); if (!d) return;
    d.classList.add("open"); document.getElementById("drawer-bg").classList.add("open");
    d.setAttribute("role", "dialog"); d.setAttribute("aria-modal", "true");
    const h = d.querySelector("h3"); if (h) { if (!h.id) h.id = id + "-title"; d.setAttribute("aria-labelledby", h.id); }
    const shell = document.querySelector(".shell"); if (shell) shell.inert = true;
    opener = from || null;
    const first = d.querySelector(".body input:not([type=hidden]), .body select, .body textarea");
    if (first) { first.focus({preventScroll: true}); return; }
    d.setAttribute("tabindex", "-1"); d.focus({preventScroll: true});   // a drawer to read: Tab goes on from its top
  }
  function closeDrawers() {
    document.querySelectorAll(".drawer.open").forEach(function (d) { d.classList.remove("open"); });
    const bg = document.getElementById("drawer-bg"); if (bg) bg.classList.remove("open");
    const shell = document.querySelector(".shell"); if (shell) shell.inert = false;
    const url = new URL(window.location);
    if (url.searchParams.has("open")) { url.searchParams.delete("open"); history.replaceState(null, "", url); }
    if (opener && document.contains(opener)) opener.focus();
    opener = null;
  }
  // an OBPP row opens and closes its compare panel (from the row, or the chevron button for the keyboard)
  function toggleRow(row) {
    const t = document.getElementById(row.getAttribute("data-toggle")); if (!t) return;
    t.classList.toggle("hidden"); row.classList.toggle("sel");
    const b = row.querySelector("[aria-controls]");
    if (b) b.setAttribute("aria-expanded", t.classList.contains("hidden") ? "false" : "true");
  }
  document.addEventListener("click", function (e) {
    const o = e.target.closest("[data-drawer]");
    if (o) { e.preventDefault(); openDrawer(o.getAttribute("data-drawer"), o); return; }
    if (e.target.closest("[data-close]") || e.target.id === "drawer-bg") { e.preventDefault(); closeDrawers(); return; }
    const chev = e.target.closest(".chevbtn");
    if (chev) { const row = chev.closest("[data-toggle]"); if (row) toggleRow(row); return; }
    const toggler = e.target.closest("[data-toggle]");
    if (toggler && !e.target.closest("a,button,input,label")) { toggleRow(toggler); return; }
    const link = e.target.closest("tr[data-href]");
    if (link && !e.target.closest("a,button,input")) { window.location = link.getAttribute("data-href"); }
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeDrawers(); });
  document.addEventListener("submit", function (e) {
    const msg = e.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) { e.preventDefault(); return; }
    // Save in the Exchange filters drawer saves the filters picked there, not only the ones applied
    const ff = document.getElementById("filters-form");
    if (ff && e.target.matches("form.savebar") && e.target.elements.query) {
      const fd = new FormData(ff);
      ["tab", "sort", "dir", "group", "by", "metric", "n"].forEach(function (k) { fd.delete(k); });
      if (fd.get("win") !== "CUSTOM") { fd.delete("from"); fd.delete("to"); }
      e.target.elements.query.value = new URLSearchParams(fd).toString();
    }
    // a form with data-api posts its fields as JSON to the API and shows the answer in the banner; without
    // JavaScript (or if the call fails to start) the form posts to its own action as before
    const api = e.target.getAttribute("data-api");
    if (api && window.fetch) {
      e.preventDefault();
      const f = e.target, body = {};
      new FormData(f).forEach(function (v, k) { if (k !== "csrf" && k !== "back") body[k] = v; });
      const btn = f.querySelector("button");
      if (btn) btn.disabled = true;
      fetch(api, {method: "POST", credentials: "same-origin",
                  headers: {"Content-Type": "application/json", "X-CSRF-Token": f.elements.csrf.value},
                  body: JSON.stringify(body)})
        .then(function (r) { return r.json().then(function (j) { return [r.status, j]; }); })
        .then(function (res) {
          const s = res[0], j = res[1];
          const text = j.message || (j.error && j.error.message) || "Done.";
          showBanner(text, s === 202 && j.online_run_started ? "ok" : s < 300 || s === 409 ? "warn" : "bad");
        })
        .catch(function () { f.removeAttribute("data-api"); f.submit(); })
        .finally(function () { if (btn) btn.disabled = false; });
    }
  });
  function showBanner(text, kind) {
    let b = document.getElementById("api-banner");
    if (!b) {
      b = document.createElement("div");
      b.id = "api-banner";
      b.setAttribute("role", "status");
      const main = document.querySelector("main") || document.body;
      main.insertBefore(b, main.firstChild);
    }
    b.className = "banner " + kind;
    b.textContent = text;
    b.scrollIntoView({block: "nearest"});
  }
  document.querySelectorAll("[data-autoopen]").forEach(function (d) { openDrawer(d.id); });

  // a chart too wide for its card scrolls sideways: open it on its newest data (the right end)
  function newestInView() {
    document.querySelectorAll(".chart-wrap").forEach(function (w) {
      if (w.scrollWidth > w.clientWidth) w.scrollLeft = w.scrollWidth;
    });
  }
  newestInView();
  window.addEventListener("resize", newestInView);

  // the Filters drawer's "Show N bonds": recounted on the server for the choices made so far
  const ff = document.getElementById("filters-form");
  const label = document.querySelector("[data-count-label]");
  if (ff && label && ff.getAttribute("data-count-url")) {
    let asked = 0;
    ff.addEventListener("change", function () {
      const n = ++asked;
      fetch(ff.getAttribute("data-count-url") + "?" + new URLSearchParams(new FormData(ff)), {credentials: "same-origin"})
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (d && n === asked) label.textContent = "Show " + d.bonds.toLocaleString("en-IN") + (d.bonds === 1 ? " bond" : " bonds");
        })
        .catch(function () {});
    });
  }
})();
