// Live GB10 page: hardware readings only when the server runs on the GB10; otherwise the unavailable notice.
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const UNAVAILABLE = "Unavailable — awaiting GB10 telemetry";
const na = (why) => `<span class="na">${esc(why || UNAVAILABLE)}</span>`;
const val = (x, unit = "", why) => (x == null ? na(why) : `${typeof x === "number" ? (Number.isInteger(x) ? x : x.toFixed(1)) : esc(x)}${unit}`);
const kv = (rows) => `<div class="kv">${rows.map(([k, v]) => `<span class="k">${esc(k)}</span><span>${v}</span>`).join("")}</div>`;
const bar = (used, total) => (used != null && total ? `<div class="bar"><i style="width:${Math.min(100, used / total * 100).toFixed(0)}%"></i></div>` : "");
const setPill = (el, text, cls) => { el.textContent = text; el.className = "pill " + (cls || ""); };
const clock = (iso) => (iso ? iso.slice(11, 19) : "");
const INF_TEXT = {
  PROVEN: (t) => ["OK · last run " + clock(t.inference.vision.last_success), "ok"],
  ENDPOINT_UP_UNPROVEN: () => ["ENDPOINT UP · no successful run yet", "warn"],
  DEGRADED: (t) => ["ERROR after " + clock(t.inference.vision.last_success), "bad"],
  STUB: () => ["STUB (no model, no inference)", "warn"],
  UNAVAILABLE: () => ["UNAVAILABLE", "bad"],
};

function render(t) {
  const h = t.host, why = t.unavailable_reason;
  const src = $("#src");
  src.className = h.gb10_detected ? "ok" : "";
  src.textContent = h.gb10_detected
    ? `Source: ${h.hostname} — NVIDIA GB10 detected. Hardware readings are live from this machine.`
    : `Source: ${h.hostname} — GB10 NOT detected. Hardware readings: ${UNAVAILABLE}. Application counters below describe this host only` +
      (h.provider_mode === "stub" ? " (STUB providers: no inference)." : ".");

  const [it, ic] = (INF_TEXT[t.inference_state] || (() => [t.inference_state, "bad"]))(t);
  setPill($("#inf"), "LOCAL INFERENCE: " + it, ic);
  setPill($("#net"), `EXTERNAL INTERNET: ${t.network}`, t.network === "ONLINE" ? "ok" : "bad");
  setPill($("#store"), `LOCAL LOG: ${t.store.kind.toUpperCase()} ${t.store.status}`, t.store.status === "READY" ? "ok" : "bad");
  const g = t.ingestion, c = g.counts || {};
  setPill($("#ing"), `INGESTION: ${g.enabled ? (g.running ? "WATCHING" : "STOPPED") : "OFF"} · q ${g.queue_size} · proc ${c.processing || 0}`, g.running ? "ok" : "bad");

  const gpu = t.gpu;
  $("#t-gpu").innerHTML = `<h2>GPU</h2>` + (gpu
    ? `<div class="big">${esc(gpu.name)}</div>${bar(gpu["memory.used"], gpu["memory.total"])}` + kv([
        ["memory", `${val(gpu["memory.used"], " MiB")} / ${val(gpu["memory.total"], " MiB")}`],
        ["utilization", val(gpu["utilization.gpu"], " %")], ["temperature", val(gpu["temperature.gpu"], " °C")],
        ["power draw", val(gpu["power.draw"], " W")], ["driver", val(gpu.driver_version)]])
    : `<div class="big">${na(why)}</div>` + kv([["memory", na(why)], ["utilization", na(why)], ["temperature", na(why)], ["power draw", na(why)]]));

  const s = t.system;
  $("#t-sys").innerHTML = `<h2>System</h2>` + (s
    ? `${bar(s.ram_used_mib, s.ram_total_mib)}` + kv([["RAM", `${val(s.ram_used_mib, " MiB")} / ${val(s.ram_total_mib, " MiB")}`],
        ["load (1 min)", val(s.load_1m)], ["CPUs", val(s.cpus)]])
    : kv([["RAM", na(why)], ["load (1 min)", na(why)], ["CPUs", na(why)]]));

  $("#t-inf").innerHTML = `<h2>Inference (per provider)</h2>` + Object.entries(t.inference).map(([k, p]) => {
    const L = p.latency;
    return `<div class="prov"><strong>${esc(k)}</strong> <span class="muted small">${esc(p.model)}</span>` + kv([
      ["endpoint", esc(p.endpoint)], ["runs", p.runs],
      ["latency p50 / p95", L ? `${L.p50_s}s / ${L.p95_s}s (n=${L.count}, last ${L.last_s}s, max ${L.max_s}s)` : na(p.note || "no successful runs yet")],
      ["last success", p.last_success ? esc(p.last_success) : na(p.note || "none yet")],
      ...(p.last_error ? [["last error", `<span class="bad">${esc(p.last_error)}</span>`]] : [])]) + `</div>`;
  }).join("");

  const pr = g.processing_s_last_10min, t2e = g.time_to_entry_s;
  $("#t-ing").innerHTML = `<h2>Ingestion</h2><div class="big">${g.completed_last_10min} <span class="muted small">completed in the last 10 min (${g.per_minute_last_10min}/min)</span></div>` + kv([
    ["queue / processing", `${g.queue_size} / ${c.processing || 0}`], ["completed / failed", `${c.completed || 0} / ${c.failed || 0}`],
    ["processing time (10 min)", pr ? `p50 ${pr.p50}s · max ${pr.max}s` : na("no completed jobs in the last 10 min")],
    ["drop → entry", t2e && t2e.n ? `median ${t2e.median}s · max ${t2e.max}s (n=${t2e.n})` : na("no completed jobs")]]) +
    `<div class="small" style="margin-top:8px">${(g.recent || []).map((j) => `<div class="prov">${esc(j.status)} · ${esc(j.name)} · ${j.duration_s ?? "—"}s · ${j.events} event(s)${j.error ? ` · <span class="bad">${esc(j.error)}</span>` : ""}</div>`).join("") || na("no jobs yet")}</div>`;

  $("#t-log").innerHTML = `<h2>Incident log</h2><div class="big">${t.log.events} <span class="muted small">events · ${t.log.updates} agent update(s)</span></div>` +
    kv([...Object.entries(t.log.by_verification_state).map(([k, v]) => [k, v]), ...Object.entries(t.log.by_source_type).map(([k, v]) => ["source: " + k, v])]);

  $("#t-host").innerHTML = `<h2>Host</h2>` + kv([["hostname", esc(h.hostname)], ["platform", esc(h.platform)], ["GB10 detected", h.gb10_detected ? "yes" : "no"],
    ["nvidia-smi", h.nvidia_smi ? "present" : "absent"], ["providers", esc(h.provider_mode)], ["server started", esc(h.server_started_at)],
    ["uptime", `${Math.floor(h.uptime_s / 60)} min`], ["snapshot", esc(t.served_at)]]);
  $("#notes").innerHTML = (t.notes || []).map((n) => `⚠ ${esc(n)}`).join("<br>");
}

async function tick() {
  try {
    const r = await fetch("/api/telemetry");
    if (!r.ok) throw new Error(r.statusText);
    render(await r.json());
  } catch (e) {
    $("#src").className = "";
    $("#src").textContent = "Backend unreachable: " + e.message;
  }
}
tick();
setInterval(tick, 2000);
