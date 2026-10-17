"""Loopback-only dashboard; bounded fixed-task jobs. Never serves .env or arbitrary files."""

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .engine import Limits

PAGE = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KISS Discovery Engine</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{background:#0a1019;color:#e6edf3;font:15px/1.55 system-ui;max-width:1180px;margin:40px auto;padding:0 24px}h1{font-size:44px;letter-spacing:-1.5px;margin-bottom:0}.overline{color:#50deb3;text-transform:uppercase;letter-spacing:3px;font-size:12px}p,small{color:#9eadbd}.layout{display:grid;grid-template-columns:310px 1fr;gap:22px;align-items:start}section,.run{border:1px solid #273646;border-radius:16px;padding:22px;background:#101925;margin:18px 0}button,a.button{background:#69e8ba;color:#082217;border:0;border-radius:9px;padding:12px 18px;font-weight:750;cursor:pointer}button:disabled{opacity:.4;cursor:wait}label{display:block;margin:14px 0;color:#b9c8d5}input,select{width:100%;padding:9px;margin-top:4px;background:#0a111c;color:#e8f1f7;border:1px solid #3b4a5e;border-radius:7px}a{color:#7dc9ff}pre{font:12px/1.5 monospace;white-space:pre-wrap;overflow-wrap:anywhere;max-height:250px;overflow:auto}.run h3{margin-top:0;word-break:break-word}.badge{padding:3px 8px;border:1px solid #405066;border-radius:20px;font-size:12px;color:#a8edd1}.candidate{border-left:2px solid #3a5d62;padding-left:12px;margin:14px 0}.error{color:#ffac9c}#job{min-height:30px}summary{cursor:pointer}@media(max-width:760px){.layout{grid-template-columns:1fr}h1{font-size:34px}}
</style><p class="overline">CreateOS × Stripe Projects · hackathon build</p><h1>KISS Discovery Engine</h1><p>Search for working code. Keep the evidence.<br>Mercury 2.5 generates. Real microVM forks execute. Tests decide.</p><div class="layout"><section><h2>New experiment</h2><form id="form"><label>Task<select><option>count_pairs · T1b</option></select></label><small>Count cross-list index pairs whose sum lies within inclusive bounds. Duplicates count; inputs stay unchanged. Fixed, explicit MVP task.</small><label>Rounds<input id="rounds" type="number" min="1" max="3" value="2"></label><label>Initial approaches<input id="width" type="number" min="1" max="2" value="2"></label><label>Candidate cap<input id="cap" type="number" min="1" max="5" value="3"></label><button id="start">Run real experiment</button></form><p id="job"></p><small>Local only. Existing credits, no plan changes. Up to 6 sandbox creations and 8 model HTTP attempts. Search ≤ 6 min by default; cleanup is separately bounded. No invented data, no silent fallback.</small></section><main><section><h2>Experiment ledger</h2><small>Code lineage ≠ physical VM lineage. Click a report for actual code, feedback, raw execution and cleanup.</small></section><div id="runs">Loading local evidence…</div></main></div><script>
const $=s=>document.querySelector(s);function node(tag,text,cls){let e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
async function refresh(){try{const r=await fetch('/api/runs');const d=await r.json();$('#runs').replaceChildren();for(const s of d.runs){let box=node('section',undefined,'run');box.append(node('h3',s.run_id));box.append(node('span',s.status+' · '+(s.stop_reason||'in progress'),'badge'));if(s.error)box.append(node('p',s.error,'error'));box.append(node('p','Best: '+(s.best_candidate_id||'not selected')));for(const c of s.candidates||[]){let e=node('div',undefined,'candidate');e.append(node('b',(c.parent_candidate_id||'∅')+' → '+c.candidate_id+' · '+c.status));e.append(node('p',(c.approach||c.requested_approach||'')+' · tests '+(c.feedback?.tests_passed??'—')+'/'+(c.feedback?.total??'—')));e.append(node('small','VM '+(c.sandbox_id||'pending')+' ← '+(c.forked_from||'pending')));box.append(e)}if(s.warnings?.length)box.append(node('p',s.warnings.join(' · '),'error'));let a=node('a','Open evidence report ↗');a.href='/report/'+encodeURIComponent(s.run_id);a.target='_blank';a.rel='noopener';box.append(a);let det=node('details');det.append(node('summary','Latest events'));det.append(node('pre',JSON.stringify(s.latest_events||[],null,2)));box.append(det);$('#runs').append(box)}$('#start').disabled=d.active;$('#job').textContent=d.active?'A real bounded run is active. States refresh automatically.':''}catch(e){$('#job').textContent='Local service unavailable: '+e.message}}
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
                cid = event.get("candidate_id")
                if not cid:
                    continue
                if event["event"] == "candidate_started":
                    candidates[cid] = {
                        k: v
                        for k, v in event.items()
                        if k not in {"run_id", "event", "timestamp"}
                    }
                elif cid in candidates:
                    if event["event"] == "candidate_evaluating":
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
                {k: v for k, v in c.items() if k not in {"code", "execution"}}
                for c in candidates.values()
            ]
            summary["latest_events"] = [
                {k: v for k, v in e.items() if k not in {"task", "feedback"}}
                for e in events[-5:]
            ]
            result.append(summary)
        except (OSError, ValueError, KeyError):
            continue
    return result


def serve(port=8097):
    root = Path.cwd() / "runs"
    root.mkdir(exist_ok=True, mode=0o700)
    job = {"process": None, "log": None}
    lock = threading.Lock()
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

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
            if self.headers.get("Host") not in allowed_hosts:
                self.send(403, {"error": "Loopback Host required"})
                return False
            return True

        def do_GET(self):
            if not self.check_host():
                return
            path = urlsplit(self.path).path
            if path == "/":
                return self.send(200, PAGE, "text/html")
            if path == "/api/runs":
                process = job["process"]
                return self.send(
                    200,
                    {
                        "active": process is not None and process.poll() is None,
                        "runs": list_runs(root),
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
                if report.is_file():
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
            if origin not in {f"http://{h}" for h in allowed_hosts}:
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

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
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
