# OmniAgent web

A second frontend for OmniAgent, alongside the existing Streamlit UI
(`omniagent/channels/streamlit_app.py`) -- both talk to the same FastAPI
service over the same four endpoints (`/datasets`, `/ask`, `/resume`,
`/feedback`), so neither gets a capability the other doesn't have.

This lives outside the Python package tree entirely (not under
`omniagent/`, `tests/`, or `scripts/`) so `just lint`/`just test`/CI never
need to know it exists -- see `.gitignore`'s `!web/lib/` block if you're
wondering why `lib/` isn't just gitignored like the Python-side `lib/`
pattern it sits next to.

## Run it

```bash
# from the repo root, with the API already running (just serve)
just web-install   # npm install
just web           # npm run dev, on :3000
```

Or directly:

```bash
cd web
npm install
cp .env.local.example .env.local   # NEXT_PUBLIC_API_URL, defaults to :8000
npm run dev
```

## Checks

```bash
just web-check   # typecheck + lint + vitest, from the repo root
```

`npm test` runs Vitest over `lib/*.test.ts` only -- the pure logic (ask-vs-
resume turn routing, value formatting, and the zod contract schemas
checked against real captured API responses). Component/DOM tests are
deliberately not included: this UI iterates fast, and jsdom + Testing
Library + mocking `react-vega` would cost real time for tests likely to
be rewritten within a week.

## Stack

Next.js 16 (App Router) + TypeScript (strict) + Tailwind v4 + shadcn/ui +
`react-vega` (the backend's `ChartSpec` is Vega-Lite-native, so charts
render directly, no translation layer) + `next-themes` (dark mode) + zod
(runtime-validated API responses, so a backend contract drift surfaces as
a readable error instead of a blank screen).

## Docker

```bash
docker compose up --build   # from the repo root -- brings up api, ui, and web together
```

`NEXT_PUBLIC_API_URL` is baked into the client bundle at build time, so it
must point at whatever the *browser* can reach (`http://localhost:8000`,
published by the `api` service), never the compose-internal `http://api:8000`
hostname the Streamlit `ui` service uses -- that only resolves inside the
compose network, not on the host where the browser runs.
