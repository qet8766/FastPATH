# Tips for FastPATH Web Viewer

This is a running checklist of the real-world gotchas we hit while wiring the web viewer.

## Server and Client Startup

- The FastAPI server does **not** serve a root HTML page. `/` returns 404 by design.
- The UI is served by Vite at `http://127.0.0.1:5173`.
- The API lives at `http://127.0.0.1:8000`.
- The client must know the API base:
  ```powershell
  $env:VITE_FASTPATH_API_BASE="http://127.0.0.1:8000"
  cd web\client
  npm run dev
  ```
- If you see `Unexpected token '<'`, the frontend is hitting the Vite server for `/api/slides` and getting HTML instead of JSON.

## Slides Must Be Preprocessed

The server only lists `.fastpath` directories. Raw `.svs` files are ignored.

Preprocess a slide:
```powershell
uv run python -m fastpath.preprocess C:\path\to\slide.svs -o C:\path\to\slides
```

Expected output:
```
slide.fastpath/
  metadata.json
  thumbnail.jpg
  tiles/level_*.idx
  tiles/level_*.pack
```

## CORS

If the UI says `Failed to fetch`, the usual culprit is CORS. The server now enables:
- `http://127.0.0.1:5173`
- `http://localhost:5173`

If you move the client to another port, add it to CORS in `web/server/main.py`.

## Useful Checks

- API slides list:
  ```
  http://127.0.0.1:8000/api/slides
  ```
- Slide metadata:
  ```
  http://127.0.0.1:8000/api/slides/<hash>/metadata
  ```

## Common Errors

- `Slide dir does not exist`:
  - The `FASTPATH_WEB_SLIDE_DIRS` env var is pointing to a wrong path.
- `Unexpected token '<'`:
  - API base not set; client is calling Vite dev server instead of FastAPI.
- `Failed to fetch`:
  - CORS issue or FastAPI server not running.

## Dev Commands

Server:
```powershell
$env:FASTPATH_WEB_SLIDE_DIRS="C:\path\to\slides"
uv run --group dev python -m web.server.main
```

Client:
```powershell
$env:VITE_FASTPATH_API_BASE="http://127.0.0.1:8000"
cd web\client
npm run dev
```
