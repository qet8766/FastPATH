import type { SlideMetadata, Viewport } from "../types";

export class ViewerState {
  metadata: SlideMetadata | null = null;
  viewport: Viewport;

  constructor(viewport: Viewport) {
    this.viewport = viewport;
  }

  setMetadata(metadata: SlideMetadata): void {
    this.metadata = metadata;
  }

  updateViewport(next: Partial<Viewport>): void {
    this.viewport = { ...this.viewport, ...next };
  }
}
