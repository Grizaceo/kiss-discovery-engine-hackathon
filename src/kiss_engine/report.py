"""Self-contained evidence report. All model-produced content is escaped."""

import json
from html import escape


def render_report(summary):
    def h(value):
        return escape(str(value))

    cards = []
    for c in summary.get("candidates", []):
        f = c.get("feedback", {})
        code = c.get("code", "No valid code received")
        cards.append(f"""<article class="candidate"><header><h2>{h(c["candidate_id"])} <span class="badge {h(c.get("status", ""))}">{h(c.get("status", ""))}</span></h2>
<p>Code parent: <b>{h(c.get("parent_candidate_id") or "∅ (initial)")}</b> → {h(c["candidate_id"])} · generation {h(c.get("generation"))}</p></header>
<dl><dt>Approach</dt><dd>{h(c.get("approach", c.get("requested_approach")))}</dd><dt>MicroVM</dt><dd>{h(c.get("sandbox_id"))}</dd><dt>Physical fork source</dt><dd>{h(c.get("forked_from"))}</dd><dt>Source SHA256</dt><dd>{h(c.get("code_sha256"))}</dd><dt>Tests</dt><dd>{h(f.get("tests_passed", "—"))}/{h(f.get("total", "—"))}</dd><dt>Candidate / baseline median</dt><dd>{h(f.get("candidate_ms", "—"))} / {h(f.get("baseline_ms", "—"))} ms</dd><dt>Generation / evaluation wall</dt><dd>{h(c.get("generation_ms", "—"))} / {h(c.get("evaluation_wall_ms", "—"))} ms</dd><dt>Selection</dt><dd>{h(c.get("selection_reason") or "not selected")}</dd></dl>
<details><summary>Code · actual provider response</summary><pre><code>{h(code)}</code></pre></details>
<details><summary>Feedback, methodology and raw execution</summary><pre>{h(json.dumps({"feedback": f, "execution": c.get("execution")}, indent=2))}</pre></details></article>""")
    tree = "".join(
        f"<li>{h(c.get('parent_candidate_id') or 'base (no logical code parent)')} → <b>{h(c['candidate_id'])}</b> · {h(c.get('status'))}</li>"
        for c in summary.get("candidates", [])
    )
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KISS · {h(summary["run_id"])}</title>
<style>:root{{color-scheme:dark}}body{{font:16px system-ui;background:#0e1117;color:#e6edf3;max-width:1120px;margin:40px auto;padding:0 24px}}h1{{font-size:36px}}.subtitle,dt{{color:#9eacbb}}header p{{font-size:13px;color:#9eacbb}}article,.panel{{background:#151b23;border:1px solid #303b49;border-radius:14px;padding:22px;margin:18px 0}}dl{{display:grid;grid-template-columns:230px 1fr;gap:9px}}dd{{margin:0;overflow-wrap:anywhere}}pre{{background:#0c1119;padding:16px;overflow:auto;font:12px/1.6 monospace;max-height:600px}}.badge{{font-size:13px;background:#333e50;padding:5px 9px;border-radius:12px}}.correct,.performance_met{{background:#114932;color:#a0f0be}}summary{{cursor:pointer;padding:10px 0}}a{{color:#79c0ff}}</style>
<h1>KISS Discovery Engine</h1><p class="subtitle">Evidence, not confidence. Mercury 2.5 · Inception direct · real CreateOS forks.</p>
<section class="panel"><b>{h(summary["run_id"])}</b><p>Status: {h(summary.get("status"))} · Stop: {h(summary.get("stop_reason"))}</p><p>Best: <b>{h(summary.get("best_candidate_id") or "none")}</b></p><p>{h(summary.get("error", ""))}</p><p>Local evidence. Timing methodology and limitations are recorded per benchmark; worker-only historical measurements remain explicitly diagnostic. No robust speedup claim from a single run.</p><p>{h(" · ".join(summary.get("warnings", [])))}</p></section>
<section class="panel"><h2>Logical solution lineage</h2><ul>{tree}</ul><p>Physical VM ancestry is shown separately in each candidate. No fabricated fork edges.</p></section>
{"".join(cards)}<section class="panel"><h2>Resource cleanup</h2><pre>{h(json.dumps(summary.get("resources", []), indent=2))}</pre></section>
<section class="panel"><h2>Run configuration</h2><pre>{h(json.dumps(summary.get("config", {}), indent=2))}</pre></section></html>"""
