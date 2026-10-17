// Browser end-to-end check of the loopback dashboard against an offline fixture server.
// Driven by tests/test_dashboard_e2e.py through the Chrome DevTools Protocol; no npm dependencies.
// Fixture runs are display-only JSON; nothing here executes candidate code.
import { spawn } from "node:child_process";
import { appendFileSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const argv = process.argv.slice(2);
const opt = {};
for (let i = 0; i < argv.length; i += 2) opt[argv[i].replace(/^--/, "")] = argv[i + 1];
const { url, chrome, root, live: LIVE, completed: COMPLETED, done } = opt;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const checks = [];
const problems = [];
let phase = "load";
const check = (name, ok, detail = "") =>
  checks.push({ name, ok: Boolean(ok), detail: ok ? "" : String(detail).slice(0, 500) });

const profile = mkdtempSync(join(tmpdir(), "kiss-e2e-"));
const proc = spawn(
  chrome,
  [
    "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
    "--disable-extensions", "--disable-background-networking", "--disable-sync", "--mute-audio",
    `--user-data-dir=${profile}`, "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
    "--window-size=1400,1000", "about:blank",
  ],
  { stdio: ["ignore", "ignore", "pipe"] },
);
let ws;
let exitCode = 1;
try {
  const wsUrl = await new Promise((resolve, reject) => {
    let buf = "";
    const t = setTimeout(() => reject(new Error("no DevTools endpoint in 20s: " + buf.slice(-400))), 20000);
    proc.stderr.on("data", (d) => {
      buf += d;
      const m = buf.match(/DevTools listening on (ws:\/\/\S+)/);
      if (m) { clearTimeout(t); resolve(m[1]); }
    });
    proc.on("exit", (code) => reject(new Error(`chromium exited early (${code}): ${buf.slice(-400)}`)));
  });
  ws = new WebSocket(wsUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error("CDP websocket error")); });
  let seq = 0;
  const pending = new Map();
  const handlers = [];
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id);
      pending.delete(m.id);
      if (m.error) p.rej(new Error(JSON.stringify(m.error)));
      else p.res(m.result);
    } else for (const h of handlers) h(m);
  };
  const send = (method, params = {}, sessionId) =>
    new Promise((res, rej) => {
      const id = ++seq;
      pending.set(id, { res, rej });
      ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
  const created = [];
  handlers.push((m) => {
    if (m.method === "Target.targetCreated" || m.method === "Target.targetInfoChanged") created.push(m.params.targetInfo.url);
  });
  await send("Target.setDiscoverTargets", { discover: true });

  async function openPage(target) {
    const { targetId } = await send("Target.createTarget", { url: "about:blank" });
    const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
    const S = (m, p) => send(m, p, sessionId);
    handlers.push((m) => {
      if (m.sessionId !== sessionId) return;
      const p = m.params;
      if (m.method === "Runtime.exceptionThrown") problems.push({ phase, kind: "exception", text: JSON.stringify(p.exceptionDetails).slice(0, 400) });
      if (m.method === "Runtime.consoleAPICalled" && ["error", "assert"].includes(p.type)) problems.push({ phase, kind: "console", text: JSON.stringify(p.args).slice(0, 400) });
      if (m.method === "Log.entryAdded" && p.entry.level === "error") problems.push({ phase, kind: "log", url: p.entry.url || "", text: p.entry.text });
    });
    await S("Page.enable");
    await S("Runtime.enable");
    await S("Log.enable");
    await S("Emulation.setDeviceMetricsOverride", { width: 1400, height: 1000, deviceScaleFactor: 1, mobile: false });
    const ev = async (expression) => {
      const r = await S("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
      if (r.exceptionDetails) throw new Error("evaluate failed: " + JSON.stringify(r.exceptionDetails).slice(0, 300));
      return r.result.value;
    };
    await S("Page.navigate", { url: target });
    return { S, ev, sessionId };
  }
  async function waitFor(page, expr, timeout = 8000) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      try { if (await page.ev(expr)) return true; } catch { /* element may be mid re-render */ }
      await sleep(120);
    }
    return false;
  }
  async function click(page, elExpr) {
    const pt = await page.ev(`(() => { const el = ${elExpr}; if (!el) return null; el.scrollIntoView({ block: "center" });
      const r = el.getBoundingClientRect(); return { x: r.left + Math.min(r.width / 2, 60), y: r.top + r.height / 2 }; })()`);
    if (!pt) throw new Error("click target not found: " + elExpr);
    await page.S("Input.dispatchMouseEvent", { type: "mouseMoved", x: pt.x, y: pt.y });
    await page.S("Input.dispatchMouseEvent", { type: "mousePressed", x: pt.x, y: pt.y, button: "left", clickCount: 1 });
    await page.S("Input.dispatchMouseEvent", { type: "mouseReleased", x: pt.x, y: pt.y, button: "left", clickCount: 1 });
  }
  const liveDir = join(root, LIVE);
  const liveEvent = (event, extra) =>
    appendFileSync(join(liveDir, "events.jsonl"), JSON.stringify({ timestamp: new Date().toISOString(), run_id: LIVE, event, ...extra }) + "\n");
  const run = (id) => `[...document.querySelectorAll('#runs .run')].find((b) => b.querySelector('h3')?.textContent === '${id}')`;
  const cand = (id, cid) => `[...${run(id)}.querySelectorAll('.candidate')].find((e) => e.querySelector('b').textContent.includes('→ ${cid} ·'))`;
  const codeDet = (id, cid) => `${cand(id, cid)}.querySelector('details')`;
  const eventsDet = (id) => `${run(id)}.querySelector(':scope > details')`;
  const job = `document.querySelector('#job').textContent`;
  const startBtn = `document.querySelector('#start')`;

  const page = await openPage(url);
  check("dashboard loads both fixture runs", await waitFor(page, `document.querySelectorAll('#runs .run').length === 2`, 15000));

  phase = "static";
  check("header and description render", await page.ev(`document.querySelector('h1').textContent === 'KISS Discovery Engine' && document.body.textContent.includes('Mercury 2.5')`));
  check("task contract renders", await page.ev(`document.querySelector('.contract').textContent.includes('count_pairs(a, b, lower, upper)')`));
  check("launch form defaults 2/2/3 with bounds", await page.ev(`(() => { const r = document.querySelector('#rounds'), w = document.querySelector('#width'), c = document.querySelector('#cap');
    return r.value === '2' && w.value === '2' && c.value === '3' && r.max === '3' && w.max === '2' && c.max === '5'; })()`));
  check("platform evidence panel renders", await waitFor(page, `document.querySelector('#platform-evidence').textContent.includes('Audit (')`));
  const evText = await page.ev(`document.querySelector('#platform-evidence').textContent`);
  check("evidence: smoke inheritance/independence", evText.includes("inheritance=true, independence=true"), evText);
  check("evidence: fixtures 5/5", evText.includes("5/5 matched"), evText);
  check("evidence: audit 34/34, unresolved=0", evText.includes("34/34 VMs destroyed, unresolved=0"), evText);
  check("live run: LIVE banner and launch disabled", await page.ev(`${job}.startsWith('LIVE:') && ${startBtn}.disabled === true`), await page.ev(job));
  check("live run box has LIVE badge", await page.ev(`${run(LIVE)}.querySelector('.badge.live')?.textContent === 'LIVE · IN PROGRESS'`));
  const comp = await page.ev(`${run(COMPLETED)}.textContent`);
  for (const s of [
    "HISTORICAL · COMPLETED", "stop: max_rounds (all configured rounds completed)", "supervisor-timed", "VMs cleaned: 4/4",
    "Best correct candidate: g1-c0", "0.97× baseline · parity within measurement noise", "1.35× baseline · slower",
    "Selection: selected as revision parent of g1-c0; superseded by g1-c0",
    "Physical microVM: sb-fixture-g1c0 ← forked from paused VM sb-fixture-g0c0",
  ]) check(`completed run shows "${s}"`, comp.includes(s), comp.slice(0, 400));
  check("exactly one SELECTED WINNER (g1-c0)", await page.ev(`[...${run(COMPLETED)}.querySelectorAll('.badge')].filter((b) => b.textContent === 'SELECTED WINNER').length === 1 && ${cand(COMPLETED, "g1-c0")}.textContent.includes('SELECTED WINNER')`));

  phase = "details";
  await click(page, `${codeDet(COMPLETED, "g0-c0")}.querySelector('summary')`);
  check("click opens 'View candidate code & explanation'", await waitFor(page, `${codeDet(COMPLETED, "g0-c0")}.open === true`, 3000));
  check("opened details show code and explanation", await page.ev(`${codeDet(COMPLETED, "g0-c0")}.textContent.includes('MARKER-COMPLETED-G0C0') && ${codeDet(COMPLETED, "g0-c0")}.textContent.includes('Explanation: fixture explanation')`));
  liveEvent("candidate_started", { candidate_id: "g0-c1", parent_candidate_id: null, generation: 0, requested_approach: "two-pointer", status: "generating", sandbox_id: null, forked_from: null });
  check("live update renders g0-c1 as generating", await waitFor(page, `${run(LIVE)}.textContent.includes('→ g0-c1 · generating')`));
  await sleep(2700);
  check("details stay open across refresh cycles with changing data", await page.ev(`${codeDet(COMPLETED, "g0-c0")}.open === true`));
  const preScroll = await page.ev(`(() => { const p = ${codeDet(COMPLETED, "g0-c0")}.querySelector('pre'); p.scrollTop = 120; return p.scrollTop; })()`);
  const pageY = await page.ev(`window.scrollY`);
  check("code block is scrollable (long code)", preScroll > 0, preScroll);
  liveEvent("generation_completed", { candidate_id: "g0-c1", approach: "two-pointer", code_sha256: "f".repeat(64), generation_ms: 1234.5 });
  await sleep(3000);
  check("code block scroll position survives a re-render", Math.abs((await page.ev(`${codeDet(COMPLETED, "g0-c0")}.querySelector('pre').scrollTop`)) - preScroll) < 2);
  check("page scroll position survives a re-render", Math.abs((await page.ev(`window.scrollY`)) - pageY) < 4);

  await click(page, `${codeDet(LIVE, "g0-c0")}.querySelector('summary')`);
  await click(page, `${eventsDet(LIVE)}.querySelector('summary')`);
  check("live candidate code and events panes open", await waitFor(page, `${codeDet(LIVE, "g0-c0")}.open && ${eventsDet(LIVE)}.open`, 3000));
  liveEvent("candidate_evaluating", { candidate_id: "g0-c1", parent_candidate_id: null, sandbox_id: "sb-fixture-live-g0c1", forked_from: "sb-fixture-live-base" });
  check("live g0-c1 moves to evaluating with its fork", await waitFor(page, `${run(LIVE)}.textContent.includes('→ g0-c1 · evaluating') && ${run(LIVE)}.textContent.includes('Physical microVM: sb-fixture-live-g0c1 ← forked from paused VM sb-fixture-live-base')`));
  liveEvent("candidate_result", { candidate_id: "g0-c1", status: "correct", evaluation_wall_ms: 4000, feedback: { status: "correct", tests_passed: 60, total: 60, candidate_ms: 9.5, baseline_ms: 7.0, benchmark: { timed_where: "supervisor wall-clock", agreement: true } } });
  check("live g0-c1 result and verdict render", await waitFor(page, `${run(LIVE)}.textContent.includes('→ g0-c1 · correct') && ${run(LIVE)}.textContent.includes('1.36× baseline · slower')`));
  check("all opened panes stay open through live updates", await page.ev(`${codeDet(COMPLETED, "g0-c0")}.open && ${codeDet(LIVE, "g0-c0")}.open && ${eventsDet(LIVE)}.open`));
  check("events pane shows the newest event", await waitFor(page, `${eventsDet(LIVE)}.querySelector('pre').textContent.includes('candidate_result')`, 4000));
  await click(page, `${codeDet(LIVE, "g0-c0")}.querySelector('summary')`);
  await sleep(2800);
  check("a pane closed by the user stays closed", await page.ev(`${codeDet(LIVE, "g0-c0")}.open === false && ${eventsDet(LIVE)}.open`));

  phase = "reports";
  for (const id of [LIVE, COMPLETED]) {
    const a = await page.ev(`(() => { const a = ${run(id)}.querySelector('a.report-link'); return a && { href: a.getAttribute('href'), target: a.target, rel: a.rel }; })()`);
    check(`report link for ${id}`, a && a.href === `/report/${id}` && a.target === "_blank" && a.rel === "noopener", JSON.stringify(a));
    const r = await page.ev(`fetch('/report/${id}').then(async (r) => ({ status: r.status, type: r.headers.get('content-type') || '', body: await r.text() }))`);
    check(`report ${id} returns 200 HTML`, r.status === 200 && r.type.startsWith("text/html") && r.body.includes(id), `${r.status} ${r.type}`);
    if (id === LIVE) check("live report renders mid-run (LIVE RUN IN PROGRESS)", r.body.includes("LIVE RUN IN PROGRESS"));
    else check("completed report shows corrected parent label", r.body.includes("selected as revision parent of g1-c0"));
  }
  const missing = await page.ev(`fetch('/report/search-20990101T999999-zzzzzz').then((r) => r.status)`);
  check("unknown report returns 404 (no crash)", missing === 404, missing);
  await click(page, `${run(COMPLETED)}.querySelector('a.report-link')`);
  check("clicking the report link opens a new tab", await (async () => {
    const t0 = Date.now();
    while (Date.now() - t0 < 5000) { if (created.some((u) => u.endsWith(`/report/${COMPLETED}`))) return true; await sleep(100); }
    return false;
  })(), JSON.stringify(created));
  const report = await openPage(url.replace(/\/$/, "") + `/report/${COMPLETED}`);
  check("report tab renders 3 candidates, lineage and back link", await waitFor(report, `document.querySelectorAll('article.candidate').length === 3 && document.body.textContent.includes('Physical microVM lineage') && !!document.querySelector('a[href="/"]')`, 8000));

  phase = "outage";
  await page.S("Fetch.enable", { patterns: [{ urlPattern: "*/api/runs*" }] });
  handlers.push((m) => {
    if (m.sessionId === page.sessionId && m.method === "Fetch.requestPaused")
      page.S("Fetch.failRequest", { requestId: m.params.requestId, errorReason: "ConnectionRefused" }).catch(() => {});
  });
  check("transient server outage is reported, not a crash", await waitFor(page, `${job}.startsWith('Local service unavailable')`, 8000), await page.ev(job));
  check("ledger and open panes survive the outage", await page.ev(`document.querySelectorAll('#runs .run').length === 2 && ${codeDet(COMPLETED, "g0-c0")}.open`));
  await page.S("Fetch.disable");
  phase = "recovered";
  check("dashboard recovers after the outage", await waitFor(page, `${job}.startsWith('LIVE:')`, 8000), await page.ev(job));

  phase = "finish";
  const s = JSON.parse(readFileSync(join(liveDir, "summary.json"), "utf8"));
  const g0c1 = { candidate_id: "g0-c1", parent_candidate_id: null, generation: 0, requested_approach: "two-pointer", approach: "two-pointer", status: "correct",
    sandbox_id: "sb-fixture-live-g0c1", forked_from: "sb-fixture-live-base", code: "def count_pairs(a, b, lower, upper):\n    return 0  # display-only fixture text\n",
    feedback: { status: "correct", tests_passed: 60, total: 60, candidate_ms: 9.5, baseline_ms: 7.0, benchmark: { timed_where: "supervisor wall-clock", agreement: true } },
    selection_reason: "not selected: status=correct (60/60 tests, median=9.500ms); best=g0-c0; correctness before measured speed" };
  Object.assign(s, { status: "completed", stop_reason: "max_rounds", finished_at: new Date().toISOString(), best_candidate_id: "g0-c0",
    candidates: [...s.candidates, g0c1], resources: ["base", "g0c0", "g0c1"].map((x) => ({ id: `sb-fixture-live-${x}`, status: "destroyed" })) });
  writeFileSync(join(liveDir, "summary.json.tmp"), JSON.stringify(s));
  renameSync(join(liveDir, "summary.json.tmp"), join(liveDir, "summary.json"));
  liveEvent("run_finished", { status: "completed" });
  check("finished run becomes historical and re-enables launch", await waitFor(page, `${job}.startsWith('Idle:') && ${startBtn}.disabled === false && ${run(LIVE)}.textContent.includes('HISTORICAL · COMPLETED') && ${run(LIVE)}.textContent.includes('VMs cleaned: 3/3')`, 8000), await page.ev(job));
  check("open panes survive the live → historical transition", await page.ev(`${codeDet(COMPLETED, "g0-c0")}.open && ${eventsDet(LIVE)}.open`));

  phase = "validation";
  await page.ev(`document.querySelector('#rounds').value = '9'`);
  await click(page, startBtn);
  await sleep(700);
  check("out-of-range input is blocked by the browser (no request)", await page.ev(`document.querySelector('#rounds').validity.rangeOverflow && ${job}.startsWith('Idle:')`), await page.ev(job));
  await page.ev(`document.querySelector('#rounds').value = '2'`);

  phase = "launch";
  await click(page, startBtn);
  check("'Run real experiment' starts the (fake) job: LIVE banner, button disabled", await waitFor(page, `${job}.startsWith('LIVE:') && ${startBtn}.disabled`, 8000), await page.ev(job));
  phase = "conflict";
  await page.ev(`document.querySelector('#form').requestSubmit()`);
  check("API error (409, one active experiment) is shown in the UI", await waitFor(page, `${job}.includes('One active experiment at a time')`, 4000), await page.ev(job));
  phase = "jobdone";
  writeFileSync(done, "1");
  check("finished job re-enables the launch button", await waitFor(page, `${job}.startsWith('Idle:') && !${startBtn}.disabled`, 8000), await page.ev(job));

  const expected = (p) => p.kind === "log" && (/favicon\.ico/.test(p.url)
    || (p.phase === "outage" && /api\/runs|ERR_CONNECTION_REFUSED/.test(p.url + p.text))
    || (p.phase === "conflict" && /409/.test(p.text))
    || (p.phase === "reports" && /404/.test(p.text)));
  const unexpected = problems.filter((p) => !expected(p));
  check("no JS exceptions or unexpected console errors", unexpected.length === 0, JSON.stringify(unexpected));
  exitCode = checks.every((c) => c.ok) ? 0 : 1;
} catch (err) {
  check("e2e driver completed", false, err.stack || String(err));
} finally {
  process.stdout.write(JSON.stringify({ ok: exitCode === 0, checks, problems }) + "\n");
  try { ws?.close(); } catch { /* ignore */ }
  proc.kill("SIGTERM");
  await sleep(300);
  rmSync(profile, { recursive: true, force: true });
  process.exit(exitCode);
}
