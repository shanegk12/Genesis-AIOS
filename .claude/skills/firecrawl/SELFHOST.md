# Running real Firecrawl locally (the Docker path)

The local engine in `fetch.py` needs nothing. This file is the upgrade: the
actual Firecrawl server from `github.com/firecrawl/firecrawl`, running on this
machine, in containers. Shane wants this for the isolation — a scraper pointed at
the open web is running other people's markup through a browser, and a container
is a better place for that than the host Python.

## What it costs

Not yet installed on this machine, as of 2026-07-30:

| Prerequisite | Status | Cost |
|---|---|---|
| WSL2 | **not installed** | `wsl --install`, admin, **requires a reboot** |
| Docker Desktop | **not installed** | ~2 GB install (Win 11 Home needs WSL2) |
| Firecrawl images | — | ~5 GB built (API, Redis, Postgres, Playwright) |

Node 24.15 is present. pnpm is not (only needed to run from source, not Docker).
177 GB free on C:, so space is not the constraint. The reboot is.

## Setup

```bash
wsl --install                       # admin PowerShell, then REBOOT
# install Docker Desktop, launch it once, confirm `docker info` works

git clone https://github.com/firecrawl/firecrawl.git D:\firecrawl
cd D:\firecrawl
```

Create `.env` in the repo root. Minimum viable, no auth, no cloud:

```
PORT=3002
HOST=0.0.0.0
USE_DB_AUTHENTICATION=false
BULL_AUTH_KEY=CHANGEME
```

Then:

```bash
docker compose build
docker compose up
```

- API: `http://localhost:3002`
- Queue dashboard: `http://localhost:3002/admin/CHANGEME/queues`

Smoke test:

```bash
curl -X POST http://localhost:3002/v2/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://docs.firecrawl.dev","formats":["markdown"]}'
```

## Pointing the skill at it

Nothing to change. `--backend auto` probes `http://localhost:3002` on every run
and uses it when it answers. Override the address with `FIRECRAWL_API_URL`, or
force one engine with `--backend local` / `--backend firecrawl`.

The output files are identical in both modes, and the backend used is written
into every page's frontmatter, so a `references/web/` folder built across both is
still readable.

## What self-hosting does NOT buy

Straight from their [self-host docs](https://docs.firecrawl.dev/contributing/self-host).
Worth knowing before spending a reboot on it:

- **No Fire-engine.** That is the IP-block handling, proxy rotation, and bot
  detection. It is cloud-only. A self-hosted instance fails on protected sites
  the same way the local Python engine does.
- **`/agent` and `/browser` are unsupported** self-hosted.
- **`/search` needs SearXNG** stood up separately (`SEARXNG_ENDPOINT`).
- **JSON format, `/extract`, and summaries need an LLM key** (`OPENAI_API_KEY`,
  or Ollama via `OLLAMA_BASE_URL`, experimental). Not free, not included.
- Scraping methods reduce to **fetch and Playwright** — which is exactly what
  `fetch.py` already does.

So the honest trade: containers buy isolation and the real Firecrawl job queue.
They do not buy better extraction than we already have. Do it for the sandbox,
not for the results.

## Optional env vars

```
OPENAI_API_KEY=          # JSON format, /extract, summary
OLLAMA_BASE_URL=         # local LLM instead, experimental
SEARXNG_ENDPOINT=        # enables /search
PROXY_SERVER=            # plus PROXY_USERNAME / PROXY_PASSWORD
PLAYWRIGHT_MICROSERVICE_URL=
```

## Cloud, for the record

Not our path — Shane ruled out the API and MCP, and the free tier is reportedly
1,000 credits with conflicting reports on whether that is monthly or one-time.
Paid starts at $16/mo (Hobby, 5,000 credits). JSON output adds 4 credits/page.
Noted so nobody re-researches it in three months.

## Licence

Firecrawl is AGPL-3.0. Fine to run internally. It matters if we ever ship a
service built on a modified copy of it — that would need the source published.
We are not doing that; this is a local tool.
