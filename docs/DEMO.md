# Local demonstration and submission package
Created 2026-10-17 during the event; updated after final demo run `search-20261017T215022-01459f`. Local-only: no public exposure, push or form submission performed.

## Central message

> **ES:** “KISS explora soluciones de código en forks reales y conserva evidencia de qué funcionó, qué falló y de dónde salió cada intento.”
>
> **EN:** “KISS explores code solutions in real microVM forks and preserves evidence of what worked, what failed, and where each attempt came from.”

---

## 1. 90-second live demo script (for Cristóbal's recording)

**Exact CLI command for the single authorized demo run** (only when Cristóbal gives the explicit signal after external audit; or click **Run real experiment** in the UI with `Rounds=2, Width=2, Total candidate cap=3`):
```sh
uv run kiss run --rounds 2 --width 2 --max-candidates 3 --max-sandboxes 4 --max-model-calls 5 --search-seconds 300 --benchmark-n 20000
```

1. **0:00–0:15 — Launch from the loopback UI (`http://127.0.0.1:8097`)**
   - Point to **1. Problem & contract** (`count_pairs(a, b, lower, upper) -> int`, 60 hidden correctness tests before supervisor-measured timing) and **2. Launch bounded run** (`Rounds=2, Width=2, Cap=3`).
   - Click **Run real experiment** (or show the active run banner `LIVE · IN PROGRESS`).
2. **0:15–0:40 — Watch live states stream from `events.jsonl`**
   - Show `g0-c0` (`sorted-bisect`) and `g0-c1` (`two-pointer`) transition from `generating` → `evaluating` inside real microVM forks of the paused base VM (`forked_from` shown live).
   - Point out Round 0 selection (`Best correct candidate`) and how `g1-c0` (`parent-feedback-revision`) is generated from its parent's code and measured feedback and evaluated inside a physical fork of the winning parent's paused VM.
3. **0:40–1:10 — Open the standalone report (`/report/<run-id>`)**
   - Click **Open full standalone evidence report ↗**.
   - Show the two lineage columns side by side: **1. Logical solution lineage (code & feedback)** vs. **2. Physical microVM lineage (CreateOS pause → fork)**.
   - Point to the 5% noise-band verdicts (`speed_verdict`: `parity within measurement noise` vs. `slower` vs. `faster beyond the noise band`) alongside raw statuses, and end on **`4/4 verified destroyed`** in the summary panel.
4. **1:10–1:30 — Show the Platform evidence panel (`3. Platform evidence`)**
   - Back on the dashboard, point to **3. Platform evidence** (fed by `GET /api/evidence`):
     - **Smoke (`smoke-20261017T200218-804c8e`):** `inheritance=true, independence=true`, egress `pypi=200 / example.com=URLError` (`3/3 VMs destroyed`).
     - **Fixtures (`fixtures-20261017T195514-b9747e`):** `5/5 matched` (`incorrect`, `controlled-timeout`, `syntax-error`, `input-mutation`, `timing-spoof`).
     - **Audit (`audit-20261017T215138-6151e4`):** **`34/34 VMs destroyed, unresolved=0`**, `20,350` provider-reported tokens across 16 Mercury calls.

---

## 1b. Detailed reference walkthrough (2–3 minutes)

1. **Open the local dashboard (`http://127.0.0.1:8097`)**
   - If not running, start it on loopback only: `uv run kiss serve --port 8097`.
   - Point to **Section 1 (Problem & contract)**: fixed MVP task `count_pairs(a, b, lower, upper) -> int` (T1b), inclusive bounds, duplicates counted by index, empty lists or `lower > upper -> 0`, no input mutation, 60 hidden supervisor correctness tests before supervisor-measured timing across 3 distinct 20,000-item datasets.
   - Point to the **Experiment ledger** badges: clearly distinguishes `LIVE · IN PROGRESS` runs from `HISTORICAL · COMPLETED` artifacts, and `supervisor-timed` runs from `historical worker-timed (diagnostic)` runs.

2. **Walk the primary end-to-end chain: `search-20261017T215022-01459f`**
   - Executed with current supervisor-timed harness:
     `uv run kiss run --rounds 2 --width 2 --max-candidates 3 --max-sandboxes 4 --max-model-calls 5 --search-seconds 300 --benchmark-n 20000`
   - **Base microVM:** `sb-01m55xge5pz50x960atf55199r` (trusted root supervisor uploaded to `/workspace/.kiss_trusted/harness.py`, `chmod 444`, then paused to `paused`).
   - **Generation 0 — two distinct initial approaches forked from paused base:**
     - `g0-c0` (`sorted-bisect`): logical parent `∅`; physical VM `sb-01m55xgnr1xme51d4bab9bnnvs ← sb-01m55xge5pz50x960atf55199r`; `60/60` tests; supervisor median `6.942 ms` vs baseline `7.133 ms` (`0.973×`, `agreement: false` → `0.97× baseline · parity within measurement noise`).
     - `g0-c1` (`two-pointer`): logical parent `∅`; physical VM `sb-01m55xh7htvnf8cgee3gxfwqds ← sb-01m55xge5pz50x960atf55199r`; `60/60` tests; supervisor median `9.667 ms` vs baseline `7.166 ms` (`1.349×`, `agreement: true` → `1.35× baseline · slower`).
   - **Round 0 selection & cleanup:** Both passed `60/60`; `g0-c0` (`6.942 ms`) ranked ahead of `g0-c1` (`9.667 ms`). `g0-c1`'s VM was immediately destroyed; `g0-c0`'s VM remained paused as the checkpoint for Generation 1.
   - **Generation 1 — revision from its own parent's code, feedback and paused VM:**
     - `g1-c0` (`parent-feedback-revision`):
       - **Logical code parent:** `g0-c0` (`candidates/g1-c0/prompt.json` contains only `g0-c0`'s code and measured feedback; adds `not a or not b` early exit while preserving `sorted(b)` + `bisect`).
       - **Physical microVM fork:** `sb-01m55xhp139bt4r3m2hjq99ewz ← sb-01m55xgnr1xme51d4bab9bnnvs` (physically forked from `g0-c0`'s paused microVM, not from base).
       - **Result:** `60/60` tests; supervisor median `6.553 ms` vs baseline `7.346 ms` (`0.892×` vs `0.973×` of parent `g0-c0`, with `agreement: false` → `0.89× baseline · parity within measurement noise`; **selected by rule; difference within measurement noise**). Note: `g0-c0`'s `not selected` text in the historical `summary.json` came from pre-fix bug K02; raw `runs/` artifacts are append-only and never rewritten.
       - **Honest measurement caveat:** Both `g0-c0` and `g1-c0` retain `agreement: false` on the single-shot root cross-check. Contrast with `search-20261017T200437-128ee8`, where parent `g0-c0` (`6.515 ms`, `0.98× baseline · parity`) remained ahead of child `g1-c0` (`6.587 ms`, `0.98× baseline · parity`), and `search-20261017T200300-4a7d42`, where `g0-c1` (`two-pointer`, `5.678 / 6.828 ms = 0.832×`, `agreement: true`) was the only result faster beyond the 5% noise band. Subtraction of IPC/data-generation overhead is noisy: `performance_met` is a finite-run threshold, not a portable speedup proof.

3. **Show preserved failures, fixtures and resource audit**
   - **Real failures retained in ledger:**
     - `search-20261017T195122-af1869`: `g0-c1` (`two-pointer`) failed `5/60` with `TypeError` on helper arguments; `g0-c0` won Round 0 (`60/60`); `g1-c0` revised `g0-c0` (`60/60`). Marked `historical worker-timed (diagnostic)`.
     - `search-20261017T195854-92454c` (launched from browser): `g0-c0` failed `5/60` (`NameError: bisect`), `g0-c1` passed `60/60`, `g1-c0` hit `truncated_generation` (`Physical microVM: none (stopped at truncated_generation before VM fork)`).
     - `search-20261017T200300-4a7d42`: `g1-c0` rejected by contract validator (`invalid_generation`) before any VM fork.
   - **Hand-authored remote failure fixtures (`runs/fixtures-20261017T195514-b9747e/summary.json`, NOT Mercury output):** `test_failure`, `timeout`, `compilation_error` (`syntax-error`), input mutation (`test_failure`), and `timing-spoof` (monkeypatches `time.perf_counter = lambda: 0.0`, classified as `protocol_error` in `src/kiss_engine/failures.py:22-26`) all classified as expected (`5/5`).
   - **Smoke (`runs/smoke-20261017T200218-804c8e/summary.json`):** `pause -> paused -> fork`, file inheritance + post-fork independence, 2 children running concurrently, `pypi.org` allowed / `example.com` blocked.
   - **Read-only audit (`runs/audit-20261017T215138-6151e4/summary.json`):** **34/34 owned sandboxes verified `destroyed` (`unresolved: []`)**; 20,350 provider-reported tokens across 16 usage events.

4. **Local screenshots (secret-free)**
   - Saved under `runs/captures-20261017/` (ignored by Git):
     - `dashboard-completed.png` — ledger view with `search-20261017T215022-01459f` and historical runs.
     - `dashboard-live-running.png` — live in-progress state captured during `search-20261017T215022-01459f`.
     - `report-search-20261017T215022-01459f.png` — standalone evidence report showing task contract, dual lineage, timings and code.

---

## 2. Reproducible instructions (from a clean checkout)

```sh
uv sync --locked --group dev
uv run pytest -q
uv run ruff check src tests

# Loopback dashboard (http://127.0.0.1:8097):
uv run kiss serve --port 8097

# Bounded 2-round demo search (2 initial approaches + selection + 1 own-parent revision):
uv run kiss run --rounds 2 --width 2 --max-candidates 3 --max-sandboxes 4 --max-model-calls 5 --search-seconds 300 --benchmark-n 20000

# Read-only reconciliation of this repo's recorded CreateOS sandbox IDs:
uv run kiss audit
```

---

## 3. Copy-ready submission & presentation text

### One-line GitHub repository description (used by `projects.dev/leaderboard` `/api/validate-repo`)
> KISS explores code solutions in real CreateOS microVM forks with Mercury 2.5 and preserves verifiable evidence of what worked, what failed, and where each attempt came from.

### Short pitch (ES — para presentación oral / Discord)
> **KISS Discovery Engine** explora soluciones de código en forks reales de microVMs de CreateOS y conserva evidencia verificable de qué funcionó, qué falló y de dónde salió cada intento. Mercury 2.5 (API directa de Inception) genera enfoques algorítmicos distintos (`sorted-bisect` y `two-pointer`) para un contrato fijo (`count_pairs`). Ningún código generado se ejecuta ni importa en el host: cada candidato corre como `nobody` bajo un supervisor raíz confiable en su propio fork físico de CreateOS (`pause -> paused -> fork`). El motor selecciona primero por exactitud (60 tests ocultos) y luego por tiempo medido desde el supervisor, etiquetando explícitamente la banda de ruido empírica del 5% (`faster beyond the noise band`, `parity within measurement noise` o `slower`), y genera la siguiente revisión pasándole únicamente el código y feedback medido de su propio padre sobre un fork físico de la VM pausada de ese padre. Al terminar, destruye y reconcilia todos los sandboxes propios (34/34 `destroyed`).

### Project story / full description (EN — for forms / README / Discord)
> **What it does:** KISS Discovery Engine is an evidence-first code exploration harness built with **CreateOS Sandbox** (provisioned via **Stripe Projects**) and **Mercury 2.5** (Inception direct API). Given the `count_pairs(a, b, lower, upper) -> int` task contract, it generates distinct initial algorithms in Generation 0 (`sorted-bisect` and `two-pointer`), evaluates each inside an isolated CreateOS microVM forked from a paused base snapshot, selects the winner strictly on 60 hidden correctness tests before supervisor-measured benchmark median, and in Generation 1 revises the winning candidate using only its own code, its own measured feedback, and a physical microVM fork of its own paused sandbox.
>
> **How it works & safety boundaries:**
> - **Zero host execution of generated code:** The host performs AST contract checks only; candidate code never runs or imports on the host.
> - **Trusted supervisor vs. untrusted worker:** Inside each microVM, a root-owned supervisor (`/workspace/.kiss_trusted/harness.py`, mode `0400` during run) spawns an unprivileged `nobody` worker (`python3 -I`). Expected answers and the reference baseline stay outside the candidate interpreter; worker-reported PIDs are never trusted for privileged termination.
> - **Separate logical and physical ancestry:** Every run records both logical code lineage (`parent_candidate_id`) and physical CreateOS VM lineage (`forked_from` verified against server responses after `pause -> paused -> fork`).
> - **Honest evidence ledger & 5% noise band:** Append-only `events.jsonl`, `summary.json`, and standalone `report.html` preserve passing candidates, wrong answers, `truncated_generation`, `invalid_generation`, noisy timing cross-checks (`agreement: false`), and a 5% empirical noise-band verdict (`speed_verdict`: in `search-20261017T215022-01459f`, `g1-c0` at `0.892×` vs parent `0.973×` with `agreement: false` is labeled `selected by rule; difference within measurement noise`; in `search-20261017T200300-4a7d42`, `g0-c1` at `0.832×` with `agreement: true` is `faster beyond the noise band`), plus verified cleanup (`34/34` owned sandboxes `destroyed`).

---

## 4. Two submission channels & permission gates

**Deadline (confirm with Cristóbal — discrepancy noted):**
- Previous note in this document: **22:00 Chile** (`America/Santiago`, UTC-3; 18:00 PT).
- Team hackathon calendar (`hackathon_calendar` / `data/hackathons.json`): **23:00 Chile** (`2026-10-17T23:00:00-03:00`; 19:00 PT).
- *Action required:* Cristóbal, please confirm whether the official submission close is **22:00** or **23:00** Chile time.
**Internal target:** 21:45 Chile.
**Hackathon code:** `CreateOS-2026` (internal slug on leaderboard filter: `createos-2026`).

### Channel A: Stripe Projects Leaderboard (`https://projects.dev/leaderboard`)
Verified by inspecting the live page and client bundle (`SubmitProjectModal`):
- **How submission works:** Web modal opened via **"Submit Your Project"** on `https://projects.dev/leaderboard` (not a CLI command; `stripe projects` v0.50.0 has no `share` or `submit` subcommand).
- **Step 1 — Identity verification:** Email OTP (`POST /api/auth/otp`) sent to the email address associated with the Stripe Projects account (6-digit Clerk verification code — requested from Cristóbal **only** at the moment of live submission after push and GitHub Pages are authorized and live).
- **Step 2 — Prepared submission field values (`POST /api/projects`):**

| Field | Prepared value / source | Status |
|---|---|---|
| `Name / Username` | `Cristóbal Muñoz` (or GitHub handle `Grizaceo`) | Ready |
| `Stripe Account ID` | Retrieved in-memory at submission time via `stripe whoami --format json` (`^acct_[a-zA-Z0-9]{16}$`; **never printed or committed to tracked files**) | Ready (local CLI) |
| `Public Repo URL` | `https://github.com/<owner>/kiss-discovery-engine-hackathon` (validated by `POST /api/validate-repo`, which pulls name + description from GitHub) | Pending push authorization |
| `Deployed Project URL` | `https://<owner>.github.io/kiss-discovery-engine-hackathon/evidence/` (serves static, zero-JS `evidence/index.html`; **never** expose `kiss serve` or any execution endpoint) | Pending push + Pages authorization |
| `Stack URL` | `https://projects.dev/s#v1:createos~project` | Ready |
| `Hackathon code` | `CreateOS-2026` (filter slug: `createos-2026`) | Ready |

### Channel B: Additional Discord deadline link
- Shared by organizers in Discord near the closing deadline.
- Uses the copy-ready pitch (§3), `Public Repo URL`, `Deployed Project URL`, and evidence summary above.

### Pre-publish repository hygiene checklist (verified read-only)
- `git status`: clean working tree.
- `.gitignore`: `.env`, `.env.*` (except `.env.example`), `.projects/`, `runs/`, and `credentials*` are gitignored (`git check-ignore -v .env .projects/ runs/`). Curated, secret-scanned `evidence/` is tracked.
- `git log --all --name-only`: zero `.env`, `.projects/`, `runs/`, or credential files in any historical commit.
- Secret & path scan across tracked files: zero secret values from `.env` / `MERCURY_ENV_FILE`, zero API key tokens, and zero personal home-directory paths. Author email in git log is accepted as-is without history rewrite.

### Exact commands to execute ONLY after Cristóbal's explicit authorization

1. **Create the public GitHub repository, set the `/api/validate-repo` description from §3, update `pyproject.toml`, and push `main`:**
   ```sh
   # DO NOT RUN until Cristóbal explicitly authorizes public repo creation + push:
   gh repo create kiss-discovery-engine-hackathon \
     --public \
     --source=. \
     --remote=origin \
     --description "KISS explores code solutions in real CreateOS microVM forks with Mercury 2.5 and preserves verifiable evidence of what worked, what failed, and where each attempt came from." \
     --push
   ```
2. **Enable GitHub Pages (serving static `evidence/index.html` from `main` `/` root — never `kiss serve`):**
   ```sh
   # DO NOT RUN until after the public push above is authorized and completed:
   OWNER="$(gh api user -q .login)"
   gh api -X POST "repos/${OWNER}/kiss-discovery-engine-hackathon/pages" \
     -f "build_type=legacy" \
     -f "source[branch]=main" \
     -f "source[path]=/"
   # Resulting Deployed Project URL once live:
   # https://${OWNER}.github.io/kiss-discovery-engine-hackathon/evidence/
   ```
3. **Single final demo run (ONLY when Cristóbal gives the explicit post-audit signal):**
   ```sh
   # DO NOT RUN until Cristóbal explicitly authorizes the single final demo run:
   uv run kiss run --rounds 2 --width 2 --max-candidates 3 --max-sandboxes 4 --max-model-calls 5 --search-seconds 300 --benchmark-n 20000
   uv run kiss audit
   ```
4. **Form submission (`https://projects.dev/leaderboard` + Discord link):**
   - Only after steps 1–2 are authorized and live, request the 6-digit email OTP from Cristóbal and submit with the table values above.
