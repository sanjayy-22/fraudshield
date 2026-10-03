// FraudShield Order Desk: plain JavaScript, no build step.
// Talks to prototypes/fraudshield-pipeline/api_dataco.py (default http://127.0.0.1:8081; override with ?api=URL).
"use strict";

const API = (new URLSearchParams(location.search).get("api") || "http://127.0.0.1:8081").replace(/\/$/, "");
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const usd = (v) => "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = (v, d = 1) => (v * 100).toFixed(d) + "%";
const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);

// Each booking status, in the words and colours the guide at the top of the page uses.
const OUTCOME = {
  CONFIRMED:             { cls: "approved", icon: "i-check", title: "Order approved",      short: "Approved" },
  VERIFICATION_REQUIRED: { cls: "verify",   icon: "i-key",   title: "Please verify",       short: "Verify" },
  UNDER_REVIEW:          { cls: "review",   icon: "i-eye",   title: "Sent to team review", short: "Team review" },
  BLOCKED:               { cls: "stopped",  icon: "i-stop",  title: "Order stopped",       short: "Stopped" },
};
const PAYMENT = {
  DEBIT: ["Card", "Debit card at checkout"], TRANSFER: ["Bank transfer", "Customer sends money from their bank"],
  PAYMENT: ["Online wallet", "A payment service such as PayPal"], CASH: ["Cash", "Paid when collected"],
};
const SPEED = { "Same Day": "Today", "First Class": "Next day", "Second Class": "In 2 days", "Standard Class": "In 4 days" };
const ACTION_WORDS = { ALLOW: "Approve", STEP_UP: "Ask to verify", HOLD: "Team review", BLOCK: "Stop" };
const SIG_FIELDS = { device_id: "#sig-device", address: "#sig-address", payment_id: "#sig-payment",
  payment_added_minutes_ago: "#sig-age", weight_kg: "#sig-weight" };

let OPT = null;       // dropdown data + thresholds from the server
let shown = null;     // the order on screen

// ------------------------------------------------------------------ server
async function api(path, opts = {}) {
  let res;
  try {
    res = await fetch(API + path, { headers: { "content-type": "application/json" }, ...opts });
  } catch {
    throw new Error("Can't reach the server. Start it with: uvicorn api_dataco:app --port 8081");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    let msg = body.detail ?? `Something went wrong (${res.status}).`;
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join(" ");
    throw new Error(msg);
  }
  return body;
}

function setConn(ok) {
  $("#conn-dot").className = "dot " + (ok ? "ok" : "down");
  $("#conn-text").textContent = ok ? "Connected" : "Can't reach the server";
}

async function start() {
  $$(".tabs button").forEach((b) => b.addEventListener("click", () => go(b.dataset.tab)));
  $$("[data-goto]").forEach((b) => b.addEventListener("click", () => go(b.dataset.goto)));
  try {
    OPT = await api("/dataco/options");
    setConn(true);
  } catch (e) {
    setConn(false); showError(e.message); setTimeout(start, 4000); return;
  }
  buildForm();
  loadDemos();
  loadRulesGuide();
  loadTour();
  refreshLists();
  setInterval(() => api("/health").then(() => setConn(true), () => setConn(false)), 15000);
}

// ------------------------------------------------------------------ guided demo
const LAYER_CLASS = { "ML model": "l-ml", "expert rules": "l-rules", "expert rule (always stops)": "l-rules",
  "a person": "l-person", "the customer": "l-customer" };
let tourBusy = false;

async function loadTour() {
  try {
    const chapters = await api("/dataco/tour");
    $("#chapters").innerHTML = chapters.map((c, i) => `
      <li class="chapter" id="ch-${esc(c.key)}">
        <div class="ch-head"><span class="num">${i + 1}</span><div><h3>${esc(c.title)}</h3><p class="ch-comp">${esc(c.component)}</p></div>
          <button type="button" class="btn blue" data-chapter="${esc(c.key)}">Run</button></div>
        <p class="muted">${esc(c.about)}</p>
        <div class="ch-steps" aria-live="polite"></div>
      </li>`).join("");
    $$("[data-chapter]").forEach((b) => b.addEventListener("click", () => runChapter(b.dataset.chapter)));
    $("#tour-all").onclick = () => runAll();
    $("#tour-reset").onclick = () => resetTour(false);
  } catch (e) { $("#tour-status").textContent = e.message; }
}

async function runChapter(key) {
  const card = $(`#ch-${key}`), out = $(".ch-steps", card), btn = $("[data-chapter]", card);
  btn.disabled = true; out.innerHTML = '<p class="loading">Running…</p>';
  try {
    const r = await api(`/dataco/tour/${key}`, { method: "POST" });
    out.innerHTML = r.steps.map(stepHtml).join("");
    $$("[data-open]", out).forEach((b) => b.addEventListener("click", async () => showOrder(await api(`/dataco/bookings/${b.dataset.open}`))));
    card.classList.add("done");
  } catch (e) { out.innerHTML = `<p class="error">${esc(e.message)}</p>`; }
  btn.disabled = false; btn.textContent = "Run again";
  refreshLists();
}

function stepHtml(s) {
  const b = s.booking, o = OUTCOME[b.status];
  const expl = s.explanation ? `<div class="ai"><div class="ai-head"><h3>In simple words</h3>${s.explanation.source === "ai"
    ? '<span class="ai-badge">Written by AI · numbers checked</span>' : '<span class="ai-badge template">Standard explanation</span>'}</div>
    <p class="ai-text">${esc(s.explanation.text)}</p></div>` : "";
  const audit = s.audit ? `<p class="audit ${s.audit.valid ? "ok" : "bad"}">Audit log: ${s.audit.records} records · chain ${s.audit.valid ? "valid" : "BROKEN"}</p>` : "";
  return `<div class="step-row">
    <div class="step-top"><svg class="${o.cls} step-icon" aria-hidden="true"><use href="#${o.icon}"/></svg>
      <b class="step-label">${esc(s.label)}</b>${badge(b.status, b.confirmed_fraud)}</div>
    <div class="step-meta"><span>Overall risk <b>${pct(b.overall_risk)}</b></span><span>AI model <b>${pct(b.model_risk)}</b></span>
      <span class="layer ${LAYER_CLASS[s.decided_by] || ""}">Decided by: ${esc(s.decided_by)}</span>
      ${b.tracking_id ? `<span>Tracking <b class="mono">${esc(b.tracking_id)}</b></span>` : ""}${b.reference ? `<span>Ref <b class="mono">${esc(b.reference)}</b></span>` : ""}</div>
    <ul class="pointers">${s.pointers.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>
    ${expl}${audit}
    <button type="button" class="link" data-open="${esc(b.booking_id)}">Open this order</button></div>`;
}

async function runAll() {
  if (tourBusy) return;
  tourBusy = true; $("#tour-all").disabled = true;
  await resetTour(true);
  for (const b of $$("[data-chapter]")) {
    $("#tour-status").textContent = `Running chapter: ${$("h3", b.closest(".chapter")).textContent}…`;
    await runChapter(b.dataset.chapter);
  }
  $("#tour-status").textContent = "Done. Open any order for the full breakdown, or try the New order tab yourself.";
  tourBusy = false; $("#tour-all").disabled = false;
}

async function resetTour(quiet = false) {
  try {
    const r = await api("/dataco/reset", { method: "POST" });
    $$(".chapter").forEach((c) => { c.classList.remove("done"); $(".ch-steps", c).innerHTML = ""; $("[data-chapter]", c).textContent = "Run"; });
    if (!quiet) $("#tour-status").textContent = `Reset done. Clock: ${r.clock.slice(0, 16)}. No orders, no known fraud.`;
    shown = null; $("#result").hidden = true; $("#order-form").hidden = false; $(".guide").hidden = false;
    refreshLists();
  } catch (e) { $("#tour-status").textContent = e.message; }
}

// ------------------------------------------------------------------ rules guide + demo buttons
function badge(status, confirmed = false) {
  const o = OUTCOME[status];
  return `<span class="badge ${o.cls}">${esc(o.short)}${confirmed ? " · confirmed fraud" : ""}</span>`;
}

async function loadRulesGuide() {
  try {
    const g = await api("/dataco/rules");
    const t = g.thresholds;
    const rows = g.rules.map((r) => `<tr><td class="w">${pct(r.weight, 0)}</td><td><b>${esc(r.name)}</b>${r.hard ? '<span class="hard">always stops</span>' : ""}<br>${esc(r.plain)}</td></tr>`).join("");
    $("#rules-guide-body").innerHTML = `
      <p>Every order gets an <b>overall risk</b>. It starts at the AI model's own estimate. Each matched rule then adds its
      percentage <i>of the risk that is left</i>, so the total never passes 100%.</p>
      <table class="guide-table"><thead><tr><th>Overall risk</th><th>What happens</th></tr></thead><tbody>
        <tr><td class="w">below ${pct(t.verify, 0)}</td><td>The AI model and a cost check decide (usually approved).</td></tr>
        <tr><td class="w">${pct(t.verify, 0)}–${pct(t.review, 0)}</td><td>Verify: the customer types a one-time code.</td></tr>
        <tr><td class="w">${pct(t.review, 0)}–${pct(t.stop, 0)}</td><td>Team review: a person checks it.</td></tr>
        <tr><td class="w">${pct(t.stop, 0)} or more</td><td>Stopped: treated as fraud.</td></tr></tbody></table>
      <div class="tablewrap"><table class="guide-table"><thead><tr><th>Weight</th><th>Rule</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="muted">The weights are set by fraud experts (they are not learned from this dataset). "Always stops" rules stop the order whatever the total.</p>`;
  } catch { /* the guide is optional */ }
}

async function loadDemos() {
  try {
    const list = await api("/dataco/demo");
    for (const [group, box] of [["one", "#demo-one"], ["combo", "#demo-combo"]]) {
      $(box).innerHTML = list.filter((s) => s.group === group).map((s) =>
        `<button type="button" class="demo-btn" data-demo="${esc(s.key)}" title="${esc(s.summary)}">${esc(s.title)} ${badge(s.expect)}</button>`).join("");
    }
    $$("[data-demo]").forEach((b) => b.addEventListener("click", () => demo(b.dataset.demo)));
  } catch { /* demos are optional */ }
}

async function demo(key) {
  try {
    const d = await api(`/dataco/demo/${key}`, { method: "POST" });
    fillForm(d.form);
    const note = $("#setup-note");
    note.innerHTML = `<h3>Demo set up: ${esc(d.title)}</h3><ul>${d.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
      <p class="muted">Expected result: ${badge(d.expect)}. Press <b>Check &amp; place order</b> below.</p>`;
    note.hidden = false;
    $("#extra").open = Object.keys(d.form.signals || {}).length > 0 || !!d.form.book_at;
    note.scrollIntoView({ block: "start", behavior: "smooth" });
  } catch (e) { showError(e.message); }
}

// ------------------------------------------------------------------ form
function options(sel, list, fn) { sel.innerHTML = list.map((x) => { const [v, t] = fn(x); return `<option value="${esc(v)}">${esc(t)}</option>`; }).join(""); }

function cardOptions(box, name, list, fn, checked) {
  box.insertAdjacentHTML("beforeend", list.map((x) => {
    const [v, title, sub] = fn(x);
    return `<label class="card-opt"><input type="radio" name="${name}" value="${esc(v)}" ${v === checked ? "checked" : ""}><b>${esc(title)}</b><small>${esc(sub)}</small></label>`;
  }).join(""));
}

function buildForm() {
  options($("#customer_segment"), OPT.segments, (s) => [s, { Consumer: "Person", Corporate: "Company", "Home Office": "Home office" }[s] || s]);
  options($("#customer_country"), OPT.customer_countries, (c) => [c, c === "EE. UU." ? "United States" : c]);
  $("#country-list").innerHTML = OPT.countries.map((c) => `<option value="${esc(c.country)}">${esc(c.region)}</option>`).join("");
  cardOptions($("#speed-options"), "speed", OPT.shipping_modes, (m) => [m, SPEED[m] || m, m], "Standard Class");
  cardOptions($("#pay-options"), "pay", OPT.payment_types, (p) => [p, PAYMENT[p][0], PAYMENT[p][1]], "DEBIT");

  $$('input[name="ctype"]').forEach((r) => r.addEventListener("change", syncCustomer));
  $("#lookup").addEventListener("click", findCustomer);
  $("#customer_id").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); findCustomer(); } });
  $("#customer_id").addEventListener("change", findCustomer);
  $("#order_country").addEventListener("input", syncCountry);
  $("#add-item").addEventListener("click", () => addItem());
  $("#order-form").addEventListener("submit", review);
  $("#confirm").addEventListener("close", place);
  $$("[data-sample]").forEach((b) => b.addEventListener("click", () => sample(b.dataset.sample)));
  sample("regular");
}

function syncCustomer() {
  const isNew = $("#ctype-new").checked;
  $("#existing-box").hidden = isNew;
  $("#new-box").hidden = !isNew;
}

async function findCustomer() {
  const id = $("#customer_id").value.trim(), out = $("#customer-info");
  if (!id) return;
  if (!/^\d+$/.test(id)) { out.textContent = "The customer number is digits only."; return; }
  try {
    const c = await api(`/dataco/customers/${id}`);
    const kind = { Consumer: "a person", Corporate: "a company", "Home Office": "a home office" }[c.segment] || c.segment;
    out.textContent = `Found: ${kind} in ${c.city}, ${c.country === "EE. UU." ? "United States" : c.country}. ${c.earlier_orders} earlier order${c.earlier_orders === 1 ? "" : "s"}.`;
  } catch (e) { out.textContent = e.message; }
}

function syncCountry() {
  $("#city-list").innerHTML = (OPT.cities[$("#order_country").value] || []).map((c) => `<option value="${esc(c)}"></option>`).join("");
}

function addItem(pid, qty = 1, disc = 0) {
  if ($("#items").children.length >= 5) return;
  const row = $("#item-tpl").content.firstElementChild.cloneNode(true);
  const n = $("#items").children.length + 1;
  $$("label", row).forEach((l, i) => { const ctl = $$("select, input", row)[i]; ctl.id = `item${n}-${i}`; l.htmlFor = ctl.id; });
  options($(".p", row), OPT.products, (p) => [p.id, `${p.name} (${usd(p.price)})`]);
  options($(".d", row), [0, 0.05, 0.1, 0.15, 0.2, 0.25], (d) => [d, d ? `${Math.round(d * 100)}% off` : "None"]);
  if (pid) $(".p", row).value = pid;
  $(".q", row).value = qty; $(".d", row).value = disc;
  row.addEventListener("input", totals);
  $(".remove", row).addEventListener("click", () => { if ($("#items").children.length > 1) { row.remove(); totals(); } });
  $("#items").appendChild(row);
  totals();
}

function totals() {
  let t = 0;
  $$("#items .item").forEach((row) => {
    const p = OPT.products.find((x) => x.id === Number($(".p", row).value));
    const v = p ? p.price * Number($(".q", row).value || 0) * (1 - Number($(".d", row).value)) : 0;
    $(".line", row).textContent = usd(v); t += v;
  });
  $("#order-total").textContent = usd(t);
  $("#add-item").hidden = $("#items").children.length >= 5;
  $$("#items .remove").forEach((b) => { b.hidden = $("#items").children.length === 1; });
}

function pick(name, value) { const el = $(`input[name="${name}"][value="${value}"]`); if (el) el.checked = true; }

function clearSignals() {
  Object.values(SIG_FIELDS).forEach((s) => { $(s).value = ""; });
  $("#sig-time").value = "";
}

function fillForm(f) {
  $("#items").innerHTML = "";
  if (f.customer_id) { $("#ctype-existing").checked = true; $("#customer_id").value = f.customer_id; }
  else {
    $("#ctype-new").checked = true;
    $("#customer_segment").value = f.customer_segment; $("#customer_country").value = f.customer_country; $("#customer_city").value = f.customer_city;
  }
  $("#order_country").value = f.order_country; $("#order_city").value = f.order_city;
  pick("speed", f.shipping_mode); pick("pay", f.payment_type);
  f.items.forEach((i) => addItem(i.product_id, i.quantity, i.discount_rate));
  clearSignals();
  Object.entries(f.signals || {}).forEach(([k, v]) => { if (SIG_FIELDS[k]) $(SIG_FIELDS[k]).value = v; });
  $("#sig-time").value = f.book_at ? String(f.book_at).slice(0, 16) : "";
  syncCustomer(); syncCountry(); hideError();
  if (f.customer_id) findCustomer();
}

function sample(kind) {
  $("#setup-note").hidden = true;
  const base = { customer_id: 12366, order_country: "El Salvador", order_city: "San Salvador", shipping_mode: "First Class",
    payment_type: "DEBIT", items: [{ product_id: 957, quantity: 1, discount_rate: 0.05 }, { product_id: 365, quantity: 3, discount_rate: 0.1 }] };
  const forms = {
    regular: base,
    transfer: { ...base, payment_type: "TRANSFER" },
    risky: { customer_id: 16106, order_country: "Países Bajos", order_city: "Almelo", shipping_mode: "Second Class", payment_type: "TRANSFER",
      items: [{ product_id: 276, quantity: 3, discount_rate: 0 }, { product_id: 172, quantity: 5, discount_rate: 0.25 }] },
    new: { customer_segment: "Consumer", customer_country: "Puerto Rico", customer_city: "Caguas", order_country: "Francia", order_city: "Paris",
      shipping_mode: "Same Day", payment_type: "TRANSFER", items: [{ product_id: 1004, quantity: 2, discount_rate: 0.2 }] },
  };
  fillForm(forms[kind]);
  $("#extra").open = false;
}

function readForm() {
  const f = {
    payment_type: $('input[name="pay"]:checked').value,
    shipping_mode: $('input[name="speed"]:checked').value,
    order_country: $("#order_country").value.trim(),
    order_city: $("#order_city").value.trim(),
    items: $$("#items .item").map((r) => ({ product_id: Number($(".p", r).value), quantity: Number($(".q", r).value), discount_rate: Number($(".d", r).value) })),
  };
  if ($("#ctype-new").checked) {
    Object.assign(f, { customer_segment: $("#customer_segment").value, customer_country: $("#customer_country").value, customer_city: $("#customer_city").value.trim() });
  } else f.customer_id = Number($("#customer_id").value.trim());
  const sig = {};
  for (const [k, sel] of Object.entries(SIG_FIELDS)) {
    const v = $(sel).value.trim();
    if (v) sig[k] = ["payment_added_minutes_ago", "weight_kg"].includes(k) ? Number(v) : v;
  }
  if (Object.keys(sig).length) f.signals = sig;
  const t = $("#sig-time").value.trim();
  if (t) f.book_at = t;
  return f;
}

function problem(f) {
  if (!$("#ctype-new").checked && !(f.customer_id > 0)) return "Step 1: type a customer number, or choose New customer.";
  if ($("#ctype-new").checked && !f.customer_city) return "Step 1: type the new customer's home city.";
  if (!OPT.countries.some((c) => c.country === f.order_country)) return "Step 2: pick a country from the list (names are in Spanish, e.g. Francia).";
  if (!f.order_city) return "Step 2: type the city.";
  if (f.items.some((i) => !(i.quantity >= 1 && i.quantity <= 5))) return "Step 3: each item can have 1 to 5 pieces.";
  if (f.signals && f.signals.weight_kg !== undefined && !(f.signals.weight_kg > 0)) return "Step 5: parcel weight must be more than 0 kg.";
  return null;
}

function showError(m) { const e = $("#form-error"); e.textContent = m; e.hidden = false; e.scrollIntoView({ block: "center", behavior: "smooth" }); }
function hideError() { $("#form-error").hidden = true; }

// ------------------------------------------------------------------ confirm + place
let pending = null;

function review(ev) {
  ev.preventDefault();
  const f = readForm(), p = problem(f);
  if (p) { showError(p); return; }
  hideError(); pending = f;
  const items = f.items.map((i) => {
    const pr = OPT.products.find((x) => x.id === i.product_id);
    return `${i.quantity} × ${esc(pr.name)}${i.discount_rate ? ` (${Math.round(i.discount_rate * 100)}% off)` : ""}`;
  }).join("<br>");
  const sig = f.signals || {};
  const extra = [sig.device_id && `device ${esc(sig.device_id)}`, sig.payment_id && `payment ${esc(sig.payment_id)}${sig.payment_added_minutes_ago !== undefined ? ` (added ${sig.payment_added_minutes_ago} min ago)` : ""}`,
    sig.weight_kg && `${sig.weight_kg} kg`, sig.address && esc(sig.address), f.book_at && `booked at ${esc(f.book_at)}`].filter(Boolean).join(" · ");
  $("#confirm-summary").innerHTML = `
    <dt>Customer</dt><dd>${f.customer_id ? "Number " + f.customer_id : "New customer from " + esc(f.customer_city)}</dd>
    <dt>Going to</dt><dd>${esc(f.order_city)}, ${esc(f.order_country)}</dd>
    <dt>Arrives</dt><dd>${esc(SPEED[f.shipping_mode])}</dd>
    <dt>Items</dt><dd>${items}</dd>
    <dt>Total</dt><dd>${$("#order-total").textContent}</dd>
    <dt>Payment</dt><dd>${esc(PAYMENT[f.payment_type][0])}</dd>
    ${extra ? `<dt>Extra signals</dt><dd>${extra}</dd>` : ""}`;
  $("#confirm").showModal();
}

async function place() {
  if ($("#confirm").returnValue !== "ok" || !pending) return;
  const btn = $("#submit-btn"); btn.disabled = true; btn.textContent = "Checking the order…";
  try { showOrder(await api("/dataco/bookings", { method: "POST", body: JSON.stringify(pending) })); }
  catch (e) { showError(e.message); }
  finally { btn.disabled = false; btn.textContent = "Check & place order"; pending = null; refreshLists(); }
}

// ------------------------------------------------------------------ result screen
function showOrder(b) {
  shown = b;
  const o = OUTCOME[b.status];
  $("#order-form").hidden = true;
  $(".guide").hidden = true;
  const box = $("#result");
  box.hidden = false;
  const title = b.confirmed_fraud ? "Stopped · confirmed fraud" : o.title;
  box.innerHTML = `
    <article class="outcome ${o.cls}">
      <div class="outcome-head"><svg aria-hidden="true"><use href="#${o.icon}"/></svg>
        <div><h2>${title}</h2><p class="order-no">Order ${esc(b.booking_id.replace("dataco-", "#"))} · ${usd(b.summary.net_total)} to ${esc(b.summary.order_city)}</p></div></div>
      <p>${esc(b.message)}</p>
      ${nextStep(b)}
    </article>

    <section class="ai" id="ai-box" aria-live="polite">
      <div class="ai-head"><h3>In simple words</h3><span id="ai-badge"></span></div>
      <p class="ai-text" id="ai-text"><span class="loading">Writing an explanation…</span></p>
      <p class="ai-note" id="ai-note"></p>
      <div class="row-start"><button type="button" class="btn ghost" id="ai-again">Write it again</button></div>
    </section>

    <section class="panel">
      <h3>How the risk adds up</h3>
      ${addsUp(b)}
      ${ruler(b)}
      <p><b>Decision:</b> ${esc(cap(b.decided_by))}.</p>
    </section>

    ${b.reasons.length ? `<section class="panel"><h3>What the AI model noticed</h3>
      <ul class="reasons">${b.reasons.map((r) => `<li>${esc(reasonText(r))}</li>`).join("")}</ul>
      <p class="muted">These shaped the model's own ${pct(b.model_risk)} estimate, before the rules.</p></section>` : ""}

    <details class="expert"><summary>Details for experts</summary>${expert(b)}</details>

    <div class="row-start">
      <button type="button" class="btn primary" id="again">Place another order</button>
      <button type="button" class="btn ghost" data-goto="mine">See all my orders</button>
    </div>`;
  $("#again").addEventListener("click", newOrder);
  $$("[data-goto]", box).forEach((x) => x.addEventListener("click", () => go(x.dataset.goto)));
  const vf = $("#verify-form", box); if (vf) vf.addEventListener("submit", verify);
  const rv = $("#to-review", box); if (rv) rv.addEventListener("click", () => go("review"));
  const ck = $("#check-again", box); if (ck) ck.addEventListener("click", async () => showOrder(await api(`/dataco/bookings/${b.booking_id}`)));
  $("#ai-again").addEventListener("click", () => explain(b, true));
  explain(b, false);
  go("new");
  box.scrollIntoView({ block: "start", behavior: "smooth" });
}

async function explain(b, refresh) {
  $("#ai-text").innerHTML = '<span class="loading">Writing an explanation…</span>';
  $("#ai-badge").innerHTML = ""; $("#ai-note").textContent = "";
  try {
    const x = await api(`/dataco/bookings/${b.booking_id}/explain${refresh ? "?refresh=true" : ""}`, { method: "POST" });
    if (!shown || shown.booking_id !== b.booking_id) return;
    $("#ai-text").textContent = x.text;
    $("#ai-badge").innerHTML = x.source === "ai"
      ? '<span class="ai-badge">Written by AI · numbers checked</span>'
      : '<span class="ai-badge template">Standard explanation</span>';
    $("#ai-note").textContent = x.source === "ai" ? `Model: ${x.model}. Every number was checked against the facts on this page.`
      : `AI explanation not used: ${x.note}.`;
  } catch (e) { $("#ai-text").textContent = e.message; }
}

function addsUp(b) {
  const steps = b.risk_steps || [];
  const rows = steps.map((s, i) => {
    if (i === 0) return `<li class="base"><span class="nm">Starting point: the AI model</span><span class="wt">${pct(s.after)}</span>
      <span class="mn">The model's own fraud estimate from the order details and the customer's history.</span></li>`;
    const h = b.rules_matched[i - 1];
    return `<li><span class="nm">+ ${esc(h.name)}${h.hard ? '<span class="hard">always stops</span>' : ""}</span><span class="wt">${pct(h.weight, 0)}</span>
      <span class="mn">${esc(h.plain)}</span>
      <span class="bar" aria-hidden="true"><b style="width:${(h.before * 100).toFixed(1)}%"></b><i style="left:${(h.before * 100).toFixed(1)}%;width:${((h.after - h.before) * 100).toFixed(1)}%"></i></span>
      <span class="ft">${pct(h.before)} + (100% − ${pct(h.before)}) × ${pct(h.weight, 0)} = <b>${pct(h.after)}</b></span></li>`;
  }).join("");
  const none = steps.length <= 1 ? `<p class="muted">No fraud rule matched this order.</p>` : "";
  return `<ul class="adds">${rows}<li class="total"><span class="nm">Overall risk</span><span class="wt">${pct(b.overall_risk)}</span></li></ul>${none}
    <p class="formula">Each rule adds its percentage of the risk that is left, so the total can never go over 100%.</p>`;
}

function ruler(b) {
  const t = OPT.thresholds;
  return `<div class="ruler" role="img" aria-label="Overall risk ${pct(b.overall_risk)} on the decision scale">
      <span class="tick" style="left:${t.verify * 100}%">Verify ${pct(t.verify, 0)}</span>
      <span class="tick" style="left:${t.review * 100}%">Review ${pct(t.review, 0)}</span>
      <span class="tick" style="left:${t.stop * 100}%">Stop ${pct(t.stop, 0)}</span>
      <span class="you" style="left:${Math.min(b.overall_risk * 100, 99.5)}%"></span></div>
    <div class="ruler-legend"><span style="--c:var(--sky)">Model decides</span><span style="--c:var(--apricot)">Verify</span>
      <span style="--c:#FFCBA0">Team review</span><span style="--c:var(--peach)">Stopped as fraud</span><span>▮ this order</span></div>`;
}

function reasonText(r) {
  if (r.feature === "is_transfer") return r.value ? "Paid by bank transfer" : "Not paid by bank transfer";
  if (r.feature.startsWith("cust_new")) return r.value ? cap(r.label) : `Not the ${r.label}`;
  const v = typeof r.value === "string" ? r.value : Number(r.value).toLocaleString("en-US", { maximumFractionDigits: 2 });
  return `${cap(r.label)}: ${v}`;
}

function nextStep(b) {
  if (b.status === "CONFIRMED") {
    const l = b.label;
    return `<div class="tracking"><span>Tracking number</span><span class="tn">${esc(l.tracking_id)}</span>
      <dl><dt>Delivery</dt><dd>${esc(SPEED[l.service] || l.service)} (${esc(l.service)})</dd><dt>Ship to</dt><dd>${esc(l.ship_to)}</dd>
      <dt>Pieces</dt><dd>${l.items}</dd><dt>Value</dt><dd>${usd(l.declared_value_usd)}</dd></dl></div>`;
  }
  if (b.status === "VERIFICATION_REQUIRED") {
    return `<form id="verify-form" class="codebox"><label for="code" class="sr">6-digit code</label>
      <input id="code" inputmode="numeric" maxlength="6" placeholder="••••••" autocomplete="one-time-code" required>
      <button class="btn primary" type="submit">Verify</button></form>
      <p class="muted">${b.attempts_left} tr${b.attempts_left === 1 ? "y" : "ies"} left. Three wrong codes stop the order as confirmed fraud.</p>
      ${b.demo_verification_code ? `<p class="demo">This is a demo, so no text message is sent. The code is <b>${esc(b.demo_verification_code)}</b></p>` : ""}`;
  }
  if (b.status === "UNDER_REVIEW") {
    return `<div class="row-start"><button type="button" class="btn blue" id="to-review">Open team review</button>
      <button type="button" class="btn ghost" id="check-again">Check again</button></div>`;
  }
  return `<div><span class="muted">Reference number</span><div class="ref">${esc(b.reference)}</div></div>`;
}

function expert(b) {
  const costs = b.decision.expected_costs || {};
  const rows = ["ALLOW", "STEP_UP", "HOLD", "BLOCK"].filter((a) => a in costs).map((a) =>
    `<tr class="${a === b.decision.model_action ? "chosen" : ""}"><td>${ACTION_WORDS[a]}</td><td>${costs[a] === null ? "not offered (model is sure, or no reviewer free)" : usd(costs[a])}</td></tr>`).join("");
  const f = b.rule_facts || {};
  const facts = [
    ["Bookings in the last hour", f.bookings_last_hour], ["Times the normal daily amount", f.times_normal_daily],
    ["Days since last order", f.days_since_last_order], ["Device", `${f.device}${f.new_device ? " (new)" : ""}`],
    ["Payment method", `${f.payment_method}${f.new_payment_method ? " (new)" : ""}${f.payment_age_minutes != null ? `, added ${f.payment_age_minutes} min ago` : ""}`],
    ["Destination seen before", f.destination_seen_before ? "yes" : "no"], ["Express delivery", f.express ? "yes" : "no"],
    ["Booking hour", f.booking_hour], ["Parcel weight", f.parcel_weight_kg != null ? `${f.parcel_weight_kg} kg (usual ${f.usual_weight_kg ?? "unknown"} kg)` : "not given"],
    ["Confirmed fraud at this address / device / payment", `${f.fraud_cases_at_address ?? 0} / ${f.fraud_cases_on_device ?? 0} / ${f.fraud_cases_on_payment ?? 0}`],
  ].map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v ?? "—")}</td></tr>`).join("");
  return `<h3 style="font-size:15px;margin:4px 0 6px">What the rules looked at</h3><table><tbody>${facts}</tbody></table>
    <h3 style="font-size:15px;margin:12px 0 6px">The AI model's own choice (before the rules)</h3>
    <p class="muted">Below ${pct(OPT.thresholds.verify, 0)} overall risk, the action with the lowest expected cost is used (lost parcel, annoyed customer, reviewer time). Model choice: <b>${ACTION_WORDS[b.decision.model_action] || "—"}</b>.</p>
    <table><thead><tr><th>Action</th><th>Expected cost</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="muted">Model certainty (90%): ${b.conformal.set.map(esc).join(" or ")}. Exact model score: ${pct(b.model_risk, 2)}.</p>
    <h3 style="font-size:15px;margin:12px 0 6px">History</h3>
    <ol class="timeline">${b.events.map((e) => `<li>${esc(e.at.slice(5, 16))}: ${esc(OUTCOME[e.status].short)}, ${esc(e.note)}</li>`).join("")}</ol>`;
}

async function verify(ev) {
  ev.preventDefault();
  try { showOrder(await api(`/dataco/bookings/${shown.booking_id}/verify`, { method: "POST", body: JSON.stringify({ code: $("#code").value.trim() }) })); }
  catch (e) { flash($("#result"), e.message); }
  refreshLists();
}

function flash(where, msg) {
  const p = document.createElement("p"); p.className = "error"; p.setAttribute("role", "alert"); p.textContent = msg;
  where.prepend(p);
}

function newOrder() {
  $("#result").hidden = true; $("#order-form").hidden = false; $(".guide").hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// ------------------------------------------------------------------ lists
async function refreshLists() {
  let mine = [], queue = [];
  try { [mine, queue] = await Promise.all([api("/dataco/bookings"), api("/dataco/review-queue")]); } catch { return; }
  $("#count-mine").textContent = mine.length;
  $("#count-review").textContent = queue.length;
  $("#mine-empty").hidden = mine.length > 0;
  $("#mine-list").innerHTML = mine.map((b) => {
    const o = OUTCOME[b.status];
    return `<li><button type="button" data-id="${esc(b.booking_id)}"><svg class="${o.cls}" aria-hidden="true"><use href="#${o.icon}"/></svg>
      <span class="t">${usd(b.summary.net_total)} to ${esc(b.summary.order_city)}, ${esc(b.summary.order_country)}</span>${badge(b.status, b.confirmed_fraud)}
      <span class="s">Order ${esc(b.booking_id.replace("dataco-", "#"))} · risk ${pct(b.overall_risk)} · ${esc(PAYMENT[b.summary.payment_type][0])} · ${esc(b.tracking_id || b.reference || "waiting")}</span></button></li>`;
  }).join("");
  $$("#mine-list button").forEach((x) => x.addEventListener("click", async () => showOrder(await api(`/dataco/bookings/${x.dataset.id}`))));

  $("#queue-empty").hidden = queue.length > 0;
  $("#queue").innerHTML = queue.map((b) => `<article class="qcard" data-id="${esc(b.booking_id)}">
    <h3>${usd(b.summary.net_total)} to ${esc(b.summary.order_city)}, ${esc(b.summary.order_country)}</h3>
    <p class="muted">Order ${esc(b.booking_id.replace("dataco-", "#"))} · customer ${b.customer_id} · ${esc(PAYMENT[b.summary.payment_type][0])}</p>
    <p>Overall risk <span class="big-risk">${pct(b.overall_risk)}</span></p>
    ${(b.rules_matched || []).length ? `<ul class="rules">${b.rules_matched.map((r) => `<li><span class="pct">${pct(r.weight, 0)}</span><span><b>${esc(r.name)}</b><br>${esc(r.plain)}</span></li>`).join("")}</ul>`
      : `<p class="muted">No rule matched: the AI model was unsure (model risk ${pct(b.model_risk)}).</p>`}
    <div class="field"><label for="note-${esc(b.booking_id)}">Note (optional)</label><input id="note-${esc(b.booking_id)}" maxlength="300" placeholder="e.g. called the customer"></div>
    <div class="row-start"><button type="button" class="btn blue" data-approve="true">Approve and ship</button>
    <button type="button" class="btn primary" data-approve="false">Reject: confirmed fraud</button></div></article>`).join("");
  $$("#queue button").forEach((btn) => btn.addEventListener("click", async () => {
    const card = btn.closest(".qcard"); btn.disabled = true;
    try {
      const b = await api(`/dataco/bookings/${card.dataset.id}/review`, { method: "POST",
        body: JSON.stringify({ approve: btn.dataset.approve === "true", note: $("input", card).value }) });
      showOrder(b);
    } catch (e) { flash(card, e.message); }
    refreshLists();
  }));
}

// ------------------------------------------------------------------ tabs
function go(tab) {
  $$(".tabs button").forEach((b) => { if (b.dataset.tab === tab) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current"); });
  ["tour", "new", "mine", "review"].forEach((t) => { $(`#view-${t}`).hidden = t !== tab; });
  if (tab !== "new") refreshLists();
}

start();
