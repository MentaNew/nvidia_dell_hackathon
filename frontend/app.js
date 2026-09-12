// RescueBase operations UI. Plain JS served by the backend: no build step, no CDN, works with the cable pulled.
const $ = (s) => document.querySelector(s);
const state = { events: [], selected: null, health: null, ingest: null, map: { available: false, bounds: null }, sources: {} };

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmtTime = (iso) => (iso ? iso.replace("T", " ").replace("+00:00", "Z").slice(0, 20) : "");
const clock = (iso) => (iso ? iso.slice(11, 19) : "");
const badge = (text, cls) => `<span class="badge ${cls}">${esc(text)}</span>`;
const setPill = (el, text, cls) => { el.textContent = text; el.className = "pill " + (cls || ""); };
const json = (body) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const KIND = { image: "VISUAL", video: "VISUAL", audio: "RADIO REPORT", text: "TEXT REPORT" };
const kindOf = (e) => (e.parent_source_id ? "VIDEO FRAME" : KIND[e.source_type] || e.source_type.toUpperCase());

// ---------------------------------------------------------------- four separate states in the header
const INF_TEXT = {
  PROVEN: (h) => ["OK · last run " + clock(h.inference_last_success), "ok"],
  ENDPOINT_UP_UNPROVEN: () => ["ENDPOINT UP · no successful run yet", "warn"],
  DEGRADED: (h) => ["ERROR after " + clock(h.inference_last_success), "bad"],
  STUB: () => ["STUB (no model, no inference)", "warn"],
  UNAVAILABLE: () => ["UNAVAILABLE", "bad"],
};
async function refreshHealth() {
  try {
    const h = await api("/api/health");
    state.health = h;
    $("#incident").textContent = h.incident.name;
    const [txt, cls] = (INF_TEXT[h.inference] || (() => [h.inference, "bad"]))(h);
    setPill($("#inf"), "LOCAL INFERENCE: " + txt, cls);
    $("#inf").title = Object.entries(h.providers).map(([k, p]) =>
      `${k}: endpoint ${p.endpoint} · ${p.model} · runs ${p.runs} · last success ${p.last_success || "none"}${p.last_error ? " · last error " + p.last_error : ""}`).join("\n");
    setPill($("#net"), `EXTERNAL INTERNET: ${h.network}`, h.network === "ONLINE" ? "ok" : "bad");
    setPill($("#store"), `LOCAL LOG: ${h.store.toUpperCase()} ${h.store_status}`, h.store_status === "READY" ? "ok" : "bad");
    const banner = $("#offline-banner");
    banner.hidden = h.network !== "OFFLINE";
    banner.textContent = `EXTERNAL INTERNET: OFFLINE   ·   LOCAL INFERENCE: ${txt}   ·   LOCAL LOG: ${h.store_status}`;
  } catch (e) {
    setPill($("#inf"), "BACKEND: UNREACHABLE", "bad");
  }
}

async function refreshIngest() {
  try {
    const s = await api("/api/ingest/status");
    state.ingest = s;
    const c = s.counts || {};
    if (!s.enabled) { setPill($("#ing"), "INGESTION: OFF", "bad"); $("#ingest-summary").textContent = "Inbox worker disabled (RESCUEBASE_INBOX_ENABLED=0)."; return; }
    const busy = (c.processing || 0) + (c.queued || 0) + (c.retrying || 0);
    setPill($("#ing"), `INGESTION: ${s.running ? "WATCHING" : "STOPPED"}${busy ? ` · ${c.processing || 0} processing · ${(c.queued || 0) + (c.retrying || 0)} queued` : ""}`, s.running ? (busy ? "warn" : "ok") : "bad");
    const t2e = s.time_to_entry_s?.median != null ? ` · drop→entry median ${s.time_to_entry_s.median}s (n=${s.time_to_entry_s.n})` : "";
    $("#ingest-summary").innerHTML = `Inbox <code>${esc(s.inbox)}</code> · scan ${esc(clock(s.last_scan) || "—")} · settle ${s.settle_s}s · workers ${s.concurrency} · completed ${c.completed || 0} · failed ${c.failed || 0}${t2e}${s.last_error ? ` · <span class="bad">${esc(s.last_error)}</span>` : ""}`;
    $("#jobs").innerHTML = (s.recent || []).map((j) => `
      <div class="job j-${j.status}">
        <span class="badge st ${j.status}">${esc(j.status)}</span> <strong>${esc(j.name)}</strong>
        <span class="muted small">${j.status === "completed" ? `${j.event_ids.length} event(s) · ${j.duration_s}s` : j.error ? esc(j.error) : ""}${j.attempts > 1 ? ` · attempt ${j.attempts}` : ""}${(j.duplicate_paths || []).length ? ` · ${j.duplicate_paths.length} duplicate file(s) ignored` : ""}</span>
      </div>`).join("") || `<p class="muted small">No inputs yet. Drop images, audio, text or clips into the inbox (subfolders exercise/, replay/, satellite/ set the label).</p>`;
    const prev = state.lastCompleted;
    state.lastCompleted = c.completed || 0;
    if (prev !== undefined && state.lastCompleted !== prev) await refreshEvents();
  } catch (e) {
    setPill($("#ing"), "INGESTION: ?", "bad");
  }
}

// ---------------------------------------------------------------- agent-written updates (drafts until a person confirms)
const linkIds = (text) => esc(text).replace(/ev_[0-9a-f]{10}/g, (id) => `<a href="#" class="evlink" data-id="${id}">${id}</a>`);
async function refreshUpdates() {
  try {
    const ups = await api("/api/updates?limit=3");
    if (!ups.length) return;
    const box = $("#updates");
    box.className = "";
    box.innerHTML = ups.map((u) => `<div class="update v-${u.verification_state}" data-id="${u.update_id}">
      <div class="row wrap">${badge(u.kind.replace(/_/g, " "), "kind")}${badge(u.verification_state.replace(/_/g, " "), "v " + u.verification_state)}</div>
      <div class="update-text">${linkIds(u.text)}</div>
      <div class="meta">${esc(u.agent)} · ${esc(u.model_name)} · ${esc(fmtTime(u.timestamp))} · cites ${u.cited_event_ids.length} event(s)${u.unknown_ids?.length ? ` · <span class="bad">${u.unknown_ids.length} unknown id(s)</span>` : ""}</div>
      <div class="row actions"><button data-uact="HUMAN_CONFIRMED">Confirm</button><button data-uact="HUMAN_REJECTED" class="ghost">Reject</button></div>
    </div>`).join("");
  } catch {}
}
$("#updates").addEventListener("click", async (ev) => {
  const a = ev.target.closest(".evlink");
  if (a) { ev.preventDefault(); return selectAny(a.dataset.id); }
  const act = ev.target.dataset.uact;
  if (!act) return;
  await api(`/api/updates/${ev.target.closest(".update").dataset.id}/verify`, json({ state: act, notes: "" }));
  await refreshUpdates();
});

// ---------------------------------------------------------------- events
async function refreshEvents() {
  const f = $("#filter").value;
  state.events = await api("/api/events" + (f ? `?state=${encodeURIComponent(f)}` : ""));
  renderEvents();
  renderTimeline();
  renderMap();
}

function timeLine(e) {
  const cap = e.captured_at ? `captured ${esc(fmtTime(e.captured_at))} (${esc(e.captured_at_source || "stated")})` : `<span class="warn-text">capture time unknown</span>`;
  return `${cap} · ingested ${esc(fmtTime(e.ingested_at))}`;
}
function whereLine(e) {
  const loc = e.location ? `${e.location.lat.toFixed(5)}, ${e.location.lon.toFixed(5)} (${esc(e.location.from)})` : "location unknown";
  return `${e.sector ? esc(e.sector) + " · " : ""}${loc}${e.region_hint ? " · in frame: " + esc(e.region_hint) : ""}`;
}

function renderEvents() {
  $("#count").textContent = `(${state.events.length})`;
  $("#events").innerHTML = state.events.map((e) => `
    <article class="card ${e.event_id === state.selected ? "selected" : ""} v-${e.verification_state}" data-id="${e.event_id}">
      <div class="row wrap">
        ${badge(kindOf(e), "kind")}
        ${badge(e.label, "lbl " + e.label)}
        ${badge(e.event_type.replace(/_/g, " "), "type")}
        ${badge(e.verification_state.replace(/_/g, " "), "v " + e.verification_state)}
        ${badge("model conf " + e.confidence, "conf")}
        ${/^stub/.test(e.model_name) ? badge("NO INFERENCE (STUB)", "sim") : ""}
      </div>
      <p class="obs">${esc(e.observation)}</p>
      <div class="meta">${timeLine(e)}</div>
      <div class="meta">${whereLine(e)}</div>
      <div class="meta">${esc(e.source_type)} ${esc(e.source_name)}${e.frame_offset_s != null ? ` @ ${e.frame_offset_s}s` : ""} · model: ${esc(e.model_name)} · ${esc(e.event_id)}${e.human_notes ? " · note: " + esc(e.human_notes) : ""}</div>
      <div class="row actions"><button data-act="HUMAN_CONFIRMED">Confirm</button><button data-act="HUMAN_REJECTED" class="ghost">Reject</button></div>
    </article>`).join("") || `<p class="muted">No events yet. Drop a file into the inbox or use manual ingest.</p>`;
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

async function getSource(id) {
  if (!state.sources[id]) { try { state.sources[id] = await api(`/api/sources/${id}`); } catch { return null; } }
  return state.sources[id];
}

async function select(id) {
  state.selected = id;
  renderEvents();
  renderTimeline();
  const e = state.events.find((x) => x.event_id === id);
  if (!e) return;
  const m = $("#media");
  m.classList.remove("muted");
  let replay = "";
  if (e.parent_source_id) {
    const clip = await getSource(e.parent_source_id);
    if (clip) replay = `<div class="replay"><div class="replay-label">RECORDED REPLAY · playback is real time · inference sampled 1 frame every ${clip.frame_interval_s}s · this frame at ${e.frame_offset_s}s</div><video controls preload="metadata" src="${clip.uri}#t=${e.frame_offset_s}"></video></div>`;
  }
  if (e.source_type === "image") m.innerHTML = `<img src="${e.source_uri}" alt="${esc(e.source_name)}">${replay}`;
  else if (e.source_type === "audio") m.innerHTML = `<audio controls src="${e.source_uri}"></audio>`;
  else m.innerHTML = `<a href="${e.source_uri}" target="_blank">${esc(e.source_name)}</a>`;
  $("#media-meta").innerHTML = `${badge(kindOf(e), "kind")} ${badge(e.label, "lbl " + e.label)} <strong>${esc(e.source_name)}</strong><br>
    <span class="muted">${timeLine(e)}<br>${whereLine(e)}<br>source ${esc(e.source_id)} · ${esc(e.model_name)} · ${e.related_event_ids.length} other event(s) from this source</span>`;
  const t = $("#transcript");
  t.hidden = true;
  if (e.source_type === "audio" || e.source_type === "text") {
    try { t.textContent = (await api(`/api/transcripts/${e.source_id}`)).text; t.hidden = false; } catch {}
  }
}

async function selectAny(id) {
  if (!state.events.some((e) => e.event_id === id)) { $("#filter").value = ""; await refreshEvents(); }
  await select(id);
  document.querySelector(`.card[data-id="${id}"]`)?.scrollIntoView({ block: "nearest" });
}

// ---------------------------------------------------------------- timeline (dashed dot = ordered by ingest time, capture time unknown)
function renderTimeline() {
  const track = $("#timeline-track");
  const evs = [...state.events].sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  if (!evs.length) { track.innerHTML = `<span class="muted">Timeline: no events</span>`; return; }
  const t0 = Date.parse(evs[0].timestamp) || 0;
  const t1 = Date.parse(evs[evs.length - 1].timestamp) || t0;
  const span = Math.max(t1 - t0, 1);
  track.innerHTML = evs.map((e, i) => {
    const x = ((Date.parse(e.timestamp) || t0) - t0) / span * 96 + 2;
    return `<button class="dot v-${e.verification_state} basis-${e.time_basis} ${e.event_id === state.selected ? "selected" : ""}" style="left:${x}%;top:${21 + (i % 3) * 8}px" title="${esc(fmtTime(e.timestamp))} (${e.time_basis}) ${esc(kindOf(e))} ${esc(e.event_type)}: ${esc(e.observation)}" data-id="${e.event_id}"></button>`;
  }).join("") + `<span class="tl-label left">${esc(fmtTime(evs[0].timestamp))}</span><span class="tl-label right">${esc(fmtTime(evs[evs.length - 1].timestamp))}</span>`;
}
$("#timeline-track").addEventListener("click", (ev) => { const d = ev.target.closest(".dot"); if (d) select(d.dataset.id); });

// ---------------------------------------------------------------- map / sectors
async function loadMap() {
  try { state.map = await api("/api/map"); } catch {}
  if (state.map.available) $("#map").innerHTML = `<img id="map-img" src="${state.map.url}" alt="site map"><div id="pins"></div>`;
}
function renderMap() {
  const bySector = {};
  for (const e of state.events) (bySector[e.sector || "Unassigned"] ||= []).push(e);
  $("#sectors").innerHTML = Object.entries(bySector).sort().map(([s, evs]) =>
    `<div class="sector"><strong>${esc(s)}</strong> <span class="muted small">${evs.length} event(s), ${evs.filter((e) => e.verification_state === "AI_CANDIDATE").length} unreviewed, ${evs.filter((e) => e.location).length} located</span></div>`).join("");
  const pins = $("#pins");
  if (!pins || !state.map.bounds) return;
  const [x0, y0, x1, y1] = state.map.bounds;
  pins.innerHTML = state.events.filter((e) => e.location).map((e) => {
    const px = (e.location.lon - x0) / (x1 - x0) * 100, py = (1 - (e.location.lat - y0) / (y1 - y0)) * 100;
    return `<button class="pin v-${e.verification_state}" style="left:${px}%;top:${py}%" title="${esc(e.observation)}" data-id="${e.event_id}"></button>`;
  }).join("");
}
$("#map").addEventListener("click", (ev) => { const p = ev.target.closest(".pin"); if (p) select(p.dataset.id); });

// ---------------------------------------------------------------- manual ingest
$("#ingest").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target, st = $("#ingest-status"), btn = form.querySelector("button");
  const fd = new FormData(form);
  st.textContent = "Analyzing locally…";
  btn.disabled = true;
  try {
    const r = await api("/api/ingest", { method: "POST", body: fd });
    st.textContent = `${r.events.length} event(s) from ${r.source.name}${r.errors?.length ? ` · ${r.errors.length} frame error(s)` : ""}`;
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
    const warn = r.uncited_claims?.length ? `<div class="bad small">Answer cites ids not in the retrieved evidence: ${r.uncited_claims.join(", ")}</div>` : "";
    box.innerHTML = `<div class="answer-text">${linked}</div>${warn}
      <div class="meta">retrieval: ${esc(r.retrieval)} · synthesis: ${esc(r.model_name)} · ${r.events.length} evidence event(s) · ${r.cited.length} cited</div>
      <div class="evidence">${r.events.slice(0, 8).map((e) => `<a href="#" class="evlink chip v-${e.verification_state}" data-id="${e.event_id}">${esc(e.event_id)} · ${esc(kindOf(e))} · ${esc(e.verification_state)}</a>`).join("")}</div>`;
  } catch (e) {
    box.innerHTML = `<span class="bad">Query failed: ${esc(e.message)}</span>`;
  }
});
$("#answer").addEventListener("click", (ev) => { const a = ev.target.closest(".evlink"); if (!a) return; ev.preventDefault(); selectAny(a.dataset.id); });

// ---------------------------------------------------------------- bounded actions
$("#sitrep-btn").addEventListener("click", async () => {
  const p = $("#sitrep");
  p.hidden = false;
  p.textContent = "Generating from the incident log…";
  try {
    const r = await api("/api/sitrep", { method: "POST" });
    p.textContent = `${r.sitrep}\n\n— ${r.bytes} bytes to transmit vs ${(r.source_media_bytes / 1048576).toFixed(1)} MB of source media · ${r.event_count} events · ${r.model_name}`;
  } catch (e) {
    p.textContent = "SITREP failed: " + e.message;
  }
});
$("#reset-btn").addEventListener("click", async () => {
  if (!confirm("Clear the incident log (events, sources, jobs) and re-ingest data/demo/ through the live pipeline?")) return;
  try {
    const r = await api("/api/demo/reset", { method: "POST" });
    alert(r.ingested.map((x) => `${x.file}: ${x.error || x.events + " event(s)"}`).join("\n") || "data/demo/ is empty; inbox files will be re-processed on their next drop");
    state.sources = {};
    await refreshEvents();
  } catch (e) {
    alert("Reset failed: " + e.message);
  }
});
$("#filter").addEventListener("change", refreshEvents);

loadMap().then(refreshEvents).catch(console.error);
refreshHealth();
refreshIngest();
refreshUpdates();
setInterval(refreshHealth, 4000);
setInterval(refreshIngest, 3000);
setInterval(refreshUpdates, 10000);
setInterval(() => refreshEvents().catch(() => {}), 20000);
