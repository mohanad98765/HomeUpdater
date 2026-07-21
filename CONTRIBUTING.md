# Contributing — المساهمة

HomeUpdater is a proprietary, source-available project (see [LICENSE](LICENSE)) —
external code contributions are not accepted without a prior written agreement.
You are welcome to **file issues** (bugs, ideas) and **report security
vulnerabilities** privately (see [SECURITY.md](SECURITY.md)).

If you have signed an agreement to contribute, follow the workflow below.

## Repository layout

```
02_التطوير/backend      FastAPI + SQLAlchemy (async) backend  (Python 3.11+)
02_التطوير/frontend     Vite + React + TypeScript UI (RTL, 6 languages)
02_التطوير/installer    Inno Setup script + code-signing (sign.ps1)
.github/workflows       CI (tests + lint) and security scans
```

## Backend dev setup

The project uses a **uv**-managed virtualenv (do NOT use pip directly):

```bash
cd 02_التطوير/backend
uv sync
```

Run the quality gate before every commit — all three must pass:

```bash
uv run ruff check app tests      # lint
uv run black --check app tests   # format
uv run pytest -q                 # tests (227+)
```

## Frontend dev setup

```bash
cd 02_التطوير/frontend
npm install
npm run dev      # dev server
npm run build    # production build (bundled into the installer)
```

## Conventions

- **Commits:** Conventional Commits, e.g. `fix(#NN): …`, `feat(#NN): …`.
- **Migrations:** never edit a shipped Alembic revision; add a new one under
  `02_التطوير/backend/alembic/versions/`.
- **Tests:** every bug fix ships with a regression test.
- **No secrets** in the repo; credentials are encrypted at rest at runtime.
