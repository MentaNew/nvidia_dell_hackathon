// RescueBase command UI. Plain JS served by the backend: no build step, no CDN, works with the cable pulled.
const $ = (s) => document.querySelector(s);
const state = { events: [], selected: null, health: null, map: { available: false, bounds: null } };

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmtTime = (iso) => (iso ? iso.replace("T", " ").slice(0, 19) : "");
const badge = (text, cls) => `<span class="badge ${cls}">${esc(text)}</span>`;
const setPill = (el, text, cls) => { el.textContent = text; el.className = "pill " + (cls || ""); };
const json = (body) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

// ---------------------------------------------------------------- health / status header
async function refreshHealth() {
  try {
    const h = await api("/api/health");
    state.health = h;
    $("#incident").textContent = h.incident.name;
    const aiCls = { OPERATIONAL: "ok", STUB: "warn", DEGRADED: "warn" }[h.local_ai] || "bad";
    setPill($("#ai"), `LOCAL AI: ${h.local_ai}`, aiCls);
    $("#ai").title = Object.entries(h.providers).map(([k, v]) => `${k}: ${v} (${h.models[k]})`).join("\n");
    setPill($("#net"), `EXTERNAL NETWORK: ${h.network}`, h.network === "ONLINE" ? "ok" : "bad");
    setPill($("#store"), `MEMORY: ${h.store.toUpperCase()} ${h.store_status}`, h.store_status === "READY" ? "" : "bad");
    const banner = $("#offline-banner");
    banner.hidden = h.network !== "OFFLINE";
    banner.textContent = `EXTERNAL NETWORK: OFFLINE  ·  LOCAL RESCUEBASE: ${h.local_ai === "UNAVAILABLE" ? "AI UNAVAILABLE" : "OPERATIONAL" + (h.local_ai === "STUB" ? " (STUB, NO INFERENCE)" : "")}`;
  } catch (e) {
    setPill($("#ai"), "BACKEND: UNREACHABLE", "bad");
  }
}

// ---------------------------------------------------------------- events
async function refreshEvents() {
  const f = $("#filter").value;
  state.events = await api("/api/events" + (f ? `?state=${encodeURIComponent(f)}` : ""));
  renderEvents();
  renderTimeline();
  renderMap();
}

function renderEvents() {
  $("#count").textContent = `(${state.events.length})`;
  $("#events").innerHTML = state.events.map((e) => `
    <article class="card ${e.event_id === state.selected ? "selected" : ""} v-${e.verification_state}" data-id="${e.event_id}">
      <div class="row wrap">
        ${badge(e.event_type.replace(/_/g, " "), "type")}
        ${badge(e.verification_state.replace(/_/g, " "), "v " + e.verification_state)}
        ${badge("conf " + e.confidence, "conf-" + e.confidence)}
        ${e.simulated ? badge("SIMULATED", "sim") : ""}
        ${/^stub/.test(e.model_name) ? badge("NO INFERENCE (STUB)", "sim") : ""}
      </div>
      <p class="obs">${esc(e.observation)}</p>
      <div class="meta">${esc(fmtTime(e.timestamp))} · ${esc(e.source_type)} ${esc(e.source_name)}${e.sector ? " · " + esc(e.sector) : ""}${e.region_hint ? " · " + esc(e.region_hint) : ""}${e.location ? ` · ${e.location.lat.toFixed(4)}, ${e.location.lon.toFixed(4)}` : ""}</div>
      <div class="meta">model: ${esc(e.model_name)} · ${esc(e.event_id)}${e.human_notes ? " · note: " + esc(e.human_notes) : ""}</div>
      <div class="row actions"><button data-act="HUMAN_CONFIRMED">Confirm</button><button data-act="HUMAN_REJECTED" class="ghost">Reject</button></div>
    </article>`).join("") || `<p class="muted">No events yet. Ingest a local image, audio clip, or text report.</p>`;
}

$("#events").addEventListener("click", async (ev) => {
  const card = ev.target.closest(".card");
  if (!card) return;
  const act = ev.target.dataset.act;
  if (!act) return select(card.dataset.id);
  const notes = act === "HUMAN_REJECTED" ? prompt("Reason (optional):") || "" : "";
  await api(`/api/events/${card.dataset.id}/verify`, json({ state: act, notes }));
  await refreshEvents();
});

async function select(id) {
  state.selected = id;
  renderEvents();
  renderTimeline();
  const e = state.events.find((x) => x.event_id === id);
  if (!e) return;
  const m = $("#media");
  m.classList.remove("muted");
  if (e.source_type === "image") m.innerHTML = `<img src="${e.source_uri}" alt="${esc(e.source_name)}">`;
  else if (e.source_type === "audio") m.innerHTML = `<audio controls src="${e.source_uri}"></audio>`;
  else m.innerHTML = `<a href="${e.source_uri}" target="_blank">${esc(e.source_name)}</a>`;
  $("#media-meta").innerHTML = `<strong>${esc(e.source_name)}</strong> · ${esc(e.source_type)} · ${esc(fmtTime(e.timestamp))}${e.simulated ? " · " + badge("SIMULATED", "sim") : ""}<br><span class="muted">source ${esc(e.source_id)} · ${esc(e.model_name)} · ${e.related_event_ids.length} related event(s) from this source</span>`;
  const t = $("#transcript");
  t.hidden = true;
  if (e.source_type !== "image") {
    try { t.textContent = (await api(`/api/transcripts/${e.source_id}`)).text; t.hidden = false; } catch {}
  }
}

async function selectAny(id) {
  if (!state.events.some((e) => e.event_id === id)) { $("#filter").value = ""; await refreshEvents(); }
  await select(id);
  document.querySelector(`.card[data-id="${id}"]`)?.scrollIntoView({ block: "nearest" });
}

// ---------------------------------------------------------------- timeline
function renderTimeline() {
  const track = $("#timeline-track");
  const evs = [...state.events].sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  if (!evs.length) { track.innerHTML = `<span class="muted">Timeline: no events</span>`; return; }
  const t0 = Date.parse(evs[0].timestamp) || 0;
  const t1 = Date.parse(evs[evs.length - 1].timestamp) || t0;
  const span = Math.max(t1 - t0, 1);
  track.innerHTML = evs.map((e, i) => {
    const x = ((Date.parse(e.timestamp) || t0) - t0) / span * 96 + 2;
    return `<button class="dot v-${e.verification_state} ${e.event_id === state.selected ? "selected" : ""}" style="left:${x}%;top:${21 + (i % 3) * 8}px" title="${esc(fmtTime(e.timestamp))} ${esc(e.event_type)}: ${esc(e.observation)}" data-id="${e.event_id}"></button>`;
  }).join("") + `<span class="tl-label left">${esc(fmtTime(evs[0].timestamp))}</span><span class="tl-label right">${esc(fmtTime(evs[evs.length - 1].timestamp))}</span>`;
}
$("#timeline-track").addEventListener("click", (ev) => { const d = ev.target.closest(".dot"); if (d) select(d.dataset.id); });

// ---------------------------------------------------------------- map / sectors
async function loadMap() {
  try { state.map = await api("/api/map"); } catch {}
  if (state.map.available) $("#map").innerHTML = `<img id="map-img" src="${state.map.url}" alt="incident map"><div id="pins"></div>`;
}
function renderMap() {
  const bySector = {};
  for (const e of state.events) (bySector[e.sector || "Unassigned"] ||= []).push(e);
  $("#sectors").innerHTML = Object.entries(bySector).sort().map(([s, evs]) =>
    `<div class="sector"><strong>${esc(s)}</strong> <span class="muted">${evs.length} event(s), ${evs.filter((e) => e.verification_state === "AI_CANDIDATE").length} unreviewed</span></div>`).join("");
  const pins = $("#pins");
  if (!pins || !state.map.bounds) return;
  const [x0, y0, x1, y1] = state.map.bounds;
  pins.innerHTML = state.events.filter((e) => e.location).map((e) => {
    const px = (e.location.lon - x0) / (x1 - x0) * 100, py = (1 - (e.location.lat - y0) / (y1 - y0)) * 100;
    return `<button class="pin v-${e.verification_state}" style="left:${px}%;top:${py}%" title="${esc(e.observation)}" data-id="${e.event_id}"></button>`;
  }).join("");
}
$("#map").addEventListener("click", (ev) => { const p = ev.target.closest(".pin"); if (p) select(p.dataset.id); });

// ---------------------------------------------------------------- ingest
$("#ingest").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target, st = $("#ingest-status"), btn = form.querySelector("button");
  const fd = new FormData(form);
  if (!fd.get("simulated")) fd.set("simulated", "false");
  st.textContent = "Analyzing locally…";
  btn.disabled = true;
  try {
    const r = await api("/api/ingest", { method: "POST", body: fd });
    st.textContent = `${r.events.length} candidate event(s) from ${r.source.name}`;
    await refreshEvents();
    if (r.events[0]) await selectAny(r.events[0].event_id);
  } catch (e) {
    st.textContent = "Failed: " + e.message;
  } finally {
    btn.disabled = false;
  }
});

// ---------------------------------------------------------------- query
$("#query").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const q = ev.target.q.value.trim();
  if (!q) return;
  const box = $("#answer");
  box.hidden = false;
  box.innerHTML = `<span class="muted">Retrieving evidence and synthesizing locally…</span>`;
  try {
    const r = await api("/api/query", json({ question: q }));
    const linked = esc(r.answer).replace(/ev_[0-9a-f]{10}/g, (id) => `<a href="#" class="evlink" data-id="${id}">${id}</a>`);
    box.innerHTML = `<div class="answer-text">${linked}</div>
      <div class="meta">retrieval: ${esc(r.retrieval)} · synthesis: ${esc(r.model_name)} · ${r.events.length} evidence event(s)</div>
      <div class="evidence">${r.events.slice(0, 8).map((e) => `<a href="#" class="evlink chip v-${e.verification_state}" data-id="${e.event_id}">${esc(e.event_id)} · ${esc(e.event_type)} · ${esc(e.verification_state)}</a>`).join("")}</div>`;
  } catch (e) {
    box.innerHTML = `<span class="bad">Query failed: ${esc(e.message)}</span>`;
  }
});
$("#answer").addEventListener("click", (ev) => { const a = ev.target.closest(".evlink"); if (!a) return; ev.preventDefault(); selectAny(a.dataset.id); });

// ---------------------------------------------------------------- bounded actions
$("#sitrep-btn").addEventListener("click", async () => {
  const p = $("#sitrep");
  p.hidden = false;
  p.textContent = "Generating from incident memory…";
  try {
    const r = await api("/api/sitrep", { method: "POST" });
    p.textContent = `${r.sitrep}\n\n— ${r.bytes} bytes to transmit vs ${(r.source_media_bytes / 1048576).toFixed(1)} MB of source media · ${r.event_count} events · ${r.model_name}`;
  } catch (e) {
    p.textContent = "SITREP failed: " + e.message;
  }
});
$("#reset-btn").addEventListener("click", async () => {
  if (!confirm("Clear incident memory and re-ingest data/demo/ through the live pipeline?")) return;
  try {
    const r = await api("/api/demo/reset", { method: "POST" });
    alert(r.ingested.map((x) => `${x.file}: ${x.error || x.events + " event(s)"}`).join("\n") || "data/demo/ is empty");
    await refreshEvents();
  } catch (e) {
    alert("Reset failed: " + e.message);
  }
});
$("#filter").addEventListener("change", refreshEvents);

loadMap().then(refreshEvents).catch(console.error);
refreshHealth();
setInterval(refreshHealth, 4000);
setInterval(() => refreshEvents().catch(() => {}), 15000);
