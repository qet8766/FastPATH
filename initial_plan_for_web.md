# FastPATH Web Viewer — Next Phase Plan

Self-hosted web viewer for pathology WSI slides. Custom WebGPU renderer, no CDN, no custom tile server needed (static file serving + client-side index parsing). Initial scope: viewer only (no annotations, no plugins).

---

## Pack V2 Contract

Client code must enforce these invariants before attempting tile reads:
- Magic: `FPLIDX1\0`
- Version: `1`
- Header size: 16 bytes
- Entry size: 12 bytes (`u64 offset` + `u32 length`, little-endian)
- Cols/rows on disk are `u16`
- Row-major entries (`row * cols + col`)
- `length == 0` means missing tile
- Index length must be exactly `16 + cols * rows * 12`
- Offsets should be read as `BigInt` and checked (`offset + length <= pack_size`) before converting to `Number`

---

## Current Baseline (Already Done)

- FastAPI server with slide discovery, metadata endpoint, and static file streaming with Range support.
- Client scaffolding (Vite + React + TS), core algorithms, and unit tests.
- Network parser/fetcher stubs, decode worker stub, and viewer/input stubs.

---

## Remaining Work

### Step A: WebGPU Renderer (Core)

Implement the renderer in `web/client/src/renderer/`:
- Create device, queue, swap chain/context.
- Build pipeline: instanced quad shader → `texture_2d_array` sampling.
- Implement `TileTextureAtlas` with LRU eviction and allocation tracking.
- Define uniforms: viewport transform + per-tile instance data.
- Render loop: single instanced draw per frame.
- WebGL2 fallback when `navigator.gpu` is unavailable.

### Step B: Network Pipeline (Real)

Implement real tile loading in `web/client/src/network/`:
- Fetch all `level_N.idx` on slide open.
- Bounds-check `TileRef` against pack file size.
- Range reads for large packs; full-pack caching for small levels.
- Concurrency limits and cancellation on viewport changes.
- Optional IndexedDB cache for index buffers (keyed by slide hash + metadata timestamp).

### Step C: Scheduler Integration

Replace stubs in `web/client/src/scheduler/TileScheduler.ts`:
- Generation counters for cancellation.
- Cache miss threshold logic.
- Low-res prefetch on open; extended viewport prefetch on pan.
- Fallback tiles during zoom transitions.
- Integrate decode worker + atlas upload.

### Step D: Viewer + Input Wiring

Wire `FastPATHViewer` to the scheduler + renderer:
- On slide open: metadata → indices → low-res prefetch → first render.
- On viewport updates: schedule fetch, decode, upload, render.
- Keyboard, wheel, drag, and momentum scrolling parity with `SlideViewer.qml`.

### Step E: UI Shell

Upgrade `App.tsx` to a functional viewer shell:
- Slide list → open slide.
- Overlay controls (zoom in/out, reset, info).
- Thumbnail minimap and viewport indicator.

---

## Test Additions (Remaining)

Server (already covered):
- Range responses (`206`/`416`) and headers
- `Content-Type` for `.idx`/`.pack`

Client:
- Scheduler integration tests (generation cancellation, fallback selection, cache miss threshold)
- Renderer unit tests for atlas allocation + eviction
- Network bounds checks for `TileRef` vs pack size

---

## Implementation Order (From Here)

| Step | What | Depends on |
|---|---|---|
| A | WebGPU renderer + atlas | None |
| B | Network pipeline real fetch | A or parallel |
| C | Scheduler integration | A + B |
| D | Viewer + input wiring | C |
| E | UI shell | C |

---

## Critical Source Files to Reference

| File | What to port |
|---|---|
| `src/fastpath_core/src/prefetch.rs` | Viewport/prefetch algorithms → `scheduler/*.ts` |
| `src/fastpath_core/src/scheduler.rs` | Generation counter, cache architecture → `TileScheduler.ts` |
| `src/fastpath/ui/app.py` | Slide load order, cache miss threshold, fallback logic |
| `src/fastpath/ui/qml/components/SlideViewer.qml` | Zoom-toward-cursor, momentum scrolling |
| `src/fastpath/config.py` | Constants |

---

## Dependencies

**Server:** `fastapi`, `uvicorn`

**Client:** `typescript`, `vite`, `react`, `react-dom`, `@webgpu/types`, `vitest`
