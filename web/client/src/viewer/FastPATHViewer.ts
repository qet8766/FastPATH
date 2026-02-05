import type { SlideMetadata, Viewport } from "../types";
import { fetchMetadata, slideBaseUrl } from "../api";
import { TileScheduler } from "../scheduler/TileScheduler";
import { ViewerState } from "./ViewerState";
import { InputHandler } from "./InputHandler";
import { SlideIndexStore } from "../network/SlideIndexStore";
import { TileNetwork } from "../network/TileNetwork";
import { TileFetchQueue } from "../network/TileFetchQueue";
import { LevelPackFetcher } from "../network/LevelPackFetcher";
import { WebGPURenderer } from "../renderer/WebGPURenderer";
import { TileTextureAtlas } from "../renderer/TileTextureAtlas";

export interface FastPATHViewerOptions {
  container: HTMLElement;
  canvas: HTMLCanvasElement;
  initialViewport: Viewport;
  onViewportChange?: (viewport: Viewport) => void;
}

export class FastPATHViewer {
  private container: HTMLElement;
  private canvas: HTMLCanvasElement;
  private state: ViewerState;
  private scheduler: TileScheduler;
  private input: InputHandler;
  private network: TileNetwork | null = null;
  private fetchQueue: TileFetchQueue | null = null;
  private renderer: WebGPURenderer;
  private atlas: TileTextureAtlas;
  private rendererReady: Promise<void>;
  private rendererError: Error | null = null;
  private resizeObserver: ResizeObserver | null = null;
  private resizeFallback: (() => void) | null = null;
  private metadata: SlideMetadata | null = null;
  private onViewportChange?: (viewport: Viewport) => void;

  constructor(options: FastPATHViewerOptions) {
    this.container = options.container;
    this.canvas = options.canvas;
    this.state = new ViewerState(options.initialViewport);
    this.scheduler = new TileScheduler();
    this.onViewportChange = options.onViewportChange;
    this.input = new InputHandler(this.container, this.state.viewport, {
      onViewportChange: (viewport) => this.updateViewport(viewport),
      getMinScale: () => this.getMinScale(),
    });

    this.atlas = new TileTextureAtlas();
    this.renderer = new WebGPURenderer(this.canvas);
    this.rendererReady = this.renderer
      .init()
      .then(() => {
        this.scheduler.attachRenderer(this.renderer, this.atlas);
      })
      .catch((error) => {
        this.rendererError = error instanceof Error ? error : new Error(String(error));
      });

    this.attachResizeObserver();
  }

  async openSlide(slideId: string): Promise<SlideMetadata> {
    const metadata = await fetchMetadata(slideId);
    const store = new SlideIndexStore(slideBaseUrl(slideId), metadata);
    this.fetchQueue = new TileFetchQueue();
    const fetcher = new LevelPackFetcher(8_000_000, this.fetchQueue);
    this.network = new TileNetwork(store, fetcher);
    await this.network.load();
    this.scheduler.attachNetwork(this.network, this.fetchQueue);
    await this.rendererReady;
    if (this.rendererError) {
      throw this.rendererError;
    }
    this.metadata = metadata;
    this.state.setMetadata(metadata);
    this.scheduler.open(metadata);
    await this.scheduler.bootstrapLevel(0);
    this.fitToSlide();
    return metadata;
  }

  updateViewport(viewport: Partial<Viewport>): void {
    this.state.updateViewport(viewport);
    const merged = this.state.viewport;
    this.input.updateViewport(merged);
    this.scheduler.updateViewport(merged);
    this.onViewportChange?.(merged);
  }

  getViewport(): Viewport {
    return this.state.viewport;
  }

  getMetadata(): SlideMetadata | null {
    return this.metadata;
  }

  zoomBy(factor: number, anchorX = 0.5, anchorY = 0.5): void {
    const viewport = this.state.viewport;
    const nextScale = Math.max(this.getMinScale(), Math.min(1.5, viewport.scale * factor));
    const effectiveFactor = nextScale / viewport.scale;
    const newWidth = viewport.width / effectiveFactor;
    const newHeight = viewport.height / effectiveFactor;
    const focusX = viewport.x + viewport.width * anchorX;
    const focusY = viewport.y + viewport.height * anchorY;
    const newX = focusX - newWidth * anchorX;
    const newY = focusY - newHeight * anchorY;
    this.updateViewport({
      ...viewport,
      x: newX,
      y: newY,
      width: newWidth,
      height: newHeight,
      scale: nextScale,
    });
  }

  centerOn(x: number, y: number): void {
    const viewport = this.state.viewport;
    const newX = x - viewport.width / 2;
    const newY = y - viewport.height / 2;
    this.updateViewport({
      ...viewport,
      x: newX,
      y: newY,
      velocityX: 0,
      velocityY: 0,
    });
  }

  fitToSlide(): void {
    if (!this.metadata) {
      return;
    }
    const rect = this.canvas.getBoundingClientRect();
    const widthPx = rect.width > 0 ? rect.width : 1024;
    const heightPx = rect.height > 0 ? rect.height : 768;
    const scaleX = widthPx / this.metadata.dimensions[0];
    const scaleY = heightPx / this.metadata.dimensions[1];
    const scale = Math.max(Math.min(scaleX, scaleY), 0.01);

    const width = widthPx / scale;
    const height = heightPx / scale;

    this.updateViewport({
      x: 0,
      y: 0,
      width,
      height,
      scale,
      velocityX: 0,
      velocityY: 0,
    });
  }

  dispose(): void {
    this.scheduler.close();
    this.input.dispose();
    this.network = null;
    this.fetchQueue?.cancelAll();
    this.fetchQueue = null;
    this.resizeObserver?.disconnect();
    if (this.resizeFallback) {
      window.removeEventListener("resize", this.resizeFallback);
      this.resizeFallback = null;
    }
    this.renderer.dispose();
  }

  private refreshViewportSize(): void {
    const rect = this.canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) {
      return;
    }
    const width = rect.width / this.state.viewport.scale;
    const height = rect.height / this.state.viewport.scale;
    this.updateViewport({ width, height });
  }

  private getMinScale(): number {
    if (!this.metadata) {
      return 0.01;
    }
    const rect = this.canvas.getBoundingClientRect();
    const canvasW = rect.width > 0 ? rect.width : 1024;
    const canvasH = rect.height > 0 ? rect.height : 768;
    const largestAxis = Math.max(this.metadata.dimensions[0], this.metadata.dimensions[1]);
    const canvasMin = Math.min(canvasW, canvasH);
    return canvasMin / largestAxis;
  }

  private attachResizeObserver(): void {
    if (typeof ResizeObserver !== "undefined") {
      this.resizeObserver = new ResizeObserver(() => this.refreshViewportSize());
      this.resizeObserver.observe(this.canvas);
    } else {
      this.resizeFallback = () => this.refreshViewportSize();
      window.addEventListener("resize", this.resizeFallback);
    }
  }
}
