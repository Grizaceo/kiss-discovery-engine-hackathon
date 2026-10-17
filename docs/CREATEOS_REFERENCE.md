# 12 — Referencia: CLI `createos`, plugins de agentes y Java SDK

> **Provenance.** Documento n.º 12 de la serie de preparación del evento (hackathon CreateOS × Stripe Projects, 17-oct-2026). Las referencias a `01-createos.md`, `06-prompts-construccion.md` y `11-pre-kickoff-audit.md` corresponden a ese workspace de preparación, fuera de este repositorio.

Documento de referencia del ecosistema CreateOS, verificado el **17-oct-2026** contra:

- CLI local: `~/.local/bin/createos` **v0.0.31** (commit `6b33b676`), cuenta autenticada `free-plan` (`createos whoami` OK).
- Docs oficiales: `createos.sh/docs` y `nodeops.network/createos/docs`.
- Repos GitHub de la org `NodeOps-app`: CLI, plugins y los **6 SDKs** (TS `createos-sandbox-sdk`, Python `createos-python-sdk`, Go, Rust, C#, Java) — links completos en §7.
- Maven Central: `sh.createos:createos-java-sdk`.

Cubre las tres superficies pedidas: **CLI**, **plugins que conectan agentes**, **Java SDK**. Para el modelo REST, fork/pause/cuotas en profundidad ver `01-createos.md` (no se duplica aquí; se referencia). Todo dato sin fuente explícita se marca **NO VERIFICADO**.

## Índice

1. [Panorama del ecosistema](#1-panorama-del-ecosistema)
2. [CLI `createos`](#2-cli-createos)
3. [Plugins de agentes](#3-plugins-de-agentes)
4. [CreateOS Java SDK](#4-createos-java-sdk)
5. [Operación: cuotas, límites y costos](#5-operación-cuotas-límites-y-costos)
6. [Discrepancias y NO VERIFICADO](#6-discrepancias-y-no-verificado)
7. [Fuentes](#7-fuentes)

---

## 1. Panorama del ecosistema

CreateOS (`createos.sh`, de NodeOps) es una plataforma con **dos caras** que comparten cuenta y autenticación:

| Cara | Qué es | API | Uso en el hackathon |
|---|---|---|---|
| **CreateOS Platform** | Deploy de apps, AI agents, MCP servers, APIs, bots, sitios estáticos; dominios, env vars, cron, escala | `api-createos.nodeops.network` | Desplegar la demo / URL pública (requisito de entrega, ver `11-pre-kickoff-audit.md`) |
| **CreateOS Sandbox** | MicroVMs Firecracker (kernel + rootfs + red propias), boot rápido, `pause/resume/fork` | `https://api.sb.createos.sh` (JSend, header `X-Api-Key`) | El motor de KISS Discovery Engine |

**Una sola cadena de superficies** (todas hablan con el mismo control plane de Sandbox):

| Pieza | Nombre / paquete | Nota |
|---|---|---|
| REST API | `https://api.sb.createos.sh` + `X-Api-Key` | Envelope JSend `{status, data}` |
| SDK TypeScript | `@nodeops-createos/sandbox` · repo `createos-sandbox-sdk` | Node 20+/Bun/Deno/edge/browser; lee `CREATEOS_SANDBOX_API_KEY` |
| SDK Python | `createos-sandbox` (PyPI, `import createos`) · repo `createos-python-sdk` | Python 3.10+; 0.1.3 verificado local en venv (`01-createos.md`) |
| SDK Go | `github.com/NodeOps-app/createos-go-sdk` | Go 1.25+; ref. en pkg.go.dev |
| **SDK Java** | `sh.createos:createos-java-sdk` (Maven Central) | v0.1.2, Java 17+ → §4 |
| SDK C# | `CreateOS.Sandbox` · repo `createos-csharp-sdk` | .NET 8+ |
| SDK Rust | crate `createos` · repo `createos-rust-sdk` | Rust + Tokio; ref. en docs.rs |
| CLI | `createos` (Go, binario) · repo `createos-cli` | v0.0.31 local → §2 |
| Plugins de agentes | Monorepo `NodeOps-app/createos-plugins` (+ 2 repos propios) | 10 hosts → §3 |
| ComputeSDK (tercero listado en docs) | `@computesdk/createos-sandbox` | Uso provider-agnóstico vía `computesdk/computesdk` |
| MCP server / Skills | `api-createos.nodeops.network/mcp` · `npx skills add .../skills --skill createos` | Para operar la **plataforma** (no sandbox); MCP no pide key para operaciones básicas |

**Autenticación unificada** (vale para CLI, SDKs y plugins):

- `createos login` → device code (default), browser o `--token <api-token>` (token desde `createos.sh/app/profile`).
- Credenciales en `~/.createos/.oauth` y `~/.createos/.token`, permisos `600`.
- Alternativa headless/CI: `export CREATEOS_API_KEY=<key>`. **Tiene precedencia** sobre la sesión guardada. Nota SDK (docs SDKs, 17-oct): el de TS lee `CREATEOS_SANDBOX_API_KEY`; Go/Python/Rust/C#/Java leen `CREATEOS_API_KEY`; los 6 aceptan `CREATEOS_SANDBOX_BASE_URL` como override.
- No pegar keys en conversaciones con agentes; exportarlas en el shell.

---

## 2. CLI `createos`

### 2.1 Instalación y actualización

```bash
# Script (por defecto instala en /usr/local/bin → requiere sudo)
curl -sfL https://raw.githubusercontent.com/NodeOps-app/createos-cli/main/install.sh | sh -

# Sin sudo (lo que ya usas)
CREATEOS_INSTALL_DIR="$HOME/.local/bin" sh -c "$(curl -sfL https://raw.githubusercontent.com/NodeOps-app/createos-cli/main/install.sh)"

# Homebrew
brew tap nodeops-app/tap && brew install createos

# Nightly (puede traer features no liberadas)
curl -sfL .../install.sh | CREATEOS_CHANNEL=nightly sh -

# Pinnear versión
curl -sfL .../install.sh | CREATEOS_VERSION=v0.0.3 sh -

# Actualizar
createos upgrade

# Desde fuente: Go 1.26+
git clone https://github.com/NodeOps-app/createos-cli && cd createos-cli && go build -o createos .
```

Fuente: README de `NodeOps-app/createos-cli` + verificación local (v0.0.31 en `~/.local/bin`).

### 2.2 Autenticación

| Comando | Qué hace |
|---|---|
| `createos login` | Menú (device code por defecto; `--device` lo salta; opción browser) |
| `createos login --token <token>` | API token del dashboard (para CI/no interactivo) |
| `createos whoami` | Usuario actual y plan (verificado: `free-plan`, member since 17-oct-2026) |
| `createos logout` | Cierra sesión |

- Debug enmascara el token (solo primeros 6 / últimos 4 chars). Nunca compartir `~/.createos/.token`.
- Los plugins de agentes usan esta misma sesión (sección 3).

### 2.3 Opciones globales

| Flag | Detalle |
|---|---|
| `--output, -o table\|json` | **Auto-JSON cuando stdout es un pipe**; `-o json` fuerza en TTY |
| `--debug, -d` | HTTP request/response con token enmascarado |
| `--api-url` | Override API plataforma (default `https://api-createos.nodeops.network`) |
| `--sandbox-api-url` | Override API sandbox (default `https://api.sb.createos.sh`) |
| `--sandbox-gateway <host:port>` | Gateway SSH para `sandbox shell --ssh` (default `gateway.sb.createos.sh:2222`) |
| `--api-key` | Key explícita (alternativa a la sesión) |
| `-v`, `--version` | Versión |

Env vars equivalentes: `CREATEOS_DEBUG`, `CREATEOS_API_URL`, `CREATEOS_SANDBOX_URL`, `CREATEOS_SANDBOX_GATEWAY`, `CREATEOS_API_KEY` (+ alias `CREATEOS_PLAN_API_KEY`, `CREATEOS_PROJECT_API_KEY`), `CREATEOS_OUTPUT`.

### 2.4 Superficie "plataforma" (resumen)

Para desplegar la entrega y operarla:

- `createos init` (vincula directorio a proyecto), `createos deploy` (VCS / upload zip / imagen Docker), `createos status`, `createos open`, `createos scale`.
- `projects add|list|get|delete|suspend|unsuspend`, `deployments list|logs|build-logs|promote|retrigger|sleep|wakeup|cancel-build`, `environments`, `env list|set|rm|pull|push` (pull/push `.env`), `domains create|verify|delete`, `cronjobs` (HTTP cron con path/method/headers/body), `templates`, `webhooks`, `vms`, `oauth-clients`, `me oauth-consents`, `ask` (asistente IA de infra).

Ejemplo de deploy no interactivo (del README):

```bash
createos projects add --name "My App" --unique-name my-app --type vcs \
  --framework nextjs --runtime node:20 --github-owner myorg --repo myorg/my-app
createos deploy --branch main
createos deployments build-logs --project <id> --deployment <id>
```

Exclusiones del zip de upload: `.env*`, claves/secretos (`*.pem`, `*.key`, `*.p12`…), `node_modules`, artefactos (`target`, `coverage`…), y `.gitignore`.

### 2.5 Superficie "sandbox" (`createos sandbox`, alias `sb`)

Grupos verificados con `createos sandbox --help` (v0.0.31) + README:

| Grupo | Comandos |
|---|---|
| Ciclo de vida | `run`, `create`/`c`, `list`/`ls`, `get`, `edit`, `pause`, `resume`, `fork`, `rm`/`delete`/`destroy` |
| Ejecución | `exec` (one-shot), `shell`/`sh` (interactivo), `process`/`proc` (manejables/reconectables) |
| Archivos | `push`/`upload`/`cp-up`, `pull`/`download`/`cp-down`, `sync` (two-way), `tunnel`/`tun` |
| Config | `shapes`, `rootfs`/`images`, `firewall`/`fw` (show/set/clear), `editor` (Zed/Cursor/VS Code) |
| Recursos | `disk`/`disks` (S3), `network`/`net`/`networks`, `template`/`tpl` (build Dockerfile) |
| Extras | `devices`/`device` (VPN), `vpn`, `setup` (herdr \| orca) |

**Resolución de identificadores (tipo Docker):** cualquier comando que tome un sandbox acepta id completo, nombre, o el **prefijo único** de cualquiera de los dos (`sb-01243e`, `my-box`, `my-b`). Si hay ambigüedad, la CLI lista coincidencias y pide más caracteres.

#### `sandbox create` — flags (verificado local, v0.0.31)

| Flag | Detalle |
|---|---|
| `--shape` | Tamaño (`createos sandbox shapes`) |
| `--name` | Nombre amigable (se genera uno si se omite) |
| `--rootfs` | Imagen base o template (**default: `alpine:3.20`** — para dev pasar `devbox:1`) |
| `--disk-mib` | Disco en MiB (default del shape: 10240) |
| `--ssh-key` | Ruta a clave pública (repetible) |
| `--egress` | Destino permitido (repetible). **Vacío = internet abierto** |
| `--env` | `KEY=VALUE` para cada exec (repetible) |
| `--ingress` | URL HTTPS pública (default: cerrado) |
| `--network/--net` | Red privada al crear (repetible) |
| `--disk` | `<name\|id>:/mount/path` (repetible) |
| `--auto-pause` | `10m`, `1h`…; sin esto corre hasta que la detengas |

#### Shapes (verificado hoy contra el control plane)

`s-0.25vcpu-512mb`, `s-0.5vcpu-1gb`, `s-1vcpu-256mb`, `s-1vcpu-1gb`, `s-1vcpu-2gb`, `s-2vcpu-2gb`, `s-2vcpu-4gb`, `s-4vcpu-4gb`, `s-4vcpu-8gb`, `s-8vcpu-8gb`, `s-8vcpu-16gb`. Todos: disco default 10 GiB, sin GPU. (El plan limita el shape máximo: Free = 1 vCPU / 1 GB.)

#### Rootfs (verificado hoy)

| Imagen | Contenido |
|---|---|
| `devbox:1` | Ubuntu 24.04 · Python 3.12 (pip/uv, pandas/numpy/scipy/…) · Node 24 · Bun · Go · Rust · Docker · SSH · 5 agentes de código preinstalados |
| `desktop:1` | XFCE + Chrome + remote desktop + computer-use APIs · mismos 5 agentes |
| `ubuntu:26.04` | Ubuntu minimal |
| `debian:13` | Debian minimal |
| `alpine:3.20` | Alpine minimal — **default del catálogo si se omite `rootfs`** |

#### Exec vs shell vs process vs run (regla de decisión del README)

- `sandbox exec` → one-shot sin estado; ideal para tests/comandos cortos. `--stream` para salida larga.
- `sandbox shell` → terminal interactiva ya, sin reconexión.
- `sandbox process` → comando manejable después de iniciarlo: `run` (foreground con registro), `start` (background + PID), `shell` (sesión persistente reatacable), `attach`, `list`/`ps`, `get`, `input`, `close-stdin`, `resize`, `signal`, `wait`, `stop`. `--pty`/`-t` cuando necesita semántica de terminal. Atajos en shell manejado: `Ctrl-]` detach, `Ctrl-N` nueva shell, `Ctrl-P` picker.
- `sandbox run <imagen>` → crea un devbox y corre una imagen Docker dentro (con `--disk`, `--sync`, `--local/--remote`, `--env`, `--rm`).

#### Sync, tunnel, firewall, templates, disk, network

- `sync <sb> --local <dir> --remote <dir>`: default **two-way**; `--mode one-way` (laptop gana) o `--mode mirror` (borra extra remoto); `--exclude` repetible; sin exclusiones automáticas (ojo `.env`, `node_modules`).
- `tunnel <sb> --local 8080 --remote 8000`: puerto del box → `127.0.0.1`.
- `firewall show|set|clear`: `set` **reemplaza** la allowlist; reglas `host`, `host:port`, `*.host`, `ip`, `ip:port`, `cidr[:port]`. IP/CIDR aplican al instante; dominios ~30 s. Un dominio bloqueado **aún resuelve** DNS (falla el connect).
- `template submit <nombre> -f Dockerfile`: 1 solo `FROM`, sin `COPY`/`ADD`, ≤64 KiB de fuente, **2 builds concurrentes** por cuenta; `template logs --follow`; hasta el plan limita cuántos templates puedes tener.
- `disk create my-data --bucket ... --endpoint ... --access-key ... --secret-key ...`: buckets S3-compatibles montables en vivo; **no se heredan en fork**; Free = 0 discos.
- `network create|ls|show|attach|detach|rm`: overlay privado sandbox-a-sandbox; dentro, nombres FQDN `<box-name>.fc.local`; hasta 8 boxes por cluster.
- `devices` + `vpn`: unir tu máquina a las redes privadas por WireGuard (requiere sudo).
- `editor`: conectar Zed/Cursor/VS Code remoto; `setup herdr|orca`: wiring de harness completos (sección 3).
- `edit <sb> --ingress on|off --auto-pause 30m`, `pause`, `resume`, `fork`, `rm --force` (idempotente).

#### `sandbox fork` — lo esencial (detalle completo en `01-createos.md`)

- Solo se puede forkar un sandbox **pausado**; el hijo es independiente (id, IP, placement) y **auto-resume a `running` por defecto**.
- El snapshot incluye **disco + memoria (RAM) + estado de CPU**; discos S3 no se heredan.
- Regla operativa de los docs: esperar `paused` (`wait_until_paused`) antes de forkear, porque el estado puede quedarse pegado.
- El hijo **cuenta al cupo de concurrentes** (y los pausados también).

### 2.6 Ejemplos copiables (los más útiles)

```bash
# One-shot
createos sandbox create --shape s-1vcpu-1gb --name my-box --rootfs devbox:1 --auto-pause 30m
createos sandbox exec my-box -- uname -a
createos sandbox exec my-box --stream -- pip install -r requirements.txt

# Público para demo
createos sandbox create --shape s-2vcpu-2gb --ingress --auto-pause 1h

# Sync + tunnel (dev loop)
createos sandbox sync my-box --local ~/work/project --remote /root/work --exclude node_modules --exclude .env
createos sandbox tunnel my-box --local 8080 --remote 8000

# Proceso largo reatacable
createos sandbox process start my-box -- python -m http.server 8000
createos sandbox process attach my-box <proc-id>
createos sandbox process stop my-box <proc-id> --grace 1s

# Snapshot → clones (patrón KISS)
createos sandbox pause base
createos sandbox get base                     # confirmar status: paused
createos sandbox fork base --name clon-1
createos sandbox resume base

# Hogar: pausar todo lo pausable y limpiar
createos sandbox list --status paused --quiet | xargs createos sandbox rm --force

# JSON + jq (auto-json en pipe)
createos sandbox list | jq '.[] | {id, name, status}'
createos sandbox get my-box --output json | jq '.status'
```

### 2.7 Comportamientos y topes del sandbox (para tener a mano)

- **Time to interactive:** ~210 ms mediana / ~250 ms p95 (create + primer comando) — medir en el evento.
- `exec` bufferiza salida topada en **1 MiB** (usar streaming para más). Procesos manejados: retención **1 MiB/proceso, 32 MiB/sandbox** (se descarta lo más viejo).
- **Sin tope de vida**: corre hasta destroy/pause/auto-pause. **Auto-pause apagado por defecto**; `auto_pause_after_seconds` 60–86.400.
- **Destroy idempotente**; llamarlo en `finally`; no confiar en auto-pause como limpieza.
- Envs: **64 claves, 4 KiB por valor, 64 KiB total, write-only**; overrides por exec cambian valores declarados pero no agregan claves nuevas.
- Uploads (API): hasta **10 GiB**; en la práctica CLI+buffer+timeouts imponen menos. Retención de banda: **50 GiB/sandbox** (ampliable).
- **Pausado factura memoria + storage** (no vCPU). Concurrentes no-destruidos cuentan al cupo.
- Regiones: `eu` o `us` (deben coincidir con el control plane).

---

## 3. Plugins de agentes

### 3.1 Modelo mental — cinco formas de conectar un agente

Fuente: `createos.sh/docs/Sandbox/Integrations/Overview` (17-oct-2026).

1. **Agente local, sandbox como herramienta** (Claude Code, Codex, OpenCode): el agente vive en tu máquina y decide cuándo mandar trabajo al box.
2. **Agente local con herramientas remotas** (Pi con `--inside-createos-sandbox`): los built-ins (bash/read/write/edit/ls/find/grep) operan dentro del box; el agente "no ve" tu filesystem.
3. **Agente dentro del sandbox** (Herdr, Orca): el proceso del agente corre en la microVM y lo manejas desde un pane/workspace local. Dos juegos de credenciales: las tuyas (crear el box) y las del agente (dentro del box).
4. **Reemplazo de capas** (DeepSeek Harness): sustituye `ctx.fs` y `ctx.subprocess` completos; todo lo que construye encima corre remoto sin saberlo.
5. **Swap de provider** (AgentBox): AgentBox ya corre agentes en boxes; el plugin cambia el box por una microVM.
- **Sin agente** (n8n, Langflow): automatizaciones que ejecutan código no confiable; el paso de workflow es el que se aísla.

### 3.2 Tabla comparativa (Overview + repo `createos-plugins`)

| Integración | Agente corre | Cómo llega al sandbox | Motor |
|---|---|---|---|
| Claude Code | Local | 18 slash commands + skill | CLI (driver `cos`) |
| Codex | Local | Skill que enseña el CLI | CLI (driver `cos`) |
| OpenCode | Local | 33 tools `sandbox_*` (docs) / 54 en V2 (repo) | CLI |
| Pi | Local | 34 sandbox tools + 7 reemplazos built-in (41) | CLI |
| Herdr | **En el sandbox** | 1 pane = 1 sandbox, PTY | CLI (+ `herdr`) |
| Orca | **En el sandbox** | 1 workspace = 1 microVM, SSH | CLI |
| DeepSeek Harness | Local | `ctx.fs` + `ctx.subprocess` reemplazados | **SDK TS**, no CLI |
| AgentBox | **En el sandbox** | Provider plugin, por box | API + websocket, no CLI |
| n8n | — | Nodo de workflow, 1 comando | **REST API** |
| Langflow | — | Backend, nodo de canvas o flow completo | **REST API**, Python |

**Mecánica común (la parte crítica):** todos menos DSH/n8n/Langflow/AgentBox **shell out al CLI `createos`** y **no guardan credenciales propias** — usan la sesión del CLI. Por eso: se instala/actualiza el CLI (los plugins lo hacen solos si falta, salvo `COS_NO_AUTOINSTALL=1`), y `createos login` (o `CREATEOS_API_KEY`) habilita a todos. Si no hay sesión y hay `tmux`, los plugins inician `createos login` en una sesión oculta para abrir el navegador (independiente de Claude/Codex: detalle del repo).

**El driver `cos`** (Claude Code y Codex) envuelve al CLI con lo aburrido ya resuelto: stage del directorio (excluye `.git`, `node_modules`, `target`, `.venv`…), egress restringido, tolerancia a cortes de red (comando detached + heartbeat + reattach), y auto-destroy. Verbos: `cos offload` (stage→run→pull→destroy), `cos up/run/down`, `cos pause/resume`, `cos auth`, y presets de egress `-p python-uv|rust-cargo|npm|github` + `-e host` extras. `cos install` lo symlinkea a `~/.local/bin/cos`. Estado por repo en `${XDG_CACHE_HOME:-~/.cache}/createos-sandbox` (override `COS_STATE_DIR`); solo toca boxes propios (`cos-*`).

### 3.3 Integración por integración

#### Claude Code — la más completa (y la que usarás en el build)

- **Marketplace/plugin:** marketplace `createos`; plugin `createos-sandbox`; comandos namespaced `/createos-sandbox:<verbo>`.
  - Docs oficiales (17-oct): `/plugin marketplace add NodeOps-app/createos-claude-plugins` + `/plugin install createos-sandbox@createos`.
  - Repo README (main): `/plugin marketplace add NodeOps-app/createos-plugin`. **Discrepancia de nombre; probar y anotar cuál responde.**
- **Instala:** CLI si falta; login por tmux si hace falta. Claude Desktop (Code tab, entorno Local) también lo soporta.
- **One-shot:** `offload <dir> <cmd>` (flags: `-o` pull artefactos, `-p` preset egress, `-e` host extra, `-E` sin restricción explícita, `-x` exclude, `-s` shape, `-K` conservar box si falla), `fanout <dir> <cmd1> <cmd2...>` (un box por comando, en paralelo), `shell` (interactivo — Claude te lo devuelve para que lo corras tú).
- **Box reutilizable:** `up` (crea/reusa por repo; `-a` adopta un box preexistente y nunca lo destruye `down`), `run <cmd>`, `sync`, `status`, `down`.
- **Networking:** `tunnel`, `expose` (URL pública — sin auth delante: la URL es lo único que protege), `unexpose`, `cluster up <N>` (nombres FQDN), `vpn`.
- **Storage/snapshots:** `disk create|attach|detach|ls|show|rm`, `template submit|ls|show|logs|rm`, `fork` (independiente, sobrevive `down`, cuenta al cupo, no hereda discos), `pause`/`resume`.
- **Defaults:** shape `s-1vcpu-1gb` (offload/fanout/shell) y `s-2vcpu-2gb` (`up`); rootfs `devbox:1`; egress sin restringir; auto-pause 30 min.
- **Qué añade a la sesión:** skill `using-createos-sandbox` (cuándo offload: builds pesados, código no confiable, matrices de tests, clean rooms) + 2 hooks: `SessionStart` (resuelve ruta del driver) y `PreToolUse` (sugiere offload al ver `npm ci`, `cargo build`, `pytest`, `make`…; se apaga con `COS_NO_HINT=1`; nunca bloquea).
- **Límites (docs):** banda 50 GiB/box; clusters ≤8; envs 64/4 KiB/64 KiB; upload API ≤10 GiB; templates single-stage (1 `FROM`, sin `COPY`/`ADD`, ≤64 KiB, 2 builds concurrentes); swap best-effort (devbox:1 no puede hoy → build OOM ⇒ shape mayor); concurrencia del plan (pausados cuentan).
- **Quota observada (repo, no política publicada):** API keys externas mostraron **2 boxes simultáneos** + tope diario; el exceso hace cola en `fanout`/`cluster`. Con tu `free-plan` (1 concurrente) el paralelismo real es 1 hasta upgrade.

#### Codex

- Instalación: `codex plugin marketplace add NodeOps-app/createos-claude-plugins` + `codex plugin add createos-sandbox-codex@createos` (docs) — el README usa `NodeOps-app/createos-plugin` y `--marketplace createos`. **Discrepancia de nombre.**
- Sin tools custom: una **skill** (`using-createos-sandbox`) que enseña cuándo y cómo usar el CLI, + hook de sesión que resuelve el driver `cos`, + el mismo driver.
- Egress igual a Claude Code (presets + `-e`); comandos `cos offload/up/run/pause/down/auth`.
- Codex Desktop comparte `~/.codex` con el CLI: instalar desde terminal es lo más simple.

#### OpenCode

- **Package:** `@createos/opencode`. Docs: instalar con `opencode plugin @createos/opencode --global`; **33 tools** `sandbox_*`.
- **Variante V2 (repo main):** plugin nativo V2 con **54 tools** (incluye `sandbox_offload`, `sandbox_fanout`, read/write/edit/patch/glob/grep remotos, procesos, desktop, screenshot) que se instala desde un checkout (`bun install --cwd packages/opencode-plugin` + `"plugins": ["./packages/opencode-plugin"]` en `opencode.jsonc`). Con opciones `mode: "remote"` y `sync: "once"` las tools shell/file corren contra un proyecto copiado.
- Comportamiento (docs): **no reemplaza** bash/read/write locales; agrega tools paralelas; sandbox **lazy** (primer `sandbox_*` call) y **se destruye cuando se borra la sesión**; working dir `/root/workspace`; ingress público habilitado.
- Config por env: `CREATEOS_ENABLED` (on/off), `CREATEOS_SHAPE` (default `s-2vcpu-2gb`), `CREATEOS_ROOTFS` (**si no se define usa el default del CLI = alpine; conviene `devbox:1`**), `CREATEOS_NETWORKS` (lista).
- `sandbox_sync`: sin exclusiones propias — **pasa excludes** (`.env`, `node_modules`, build output). `sandbox_exec` exige sandbox ID → pedir `sandbox_info`/`sandbox_list` primero. `sandbox_vpn_up` es advisory (sudo).
- Grupos (33): Lifecycle 8, Config 5, Ports/sync 3, Networks 6, Disks 6, Device VPN 5.
- **Esta sesión corre en OpenCode** → este plugin es candidato directo para que *yo* ejecute trabajo en sandboxes cuando lo pidas explícito ("corre esto en el sandbox…").

#### Pi

- **Package:** `@createos/pi`; instalación `pi install git:github.com/NodeOps-app/createos-claude-plugins` (docs) — README usa `.../createos-plugin`. **Discrepancia.**
- Dos modos: tool-only (default) u **`--inside-createos-sandbox`** (docs) / `--inside-sandbox` (README) → los 7 built-ins se reemplazan y todo corre en `/root/workspace`.
- Flags (con el flag de activación): `--createos-shape` (default `s-2vcpu-2gb`), `--createos-rootfs`, `--createos-network`, `--createos-sync-once`, `--createos-watch` (mutuamente excluyentes), `--createos-avoid-git-ignore`.
- 41 tools (7 reemplazos + 34 nuevos) incluido `sandbox_fanout` (**hasta 3 escenarios en paralelo**, cada uno su box; escenario con puerto → servicio con URL pública y health-check; box destruido al terminar, incluso en error).
- Comandos: `/sandbox`, `/network`, `/device`. Ciclo de sesión: sesión **persistida** deja el box corriendo (imprime cómo limpiarlo); **efímera** lo destruye al salir. Syncs nunca tocan home/root/`.ssh`, `.aws`, `.gnupg`, `.kube`, `.docker`.

#### Herdr (agente dentro del sandbox)

- Plugin `createos.sandbox`; corre Claude Code, Codex, OpenCode, Pi o Cursor **dentro** del box y adjunta su PTY a un pane de Herdr. 1 pane ↔ 1 sandbox.
- **Requiere:** Herdr ≥ 0.7.5, Bun, git worktree. Setup: `createos sandbox setup herdr` (o `--doctor`), manual: `herdr plugin install NodeOps-app/createos-claude-plugins/packages/herdr-plugin`.
- Al iniciar: crea sandbox, sube el worktree (vía git), commit base, instala el agente, arranca PTY. Provisioning ~20 s. Si algo falla tras crear el box → lo borra.
- `config.json` del plugin: `agent` (default `claude-code`), `shape` (`s-2vcpu-4gb`), `rootfs`, `autoPause` (30m), `remoteRoot` (`/workspace`), `egress`, `excludes`, `syncExcludes`. Claves desconocidas = error. **No poner tokens ahí.**
- Upload filtrado: lo que git conoce − excludes − deny-list de credenciales (`.env` salvo plantillas, `.ssh`, `.gnupg`, credenciales cloud, `.netrc`, `.npmrc`, `.pypirc`, `.git-credentials`, claves, tfstate). Es red de seguridad por nombre, no por contenido.
- **Known issues:** CLI ≤ v0.0.24 rompía pause/resume; la resolución de sandbox del CLI escanea solo las primeras **200 filas** de tu lista (nos afectaría con muchísimos boxes). Sync con Mutagen (primera vez descarga).

#### Orca (agente dentro del sandbox)

- Repo propio: `NodeOps-app/createos-orca-plugin` (Orca exige plugin en la raíz del repo, sin symlinks → no puede vivir en el monorepo). Install: `createos sandbox setup orca` o Settings→Plugins→Install from git URL `https://github.com/NodeOps-app/createos-orca-plugin.git#v0.1.0`.
- "Run on: Per-Workspace Environment > CreateOS Sandbox". `CREATEOS_AGENTS=claude,codex` instala agentes en el box. Requiere remote git del proyecto (match de identidad). **Suspend/resume no soportados aún.**

#### DeepSeek Harness

- Package `@nodeops-createos/dsh-createos` (Node `^22.19` o `>=24`). Reemplaza `ctx.fs` (read/write/edit/glob/search, escrituras atómicas) y `ctx.subprocess` (bash one-shot + esperas de procesos manejados) + PTYs; ambos sobre **un mismo sandbox**.
- **No usa el CLI**: SDK + `CREATEOS_SANDBOX_API_KEY`, `CREATEOS_SANDBOX_SHAPE` (obligatorias), `CREATEOS_SANDBOX_BASE_URL` y `CREATEOS_SANDBOX_ROOTFS` (opcionales). `createos login` no influye.
- **Sandbox vive 5 min por defecto** (`lifetimeMs` configurable); se destruye al descargar el plugin; workspace **no** se copia (las rutas deben existir en el box); un runtime = un sandbox por proceso web. Límites: journal de output acotado; ops ambiguas (input/resize/signal…) nunca se reintentan.

#### AgentBox

- `npm install -g @madarco/agentbox @nodeops-createos/agentbox` + `agentbox plugin add @nodeops-createos/agentbox` + `agentbox create --provider createos`. Requiere AgentBox con soporte de provider plugins y Node ≥20.10.
- Key: prompt en primer `create`, o `CREATEOS_API_KEY`, o `~/.agentbox/secrets.env` (en ese orden). **No usa CLI**; websocket autenticado en vez de SSH. Default box: 2 vCPU / 2 GB / 20 GB.
- Pause/resume nativo (pause ~2 min por archivado; despertar ~15 s). Sin checkpoints (CreateOS aún no tiene snapshot compatible para AgentBox → lo reporta como no soportado). Sin `prepare` obligatorio (valida credenciales).

#### n8n

- Nodo comunitario `@createos/n8n-nodes-createos` (repo propio). Credencial **CreateOS API** dentro de n8n (no CLI): crear/gestionar sandboxes, ejecutar comandos, transferir archivos, templates/redes/discos desde workflows. Fuente: Overview + README del monorepo.

#### Langflow

- `langflow-sandbox-createos` (Python, pip; corre **dentro** del server Langflow). Tres superficies: endurecer el Python Interpreter de un flow existente, nodo "CreateOS Sandbox" para cablear a mano (con reuso de guest y retorno de archivos), o ejecutor que corre el flow graph completo en la microVM. Lee `CREATEOS_SANDBOX_API_KEY` del entorno; directo contra REST (httpx). Única integración en Python del monorepo.

### 3.4 Cuál elegir (y por qué importa poco para KISS)

- **Para construir hoy:** ya usas Claude Code para el build (`06-prompts-construccion.md`) → el plugin de Claude Code te da `offload`/`fanout` para builds pesados y `up/run` como dev loop remoto. Alternativa: el plugin de OpenCode (esta sesión) si prefieres dirigirlo a mí.
- **Para KISS:** el orquestador **no necesita ningún plugin** — usa el CLI o el SDK directamente. Los plugins son para los *agentes de código* que construyen, no para el runtime del proyecto.
- Ojo cuota: cualquier plugin que crees **cuenta contra el mismo cupo** (Free = 1 concurrente). Durante el build, no dejes boxes vivos mientras el demo forkea.

### 3.5 ¿Y Hermes o Devin? — sin integración nativa (verificado 17-oct-2026)

Ninguno de los dos está en la lista oficial (los 10 plugins de §3.2), entre los clientes soportados del MCP de la plataforma (Cursor, VS Code Copilot, Claude Code, Gemini CLI/Code Assist, Windsurf, OpenCode, Zapier, ElevenLabs) ni como repo propio en la org `NodeOps-app`. Lo que sí hay son puentes indirectos:

**Hermes** (el de esta máquina: Hermes Agent `NousResearch/hermes-agent`, local v0.22.2):

- **Trae cliente MCP incorporado** (stdio y HTTP, con filtros `tools.include/exclude` por servidor — config en `~/.hermes/config.yaml` o `hermes mcp add`). Eso permite colgarle a mano el **MCP de la plataforma** de CreateOS (`api-createos.nodeops.network/mcp`; 73 tools de proyectos/deploys/analytics — **no toca sandboxes**). Aunque Hermes no está en la lista de clientes "soportados", es un cliente MCP estándar.
- **Sandbox no tiene MCP** (ni para Hermes ni para nadie): la vía es un **skill de Hermes sobre el CLI** `createos` (ya autenticado aquí) o REST directo (precedente: Langflow hace exactamente REST con httpx). Todos los plugins oficiales son superficies delgadas sobre el mismo CLI/SDK → un skill propio queda estructuralmente idéntico a lo oficial.
- Terceros: **Swytchcode** anunció su integración con CreateOS (5-oct-2026) y lista a Hermes entre los frameworks compatibles (junto a OpenAI Agents SDK, LangGraph, CrewAI…). Runtime externo, no plugin de CreateOS; profundidad real **NO VERIFICADO**.

**Devin** (Cognition):

- **Acepta MCP servers custom** (stdio/SSE/HTTP; Customize → MCPs) → mismo puente que Hermes para el MCP de la **plataforma** (deploys). No está entre los clientes soportados; sin probar.
- **Sandbox**: Devin ejecuta shell en su propia VM → instalar ahí el CLI `createos` + `CREATEOS_API_KEY` (o REST/SDK). Sin docs ni plantilla de CreateOS; **NO VERIFICADO**.
- Outposts (enterprise): patrón de correr `devin worker` en infraestructura propia (Cloudflare y CoreWeave publican guías); CreateOS no publica plantilla → DIY completo.

Práctico: para el hackathon no cambia nada (KISS usa CLI/SDK directo, no plugins). Si quieres Hermes operando sandboxes, el camino corto es un skill sobre el CLI — no esperar soporte nativo.

---

## 4. CreateOS Java SDK

### 4.1 Datos del paquete

| Campo | Valor |
|---|---|
| Coordenadas | `sh.createos:createos-java-sdk` (**Maven Central**, sin token ni repo extra) |
| Última versión | **0.1.2** (2026-09-21) — CHANGELOG del repo + Maven Central |
| Licencia | MIT |
| Requisitos | **Java 17+**, Maven 3.9+ (CI compila 17/21/25/26) |
| Dependencias runtime | Jackson (`databind` + `datatype-jsr310`) |
| Transporte | `java.net.http.HttpClient` del JDK (sin deps extra) |
| Repo | `github.com/NodeOps-app/createos-java-sdk` |
| Javadocs | `mvn javadoc:javadoc`; se publican como artifact en `mvn verify` |

Historia (CHANGELOG): 0.1.0 inicial (16-sep-2026, primeros ejemplos); 0.1.1 rebrand de coordenadas `network.nodeops.*` → `sh.createos.*` y **la env var de key pasó a `CREATEOS_API_KEY`** (antes `CREATEOS_SANDBOX_API_KEY`); 0.1.2 access tokens delegados + redacción de tokens en `toString()`.

**Estado local:** Java 21 Temurin instalado y OK; **Maven no está instalado** (`mvn: command not found`) → si el orquestador va en Java, instalar Maven (o usar Gradle) antes de compilar. (No instalar sin avisar; sin sudo probablemente con `~/.local` o SDKMAN.)

### 4.2 Configuración

```xml
<dependency>
  <groupId>sh.createos</groupId>
  <artifactId>createos-java-sdk</artifactId>
  <version>0.1.2</version>
</dependency>
```

```java
CreateOsClient client = CreateOsClient.builder()
    .apiKey(apiKey)                              // o vacío: lee CREATEOS_API_KEY
    .baseUri(URI.create("http://localhost:8080"))// opcional; default = control plane de producción
    .timeout(Duration.ofSeconds(30))             // timeout HTTP default
    // .httpClient(...), .userAgent(...), .retryPolicy(...)
    .build();
```

- `CREATEOS_API_KEY` se lee automáticamente si no se da `apiKey` explícita (explícito gana).
- `CREATEOS_SANDBOX_BASE_URL` sobreescribe la URL del control plane.
- Los modelos de wire son **records inmutables**; errores vía `ApiException` (unchecked); estilo Google Java.

### 4.3 Hello world (compilado y validado por CI del repo)

```java
import sh.createos.CreateOsClient;
import sh.createos.Sandbox;
import sh.createos.model.CreateSandboxRequest;
import sh.createos.model.RunCommandRequest;

public final class HelloWorld {
  private HelloWorld() {}

  public static void main(String[] arguments) {
    CreateOsClient client =
        CreateOsClient.builder().apiKey(System.getenv("CREATEOS_API_KEY")).build();
    Sandbox sandbox =
        client.createSandbox(
            CreateSandboxRequest.builder("s-4vcpu-4gb")
                .rootFileSystem("devbox:1")
                .build());
    try {
      var response =
          sandbox.runCommand(
              RunCommandRequest.of(
                  "sh", "-c", "printf 'Java says hello from %s\\n' \"$(uname -m)\""));
      System.out.print(response.result().standardOutput());
    } finally {
      sandbox.destroy();
    }
  }
}
```

### 4.4 Mapa de capacidades

| Área | API (evidenciada en README/examples) |
|---|---|
| Ciclo de vida | `client.createSandbox(...)`, `sandbox.pause()`, `resume()`, `fork(ForkSandboxRequest.DEFAULT)`, `destroy()`, `refresh()`; waits `waitUntilPaused/Running/Destroyed(Duration)` |
| Comandos | `runCommand(RunCommandRequest.of(cmd, args...))` → `result()` (stdout/stderr/exit); `streamCommand(...)` → stream de eventos `STDOUT/STDERR/EXIT/ERROR/HEARTBEAT` |
| Archivos | `sandbox.files().upload(path, InputStream)`, `download(path)`; `RequestOptions` para timeouts largos por operación (uploads **no se reintentan**) |
| Procesos manejados | `sandbox.processes().create(new CreateProcessRequest(...))`, `waitFor(id, "tree", Duration)`; replay de output, stdin, PTY interactiva, resize, señales, delete de árbol |
| Ingress/URLs | `CreateSandboxRequest...ingressEnabled(true)`, `sandbox.waitForPort("127.0.0.1", 8080, Duration)`, `sandbox.previewUrl(8080)` |
| Redes | `client.networks().create/get/delete`, `sandbox.attachNetwork(id)/detachNetwork(id)`, `members()` (sandboxId, ip, status) |
| Templates | `client.templates().list(PaginationOptions.ALL)`; ejemplo `template` construye rootfs con Docker desde Dockerfile y sigue logs |
| Desktop | `sandbox.computer().mouse()/keyboard()/windows()/screens()`; screenshots, clipboard, noVNC temporal (imagen `desktop:1`) |
| Access tokens | `sandbox.createAccessToken()`, `sandbox.withAccessToken(token)` (handle acotado a ese box), `getAccessToken()`, `rotateAccessToken()`, `disableAccessToken()`; 409 al crear otro token activo; revocación inmediata en la región home |
| Errores | `ApiException`: `statusCode()`, `serviceCode()`, `requestId()`, método, endpoint, body acotado, headers; waits agotados → `IllegalStateException` con estado objetivo y timeout |

### 4.5 Snippets clave

```java
// Streaming (salida larga, sin cortar a 1 MiB)
try (var stream = sandbox.streamCommand(
    RunCommandRequest.of("sh", "-c", "for n in 1 2 3; do echo step $n; sleep 1; done"))) {
  for (var event = stream.receive(); event != null; event = stream.receive()) {
    switch (event.type()) {
      case STDOUT -> System.out.print(event.data());
      case STDERR -> System.err.print(event.data());
      case EXIT -> System.out.println("exit: " + event.exitCode());
      case ERROR -> System.err.println(event.message());
      case HEARTBEAT -> {}
    }
  }
}

// Archivos sin escapes de shell
sandbox.files().upload("/workspace/config.json", new ByteArrayInputStream(bytes));
try (InputStream in = sandbox.files().download("/workspace/config.json")) { /* ... */ }

// Servicio → URL pública
Sandbox box = client.createSandbox(
    CreateSandboxRequest.builder("s-1vcpu-1gb").rootFileSystem("devbox:1").ingressEnabled(true).build());
box.processes().create(new CreateProcessRequest("python3",
    List.of("-m", "http.server", "8080", "--bind", "0.0.0.0"), null, Map.of(), null));
box.waitForPort("127.0.0.1", 8080, Duration.ofSeconds(15));
URI url = box.previewUrl(8080);

// Pause → fork → resume (patrón clon)
sandbox.pause();
sandbox.waitUntilPaused(Duration.ofMinutes(2));
Sandbox clone = sandbox.fork(ForkSandboxRequest.DEFAULT);   // hijo nace running
try {
  sandbox.resume();
  sandbox.waitUntilRunning(Duration.ofMinutes(2));
} finally {
  clone.destroy();
  sandbox.destroy();
}
```

### 4.6 Receta KISS en Java (pseudocódigo de referencia, no código de proyecto)

```java
CreateOsClient client = CreateOsClient.builder().build(); // CREATEOS_API_KEY

// 1) Base con entorno listo → snapshot
Sandbox base = client.createSandbox(
    CreateSandboxRequest.builder("s-1vcpu-1gb").rootFileSystem("devbox:1").build());
base.files().upload("/workspace/tests.py", ...);           // tests + runner (sin keys)
base.pause();
base.waitUntilPaused(Duration.ofMinutes(2));               // regla: nunca forkear sin estar paused

// 2) Ronda: N clones desde el snapshot
List<Sandbox> clones = IntStream.range(0, n)
    .mapToObj(i -> base.fork(ForkSandboxRequest.DEFAULT))  // disco+RAM+CPU; sin discos S3
    .toList();

// 3) En cada clon: escribir candidato y correr tests
var res = clones.get(i).runCommand(RunCommandRequest.of("sh", "-c", "python3 /workspace/run_tests.py"));
//    → leer result().standardOutput() y el exit code; decidir pasa/falla

// 4) Poda y limpieza (SIEMPRE en finally)
clones.forEach(Sandbox::destroy);
base.destroy();
```

Notas para el diseño: el fork **ya trae la memoria** del pausado (procesos/archivos abiertos listos si los preparaste); las keys del LLM quedan en el orquestador (Java) y **no** entran al box; el SDK no hace fork de discos S3; para outputs largos usar `streamCommand`; verificar exit codes explícitamente (el SDK devuelve `result()`, no lanza excepción de negocio).

### 4.7 Ejemplos del repo (compilados con `mvn verify`; ejecución live con opt-in)

`helloworld`, `executionserver` (servidor HTTP de ejecución), `commandstreaming`, `filesandsnapshots` (upload, pause, fork copy-on-write, resume, divergencia de filesystems), `ingresspreview`, `network` (overlay privado completo), `customtemplate` (Dockerfile → template → sandbox con Docker), `managedprocess` (replay, stdin, PTY, resize, señales, árbol), `desktop` (noVNC).

Correr: `mvn install && make test`; los ejemplos se compilan a `target/example-classes` (excluidos del JAR del SDK). `make format` / `make check` para estilo/Checkstyle.

---

## 5. Operación: cuotas, límites y costos

Tabla de planes (control plane, releída 2026-09-08; la misma en `01-createos.md`). **La concurrencia cuenta todo sandbox no-destruido, pausados incluidos**; create sobre el tope → `429` sin cola; el tope diario cuenta creados en 24 h rodantes, destruidos incluidos.

| Plan | Concurrentes | Por día | Max disco | Shape máx |
|---|---|---|---|---|
| **Free (tu plan hoy)** | **1** | 10 | 10 GiB | 1 vCPU / 1 GB |
| Beginner | 5 | 50 | 30 GiB | 4 vCPU / 4 GB |
| Pro | 20 | 200 | 50 GiB | 8 vCPU / 8 GB |
| Enterprise | 30 | 300 | 60 GiB | 8 vCPU / 16 GB |

Otros números clave (docs Limits, 17-oct):

- **Red:** ingress cerrado por defecto (1 URL HTTPS si se habilita); egress **abierto** con lista vacía; reglas por host/ip/cidr; redes overlay opt-in; **50 GiB de banda por sandbox** (ampliable).
- **Vida:** sin tope; auto-pause off (60–86.400 s); pause = snapshot Firecracker (memoria+disco+CPU), no factura vCPU; destroy en `finally`.
- **Envs:** 64 claves / 4 KiB valor / 64 KiB total, write-only. **Regiones:** `eu`/`us`.
- **Precio por segundo (todos los planes):** $0.03616363/vCPU-h + $0.01159025/GiB-RAM-h + $0.0001584/GB-h storage; sin egress. Pausado: memoria+storage. Cuentas nuevas: 500 créditos. (Cálculo del sábado en `01-createos.md`: < $1.)
- Certificaciones ISO 27001 / SOC 2 Type II.

Recordatorio del estado real: tu cuenta es **free-plan** con ~3500 créditos cargados (`11-pre-kickoff-audit.md`) — los créditos **no cambian las cuotas**: cualquier demo con forks en paralelo requiere upgrade (Beginner/Pro) o diseño secuencial. No contratar sin autorización del usuario.

---

## 6. Discrepancias y NO VERIFICADO

1. **Nombres de marketplace/repos inconsistentes entre docs y READMEs** (createos-claude-plugins vs createos-plugin vs createos-plugins). Probar en el evento y anotar el que funcione; los slugs pueden cambiar.
2. **OpenCode: 33 tools (docs) vs 54 tools V2 (repo main)** y dos paths de instalación (`opencode plugin @createos/opencode --global` vs checkout + `opencode.jsonc`). Elegir según la versión de OpenCode instalada.
3. **Pi:** flag de activación `--inside-createos-sandbox` (docs) vs `--inside-sandbox` (README); 41 tools = 7 reemplazos + 34 sandbox (docs) vs "33 tools" (Overview). Verificar con `pi --help` local.
4. **Herdr:** el bug de pause/resume (CLI ≤ 0.0.24) no aplica a v0.0.31; el escaneo de solo 200 filas de sandbox sí podría afectar cuentas con muchos boxes.
5. **Tiempo real de fork: NO VERIFICADO** (docs solo dicen que depende del snapshot/host/carga). Medir en el evento con el primer fork real.
6. **Java SDK joven:** primera publicación sep-2026, repo con 0 stars → superficie estable por diseño (records, CI con ejemplos) pero sin rodaje; probar el hello world antes de confiar el orquestador a él.
7. **Time to interactive ~210 ms mediano / ~250 ms p95**: cifra de docs, medir en vivo.
8. **Quota observada de plugins (2 boxes simultáneos)**: observación del README del monorepo, no política publicada; con free-plan igual manda el tope de 1.

---

## 7. Fuentes

Docs (consultadas 17-oct-2026):

- Integrations Overview — https://createos.sh/docs/Sandbox/Integrations/Overview
- Claude Code — https://createos.sh/docs/Sandbox/Integrations/Claude-Code
- Codex — https://createos.sh/docs/Sandbox/Integrations/Codex
- OpenCode — https://createos.sh/docs/Sandbox/Integrations/OpenCode
- Pi — https://createos.sh/docs/Sandbox/Integrations/Pi
- Herdr — https://createos.sh/docs/Sandbox/Integrations/Herdr
- Orca — https://createos.sh/docs/Sandbox/Integrations/Orca
- DeepSeek Harness — https://createos.sh/docs/Sandbox/Integrations/DeepSeek-Harness
- AgentBox — https://createos.sh/docs/Sandbox/Integrations/AgentBox
- Limits & defaults — https://createos.sh/docs/Sandbox/Limits
- Sandbox Overview — https://createos.sh/docs/Sandbox/Overview
- SDKs Overview (6 lenguajes + links de referencia) — https://createos.sh/docs/Sandbox/SDK/Overview
- REST API — https://createos.sh/docs/Sandbox/REST-API/Overview
- CLI developer hub — https://createos.sh/docs ; producto CLI — https://createos.sh/products/cli

Repos y paquetes (org `NodeOps-app`; los 6 SDKs + CLI + plugins verificados como existentes y activos vía GitHub API, 17-oct-2026):

- CLI — https://github.com/NodeOps-app/createos-cli (README, install.sh)
- Plugins y extensiones — https://github.com/NodeOps-app/createos-plugins (README, packages/)
- SDK TypeScript — https://github.com/NodeOps-app/createos-sandbox-sdk · npm: https://www.npmjs.com/package/@nodeops-createos/sandbox
- SDK Python — https://github.com/NodeOps-app/createos-python-sdk · PyPI: https://pypi.org/project/createos-sandbox/
- SDK Go — https://github.com/NodeOps-app/createos-go-sdk · ref: https://pkg.go.dev/github.com/NodeOps-app/createos-go-sdk
- SDK Rust — https://github.com/NodeOps-app/createos-rust-sdk · ref: https://docs.rs/createos/latest/createos/
- SDK C# — https://github.com/NodeOps-app/createos-csharp-sdk
- SDK Java — https://github.com/NodeOps-app/createos-java-sdk · Maven Central: https://central.sonatype.com/artifact/sh.createos/createos-java-sdk
- ComputeSDK provider — https://github.com/computesdk/computesdk (`@computesdk/createos-sandbox`)

Fuera del ecosistema oficial (contexto §3.5):

- Devin — MCP servers custom — https://docs.devin.ai/work-with-devin/mcp
- Hermes Agent — MCP — https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp · repo https://github.com/NousResearch/hermes-agent
- Swytchcode + CreateOS (blog 5-oct-2026) — https://www.swytchcode.com/blogs/createos-integration-is-now-live-on-swytchcode

Verificación local de hoy (17-oct-2026):

- `createos --help`, `createos version` (v0.0.31), `createos whoami` (free-plan).
- `hermes --version` → Hermes Agent v0.22.2 (2026.9.24); trae cliente MCP incorporado (clave para §3.5).
- `createos sandbox --help`, `createos sandbox create --help`, `createos sandbox setup --help` (herdr | orca).
- `createos sandbox shapes` (11 shapes listados arriba).
- `createos sandbox rootfs` (5 imágenes; default `alpine:3.20`).
- `java -version` → OpenJDK 21.0.5 Temurin (OK); `mvn -version` → no instalado.
