# GitHub Pages Site + README — Design

**Date:** 2026-08-14
**Scope:** Professional README, static landing page, in-browser playable Go build via
pygbag, and GitHub Actions auto-deploy to Pages.

## Decisions (agreed)
- The pygbag web build is produced by **GitHub Actions (Python 3.11+)**, since local
  Python is 3.9 (pygbag prefers 3.11+). Local pygbag install is only a smoke test.
- User will enable **Settings → Pages → Source: GitHub Actions** once (manual, cannot be
  scripted). After that, pushes to `main` auto-deploy.
- Desktop play must keep working: `main.py` becomes asyncio-compatible so the same file
  runs in desktop (`python3 main.py`) and browsers (pygbag).

## Deliverables
1. `README.md` — professional rewrite (overview, features, run, controls, AI, testing,
   architecture, tech stack, screenshots).
2. `index.html` — static landing page (hero, features, "Play in browser", screenshots
   `arc.png`/`arch.png`, how-to-run, footer).
3. `main.py` — pygbag/asyncio compatible game loop (desktop unchanged behavior).
4. `.github/workflows/deploy.yml` — build with Python 3.11 + pygbag, deploy `dist/web`
   to Pages.

## GitHub Actions details
- Trigger: push to `main`.
- Steps: checkout; setup-python 3.11; `pip install pygame pygbag`; `python -m pygbag main.py`
  (outputs `dist/web`); configure-pages; upload-pages-artifact; deploy-pages.
- `GITHUB_TOKEN` permissions: `contents: read`, `pages: write`, `id-token: write`.

## Out of scope
- No scaffolding framework; hand-written static `index.html`.
- Landing page links the deployed game (same repo Pages root).