# Caddy Reverse Proxy Migration (Mandatory SPA + `/slides`)

Goal: Replace the web viewer’s single-process Hypercorn (HTTPS/HTTP3 + static files) with a **mandatory** Caddy front door.
After this migration, browsers talk only to Caddy; FastAPI serves **dynamic API only**.

## Target Architecture

```
Browser
  |
  v
Caddy (TLS + HTTP/3, static + proxy)
  ├─ /api/*                -> reverse_proxy -> FastAPI (uvicorn) on localhost
  ├─ /slides/{slide_id}/*  -> file_server   -> junction_dir/{slide_id}/...
  └─ /*                    -> file_server   -> dist/ (SPA, try_files to /index.html)
```

## Key Constraint: Slide IDs

Slide IDs are computed as the first 12 hex chars of `sha1(str(path))` where `path` is the `.fastpath` directory path
(`web/server/routes/slides.py::_slide_id_for_path`).

Caddy cannot compute this mapping dynamically, so we expose a filesystem layout Caddy *can* serve:

- FastAPI builds the slide index and creates Windows directory junctions:
  - `junction_dir/{slide_id}` (junction) -> `C:\...\some_slide.fastpath\`
- Caddy serves `/slides/{slide_id}/...` directly from `junction_dir`.

This keeps `/slides/...` high-performance (Caddy handles Range requests natively) and keeps FastAPI simple.

## Environment Variables

| Variable | Default | Used by | Description |
|---|---|---|---|
| `FASTPATH_WEB_SLIDE_DIRS` | `cwd` | FastAPI | Semicolon-separated roots to scan for `*.fastpath` dirs |
| `FASTPATH_WEB_JUNCTION_DIR` | `.fastpath_junctions` | FastAPI + Caddy | Directory where `{slide_id}` junctions are created |
| `FASTPATH_WEB_DIST_DIR` | `web/client/dist` | Caddy | SPA build output directory |

## Status

All migration steps are complete.

## Verification Checklist

- `GET https://localhost/api/slides` returns list
- `GET https://localhost/api/slides/{id}/metadata` returns metadata
- `GET -I https://localhost/slides/{id}/tiles/level_0.pack` shows `Accept-Ranges: bytes`
- `Range: bytes=0-1023` returns `206` via Caddy
- SPA loads at `https://localhost/` and client-side routes work
- Playwright e2e passes (starts uvicorn + caddy, validates SPA + API + Range)
