/* MassageVIP Riyadh — CEO dashboard (vanilla JS, no build step).
 *
 * Security notes:
 *  - The token/key lives in sessionStorage only (cleared when the tab closes).
 *  - All rendered values are inserted with textContent, never innerHTML, so
 *    CRM data cannot inject markup.
 *  - No Supabase key ever reaches this page; it only talks to our own API.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "massagevip.auth";
  var state = { auth: null, days: 30, summary: null };

  var $ = function (id) { return document.getElementById(id); };

  function el(tag, opts, children) {
    var node = document.createElement(tag);
    opts = opts || {};
    if (opts.class) node.className = opts.class;
    if (opts.text !== undefined) node.textContent = String(opts.text);
    if (opts.type) node.type = opts.type;
    if (opts.value !== undefined) node.value = opts.value;
    (children || []).forEach(function (c) { if (c) node.appendChild(c); });
    return node;
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  function badge(kind, label) {
    return el("span", { class: "badge " + (kind || ""), text: label || kind });
  }

  function num(value) {
    if (value === null || value === undefined) return "—";
    return Number(value).toLocaleString();
  }

  function row(label, value, extra) {
    return el("div", { class: "row" }, [
      el("span", { class: "k", text: label }),
      el("span", { class: "v", text: value }),
      extra || null
    ]);
  }

  function loadAuth() {
    try { state.auth = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "null"); }
    catch (e) { state.auth = null; }
    return state.auth;
  }

  function saveAuth(auth) {
    state.auth = auth;
    if (auth) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(auth));
    else sessionStorage.removeItem(STORAGE_KEY);
  }

  function authHeaders() {
    if (!state.auth) return {};
    if (state.auth.type === "apiKey") return { "X-API-Key": state.auth.value };
    return { Authorization: "Bearer " + state.auth.value };
  }

  function api(path, options) {
    options = options || {};
    var headers = Object.assign({ "Content-Type": "application/json" }, authHeaders(), options.headers || {});
    return fetch(path, Object.assign({}, options, { headers: headers })).then(function (resp) {
      if (resp.status === 401 || resp.status === 403) {
        var err = new Error("Your session expired or is not permitted. Please sign in again.");
        err.status = resp.status;
        throw err;
      }
      if (!resp.ok) {
        return resp.json().catch(function () { return {}; }).then(function (body) {
          throw new Error(body.detail || ("Request failed (" + resp.status + ")"));
        });
      }
      return resp.json();
    });
  }

  // ---------------------------------------------------------------- views
  function showLogin(message) {
    $("login-view").hidden = false;
    $("dash-view").hidden = true;
    $("logout").hidden = true;
    var box = $("login-error");
    box.hidden = !message;
    box.textContent = message || "";
  }

  function showDashboard() {
    $("login-view").hidden = true;
    $("dash-view").hidden = false;
    $("logout").hidden = false;
  }

  function kpi(label, value, provenance) {
    var children = [el("div", { class: "label", text: label }), el("div", { class: "value", text: value })];
    if (provenance) children.push(el("div", {}, [badge(provenance, provenance === "measured" ? "measured" : provenance)]));
    return el("div", { class: "kpi" }, children);
  }

  function renderSummary(data) {
    var leads = data.leads || {}, wa = data.whatsapp || {}, bookings = data.bookings || {};
    var conv = data.conversion || {}, fu = data.follow_ups || {}, money = data.money || {};

    var kpis = $("kpis");
    clear(kpis);
    [
      ["Total leads", num(leads.total), leads.provenance],
      ["New leads today", num(leads.new_today), leads.provenance],
      ["WhatsApp inquiries", num(wa.inbound_messages), wa.provenance],
      ["Qualified leads", num(leads.qualified), leads.provenance],
      ["Confirmed bookings", num(bookings.confirmed), bookings.provenance],
      ["Completed bookings", num(bookings.completed), bookings.provenance],
      ["Lost leads", num(leads.lost), leads.provenance],
      ["Lead → booking", num(conv.lead_to_booking_rate_pct) + "%", conv.provenance]
    ].forEach(function (k) { kpis.appendChild(kpi(k[0], k[1], k[2])); });

    // Conversion
    var conversion = $("conversion");
    clear(conversion);
    conversion.appendChild(row("Lead → booking conversion", num(conv.lead_to_booking_rate_pct) + "%"));
    conversion.appendChild(row("Basis", conv.basis || "—"));
    conversion.appendChild(el("p", { class: "muted", text: conv.caveat || "" }));

    // Sources
    var sources = $("sources");
    clear(sources);
    var bySource = leads.by_source || {};
    var entries = Object.keys(bySource).map(function (k) { return [k, bySource[k]]; });
    entries.sort(function (a, b) { return b[1] - a[1]; });
    var max = entries.length ? entries[0][1] : 0;
    if (!entries.length) sources.appendChild(el("p", { class: "muted", text: "No leads recorded yet." }));
    entries.forEach(function (pair) {
      var pct = max ? Math.round((pair[1] / max) * 100) : 0;
      var bar = el("div", { class: "bar" }, [el("i")]);
      bar.firstChild.style.width = pct + "%";
      sources.appendChild(el("div", {}, [row(pair[0], num(pair[1])), bar]));
    });

    // Pipeline
    var pipeline = $("pipeline");
    clear(pipeline);
    var byStage = leads.by_stage || {};
    ["NEW", "CONTACTED", "QUALIFIED", "BOOKED", "COMPLETED", "LOST"].forEach(function (s) {
      pipeline.appendChild(row(s, num(byStage[s] || 0)));
    });

    // Campaigns
    var campaigns = $("campaigns");
    clear(campaigns);
    var rows = data.campaigns || [];
    if (!rows.length) {
      campaigns.appendChild(el("p", { class: "muted", text: "No campaigns configured yet. Campaign tracking links can be added in the CRM." }));
    } else {
      var table = el("table");
      var thead = el("thead", {}, [el("tr", {}, [
        el("th", { text: "Campaign" }), el("th", { text: "Leads" }),
        el("th", { text: "Bookings" }), el("th", { text: "Spend" })
      ])]);
      var tbody = el("tbody");
      rows.forEach(function (c) {
        tbody.appendChild(el("tr", {}, [
          el("td", { text: c.name }),
          el("td", { text: num(c.leads) }),
          el("td", { text: num(c.bookings) }),
          el("td", {}, [c.spend === null ? badge("not_recorded", "not recorded") : el("span", { text: num(c.spend) })])
        ]));
      });
      table.appendChild(thead); table.appendChild(tbody);
      campaigns.appendChild(el("div", { class: "scroll-x" }, [table]));
    }

    // Follow-ups
    var followups = $("followups");
    clear(followups);
    followups.appendChild(row("Due now", num(fu.due_now)));
    followups.appendChild(row("Scheduled", num(fu.scheduled)));
    followups.appendChild(row("Failed", num(fu.failed)));
    followups.appendChild(el("p", { class: "muted", text: "Follow-ups only ever create drafts for staff to review; nothing is sent automatically." }));

    // Money
    var moneyBox = $("money");
    clear(moneyBox);
    moneyBox.appendChild(row("Revenue (recorded)", num(money.revenue_recorded) + " " + (money.currency || "")));
    moneyBox.appendChild(row("Expenses (recorded)", num(money.expenses_recorded) + " " + (money.currency || "")));
    moneyBox.appendChild(row("Priced bookings", num(money.priced_bookings)));
    moneyBox.appendChild(el("div", {}, [badge(money.provenance, money.provenance)]));
    moneyBox.appendChild(el("p", { class: "muted", text: money.caveat || "" }));

    // Health
    var health = $("health");
    clear(health);
    var sh = data.system_health || {};
    var dbPill = el("span", { class: "pill " + (sh.database === "ok" ? "ok" : "bad"), text: sh.database || "unknown" });
    health.appendChild(el("div", { class: "row" }, [el("span", { class: "k", text: "Database" }), dbPill]));
    var last = sh.last_automation_run;
    health.appendChild(row("Last automation run", last ? (last.run_type + " · " + last.status) : "never"));

    // Notes
    var notes = $("notes");
    clear(notes);
    var mn = data.measurement_notes || {};
    Object.keys(mn).forEach(function (k) { notes.appendChild(row(k, mn[k])); });

    $("generated").textContent = "Updated " + new Date(data.generated_at).toLocaleString() +
      " · window: " + data.period_days + " days";
  }

  function load() {
    var box = $("dash-error");
    box.hidden = true;
    return api("/api/analytics/summary?days=" + state.days)
      .then(function (data) { state.summary = data; renderSummary(data); })
      .catch(function (err) {
        if (err.status === 401 || err.status === 403) { saveAuth(null); showLogin(err.message); return; }
        box.hidden = false;
        box.textContent = err.message || "Could not load metrics.";
      });
  }

  // -------------------------------------------------------------- events
  $("login-form").addEventListener("submit", function (event) {
    event.preventDefault();
    var email = $("email").value.trim();
    var password = $("password").value;
    $("login-error").hidden = true;
    api("/api/auth/login", { method: "POST", body: JSON.stringify({ email: email, password: password }) })
      .then(function (body) {
        saveAuth({ type: "jwt", value: body.access_token });
        showDashboard();
        return load();
      })
      .catch(function (err) { showLogin(err.message || "Sign in failed."); });
  });

  $("key-form").addEventListener("submit", function (event) {
    event.preventDefault();
    var key = $("apikey").value.trim();
    if (!key) return;
    saveAuth({ type: "apiKey", value: key });
    showDashboard();
    load();
  });

  $("logout").addEventListener("click", function () { saveAuth(null); showLogin(); });
  $("refresh").addEventListener("click", load);
  $("range").addEventListener("change", function (e) { state.days = Number(e.target.value) || 30; load(); });

  // --------------------------------------------------------------- start
  if (loadAuth()) { showDashboard(); load(); } else { showLogin(); }
})();
