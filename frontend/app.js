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
  CONFIRMED:             { cls: "approved", icon: "i-check", title: "Order approved",       short: "Approved" },
  VERIFICATION_REQUIRED: { cls: "verify",   icon: "i-key",   title: "Please verify",        short: "Verify" },
  UNDER_REVIEW:          { cls: "review",   icon: "i-eye",   title: "Sent to team review",  short: "Team review" },
  BLOCKED:               { cls: "stopped",  icon: "i-stop",  title: "Order stopped",        short: "Stopped" },
};
const PAYMENT = {
  DEBIT: ["Card", "Debit card at checkout"], TRANSFER: ["Bank transfer", "Customer sends money from their bank"],
  PAYMENT: ["Online wallet", "A payment service such as PayPal"], CASH: ["Cash", "Paid when collected"],
};
const SPEED = { "Same Day": "Today", "First Class": "Next day", "Second Class": "In 2 days", "Standard Class": "In 4 days" };
const ACTION_WORDS = { ALLOW: "Approve", STEP_UP: "Ask to verify", HOLD: "Team review", BLOCK: "Stop" };

let OPT = null;       // dropdown data from the server
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
  refreshLists();
  setInterval(() => api("/health").then(() => setConn(true), () => setConn(false)), 15000);
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

function sample(kind) {
  $("#items").innerHTML = "";
  if (kind === "new") {
    $("#ctype-new").checked = true;
    $("#customer_segment").value = "Consumer"; $("#customer_country").value = "Puerto Rico"; $("#customer_city").value = "Caguas";
    $("#order_country").value = "Francia"; $("#order_city").value = "Paris"; pick("speed", "Same Day");
    addItem(1004, 2, 0.2); pick("pay", "TRANSFER");
  } else if (kind === "risky") {
    $("#ctype-existing").checked = true; $("#customer_id").value = "16106";
    $("#order_country").value = "Países Bajos"; $("#order_city").value = "Almelo"; pick("speed", "Second Class");
    addItem(276, 3, 0); addItem(172, 5, 0.25); pick("pay", "TRANSFER");
  } else {
    $("#ctype-existing").checked = true; $("#customer_id").value = "12366";
    $("#order_country").value = "El Salvador"; $("#order_city").value = "San Salvador"; pick("speed", "First Class");
    addItem(957, 1, 0.05); addItem(365, 3, 0.1); pick("pay", kind === "transfer" ? "TRANSFER" : "DEBIT");
  }
  syncCustomer(); syncCountry(); hideError();
  if (!$("#ctype-new").checked) findCustomer();
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
  return f;
}

function problem(f) {
  if (!$("#ctype-new").checked && !(f.customer_id > 0)) return "Step 1: type a customer number, or choose New customer.";
  if ($("#ctype-new").checked && !f.customer_city) return "Step 1: type the new customer's home city.";
  if (!OPT.countries.some((c) => c.country === f.order_country)) return "Step 2: pick a country from the list (names are in Spanish, e.g. Francia).";
  if (!f.order_city) return "Step 2: type the city.";
  if (f.items.some((i) => !(i.quantity >= 1 && i.quantity <= 5))) return "Step 3: each item can have 1 to 5 pieces.";
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
  $("#confirm-summary").innerHTML = `
    <dt>Customer</dt><dd>${f.customer_id ? "Number " + f.customer_id : "New customer from " + esc(f.customer_city)}</dd>
    <dt>Going to</dt><dd>${esc(f.order_city)}, ${esc(f.order_country)}</dd>
    <dt>Arrives</dt><dd>${esc(SPEED[f.shipping_mode])}</dd>
    <dt>Items</dt><dd>${items}</dd>
    <dt>Total</dt><dd>${$("#order-total").textContent}</dd>
    <dt>Payment</dt><dd>${esc(PAYMENT[f.payment_type][0])}</dd>`;
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
function riskLevel(p) {
  if (p < 0.02) return ["Low", "Under 2%. Most card orders are here."];
  if (p < 0.1) return ["Medium", "2–10%. Typical for bank transfers, the only payment type with fraud in the data."];
  return ["High", "10% or more. Higher than almost all past orders."];
}

function reasonText(r) {
  if (r.feature === "is_transfer") return r.value ? "Paid by bank transfer" : "Not paid by bank transfer";
  if (r.feature.startsWith("cust_new")) return r.value ? r.label.charAt(0).toUpperCase() + r.label.slice(1) : `Not the ${r.label}`;
  const v = typeof r.value === "string" ? r.value : Number(r.value).toLocaleString("en-US", { maximumFractionDigits: 2 });
  return `${r.label.charAt(0).toUpperCase() + r.label.slice(1)}: ${v}`;
}

function showOrder(b) {
  shown = b;
  const o = OUTCOME[b.status];
  $("#order-form").hidden = true;
  $(".guide").hidden = true;
  const box = $("#result");
  box.hidden = false;
  const [level, levelNote] = riskLevel(b.p_fraud);
  const pos = Math.min(100, (b.p_fraud / 0.25) * 100);
  box.innerHTML = `
    <article class="outcome ${o.cls}">
      <div class="outcome-head"><svg aria-hidden="true"><use href="#${o.icon}"/></svg>
        <div><h2>${o.title}</h2><p class="order-no">Order ${esc(b.booking_id.replace("dataco-", "#"))} · ${usd(b.summary.net_total)} to ${esc(b.summary.order_city)}</p></div></div>
      <p>${esc(b.message)}</p>
      ${nextStep(b)}
    </article>

    <section class="panel">
      <h3>Why did this happen?</h3>
      <div>
        <div class="risk-top"><span>Fraud risk</span><span><span class="risk-level">${level}</span> · ${pct(b.p_fraud)}</span></div>
        <div class="meter" role="img" aria-label="Fraud risk ${pct(b.p_fraud)}, ${level}"><i style="left:${pos}%"></i></div>
        <div class="scale" aria-hidden="true"><span style="left:4%">Low</span><span style="left:24%">Medium</span><span style="left:70%">High</span><span style="left:100%">25%</span></div>
        <p class="muted">${esc(levelNote)}</p>
      </div>
      <p>${explainDecision(b)}</p>
      ${b.reasons.length ? `<div><h3>What pushed the risk up</h3><ul class="reasons">${b.reasons.map((r) => `<li>${esc(reasonText(r))}</li>`).join("")}</ul></div>` : ""}
      ${rulesBlock(b)}
    </section>

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
  go("new");
  box.scrollIntoView({ block: "start", behavior: "smooth" });
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
      <p class="muted">${b.attempts_left} tr${b.attempts_left === 1 ? "y" : "ies"} left. Three wrong codes stop the order.</p>
      ${b.demo_verification_code ? `<p class="demo">This is a demo, so no text message is sent. The code is <b>${esc(b.demo_verification_code)}</b></p>` : ""}`;
  }
  if (b.status === "UNDER_REVIEW") {
    return `<div class="row-start"><button type="button" class="btn blue" id="to-review">Open team review</button>
      <button type="button" class="btn ghost" id="check-again">Check again</button></div>`;
  }
  return `<div><span class="muted">Reference number</span><div class="ref">${esc(b.reference)}</div></div>`;
}

function explainDecision(b) {
  const a = b.decision.action, set = b.conformal.set;
  if (a === "ALLOW") return "The risk is low enough, so the order ships without extra checks.";
  if (a === "HOLD") return "The system <b>can't tell</b> if this order is safe or fraud, so a person checks it.";
  if (a === "STEP_UP") return set.length === 1 && set[0] === "fraud"
    ? "The order looks like past fraud cases, so we ask the customer to prove it's them. Most orders like this are still genuine."
    : "Checking with the customer costs less than the risk, so we ask for a code.";
  return "The risk is too high to ship.";
}

function rulesBlock(b) {
  const rules = b.rules_detail || [];
  if (!rules.length) return `<div><h3>Rules matched</h3><p class="muted">None.</p></div>`;
  const combined = b.rule_score;
  return `<div><h3>Rules matched</h3>
    <ul class="rules">${rules.map((r) => `<li><span class="pct">${pct(r.score, 0)}</span><span>${esc(cap(r.text))}</span></li>`).join("")}</ul>
    ${rules.length > 1 ? `<p class="muted">Together: ${pct(combined, 0)}.</p>` : ""}
    <p class="muted">A rule's percentage is how suspicious it is on its own. Rules explain the decision; the risk score above decides it.</p></div>`;
}

function expert(b) {
  const costs = b.decision.expected_costs || {};
  const rows = ["ALLOW", "STEP_UP", "HOLD", "BLOCK"].filter((a) => a in costs).map((a) =>
    `<tr class="${a === b.decision.action ? "chosen" : ""}"><td>${ACTION_WORDS[a]}</td><td>${costs[a] === null ? "not offered (model is sure, or no reviewer free)" : usd(costs[a])}</td></tr>`).join("");
  return `<p class="muted">The system picks the action with the lowest expected cost (lost parcel, annoyed customer, reviewer time).</p>
    <table><thead><tr><th>Action</th><th>Expected cost</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="muted">Model certainty (90%): ${b.conformal.set.map(esc).join(" or ")}. Exact score: ${pct(b.p_fraud, 2)}.</p>
    <h3 style="font-size:15px;margin:12px 0 6px">History</h3>
    <ol class="timeline">${b.events.map((e) => `<li>${esc(e.at.slice(11, 16))}: ${esc(OUTCOME[e.status].short)}, ${esc(e.note)}</li>`).join("")}</ol>`;
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
function badge(status) {
  const o = OUTCOME[status];
  return `<span class="badge ${o.cls}">${esc(o.short)}</span>`;
}

async function refreshLists() {
  let mine = [], queue = [];
  try { [mine, queue] = await Promise.all([api("/dataco/bookings"), api("/dataco/review-queue")]); } catch { return; }
  $("#count-mine").textContent = mine.length;
  $("#count-review").textContent = queue.length;
  $("#mine-empty").hidden = mine.length > 0;
  $("#mine-list").innerHTML = mine.map((b) => {
    const o = OUTCOME[b.status];
    return `<li><button type="button" data-id="${esc(b.booking_id)}"><svg class="${o.cls}" aria-hidden="true"><use href="#${o.icon}"/></svg>
      <span class="t">${usd(b.summary.net_total)} to ${esc(b.summary.order_city)}, ${esc(b.summary.order_country)}</span>${badge(b.status)}
      <span class="s">Order ${esc(b.booking_id.replace("dataco-", "#"))} · ${esc(PAYMENT[b.summary.payment_type][0])} · ${esc(b.tracking_id || b.reference || "waiting")}</span></button></li>`;
  }).join("");
  $$("#mine-list button").forEach((x) => x.addEventListener("click", async () => showOrder(await api(`/dataco/bookings/${x.dataset.id}`))));

  $("#queue-empty").hidden = queue.length > 0;
  $("#queue").innerHTML = queue.map((b) => `<article class="qcard" data-id="${esc(b.booking_id)}">
    <h3>${usd(b.summary.net_total)} to ${esc(b.summary.order_city)}, ${esc(b.summary.order_country)}</h3>
    <p class="muted">Order ${esc(b.booking_id.replace("dataco-", "#"))} · customer ${b.customer_id} · ${esc(PAYMENT[b.summary.payment_type][0])}</p>
    <p>Fraud risk <span class="big-risk">${pct(b.p_fraud)}</span> · ${riskLevel(b.p_fraud)[0]}</p>
    ${(b.rules_detail || []).length ? `<ul class="rules">${b.rules_detail.map((r) => `<li><span class="pct">${pct(r.score, 0)}</span><span>${esc(cap(r.text))}</span></li>`).join("")}</ul>` : ""}
    <div class="field"><label for="note-${esc(b.booking_id)}">Note (optional)</label><input id="note-${esc(b.booking_id)}" maxlength="300" placeholder="e.g. called the customer"></div>
    <div class="row-start"><button type="button" class="btn blue" data-approve="true">Approve and ship</button>
    <button type="button" class="btn primary" data-approve="false">Reject and stop</button></div></article>`).join("");
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
  ["new", "mine", "review"].forEach((t) => { $(`#view-${t}`).hidden = t !== tab; });
  if (tab !== "new") refreshLists();
}

start();
