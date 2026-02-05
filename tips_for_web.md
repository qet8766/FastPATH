# FastPATH Web Tips (Caddy Single-Origin)

## Quick Start (Automated)

```powershell
# Production mode (built SPA)
.\web\start-web.ps1

# Development mode (HMR via Vite)
.\web\start-web.ps1 -Dev

# With custom paths
.\web\start-web.ps1 -SlideDir "C:\path\to\slides" -JunctionDir "C:\path\to\junctions"

# Don't open browser
.\web\start-web.ps1 -NoBrowser

# Force rebuild client
.\web\start-web.ps1 -Build

# If port 443 is blocked
.\web\start-web.ps1 -HttpsAddr "https://localhost:8443"
```

Or use the batch file:
```cmd
web\start-web.bat       REM Production mode
web\start-web.bat dev   REM Development mode with HMR
```

Press **Ctrl+C** to stop all services.

## Manual Start (Two Terminals)

If you prefer manual control:

### Terminal A (API)

```powershell
$env:FASTPATH_WEB_SLIDE_DIRS="C:\path\to\slides"
$env:FASTPATH_WEB_JUNCTION_DIR="C:\path\to\junctions"   # optional
uv run --group dev uvicorn web.server.main:app --host 127.0.0.1 --port 8000 --reload
```

### Terminal B (Caddy)

Production (no HMR):
```powershell
cd web/client && npm install && npm run build
$env:FASTPATH_WEB_DIST_DIR="C:\chest\projects\fastpath_web\web\client\dist"
$env:FASTPATH_WEB_HTTPS_ADDR="https://localhost"       # optional (use :8443 if 443 is blocked)
caddy run --config web/Caddyfile
```

Development (HMR):
```powershell
cd web/client && npm install && npm run dev            # Terminal B
caddy run --config web/Caddyfile.dev                   # Terminal C
```

## Browsing

- **Production**: `https://localhost/` (or `:8443` if port 443 is blocked)
- **Development**: `http://127.0.0.1:8080/`

If the browser blocks the HTTPS page, run `caddy trust` once to install the local CA.

## Notes

- Junctions are Windows-only; Caddy serves `/slides/{id}` from `FASTPATH_WEB_JUNCTION_DIR`.
- `FASTPATH_WEB_DIST_DIR` is only needed when serving the built SPA (no HMR).
- If you browse Vite directly on `:5173`, you are bypassing the single-origin model.
