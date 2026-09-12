// Live GB10 page: 1 Hz scrolling graphs from server-side history (survives navigation), tiles every 2 s.
// Hardware readings only when the server runs on the GB10; anything unsupported reads "unavailable", never zero.
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const UNAVAILABLE = "Unavailable — awaiting GB10 telemetry";
const SPAN = 60;
const na = (why) => `<span class="na">${esc(why || UNAVAILABLE)}</span>`;
const val = (x, unit = "", why) => (x == null ? na(why) : `${typeof x === "number" ? (Number.isInteger(x) ? x : x.toFixed(1)) : esc(x)}${unit}`);
const kv = (rows) => `<div class="kv">${rows.map(([k, v]) => `<span class="k">${esc(k)}</span><span>${v}</span>`).join("")}</div>`;
const bar = (pct) => (pct != null ? `<div class="bar"><i style="width:${Math.min(100, pct).toFixed(0)}%"></i></div>` : "");
const setPill = (el, text, cls) => { el.textContent = text; el.className = "pill " + (cls || ""); };
const clock = (iso) => (iso ? iso.slice(11, 19) : "");
const COLOR = { vision: "#0b5fff", speech: "#6b21a8", transcription: "#6b21a8", reasoning: "#5f6670", report: "#5f6670", embedding: "#8a94a0", queue: "#c77800" };
const INF_TEXT = {
  PROVEN: (t) => ["OK · last run " + clock(t.inference.vision.last_success), "ok"],
  ENDPOINT_UP_UNPROVEN: () => ["ENDPOINT UP · no successful run yet", "warn"],
  DEGRADED: (t) => ["ERROR after " + clock(t.inference.vision.last_success), "bad"],
  STUB: () => ["STUB (no model, no inference)", "warn"],
  UNAVAILABLE: () => ["UNAVAILABLE", "bad"],
};

// ---------------------------------------------------------------- canvas graphs (no libraries; local only)
function drawGraph(canvas, g) {
  const dpr = window.devicePixelRatio || 1, W = canvas.clientWidth || 600, H = canvas.clientHeight || 170;
  if (canvas.width !== Math.round(W * dpr) || canvas.height !== Math.round(H * dpr)) { canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr); }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const L = 46, R = 12, T = 10, B = 24, w = W - L - R, h = H - T - B;
  const x = (t) => L + (1 - (g.now - t) / SPAN) * w;
  const y = (v) => T + h - (Math.min(g.yMax, Math.max(g.yMin, v)) - g.yMin) / (g.yMax - g.yMin) * h;
  ctx.clearRect(0, 0, W, H);
  ctx.font = "11px system-ui, sans-serif";
  ctx.lineWidth = 1;
  for (const tv of g.yTicks) {
    ctx.strokeStyle = "#e3e6ea"; ctx.beginPath(); ctx.moveTo(L, y(tv)); ctx.lineTo(L + w, y(tv)); ctx.stroke();
    ctx.fillStyle = "#5f6670"; ctx.textAlign = "right"; ctx.textBaseline = "middle"; ctx.fillText(g.yFmt(tv), L - 6, y(tv));
  }
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  for (let s = 0; s <= SPAN; s += 15) {
    const tx = x(g.now - s);
    ctx.strokeStyle = "#eef0f2"; ctx.beginPath(); ctx.moveTo(tx, T); ctx.lineTo(tx, T + h); ctx.stroke();
    ctx.fillStyle = "#5f6670"; ctx.fillText(s === 0 ? "now" : `-${s}s`, tx, T + h + 5);
  }
  ctx.strokeStyle = "#c9ced4"; ctx.strokeRect(L, T, w, h);
  for (const sp of g.spans || []) {
    const x0 = Math.max(L, x(sp.t0)), x1 = Math.min(L + w, x(sp.t1));
    if (x1 <= L) continue;
    ctx.globalAlpha = 0.18; ctx.fillStyle = sp.color; ctx.fillRect(x0, T, Math.max(2, x1 - x0), h); ctx.globalAlpha = 1;
  }
  for (const s of g.series || []) {
    ctx.strokeStyle = s.color; ctx.lineWidth = 2; ctx.beginPath();
    let pen = false;
    for (const [t, v] of s.pts) {
      if (v == null || t < g.now - SPAN) { pen = false; continue; }  // gaps stay gaps: no zero-filling
      pen ? ctx.lineTo(x(t), y(v)) : ctx.moveTo(x(t), y(v));
      pen = true;
    }
    ctx.stroke(); ctx.lineWidth = 1;
  }
  for (const d of g.dots || []) {
    if (d.t < g.now - SPAN) continue;
    const px = x(d.t), py = y(d.v);
    ctx.fillStyle = d.color; ctx.beginPath();
    if (d.shape === "diamond") { ctx.moveTo(px, py - 6); ctx.lineTo(px + 6, py); ctx.lineTo(px, py + 6); ctx.lineTo(px - 6, py); ctx.closePath(); }
    else ctx.arc(px, py, 4, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.textAlign = "left"; ctx.textBaseline = "top";
  for (const m of g.markers || []) {
    if (m.t < g.now - SPAN) continue;
    const px = x(m.t);
    ctx.strokeStyle = m.color; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(px, T); ctx.lineTo(px, T + h); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = m.color; ctx.beginPath();
    if (m.end) { ctx.moveTo(px - 5, T + 2); ctx.lineTo(px + 5, T + 2); ctx.lineTo(px, T + 11); } else { ctx.moveTo(px - 5, T + 11); ctx.lineTo(px + 5, T + 11); ctx.lineTo(px, T + 2); }
    ctx.closePath(); ctx.fill();
    ctx.fillText(m.label, px + 7, T + 2);
  }
  let lx = L + 6;
  for (const [label, color] of g.legend || []) {
    ctx.fillStyle = color; ctx.fillRect(lx, T + h - 15, 10, 10);
    ctx.fillStyle = "#333"; ctx.fillText(label, lx + 14, T + h - 16);
    lx += 14 + ctx.measureText(label).width + 16;
  }
  if (g.unavailable) {
    ctx.fillStyle = "#a15c00"; ctx.font = "bold 14px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(g.unavailable, L + w / 2, T + h / 2 - 8);
  }
  if (g.note) {
    ctx.fillStyle = "#a15c00"; ctx.font = "bold 11px system-ui, sans-serif"; ctx.textAlign = "right"; ctx.textBaseline = "top";
    ctx.fillText(g.note, L + w - 6, T + 4);
  }
}

const KIND_LETTER = { vision: "V", transcription: "T", report: "R" };
function jobMarkers(hist) {
  return (hist.jobs || []).map((j) => ({ t: j.t, color: COLOR[j.kind] || "#333", end: j.phase === "end",
    label: `${KIND_LETTER[j.kind] || "?"}${j.phase === "end" ? (j.status === "completed" ? "✓" : "✗") : ""}` }));
}
function callSpans(hist) {
  const out = [];
  for (const [kind, calls] of Object.entries(hist.calls || {})) for (const [end, s] of calls) out.push({ t0: end - s, t1: end, color: COLOR[kind] || "#333" });
  return out;
}

function drawAll(hist) {
  const now = hist.now, S = hist.samples || [];
  const pct = { yMin: 0, yMax: 100, yTicks: [0, 25, 50, 75, 100], yFmt: (v) => v + "%" };
  const haveUtil = S.some((s) => s.gpu_util != null), haveMem = S.some((s) => s.mem_pct != null);
  const why = hist.gb10 ? "nvidia-smi reports N/A for this reading on this device" : UNAVAILABLE;
  drawGraph($("#g-util"), { ...pct, now, series: [{ pts: S.map((s) => [s.t, s.gpu_util]), color: "#137333" }], markers: jobMarkers(hist), spans: callSpans(hist),
    legend: [["GPU util %", "#137333"], ["vision call", COLOR.vision], ["speech call", COLOR.speech], ["reasoning call", COLOR.reasoning]], unavailable: haveUtil ? null : why });
  const last = [...S].reverse().find((s) => s.mem_pct != null);
  $("#mem-sub").textContent = last ? `fixed 0–100 % · ${last.mem_used_mib} / ${last.mem_total_mib} MiB · source: ${last.mem_source}` : "fixed 0–100 % of the single GB10 pool (one figure, not RAM + VRAM)";
  drawGraph($("#g-mem"), { ...pct, now, series: [{ pts: S.map((s) => [s.t, s.mem_pct]), color: "#0b5fff" }], legend: [["unified memory used %", "#0b5fff"]], unavailable: haveMem ? null : why });
  const dots = [];
  for (const [kind, calls] of Object.entries(hist.calls || {})) for (const [end, s] of calls) dots.push({ t: end, v: s, color: COLOR[kind] || "#333" });
  for (const j of hist.jobs || []) if (j.phase === "end" && j.drop_to_entry_s != null) dots.push({ t: j.t, v: j.drop_to_entry_s, color: COLOR.queue, shape: "diamond" });
  const top = Math.max(1, ...dots.map((d) => d.v)) * 1.15;
  const step = top <= 2 ? 0.5 : top <= 10 ? 2 : top <= 30 ? 5 : top <= 120 ? 20 : 60;
  const yMax = Math.ceil(top / step) * step;
  const ticks = []; for (let v = 0; v <= yMax + 1e-9; v += step) ticks.push(+v.toFixed(2));
  const latWhy = hist.provider_mode === "stub" ? "STUB providers on this host: no inference calls (no latency to plot)" : "no model calls or completed jobs in the last 60 s";
  const stubNote = hist.provider_mode === "stub" ? "STUB providers: ◆ are pipeline timings without any inference" : null;
  drawGraph($("#g-lat"), { now, yMin: 0, yMax, yTicks: ticks, yFmt: (v) => v + "s", dots, markers: jobMarkers(hist),
    legend: [["● vision call", COLOR.vision], ["● speech call", COLOR.speech], ["● reasoning call", COLOR.reasoning], ["◆ queue→event", COLOR.queue]],
    unavailable: dots.length ? null : latWhy, note: dots.length ? stubNote : null });
}

// ---------------------------------------------------------------- tiles
function renderTiles(t) {
  const h = t.host, det = h.detection, why = t.unavailable_reason;
  const src = $("#src");
  src.className = h.gb10_detected ? "ok" : "";
  src.innerHTML = h.gb10_detected
    ? `Source: ${esc(h.hostname)} — NVIDIA GB10 detected via ${esc(det.method)}. Hardware readings are live from this machine. <span class="small">Unverified on a GB10 until the acceptance run.</span>`
    : `Source: ${esc(h.hostname)} — GB10 NOT detected (nvidia-smi ${det.nvidia_smi_present ? "present, name " + esc(det.nvidia_smi_name || "?") : "absent"}). Hardware readings: ${UNAVAILABLE}. ` +
      `Application counters below describe this host only${h.provider_mode === "stub" ? " (STUB providers: no inference)" : ""}. <span class="small">${esc(det.override_hint)}</span>`;
  const [it, ic] = (INF_TEXT[t.inference_state] || (() => [t.inference_state, "bad"]))(t);
  setPill($("#inf"), "LOCAL INFERENCE: " + it, ic);
  setPill($("#net"), `EXTERNAL INTERNET: ${t.network}`, t.network === "ONLINE" ? "ok" : "bad");
  setPill($("#store"), `LOCAL LOG: ${t.store.kind.toUpperCase()} ${t.store.status}`, t.store.status === "READY" ? "ok" : "bad");
  const g = t.ingestion, c = g.counts || {};
  setPill($("#ing"), `INGESTION: ${g.enabled ? (g.running ? "WATCHING" : "STOPPED") : "OFF"} · q ${g.queue_size} · proc ${c.processing || 0}`, g.running ? "ok" : "bad");

  const gpu = t.gpu;
  $("#t-gpu").innerHTML = `<h2>GPU</h2>` + (gpu
    ? `<div class="big">${esc(gpu.name)}</div>` + kv([["utilization", val(gpu["utilization.gpu"], " %", why)], ["temperature", val(gpu["temperature.gpu"], " °C", "nvidia-smi N/A")],
        ["power draw", val(gpu["power.draw"], " W", "nvidia-smi N/A")], ["driver", val(gpu.driver_version)]])
    : `<div class="big">${na(why)}</div>` + kv([["utilization", na(why)], ["temperature", na(why)], ["power draw", na(why)]]));
  const m = t.memory;
  $("#t-mem").innerHTML = `<h2>Unified memory</h2>` + (m
    ? `<div class="big">${m.pct} %</div>${bar(m.pct)}` + kv([["used / total", `${val(m.used_mib, " MiB")} / ${val(m.total_mib, " MiB")}`], ["source", esc(m.source)], ["note", "one pool on the GB10: this is not RAM + VRAM"]])
    : `<div class="big">${na(why)}</div>` + kv([["used / total", na(why)], ["source", na(why)]]));
  const s = t.system;
  $("#t-sys").innerHTML = `<h2>System</h2>` + kv([["load (1 min)", s ? val(s.load_1m) : na(why)], ["CPUs", s ? val(s.cpus) : na(why)], ["history kept", `${h.history_samples} samples (server-side, 1 Hz)`]]);

  $("#t-inf").innerHTML = `<h2>Inference (per provider)</h2>` + Object.entries(t.inference).map(([k, p]) => {
    const L = p.latency;
    return `<div class="prov"><strong>${esc(k)}</strong> <span class="muted small">${esc(p.model)}</span>` + kv([
      ["endpoint", esc(p.endpoint)], ["runs", p.runs],
      ["model-call latency p50 / p95", L ? `${L.p50_s}s / ${L.p95_s}s (n=${L.count}, last ${L.last_s}s, max ${L.max_s}s)` : na(p.note || "no successful runs yet")],
      ["last success", p.last_success ? esc(p.last_success) : na(p.note || "none yet")],
      ...(p.last_error ? [["last error", `<span class="bad">${esc(p.last_error)}</span>`]] : [])]) + `</div>`;
  }).join("");

  const pr = g.processing_s_last_10min, t2e = g.time_to_entry_s;
  $("#t-ing").innerHTML = `<h2>Ingestion</h2><div class="big">${g.completed_last_10min} <span class="muted small">completed in the last 10 min (${g.per_minute_last_10min}/min)</span></div>` + kv([
    ["queue / processing", `${g.queue_size} / ${c.processing || 0}`], ["completed / failed", `${c.completed || 0} / ${c.failed || 0}`],
    ["job processing time (10 min)", pr ? `p50 ${pr.p50}s · max ${pr.max}s` : na("no completed jobs in the last 10 min")],
    ["queue→event (drop → entry)", t2e && t2e.n ? `median ${t2e.median}s · max ${t2e.max}s (n=${t2e.n})` : na("no completed jobs")]]) +
    `<div class="small" style="margin-top:8px">${(g.recent || []).map((j) => `<div class="prov">${esc(j.status)} · ${esc(j.name)} · ${j.duration_s ?? "—"}s · ${j.events} event(s)${j.error ? ` · <span class="bad">${esc(j.error)}</span>` : ""}</div>`).join("") || na("no jobs yet")}</div>`;

  $("#t-log").innerHTML = `<h2>Incident log</h2><div class="big">${t.log.events} <span class="muted small">events · ${t.log.updates} agent update(s)</span></div>` +
    kv([...Object.entries(t.log.by_verification_state).map(([k, v]) => [k, v]), ...Object.entries(t.log.by_source_type).map(([k, v]) => ["source: " + k, v])]);

  $("#t-host").innerHTML = `<h2>Host and GB10 detection</h2>` + kv([["hostname", esc(h.hostname)], ["platform", esc(h.platform)],
    ["GB10 detected", h.gb10_detected ? `yes — ${esc(det.method)}` : "no"], ["nvidia-smi", det.nvidia_smi_present ? `present (${esc(det.nvidia_smi_name || "no name")})` : "absent"],
    ["override", det.override_active ? "RESCUEBASE_ASSUME_GB10=1 active (unlocks real readings only)" : "off"], ["providers", esc(h.provider_mode)],
    ["server started", esc(h.server_started_at)], ["uptime", `${Math.floor(h.uptime_s / 60)} min`], ["snapshot", esc(t.served_at)]]);
  $("#notes").innerHTML = (t.notes || []).map((n) => `⚠ ${esc(n)}`).join("<br>");
}

let tickN = 0;
async function tick() {
  tickN++;
  try {
    const r = await fetch(`/api/telemetry/history?seconds=${SPAN}`);
    if (!r.ok) throw new Error(r.statusText);
    drawAll(await r.json());
  } catch (e) {
    $("#src").className = "";
    $("#src").textContent = "Backend unreachable: " + e.message;
  }
  if (tickN % 2 === 1) {
    try { const r = await fetch("/api/telemetry"); if (r.ok) renderTiles(await r.json()); } catch {}
  }
}
tick();
setInterval(tick, 1000);
window.addEventListener("resize", () => tick());
