"""Self-contained evidence report. All model-produced content is escaped."""

import json
import math
from html import escape

STOP_NOTES = {
    "max_rounds": "configured generation rounds completed",
    "max_candidates": "configured candidate cap reached",
    "max_model_calls": "configured Mercury API call budget reached",
    "max_sandboxes": "configured CreateOS sandbox creation cap reached",
    "performance_target_met": "stop_on_target enabled and performance threshold met",
    "no_evaluable_candidates": "no candidate produced an evaluable sandbox verdict",
    "time_limit": "orchestrator wall-clock deadline reached",
    "cancelled": "cancelled by signal; owned resources cleaned",
    "infrastructure_error": "halted on infrastructure/provider error",
}


# In runs 200300, 200437 and 215022, g0-c0 (sorted-bisect, same approach as baseline)
# measured 0.973x-1.044x, and baseline varied 6.618-7.346 ms across VMs (~5% noise band).
NOISE_BAND = 0.05


def speed_verdict(f):
    f = f or {}
    c, b = f.get("candidate_ms"), f.get("baseline_ms")
    if not (
        isinstance(c, (int, float))
        and not isinstance(c, bool)
        and isinstance(b, (int, float))
        and not isinstance(b, bool)
        and math.isfinite(c)
        and math.isfinite(b)
        and c > 0
        and b > 0
    ):
        return "not benchmarked"
    ratio = c / b
    agree = (f.get("benchmark") or {}).get("agreement")
    if ratio > 1 + NOISE_BAND:
        return f"{ratio:.2f}× baseline · slower"
    if ratio < 1 - NOISE_BAND and agree:
        return f"{ratio:.2f}× baseline · faster beyond the noise band"
    return f"{ratio:.2f}× baseline · parity within measurement noise"


def _fmt_ms(val):
    if isinstance(val, (int, float)) and math.isfinite(val):
        return f"{val:.3f} ms (raw: {val})"
    return "—"


def _selection_text(c, summary):
    reason = c.get("selection_reason")
    if reason:
        return reason
    if summary.get("status") == "running":
        return "pending selection (experiment round in progress)"
    best = summary.get("best_candidate_id")
    rev_parent = summary.get("revision_parent_id")
    cid = c.get("candidate_id")
    if best and cid == best:
        return "selected as best candidate (correctness first, then fastest median)"
    if rev_parent and cid == rev_parent:
        return "selected as revision parent only (no passing candidate in run)"
    if c.get("selected_in_rounds"):
        return (
            f"selected in round(s) {c['selected_in_rounds']} and used as parent; "
            f"superseded by {rev_parent or best or 'later candidate'}"
        )
    f = c.get("feedback") or {}
    passed = f.get("tests_passed", "—")
    total = f.get("total", 60)
    ms = f.get("candidate_ms")
    ms_part = (
        f", median {ms:.3f} ms"
        if isinstance(ms, (int, float)) and math.isfinite(ms)
        else ""
    )
    return (
        f"not selected (historical record): status={c.get('status')} "
        f"({passed}/{total} tests{ms_part}); best={best or 'none'} ranked ahead on correctness then median ms"
    )


def _timing_method(f):
    bench = (f or {}).get("benchmark") or {}
    timed_where = str(bench.get("timed_where") or "")
    if "supervisor" in timed_where:
        agr = bench.get("agreement")
        agr_txt = (
            f" · single-shot root cross-check agreement={agr}"
            if agr is not None
            else ""
        )
        return (
            "Authoritative supervisor wall-clock minus null-roundtrip IPC overhead (3 distinct datasets)"
            + agr_txt
        )
    if timed_where:
        return (
            "Historical worker self-timing (diagnostic only; pre-supervisor-timing run)"
        )
    return "Not benchmarked (stopped before benchmark phase)"


def render_report(summary, static=False):
    def h(value):
        return escape(str(value))

    status = summary.get("status") or "unknown"
    is_live = status == "running"
    state_label = (
        "LIVE RUN IN PROGRESS"
        if is_live
        else f"HISTORICAL EVIDENCE ARTIFACT · {status.upper()}"
    )
    stop = summary.get("stop_reason") or ("in progress" if is_live else "—")
    stop_desc = STOP_NOTES.get(stop, "")
    stop_display = f"{stop} ({stop_desc})" if stop_desc else stop
    resources = summary.get("resources") or []
    destroyed = sum(1 for r in resources if r.get("status") == "destroyed")
    benchmark_n = (summary.get("config") or {}).get("benchmark_n", 20000)
    best_id = summary.get("best_candidate_id")
    rev_parent_id = summary.get("revision_parent_id")
    rev_parent_row = (
        f"<dt>Revision parent</dt><dd><b>{h(rev_parent_id)}</b> (highest-ranked evaluable candidate used for revision; not a passing winner)</dd>"
        if rev_parent_id and rev_parent_id != best_id
        else ""
    )

    cards = []
    for c in summary.get("candidates", []):
        f = c.get("feedback") or {}
        code = c.get("code", "No valid code received")
        cid = c.get("candidate_id", "")
        is_best = bool(
            summary.get("best_candidate_id") and cid == summary.get("best_candidate_id")
        )
        sv = speed_verdict(f)
        is_faster = "faster beyond the noise band" in sv
        speed_badge = (
            f' <span class="badge{" faster" if is_faster else ""}">{h(sv)}</span>'
            if sv != "not benchmarked"
            else ""
        )
        winner_badge = (
            ' <span class="badge winner">SELECTED WINNER</span>' if is_best else ""
        )
        gen = c.get("generation", 0)
        parent_id = c.get("parent_candidate_id")
        gen_desc = (
            "Generation 0 · initial candidate (no parent code)"
            if not parent_id
            else f"Generation {gen} · revision of logical code parent {parent_id} (received {parent_id} code + measured feedback)"
        )
        sb_id = c.get("sandbox_id")
        fork_src = c.get("forked_from")
        if sb_id:
            vm_desc = f"{sb_id} ← physically forked from paused VM {fork_src}"
        elif is_live and c.get("status") in {"generating", "evaluating"}:
            vm_desc = "pending (generation/evaluation in progress)"
        else:
            vm_desc = "none (not forked — candidate stopped at generation/validation before remote execution)"

        errors = f.get("errors") or []
        detail = f.get("detail")
        err_block = ""
        if detail or errors:
            sample_err = (
                errors[0].get("candidate_error")
                or f"case={errors[0].get('case')} expected={errors[0].get('expected')} got={errors[0].get('got')}"
                if errors
                else ""
            )
            err_block = (
                f"<dt>Failure / error detail</dt><dd class='err'>{h(detail or '')}"
                + (f" · First failure: {h(sample_err)}" if sample_err else "")
                + "</dd>"
            )
        explanation = c.get("explanation")
        exp_block = (
            f"<dt>Model explanation</dt><dd>{h(explanation)}</dd>"
            if explanation
            else ""
        )
        cards.append(f"""<article class="candidate{" best-card" if is_best else ""}"><header><h2>{h(cid)} <span class="badge {h(c.get("status", ""))}">{h(c.get("status", ""))}</span>{speed_badge}{winner_badge}</h2>
<p>Code parent: <b>{h(parent_id or "∅ (initial)")}</b> → <b>{h(cid)}</b> · {h(gen_desc)}</p></header>
<dl><dt>Approach</dt><dd>{h(c.get("approach", c.get("requested_approach")))}</dd><dt>Physical microVM &amp; fork</dt><dd>{h(vm_desc)}</dd><dt>Source SHA256</dt><dd>{h(c.get("code_sha256") or "—")}</dd><dt>Correctness tests</dt><dd>{h(f.get("tests_passed", "—"))}/{h(f.get("total", "—"))} (phase: {h(f.get("phase") or "—")})</dd><dt>Candidate / baseline median</dt><dd>{h(_fmt_ms(f.get("candidate_ms")))} / {h(_fmt_ms(f.get("baseline_ms")))} · <b>{h(sv)}</b></dd><dt>Timing methodology</dt><dd>{h(_timing_method(f))}</dd><dt>Generation / evaluation wall</dt><dd>{h(_fmt_ms(c.get("generation_ms")))} / {h(_fmt_ms(c.get("evaluation_wall_ms")))}</dd><dt>Selection outcome</dt><dd>{h(_selection_text(c, summary))}</dd>{exp_block}{err_block}</dl>
<details open><summary>Code · actual provider response</summary><pre><code>{h(code)}</code></pre></details>
<details><summary>Feedback, methodology and raw execution</summary><pre>{h(json.dumps({"feedback": f, "execution": c.get("execution")}, indent=2))}</pre></details></article>""")
    code_tree = "".join(
        f"<li><b>{h(c.get('parent_candidate_id') or '∅ (initial generation 0)')}</b> → <b>{h(c['candidate_id'])}</b> ({h(c.get('requested_approach') or c.get('approach'))}) · status: <b>{h(c.get('status'))}</b></li>"
        for c in summary.get("candidates", [])
    )
    vm_tree = "".join(
        f"<li><b>{h(c['candidate_id'])}</b>: paused VM <code>{h(c.get('forked_from'))}</code> → forked child VM <code>{h(c.get('sandbox_id'))}</code></li>"
        if c.get("sandbox_id")
        else f"<li><b>{h(c['candidate_id'])}</b>: no microVM forked (stopped at <code>{h(c.get('status'))}</code> before execution)</li>"
        for c in summary.get("candidates", [])
    )
    back_link = (
        "" if static else '<p><a href="/">← Back to local experiment ledger</a></p>\n'
    )
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KISS · {h(summary["run_id"])}</title>
<style>:root{{color-scheme:dark}}body{{font:15px/1.55 system-ui;background:#0e1117;color:#e6edf3;max-width:1120px;margin:36px auto;padding:0 24px}}h1{{font-size:34px;margin-bottom:4px}}h2{{margin-top:0}}.subtitle,dt{{color:#9eacbb}}header p{{font-size:13px;color:#9eacbb}}article,.panel{{background:#151b23;border:1px solid #303b49;border-radius:14px;padding:22px;margin:18px 0}}.best-card{{border-color:#2ea043}}dl{{display:grid;grid-template-columns:230px 1fr;gap:9px}}dd{{margin:0;overflow-wrap:anywhere}}pre{{background:#0c1119;padding:16px;overflow:auto;font:12px/1.6 monospace;max-height:600px;border-radius:8px}}.badge{{font-size:12px;background:#333e50;padding:4px 9px;border-radius:12px;display:inline-block}}.correct,.faster,.winner{{background:#114932;color:#a0f0be}}.live{{background:#5a3e0b;color:#ffd885}}.err{{color:#ffac9c}}summary{{cursor:pointer;padding:8px 0;font-weight:600}}a{{color:#79c0ff}}.cols{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}@media(max-width:760px){{.cols,dl{{grid-template-columns:1fr}}}}</style>
{back_link}<h1>KISS Discovery Engine</h1><p class="subtitle">Evidence, not confidence. Mercury 2.5 · Inception direct · real CreateOS microVM forks.</p>
<section class="panel"><p><span class="badge {"live" if is_live else ""}">{h(state_label)}</span></p><h2>{h(summary["run_id"])}</h2><dl><dt>Run status &amp; stop reason</dt><dd><b>{h(status)}</b> · {h(stop_display)}</dd><dt>Best correct candidate</dt><dd><b>{h(best_id or "none")}</b> (rule: 60/60 correctness first, then tests_passed, then lowest supervisor-measured median ms)</dd>{rev_parent_row}<dt>Started / finished (UTC)</dt><dd>{h(summary.get("started_at") or "—")} → {h(summary.get("finished_at") or ("running" if is_live else "—"))}</dd><dt>Mercury 2.5 HTTP calls</dt><dd>{h(summary.get("model_calls", "—"))}</dd><dt>Owned CreateOS microVMs</dt><dd>{h(destroyed)}/{h(len(resources))} verified destroyed</dd></dl><p class="err">{h(summary.get("error", ""))}</p><p class="err">{h(" · ".join(summary.get("warnings", [])))}</p><p class="subtitle">Timing methodology and caveats are recorded per candidate. Subtraction of IPC/data-generation overhead is noisy: <code>performance_met</code> is a finite-run threshold, not a portable speedup proof.</p></section>
<section class="panel"><h2>Task contract · count_pairs (T1b)</h2><p><code>count_pairs(a: list[int], b: list[int], lower: int, upper: int) -&gt; int</code> — count cross-list index pairs <code>(i, j)</code> such that <code>lower &lt;= a[i] + b[j] &lt;= upper</code> (inclusive). Duplicates count by index; empty lists or <code>lower &gt; upper</code> return <code>0</code>; caller inputs must not be mutated; Python 3 standard library only; <code>|a[i]|, |b[j]| &lt;= 10^9</code>, <code>|lower|, |upper| &lt;= 2×10^9</code>, up to <code>10^6</code> elements. Evaluated remotely as unprivileged <code>nobody</code> worker under a root-owned supervisor across 60 correctness tests and 3 seeded datasets of <code>N={h(benchmark_n)}</code> items per list.</p></section>
<section class="panel"><h2>Lineage: Logical code ancestry vs. Physical microVM forks</h2><div class="cols"><div><h3>1. Logical solution lineage (code &amp; feedback)</h3><ul>{code_tree}</ul><p class="subtitle">Generation 1+ receives only its own logical parent's code and measured feedback.</p></div><div><h3>2. Physical microVM lineage (CreateOS pause → fork)</h3><ul>{vm_tree}</ul><p class="subtitle">Gen 0 forks from the paused base VM; Gen 1+ physically forks from its logical parent's paused VM.</p></div></div></section>
{"".join(cards)}<section class="panel"><h2>Resource cleanup</h2><pre>{h(json.dumps(resources, indent=2))}</pre></section>
<section class="panel"><h2>Run configuration</h2><pre>{h(json.dumps(summary.get("config", {}), indent=2))}</pre></section></html>"""
