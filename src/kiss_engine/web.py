"""Loopback-only dashboard; bounded fixed-task jobs. Never serves .env or arbitrary files."""

import json
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .engine import Limits
from .report import render_report

STALE_SECONDS = 900

PAGE = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KISS Discovery Engine</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{background:#0a1019;color:#e6edf3;font:15px/1.55 system-ui;max-width:1220px;margin:32px auto;padding:0 24px}h1{font-size:40px;letter-spacing:-1.2px;margin:4px 0 8px}h2{margin:0 0 10px;font-size:20px}.overline{color:#50deb3;text-transform:uppercase;letter-spacing:3px;font-size:12px;margin:0}p,small{color:#9eadbd;margin:6px 0}.layout{display:grid;grid-template-columns:340px 1fr;gap:22px;align-items:start}section,.run{border:1px solid #273646;border-radius:16px;padding:20px;background:#101925;margin:14px 0}.run.live-run{border-color:#d29922;background:#171f2c}button,a.button{background:#69e8ba;color:#082217;border:0;border-radius:9px;padding:11px 18px;font-weight:750;cursor:pointer;width:100%;margin-top:8px}button:disabled{opacity:.4;cursor:wait}label{display:block;margin:12px 0;color:#b9c8d5;font-size:14px}input,select{width:100%;padding:8px;margin-top:4px;background:#0a111c;color:#e8f1f7;border:1px solid #3b4a5e;border-radius:7px}a{color:#7dc9ff}.report-link{display:inline-block;margin:8px 0;font-weight:650}pre{font:12px/1.5 monospace;white-space:pre-wrap;overflow-wrap:anywhere;max-height:260px;overflow:auto;background:#090f17;padding:12px;border-radius:8px;border:1px solid #223041}.run h3{margin:6px 0;word-break:break-word;font-size:19px}.badges{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px}.badge{padding:3px 9px;border:1px solid #405066;border-radius:20px;font-size:12px;color:#a8edd1;background:#132530}.badge.hist{color:#b8c7d9;background:#182230;border-color:#344558}.badge.live{color:#ffd885;background:#4b3409;border-color:#9e6a03}.badge.warn{color:#ffac9c;background:#3b1d22;border-color:#7d333d}.badge.win{color:#a0f0be;background:#114932;border-color:#2ea043}.candidate{border-left:3px solid #3a5d62;padding:8px 0 8px 14px;margin:14px 0;background:#0c141f;border-radius:0 10px 10px 0}.candidate.winner{border-left-color:#50deb3;background:#0d1a22}.candidate p,.candidate small{margin:4px 0;display:block}.error{color:#ffac9c}#job{min-height:26px;font-weight:600;color:#ffd885}summary{cursor:pointer;color:#9ecbff;font-size:13px;margin-top:4px}.contract{font-size:13px;background:#0b121c;border:1px solid #223244;border-radius:10px;padding:10px 12px;margin:10px 0}code{font-family:monospace;color:#c9e1ff}@media(max-width:820px){.layout{grid-template-columns:1fr}h1{font-size:32px}}
</style><p class="overline">CreateOS × Stripe Projects · hackathon build</p><h1>KISS Discovery Engine</h1><p>KISS explores code solutions in real microVM forks and preserves evidence of what worked, what failed, and where each attempt came from.<br><b>Mercury 2.5</b> (Inception direct) generates · <b>CreateOS Sandbox</b> pauses &amp; forks · <b>Trusted supervisor</b> tests &amp; times.</p><div class="layout"><section><h2>1. Problem &amp; contract</h2><div class="contract"><b>Task T1b:</b> <code>count_pairs(a, b, lower, upper) -&gt; int</code><br><small>• Count index pairs <code>(i, j)</code> across two lists with <code>lower &lt;= a[i] + b[j] &lt;= upper</code> (inclusive).<br>• Duplicates count by index; empty lists or <code>lower &gt; upper</code> return <code>0</code>.<br>• Caller inputs must not be mutated; Python 3 stdlib only; <code>|v| &lt;= 10^9</code>, <code>len &lt;= 10^6</code>.<br>• <b>Selection rule:</b> 60 hidden correctness tests first; ties broken by supervisor-measured median across 3×20,000-item datasets (minus same-dataset null roundtrip overhead).</small></div><h2>2. Launch bounded run</h2><form id="form"><label>Task<select><option>count_pairs · T1b (fixed MVP)</option></select></label><label>Rounds (Gen 0 initial + Gen 1+ revisions)<input id="rounds" type="number" min="1" max="3" value="2"></label><label>Initial approaches in Gen 0 (sorted-bisect, two-pointer)<input id="width" type="number" min="1" max="2" value="2"></label><label>Total candidate cap<input id="cap" type="number" min="1" max="5" value="3"></label><button id="start">Run real experiment</button></form><p id="job"></p><small>Loopback only. Uses existing credits; no plan changes. Capped at ≤6 sandboxes, ≤8 Mercury calls, ≤6 min search wall time + bounded cleanup. Candidate code never executes on the host.</small><h2>3. Platform evidence</h2><div id="platform-evidence" class="contract"><small>Loading smoke, fixture &amp; audit evidence…</small></div></section><main><section><h2>Experiment ledger (live status vs. historical artifacts)</h2><small><b>Logical code lineage</b> (which parent's code &amp; feedback prompted Mercury) is tracked separately from <b>physical microVM fork lineage</b> (which paused CreateOS VM was forked). Expand any candidate below for code, explanation, timings and errors, or open its standalone report.</small></section><div id="runs">Loading local evidence…</div></main></div><script>
const $=s=>document.querySelector(s);function node(tag,text,cls){let e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
const STOP_DESC={max_rounds:'all configured rounds completed',max_candidates:'candidate cap reached',max_model_calls:'Mercury call cap reached',max_sandboxes:'sandbox creation cap reached',performance_target_met:'target threshold met',no_evaluable_candidates:'no candidate produced a valid evaluation',time_limit:'wall-clock deadline reached',cancelled:'cancelled'};
const NOISE_BAND=0.05;
function fmtMs(v){return typeof v==='number'&&Number.isFinite(v)?v.toFixed(3)+' ms':'—'}
function speedVerdict(f){const c=f?.candidate_ms,b=f?.baseline_ms;if(!(typeof c==='number'&&Number.isFinite(c)&&c>0&&typeof b==='number'&&Number.isFinite(b)&&b>0))return 'not benchmarked';const ratio=c/b,agree=f?.benchmark?.agreement;if(ratio>1+NOISE_BAND)return `${ratio.toFixed(2)}× baseline · slower`;if(ratio<1-NOISE_BAND&&agree)return `${ratio.toFixed(2)}× baseline · faster beyond the noise band`;return `${ratio.toFixed(2)}× baseline · parity within measurement noise`}
function timingTag(c){const tw=c?.feedback?.benchmark?.timed_where||'';if(tw.includes('supervisor'))return 'supervisor-timed';if(tw)return 'historical worker-timed (diagnostic)';return ''}
function selectionNote(c,s){if(c.selection_reason)return c.selection_reason;if(s.status==='running')return 'pending selection (round in progress)';if(s.best_candidate_id&&c.candidate_id===s.best_candidate_id)return 'selected as best candidate (60/60 correctness first, then lowest median ms)';if(s.revision_parent_id&&c.candidate_id===s.revision_parent_id)return 'selected as revision parent only (no passing candidate)';if(c.selected_in_rounds?.length)return `selected in round(s) ${JSON.stringify(c.selected_in_rounds)} and used as parent; superseded by ${s.revision_parent_id||s.best_candidate_id||'later candidate'}`;const f=c.feedback||{};const m=typeof f.candidate_ms==='number'?`, ${f.candidate_ms.toFixed(3)} ms`:'';return `not selected (historical record): status=${c.status} (${f.tests_passed??'—'}/${f.total??60} tests${m}); best=${s.best_candidate_id||'none'} ranked ahead`}
function renderEvidence(ev){const box=$('#platform-evidence');if(!box)return;box.replaceChildren();if(ev.smoke){const s=ev.smoke,eg=s.egress||{};const py=eg['https://pypi.org/simple/']?.status??'—',ex=eg['https://example.com/']?.error_type??'—';box.append(node('p',`Smoke (${s.run_id}): inheritance=${s.inheritance_verified}, independence=${s.independence_verified}, egress pypi=${py} / example.com=${ex} (${s.destroyed_count}/${s.owned_count} VMs destroyed)`))}if(ev.fixtures){const f=ev.fixtures,rows=(f.results||[]).map(x=>`${x.fixture}:${x.expected}→${x.actual}`).join(', ');box.append(node('p',`Fixtures (${f.run_id}): ${(f.results||[]).filter(x=>x.ok).length}/${(f.results||[]).length} matched (${rows})`))}if(ev.audit){const a=ev.audit,tok=a.provider_reported_tokens?.total_tokens??'—';box.append(node('p',`Audit (${a.run_id}): ${a.destroyed_count}/${a.owned_count} VMs destroyed, unresolved=${(a.unresolved||[]).length}, tokens=${tok} (${a.usage_events} calls)`))}if(!box.childNodes.length)box.append(node('small','No smoke/fixtures/audit artifacts found in runs/.'))}
async function refresh(){try{const [r,er]=await Promise.all([fetch('/api/runs'),fetch('/api/evidence')]);const d=await r.json();if(er.ok)renderEvidence(await er.json());$('#runs').replaceChildren();for(const s of d.runs){const isLive=s.status==='running';let box=node('section',undefined,'run'+(isLive?' live-run':''));let badges=node('div',undefined,'badges');badges.append(node('span',isLive?'LIVE · IN PROGRESS':'HISTORICAL · '+(s.status||'').toUpperCase(),'badge '+(isLive?'live':'hist')));const stopTxt=s.stop_reason?(s.stop_reason+(STOP_DESC[s.stop_reason]?' ('+STOP_DESC[s.stop_reason]+')':'')):'in progress';badges.append(node('span','stop: '+stopTxt,'badge hist'));const tTag=(s.candidates||[]).map(timingTag).find(Boolean);if(tTag)badges.append(node('span',tTag,'badge '+(tTag.includes('historical')?'warn':'hist')));const res=s.resources||[];if(res.length){const dest=res.filter(x=>x.status==='destroyed').length;badges.append(node('span',`VMs cleaned: ${dest}/${res.length}`,'badge hist'))}box.append(badges);box.append(node('h3',s.run_id));box.append(node('small',`UTC: ${s.started_at||'—'} → ${s.finished_at||(isLive?'running now':'—')} · Mercury calls: ${s.model_calls??'—'}`));if(s.error)box.append(node('p','Run error: '+s.error,'error'));box.append(node('p','Best correct candidate: '+(s.best_candidate_id||'none (no passing candidate)')+' — rule: correctness (60/60) before measured median ms'));if(s.revision_parent_id&&s.revision_parent_id!==s.best_candidate_id)box.append(node('p','Revision parent: '+s.revision_parent_id+' (highest-ranked evaluable candidate used for revision; not a passing winner)'));for(const c of s.candidates||[]){const isWin=Boolean(s.best_candidate_id&&c.candidate_id===s.best_candidate_id);let e=node('div',undefined,'candidate'+(isWin?' winner':''));const genLbl=c.parent_candidate_id?`Gen ${c.generation??1} (revision of ${c.parent_candidate_id})`:`Gen ${c.generation??0} (initial)`;let head=node('b',`${genLbl}: ${c.parent_candidate_id||'∅'} → ${c.candidate_id} · ${c.status}`);e.append(head);const f=c.feedback||{};const sv=speedVerdict(f);if(sv!=='not benchmarked'){e.append(document.createTextNode(' '));e.append(node('span',sv,'badge '+(sv.includes('faster beyond the noise band')?'win':'hist')))}if(isWin){e.append(document.createTextNode(' '));e.append(node('span','SELECTED WINNER','badge win'))}const msTxt=typeof f.candidate_ms==='number'?` · median ${fmtMs(f.candidate_ms)} vs baseline ${fmtMs(f.baseline_ms)} (${sv})`:'';const agr=f.benchmark?.agreement;const agrTxt=agr===false?' · [root cross-check agreement: false]':agr===true?' · [root cross-check agreement: true]':'';e.append(node('p',`Approach: ${c.approach||c.requested_approach||'—'} · Tests: ${f.tests_passed??'—'}/${f.total??'—'}${msTxt}${agrTxt}`));let vmTxt;if(c.sandbox_id){vmTxt=`Physical microVM: ${c.sandbox_id} ← forked from paused VM ${c.forked_from||'base'}`}else if(isLive&&(c.status==='generating'||c.status==='evaluating')){vmTxt='Physical microVM: pending (generation/evaluation in progress)'}else{vmTxt=`Physical microVM: none (stopped at ${c.status} before VM fork)`}e.append(node('small',vmTxt));e.append(node('small','Selection: '+selectionNote(c,s)));const errDetail=f.detail||(f.errors&&f.errors[0]?(f.errors[0].candidate_error||JSON.stringify(f.errors[0])):'');if(errDetail)e.append(node('small','Error/detail: '+errDetail,'error'));if(c.code||c.explanation){let cdet=node('details');cdet.append(node('summary','View candidate code & explanation'));if(c.explanation)cdet.append(node('small','Explanation: '+c.explanation));if(c.code)cdet.append(node('pre',c.code));e.append(cdet)}box.append(e)}if(s.warnings?.length)box.append(node('p',s.warnings.join(' · '),'error'));let a=node('a','Open full standalone evidence report ↗','report-link');a.href='/report/'+encodeURIComponent(s.run_id);a.target='_blank';a.rel='noopener';box.append(a);let det=node('details');det.append(node('summary','Latest append-only events'));det.append(node('pre',JSON.stringify(s.latest_events||[],null,2)));box.append(det);$('#runs').append(box)}$('#start').disabled=d.active;$('#job').textContent=d.active?'LIVE: A real bounded experiment is executing now. States refresh every 2.5s.':'Idle: no experiment currently running. Showing saved local runs below.'}catch(e){$('#job').textContent='Local service unavailable: '+e.message}}
$('#form').addEventListener('submit',async e=>{e.preventDefault();$('#start').disabled=true;try{const config={rounds:Number($('#rounds').value),width:Number($('#width').value),max_candidates:Number($('#cap').value)};const r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(config)});const d=await r.json();if(!r.ok)throw new Error(d.error);$('#job').textContent='Started real job';await refresh()}catch(e){$('#job').textContent=e.message;$('#start').disabled=false}});refresh();setInterval(refresh,2500);
</script></html>"""


def list_runs(root):
    result = []
    if not root.exists():
        return result
    for path in sorted(root.glob("search-*"), reverse=True)[:25]:
        try:
            summary = json.loads((path / "summary.json").read_text())
            # Live candidate state comes from the append-only stream between summary checkpoints.
            events = []
            event_file = path / "events.jsonl"
            if event_file.exists():
                lines = event_file.read_text().splitlines()[-150:]
                for line in lines:
                    try:
                        events.append(json.loads(line))
                    except ValueError:
                        pass
            candidates = {
                c["candidate_id"]: dict(c) for c in summary.get("candidates", [])
            }
            for event in events if summary.get("status") == "running" else []:
                if event.get("event") == "selection" and event.get("candidate_id"):
                    summary["revision_parent_id"] = event.get(
                        "revision_parent_id", event["candidate_id"]
                    )
                    if event.get("passing") is True:
                        summary["best_candidate_id"] = event["candidate_id"]
                    elif "best_candidate_id" in event:
                        summary["best_candidate_id"] = event["best_candidate_id"]
                    elif event.get("passing") is not False:
                        summary["best_candidate_id"] = event["candidate_id"]
                    if event["candidate_id"] in candidates:
                        candidates[event["candidate_id"]]["selection_reason"] = (
                            event.get("reason")
                        )
                    continue
                if event.get("event") == "candidate_superseded" and event.get(
                    "candidate_id"
                ):
                    cid = event["candidate_id"]
                    if cid in candidates:
                        rounds = candidates[cid].setdefault("selected_in_rounds", [])
                        if (
                            event.get("round") is not None
                            and event["round"] - 1 not in rounds
                        ):
                            rounds.append(event["round"] - 1)
                        candidates[cid]["selection_reason"] = (
                            f"selected in round(s) {rounds} and used as parent; "
                            f"superseded by {event.get('superseded_by')} in round {event.get('round')}"
                        )
                    continue
                cid = event.get("candidate_id")
                if not cid:
                    continue
                if event["event"] == "candidate_started":
                    candidates.setdefault(
                        cid,
                        {
                            k: v
                            for k, v in event.items()
                            if k not in {"run_id", "event", "timestamp"}
                        },
                    )
                elif cid in candidates:
                    if event["event"] == "generation_completed":
                        candidates[cid].update(
                            approach=event.get("approach"),
                            code_sha256=event.get("code_sha256"),
                            generation_ms=event.get("generation_ms"),
                        )
                    elif event["event"] == "candidate_evaluating":
                        candidates[cid].update(
                            status="evaluating",
                            sandbox_id=event["sandbox_id"],
                            forked_from=event["forked_from"],
                        )
                    elif event["event"] == "candidate_result":
                        candidates[cid].update(
                            status=event["status"], feedback=event["feedback"]
                        )
                    elif event["event"] == "candidate_generation_failed":
                        candidates[cid]["status"] = event["status"]
            summary["candidates"] = [
                {k: v for k, v in c.items() if k != "execution"}
                for c in candidates.values()
            ]
            if summary.get("status") == "running":
                last_ts = (
                    events[-1].get("timestamp")
                    if events and events[-1].get("timestamp")
                    else summary.get("started_at")
                )
                age = None
                if isinstance(last_ts, str):
                    try:
                        age = (
                            datetime.now(UTC) - datetime.fromisoformat(last_ts)
                        ).total_seconds()
                    except ValueError:
                        age = None
                if age is None:
                    ref = event_file if event_file.exists() else (path / "summary.json")
                    age = time.time() - ref.stat().st_mtime
                if age > STALE_SECONDS:
                    summary["status"] = "stale"
            summary["latest_events"] = [
                {k: v for k, v in e.items() if k not in {"task", "feedback"}}
                for e in events[-5:]
            ]
            result.append(summary)
        except (OSError, ValueError, KeyError):
            continue
    return result


def platform_evidence(root):
    out = {"smoke": None, "fixtures": None, "audit": None}
    if not root.exists():
        return out
    for path in sorted(root.glob("smoke-*"), reverse=True):
        try:
            s = json.loads((path / "summary.json").read_text())
            cleanup = s.get("cleanup") or []
            out["smoke"] = {
                "run_id": s.get("run_id"),
                "ok": bool(s.get("ok")),
                "inheritance_verified": bool(s.get("inheritance_verified")),
                "independence_verified": bool(s.get("independence_verified")),
                "concurrent_running_observed": s.get("concurrent_running_observed"),
                "egress": s.get("egress") or {},
                "destroyed_count": sum(
                    1 for r in cleanup if r.get("status") == "destroyed"
                ),
                "owned_count": len(cleanup),
            }
            break
        except (OSError, ValueError, KeyError):
            continue
    for path in sorted(root.glob("fixtures-*"), reverse=True):
        try:
            s = json.loads((path / "summary.json").read_text())
            cleanup = s.get("cleanup") or []
            out["fixtures"] = {
                "run_id": s.get("run_id"),
                "ok": bool(s.get("ok")),
                "results": [
                    {
                        "fixture": r.get("fixture"),
                        "expected": r.get("expected"),
                        "actual": r.get("actual"),
                        "ok": bool(r.get("ok")),
                    }
                    for r in (s.get("results") or [])
                    if isinstance(r, dict)
                ],
                "destroyed_count": sum(
                    1 for r in cleanup if r.get("status") == "destroyed"
                ),
                "owned_count": len(cleanup),
            }
            break
        except (OSError, ValueError, KeyError):
            continue
    for path in sorted(root.glob("audit-*"), reverse=True):
        try:
            s = json.loads((path / "summary.json").read_text())
            out["audit"] = {
                "run_id": s.get("run_id"),
                "owned_count": s.get("owned_count", 0),
                "destroyed_count": s.get("destroyed_count", 0),
                "unresolved": [
                    {"id": r.get("id"), "status": r.get("status")}
                    for r in (s.get("unresolved") or [])
                    if isinstance(r, dict)
                ],
                "usage_events": s.get("usage_events", 0),
                "provider_reported_tokens": s.get("provider_reported_tokens") or {},
            }
            break
        except (OSError, ValueError, KeyError):
            continue
    return out


def make_handler(root, port, job=None, lock=None):
    root = Path(root)
    job = job if job is not None else {"process": None, "log": None}
    lock = lock or threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _allowed_hosts(self):
            p = port or self.server.server_port
            return {f"127.0.0.1:{p}", f"localhost:{p}"}

        def send(self, status, data, ctype="application/json"):
            body = data.encode() if isinstance(data, str) else json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'",
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def check_host(self):
            if self.headers.get("Host") not in self._allowed_hosts():
                self.send(403, {"error": "Loopback Host required"})
                return False
            return True

        def do_GET(self):
            if not self.check_host():
                return
            path = urlsplit(self.path).path
            if path == "/":
                return self.send(200, PAGE, "text/html")
            if path == "/api/evidence":
                return self.send(200, platform_evidence(root))
            if path == "/api/runs":
                process = job["process"]
                runs = list_runs(root)
                return self.send(
                    200,
                    {
                        "active": (process is not None and process.poll() is None)
                        or any(r.get("status") == "running" for r in runs),
                        "runs": runs,
                    },
                )
            if path.startswith("/report/"):
                run_id = path[len("/report/") :]
                if not run_id.startswith("search-") or any(
                    c
                    not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
                    for c in run_id
                ):
                    return self.send(400, {"error": "Invalid run ID"})
                report = root / run_id / "report.html"
                summary_file = root / run_id / "summary.json"
                if report.is_file():
                    if summary_file.is_file():
                        try:
                            return self.send(
                                200,
                                render_report(json.loads(summary_file.read_text())),
                                "text/html",
                            )
                        except (OSError, ValueError, KeyError):
                            pass
                    return self.send(200, report.read_text(), "text/html")
                return self.send(
                    404, {"error": "Report not available yet; run is active or unknown"}
                )
            return self.send(404, {"error": "Not found"})

        def do_POST(self):
            if not self.check_host():
                return
            if urlsplit(self.path).path != "/api/run":
                return self.send(404, {"error": "Not found"})
            origin = self.headers.get("Origin")
            if origin not in {f"http://{h}" for h in self._allowed_hosts()}:
                return self.send(403, {"error": "Same-origin request required"})
            if self.headers.get("Content-Type") != "application/json":
                return self.send(415, {"error": "JSON required"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= 1000:
                    raise ValueError("Bounded JSON body required")
                config = json.loads(self.rfile.read(length))
                if not isinstance(config, dict) or set(config) - {
                    "rounds",
                    "width",
                    "max_candidates",
                }:
                    raise ValueError(
                        "Only rounds, width and max_candidates are adjustable"
                    )
                limits = Limits(**config)
                limits.max_sandboxes = 6
                limits.max_model_calls = 8
                limits.validate()
            except (TypeError, ValueError) as exc:
                return self.send(400, {"error": str(exc)})
            with lock:
                if job["process"] is not None and job["process"].poll() is None:
                    return self.send(409, {"error": "One active experiment at a time"})
                if job["log"]:
                    job["log"].close()
                job["log"] = (root / "web-jobs.log").open("a")
                args = [
                    sys.executable,
                    "-m",
                    "kiss_engine.cli",
                    "run",
                    "--rounds",
                    str(limits.rounds),
                    "--width",
                    str(limits.width),
                    "--max-candidates",
                    str(limits.max_candidates),
                    "--max-sandboxes",
                    "6",
                    "--max-model-calls",
                    "8",
                ]
                job["process"] = subprocess.Popen(
                    args, stdout=job["log"], stderr=subprocess.STDOUT, close_fds=True
                )
            return self.send(202, {"started": True, "task": "count_pairs"})

    return Handler


def serve(port=8097):
    root = Path.cwd() / "runs"
    root.mkdir(exist_ok=True, mode=0o700)
    job = {"process": None, "log": None}
    lock = threading.Lock()
    handler_cls = make_handler(root, port, job=job, lock=lock)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
    server.daemon_threads = True
    print(f"KISS dashboard http://127.0.0.1:{port} (loopback only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if job["process"] and job["process"].poll() is None:
            # Child is independently bounded and owns finally-cleanup. Do not kill it mid-cleanup.
            print(
                "Active bounded job continues to completion and cleanup; see runs/web-jobs.log",
                flush=True,
            )
        if job["log"]:
            job["log"].close()
