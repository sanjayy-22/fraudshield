// FraudShield Booking Desk: plain JavaScript, no build step.
// Backend: prototypes/fraudshield-pipeline/api_dataco.py (default http://127.0.0.1:8081, override with ?api=URL).
"use strict";

const API = (new URLSearchParams(location.search).get("api") || "http://127.0.0.1:8081").replace(/\/$/, "");
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const usd = (v) => "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const STATUS_TEXT = { CONFIRMED: "Confirmed", VERIFICATION_REQUIRED: "Verify", UNDER_REVIEW: "Under review", BLOCKED: "Blocked" };
const ACTION_TEXT = { ALLOW: "Allow", STEP_UP: "Step-up (verify)", HOLD: "Hold for review", BLOCK: "Block" };
const PAY_TEXT = {
  DEBIT: ["Debit card", "Paid by card at checkout"], TRANSFER: ["Bank transfer", "Customer sends a transfer"],
  PAYMENT: ["Online payment", "Third-party payment service"], CASH: ["Cash", "Paid on collection"],
};

let OPTIONS = null;
let current = null;           // booking shown in the result panel

// ------------------------------------------------------------------ API
async function api(path, opts = {}) {
  let res;
  try {
    res = await fetch(API + path, { headers: { "content-type": "application/json" }, ...opts });
  } catch {
    throw new Error(`Can't reach the backend at ${API}. Start it with: uvicorn api_dataco:app --port 8081`);
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    let msg = body.detail ?? `Request failed (${res.status})`;
    if (Array.isArray(msg)) msg = msg.map((d) => `${(d.loc || []).slice(1).join(".") || "form"}: ${d.msg}`).join("; ");
    throw new Error(msg);
  }
  return body;
}

// ------------------------------------------------------------------ start-up
async function init() {
  wireTabs();
  try {
    OPTIONS = await api("/dataco/options");
    setStatus(true, "backend connected");
  } catch (e) {
    setStatus(false, "backend offline");
    showFormError(e.message);
    setTimeout(init, 4000);
    return;
  }
  buildForm();
  tickClock();
  setInterval(tickClock, 15000);
  refreshLists();
}

function setStatus(ok, text) {
  $("#api-dot").className = "dot " + (ok ? "ok" : "down");
  $("#api-text").textContent = text;
}

async function tickClock() {
  try {
    const h = await api("/health");
    $("#clock").textContent = "clock " + h.clock.slice(0, 16);
    setStatus(true, "backend connected");
  } catch {
    setStatus(false, "backend offline");
  }
}

// ------------------------------------------------------------------ form
function fillSelect(sel, items, toOption) {
  sel.innerHTML = items.map((x) => { const [v, t] = toOption(x); return `<option value="${esc(v)}">${esc(t)}</option>`; }).join("");
}

function buildForm() {
  fillSelect($("#customer_segment"), OPTIONS.segments, (s) => [s, s]);
  fillSelect($("#customer_country"), OPTIONS.customer_countries, (c) => [c, c === "EE. UU." ? "EE. UU. (United States)" : c]);
  fillSelect($("#shipping_mode"), OPTIONS.shipping_modes, (m) => [m, `${m} (${OPTIONS.scheduled_days[m]} day${OPTIONS.scheduled_days[m] === 1 ? "" : "s"} scheduled)`]);
  $("#shipping_mode").value = "Standard Class";
  $("#country-list").innerHTML = OPTIONS.countries.map((c) => `<option value="${esc(c.country)}">${esc(c.region)} · ${esc(c.market)}</option>`).join("");
  $("#pay-options").innerHTML = OPTIONS.payment_types.map((p, i) =>
    `<label><input type="radio" name="payment_type" value="${p}" id="pay-${p}" ${i === 0 ? "checked" : ""}>
      <span>${esc(PAY_TEXT[p][0])}</span><small>${esc(PAY_TEXT[p][1])}</small></label>`).join("");

  document.querySelectorAll('input[name="ctype"]').forEach((r) => r.addEventListener("change", syncCustomerType));
  $("#lookup").addEventListener("click", lookupCustomer);
  $("#customer_id").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); lookupCustomer(); } });
  $("#order_country").addEventListener("input", syncCities);
  $("#add-item").addEventListener("click", () => addItem());
  $("#booking-form").addEventListener("submit", onReview);
  $("#confirm-dialog").addEventListener("close", onConfirmClosed);
  document.querySelectorAll("[data-sample]").forEach((b) => b.addEventListener("click", () => loadSample(b.dataset.sample)));
  addItem();
  loadSample("regular");
}

function syncCustomerType() {
  const isNew = $("#ctype-new").checked;
  $("#existing-box").hidden = isNew;
  $("#new-box").hidden = !isNew;
}

async function lookupCustomer() {
  const id = $("#customer_id").value.trim();
  const info = $("#customer-info");
  if (!/^\d+$/.test(id)) { info.textContent = "Customer ID must be a number."; return; }
  try {
    const c = await api(`/dataco/customers/${id}`);
    info.textContent = `${c.segment} customer in ${c.city}, ${c.country} · ${c.earlier_orders} earlier order${c.earlier_orders === 1 ? "" : "s"}`;
  } catch (e) {
    info.textContent = e.message;
  }
}

function syncCities() {
  const list = OPTIONS.cities[$("#order_country").value] || [];
  $("#city-list").innerHTML = list.map((c) => `<option value="${esc(c)}"></option>`).join("");
  const g = OPTIONS.countries.find((c) => c.country === $("#order_country").value);
  $("#geo-hint").textContent = g ? `Region: ${g.region} · market: ${g.market}` :
    "Country names follow the DataCo data, which is in Spanish (Francia, Alemania, Estados Unidos…).";
}

function addItem(productId, qty = 1, disc = 0) {
  const rows = $("#items");
  if (rows.children.length >= 5) return;
  const node = $("#item-row").content.firstElementChild.cloneNode(true);
  fillSelect($(".product", node), OPTIONS.products, (p) => [p.id, `${p.name} · ${usd(p.price)}`]);
  fillSelect($(".disc", node), [0, 0.05, 0.1, 0.15, 0.2, 0.25], (d) => [d, `${Math.round(d * 100)}%`]);
  if (productId) $(".product", node).value = productId;
  $(".qty", node).value = qty;
  $(".disc", node).value = disc;
  node.addEventListener("input", updateTotals);
  $(".remove", node).addEventListener("click", () => { if (rows.children.length > 1) { node.remove(); updateTotals(); } });
  rows.appendChild(node);
  updateTotals();
}

function readItems() {
  return [...$("#items").children].map((row) => ({
    product_id: Number($(".product", row).value),
    quantity: Number($(".qty", row).value),
    discount_rate: Number($(".disc", row).value),
  }));
}

function updateTotals() {
  let total = 0;
  [...$("#items").children].forEach((row) => {
    const p = OPTIONS.products.find((x) => x.id === Number($(".product", row).value));
    const line = p ? p.price * Number($(".qty", row).value || 0) * (1 - Number($(".disc", row).value)) : 0;
    $(".line", row).textContent = usd(line);
    total += line;
  });
  $("#order-total").textContent = usd(total);
  $("#add-item").hidden = $("#items").children.length >= 5;
}

function loadSample(kind) {
  $("#items").innerHTML = "";
  if (kind === "new") {
    $("#ctype-new").checked = true;
    $("#customer_segment").value = "Consumer"; $("#customer_country").value = "Puerto Rico"; $("#customer_city").value = "Caguas";
    $("#order_country").value = "Francia"; $("#order_city").value = "Paris"; $("#shipping_mode").value = "Same Day";
    addItem(1004, 2, 0.2);
    $(`#pay-TRANSFER`).checked = true;
  } else if (kind === "risky") {
    $("#ctype-existing").checked = true;
    $("#customer_id").value = "16106";
    $("#order_country").value = "Países Bajos"; $("#order_city").value = "Almelo"; $("#shipping_mode").value = "Second Class";
    addItem(276, 3, 0); addItem(172, 5, 0.25);
    $("#pay-TRANSFER").checked = true;
    lookupCustomer();
  } else {
    $("#ctype-existing").checked = true;
    $("#customer_id").value = "12366";
    $("#order_country").value = "El Salvador"; $("#order_city").value = "San Salvador"; $("#shipping_mode").value = "First Class";
    addItem(957, 1, 0.05); addItem(365, 3, 0.1);
    $(kind === "transfer" ? "#pay-TRANSFER" : "#pay-DEBIT").checked = true;
    lookupCustomer();
  }
  syncCustomerType(); syncCities(); hideFormError();
}

function readForm() {
  const isNew = $("#ctype-new").checked;
  const form = {
    payment_type: $('input[name="payment_type"]:checked').value,
    shipping_mode: $("#shipping_mode").value,
    order_country: $("#order_country").value.trim(),
    order_city: $("#order_city").value.trim(),
    items: readItems(),
  };
  if (isNew) {
    Object.assign(form, { customer_segment: $("#customer_segment").value, customer_country: $("#customer_country").value,
      customer_city: $("#customer_city").value.trim() });
  } else {
    form.customer_id = Number($("#customer_id").value.trim());
  }
  return form;
}

function validate(form) {
  if (!$("#ctype-new").checked && !(form.customer_id > 0)) return "Enter a customer ID, or choose New customer.";
  if ($("#ctype-new").checked && !form.customer_city) return "Enter the new customer's home city.";
  if (!OPTIONS.countries.some((c) => c.country === form.order_country)) return "Pick a destination country from the list.";
  if (!form.order_city) return "Enter the destination city.";
  if (form.items.some((i) => !(i.quantity >= 1 && i.quantity <= 5))) return "Quantity per item must be between 1 and 5.";
  return null;
}

function showFormError(msg) { const e = $("#form-error"); e.textContent = msg; e.hidden = false; }
function hideFormError() { $("#form-error").hidden = true; }

// ------------------------------------------------------------------ confirm + submit
let pendingForm = null;

function onReview(ev) {
  ev.preventDefault();
  const form = readForm();
  const err = validate(form);
  if (err) { showFormError(err); return; }
  hideFormError();
  pendingForm = form;
  const items = form.items.map((i) => {
    const p = OPTIONS.products.find((x) => x.id === i.product_id);
    return `${i.quantity} × ${esc(p.name)}${i.discount_rate ? ` (−${Math.round(i.discount_rate * 100)}%)` : ""}`;
  }).join("<br>");
  $("#confirm-summary").innerHTML = `
    <dt>Customer</dt><dd>${form.customer_id ? "#" + form.customer_id : `New · ${esc(form.customer_segment)}, ${esc(form.customer_city)}`}</dd>
    <dt>Ship to</dt><dd>${esc(form.order_city)}, ${esc(form.order_country)}</dd>
    <dt>Service</dt><dd>${esc(form.shipping_mode)}</dd>
    <dt>Items</dt><dd>${items}</dd>
    <dt>Total</dt><dd><strong>${$("#order-total").textContent}</strong></dd>
    <dt>Payment</dt><dd>${esc(PAY_TEXT[form.payment_type][0])}</dd>`;
  $("#confirm-dialog").showModal();
}

async function onConfirmClosed() {
  if ($("#confirm-dialog").returnValue !== "ok" || !pendingForm) return;
  const btn = $("#review-btn");
  btn.disabled = true; btn.textContent = "Checking…";
  try {
    const b = await api("/dataco/bookings", { method: "POST", body: JSON.stringify(pendingForm) });
    showBooking(b);
  } catch (e) {
    showFormError(e.message);
  } finally {
    btn.disabled = false; btn.textContent = "Review booking"; pendingForm = null;
    refreshLists();
  }
}

// ------------------------------------------------------------------ result panel
function showBooking(b) {
  current = b;
  $("#result-empty").hidden = true;
  const body = $("#result-body");
  body.hidden = false;
  body.innerHTML = `
    <div class="status-line"><span class="pill ${b.status}">${STATUS_TEXT[b.status]}</span><span class="bid">${esc(b.booking_id)}</span></div>
    <p class="big-status">${esc(b.message)}</p>
    ${statusBlock(b)}
    ${whyBlock(b)}
    <details><summary>History</summary><ol class="timeline">${b.events.map((e) =>
      `<li><time>${esc(e.at.slice(11, 16))}</time><span><strong>${esc(STATUS_TEXT[e.status])}</strong> · ${esc(e.note)}</span></li>`).join("")}</ol></details>`;
  const v = $("#verify-form", body);
  if (v) v.addEventListener("submit", onVerify);
  const r = $("#refresh-status", body);
  if (r) r.addEventListener("click", async () => showBooking(await api(`/dataco/bookings/${b.booking_id}`)));
  const go = $("#go-review", body);
  if (go) go.addEventListener("click", () => selectTab("review"));
  body.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function statusBlock(b) {
  if (b.status === "CONFIRMED") {
    const l = b.label;
    return `<div class="label-card" aria-label="Shipping label">
      <span class="hint">TRACKING ID</span><span class="trk">${esc(l.tracking_id)}</span>
      <dl><dt>Service</dt><dd>${esc(l.service)} · ${l.scheduled_days} day${l.scheduled_days === 1 ? "" : "s"} scheduled</dd>
      <dt>Ship to</dt><dd>${esc(l.ship_to)}</dd><dt>Region</dt><dd>${esc(l.region)}</dd>
      <dt>Customer</dt><dd>#${l.customer_id}</dd><dt>Units</dt><dd>${l.items}</dd>
      <dt>Value</dt><dd>${usd(l.declared_value_usd)}</dd><dt>Booked</dt><dd>${esc(l.booked_at.slice(0, 16))}</dd></dl></div>`;
  }
  if (b.status === "VERIFICATION_REQUIRED") {
    return `<form id="verify-form" class="code-box">
      <label class="hint" for="code">One-time code (${b.attempts_left} attempt${b.attempts_left === 1 ? "" : "s"} left)</label>
      <div class="code-box"><input id="code" inputmode="numeric" maxlength="6" autocomplete="one-time-code" required>
      <button class="primary" type="submit">Verify</button></div></form>
      ${b.demo_verification_code ? `<p class="demo-note">Demo: no SMS is sent. The code is <strong class="mono">${esc(b.demo_verification_code)}</strong>. Three wrong codes block the booking.</p>` : ""}`;
  }
  if (b.status === "UNDER_REVIEW") {
    return `<div class="actions" style="justify-content:flex-start">
      <button type="button" class="secondary" id="refresh-status">Check status</button>
      <button type="button" class="link" id="go-review">Open the review queue (analyst)</button></div>`;
  }
  return `<p class="muted">Reference</p><p class="ref">${esc(b.reference)}</p>`;
}

function whyBlock(b) {
  const order = ["ALLOW", "STEP_UP", "HOLD", "BLOCK"];
  const costs = b.decision.expected_costs || {};
  const rows = order.filter((a) => a in costs).map((a) =>
    `<tr class="${a === b.decision.action ? "chosen" : ""}"><td>${ACTION_TEXT[a]}</td><td class="num">${costs[a] === null ? "not offered" : usd(costs[a])}</td></tr>`).join("");
  const reasons = b.reasons.map((r) => `<li>${esc(r.label)}${typeof r.value === "string" ? `: ${esc(r.value)}` :
    (r.feature.startsWith("is_") ? "" : `: ${esc(Number(r.value).toLocaleString("en-US", { maximumFractionDigits: 2 }))}`)}</li>`).join("");
  const pct = Math.min(100, (b.p_fraud / 0.25) * 100);
  return `<details open><summary>Why this decision</summary><div class="why">
    <div><div class="row between"><span>Fraud probability</span><strong class="mono">${(b.p_fraud * 100).toFixed(1)}%</strong></div>
    <div class="meter" role="img" aria-label="fraud probability ${(b.p_fraud * 100).toFixed(1)} percent on a 0 to 25 percent scale"><span style="width:${pct}%"></span></div>
    <p class="hint">Scale 0–25%. The highest score on the DataCo test orders was about 21%. Hold is offered only when the model is unsure and a reviewer is free.</p></div>
    <div><strong>Model decision:</strong> ${ACTION_TEXT[b.decision.action]}. ${setText(b)}</div>
    <table><thead><tr><th>Action</th><th class="num">Expected cost</th></tr></thead><tbody>${rows}</tbody></table>
    ${reasons ? `<div><strong>What raised the risk</strong><ul>${reasons}</ul></div>` : ""}
    ${b.rule_text.length ? `<div><strong>Rules matched</strong><ul>${b.rule_text.map((t) => `<li>${esc(t)}</li>`).join("")}</ul></div>` : ""}
  </div></details>`;
}

function setText(b) {
  const set = b.conformal.set;
  if (b.conformal.ambiguous) return "At 90% confidence the model can't tell legitimate from fraud, so a reviewer looks if one is free.";
  if (set[0] === "fraud") return `Its score is in the range of past fraud orders, so we verify first. Most orders scored like this (about ${Math.round((1 - b.p_fraud) * 100)}%) are still legitimate.`;
  return "Its score is in the range of past legitimate orders.";
}

async function onVerify(ev) {
  ev.preventDefault();
  const code = $("#code").value.trim();
  try {
    showBooking(await api(`/dataco/bookings/${current.booking_id}/verify`, { method: "POST", body: JSON.stringify({ code }) }));
  } catch (e) {
    showFormError(e.message);
  }
  refreshLists();
}

// ------------------------------------------------------------------ lists
async function refreshLists() {
  let mine = [], queue = [];
  try {
    [mine, queue] = await Promise.all([api("/dataco/bookings"), api("/dataco/review-queue")]);
  } catch { return; }
  $("#count-mine").textContent = mine.length;
  $("#count-review").textContent = queue.length;
  $("#mine-empty").hidden = mine.length > 0;
  $("#mine-rows").innerHTML = mine.map((b) => `<tr class="clickable" data-id="${esc(b.booking_id)}">
    <td class="mono">${esc(b.booking_id)}</td><td class="mono">${esc(b.created_at.slice(5, 16))}</td><td>#${b.customer_id}</td>
    <td>${esc(PAY_TEXT[b.summary.payment_type][0])}</td><td>${esc(b.summary.order_city)}, ${esc(b.summary.order_country)}</td>
    <td class="num">${usd(b.summary.net_total)}</td><td><span class="pill ${b.status}">${STATUS_TEXT[b.status]}</span></td>
    <td class="mono">${esc(b.tracking_id || b.reference || "—")}</td></tr>`).join("");
  document.querySelectorAll("#mine-rows tr").forEach((tr) => tr.addEventListener("click", async () => {
    showBooking(await api(`/dataco/bookings/${tr.dataset.id}`)); selectTab("new");
  }));
  $("#queue-empty").hidden = queue.length > 0;
  $("#queue").innerHTML = queue.map((b) => `<article class="qcard" data-id="${esc(b.booking_id)}">
    <div class="status-line"><strong class="mono">${esc(b.booking_id)}</strong><span class="pill UNDER_REVIEW">Under review</span></div>
    <p class="muted">Customer #${b.customer_id} · ${esc(PAY_TEXT[b.summary.payment_type][0])} · ${usd(b.summary.net_total)} to ${esc(b.summary.order_city)}, ${esc(b.summary.order_country)}</p>
    <p>Fraud probability <strong class="mono">${(b.p_fraud * 100).toFixed(1)}%</strong></p>
    <ul>${b.reasons.map((r) => `<li>${esc(r.label)}</li>`).join("")}</ul>
    <label for="note-${esc(b.booking_id)}">Note (optional)</label><input id="note-${esc(b.booking_id)}" maxlength="300">
    <div class="qbtns"><button type="button" class="approve" data-approve="true">Approve</button>
    <button type="button" class="reject" data-approve="false">Reject</button></div></article>`).join("");
  document.querySelectorAll(".qcard button").forEach((btn) => btn.addEventListener("click", async () => {
    const card = btn.closest(".qcard"), id = card.dataset.id;
    btn.disabled = true;
    try {
      const b = await api(`/dataco/bookings/${id}/review`, { method: "POST",
        body: JSON.stringify({ approve: btn.dataset.approve === "true", note: $("input", card).value }) });
      if (current && current.booking_id === id) showBooking(b);
    } catch (e) { alertInline(card, e.message); }
    refreshLists();
  }));
}

function alertInline(card, msg) { const p = document.createElement("p"); p.className = "error"; p.textContent = msg; card.append(p); }

// ------------------------------------------------------------------ tabs
function wireTabs() {
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => selectTab(b.dataset.tab)));
}
function selectTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  ["new", "mine", "review"].forEach((t) => { $(`#view-${t}`).hidden = t !== name; });
  if (name !== "new") refreshLists();
}

init();
