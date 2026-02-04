import type { Viewport } from "../types";

const ZOOM_FACTOR = 1.4;
const MIN_SCALE = 0.05;
const MAX_SCALE = 16;

export interface InputHandlerOptions {
  onViewportChange: (viewport: Viewport) => void;
}

export class InputHandler {
  private element: HTMLElement;
  private viewport: Viewport;
  private onViewportChange: (viewport: Viewport) => void;
  private pointerId: number | null = null;
  private lastPointer: { x: number; y: number; time: number } | null = null;

  constructor(element: HTMLElement, viewport: Viewport, options: InputHandlerOptions) {
    this.element = element;
    this.viewport = viewport;
    this.onViewportChange = options.onViewportChange;
    this.attach();
  }

  updateViewport(viewport: Viewport): void {
    this.viewport = viewport;
  }

  dispose(): void {
    this.element.removeEventListener("wheel", this.handleWheel);
    this.element.removeEventListener("pointerdown", this.handlePointerDown);
    window.removeEventListener("pointermove", this.handlePointerMove);
    window.removeEventListener("pointerup", this.handlePointerUp);
  }

  private attach(): void {
    this.element.addEventListener("wheel", this.handleWheel, { passive: false });
    this.element.addEventListener("pointerdown", this.handlePointerDown);
    window.addEventListener("pointermove", this.handlePointerMove);
    window.addEventListener("pointerup", this.handlePointerUp);
  }

  private handleWheel = (event: WheelEvent): void => {
    event.preventDefault();
    const rect = this.element.getBoundingClientRect();
    const offsetX = event.clientX - rect.left;
    const offsetY = event.clientY - rect.top;
    const normX = rect.width > 0 ? offsetX / rect.width : 0.5;
    const normY = rect.height > 0 ? offsetY / rect.height : 0.5;

    const zoomIn = event.deltaY < 0;
    const nextScale = this.clampScale(
      this.viewport.scale * (zoomIn ? ZOOM_FACTOR : 1 / ZOOM_FACTOR)
    );
    const scaleFactor = nextScale / this.viewport.scale;
    const newWidth = this.viewport.width / scaleFactor;
    const newHeight = this.viewport.height / scaleFactor;

    const focusX = this.viewport.x + this.viewport.width * normX;
    const focusY = this.viewport.y + this.viewport.height * normY;

    const newX = focusX - newWidth * normX;
    const newY = focusY - newHeight * normY;

    this.emit({
      ...this.viewport,
      x: newX,
      y: newY,
      width: newWidth,
      height: newHeight,
      scale: nextScale,
    });
  };

  private handlePointerDown = (event: PointerEvent): void => {
    this.pointerId = event.pointerId;
    this.element.setPointerCapture(event.pointerId);
    this.lastPointer = {
      x: event.clientX,
      y: event.clientY,
      time: performance.now(),
    };
  };

  private handlePointerMove = (event: PointerEvent): void => {
    if (this.pointerId !== event.pointerId || !this.lastPointer) {
      return;
    }

    const rect = this.element.getBoundingClientRect();
    const dx = event.clientX - this.lastPointer.x;
    const dy = event.clientY - this.lastPointer.y;
    const now = performance.now();
    const dt = Math.max(now - this.lastPointer.time, 1);

    const scaleX = rect.width > 0 ? this.viewport.width / rect.width : 1;
    const scaleY = rect.height > 0 ? this.viewport.height / rect.height : 1;

    const newX = this.viewport.x - dx * scaleX;
    const newY = this.viewport.y - dy * scaleY;

    const velocityX = (-dx / dt) * 1000;
    const velocityY = (-dy / dt) * 1000;

    this.lastPointer = { x: event.clientX, y: event.clientY, time: now };

    this.emit({
      ...this.viewport,
      x: newX,
      y: newY,
      velocityX,
      velocityY,
    });
  };

  private handlePointerUp = (event: PointerEvent): void => {
    if (this.pointerId !== event.pointerId) {
      return;
    }
    this.pointerId = null;
    this.lastPointer = null;
  };

  private clampScale(scale: number): number {
    return Math.max(MIN_SCALE, Math.min(MAX_SCALE, scale));
  }

  private emit(viewport: Viewport): void {
    this.viewport = viewport;
    this.onViewportChange(viewport);
  }
}
