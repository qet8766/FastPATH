import React, { useEffect, useMemo, useRef, useState } from "react";
import { fetchSlides } from "./api";
import type { SlideMetadata, SlideSummary, Viewport } from "./types";
import { FastPATHViewer } from "./viewer/FastPATHViewer";

const ZOOM_STEP = 1.25;

export default function App() {
  const [slides, setSlides] = useState<SlideSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [activeSlide, setActiveSlide] = useState<SlideSummary | null>(null);
  const [activeMetadata, setActiveMetadata] = useState<SlideMetadata | null>(null);
  const [loading, setLoading] = useState(false);
  const [viewport, setViewport] = useState<Viewport | null>(null);
  const viewerRef = useRef<FastPATHViewer | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    let mounted = true;
    fetchSlides()
      .then((data) => {
        if (mounted) {
          setSlides(data);
        }
      })
      .catch((err) => {
        if (mounted) {
          setError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (!containerRef.current || !canvasRef.current || viewerRef.current) {
      return;
    }
    viewerRef.current = new FastPATHViewer({
      container: containerRef.current,
      canvas: canvasRef.current,
      initialViewport: {
        x: 0,
        y: 0,
        width: 1024,
        height: 768,
        scale: 1,
        velocityX: 0,
        velocityY: 0,
      },
      onViewportChange: (next) => setViewport(next),
    });

    return () => {
      viewerRef.current?.dispose();
      viewerRef.current = null;
    };
  }, []);

  const handleOpenSlide = async (slide: SlideSummary) => {
    if (!viewerRef.current) {
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const metadata = await viewerRef.current.openSlide(slide.hash);
      setActiveSlide(slide);
      setActiveMetadata(metadata);
      setViewport(viewerRef.current.getViewport());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const handleZoomIn = () => {
    viewerRef.current?.zoomBy(ZOOM_STEP);
  };

  const handleZoomOut = () => {
    viewerRef.current?.zoomBy(1 / ZOOM_STEP);
  };

  const handleFit = () => {
    viewerRef.current?.fitToSlide();
  };

  const handleMinimapClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!activeMetadata || !viewerRef.current) {
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    const relX = (event.clientX - rect.left) / rect.width;
    const relY = (event.clientY - rect.top) / rect.height;
    const slideX = relX * activeMetadata.dimensions[0];
    const slideY = relY * activeMetadata.dimensions[1];
    viewerRef.current.centerOn(slideX, slideY);
  };

  const minimapStyle = useMemo(() => {
    if (!activeMetadata || !viewport) {
      return null;
    }
    const slideWidth = activeMetadata.dimensions[0];
    const slideHeight = activeMetadata.dimensions[1];
    const left = clamp(viewport.x / slideWidth, 0, 1);
    const top = clamp(viewport.y / slideHeight, 0, 1);
    const width = clamp(viewport.width / slideWidth, 0, 1);
    const height = clamp(viewport.height / slideHeight, 0, 1);
    return {
      left: `${left * 100}%`,
      top: `${top * 100}%`,
      width: `${width * 100}%`,
      height: `${height * 100}%`,
    } as React.CSSProperties;
  }, [activeMetadata, viewport]);

  return (
    <div className="app">
      <aside className="sidebar">
        <h1>FastPATH</h1>
        <p className="subtitle">Web Viewer</p>
        {error ? <p className="error">{error}</p> : null}
        <ul className="slide-list">
          {slides.map((slide) => (
            <li
              key={slide.hash}
              className={`slide-item ${activeSlide?.hash === slide.hash ? "active" : ""}`}
              onClick={() => handleOpenSlide(slide)}
            >
              <img src={slide.thumbnailUrl} alt={slide.name} />
              <div>
                <div className="slide-name">{slide.name}</div>
                <div className="slide-meta">
                  {slide.dimensions[0]} × {slide.dimensions[1]} px
                </div>
              </div>
            </li>
          ))}
        </ul>
      </aside>
      <main className="viewer" ref={containerRef}>
        <canvas ref={canvasRef} className="viewer-canvas" />
        {!activeSlide && !loading ? (
          <div className="viewer-placeholder">Select a slide to start rendering tiles.</div>
        ) : null}
        {loading ? <div className="viewer-placeholder">Loading slide...</div> : null}
        <div className="viewer-controls">
          <div className="zoom-controls">
            <button type="button" onClick={handleZoomIn}>
              +
            </button>
            <button type="button" onClick={handleZoomOut}>
              −
            </button>
            <button type="button" onClick={handleFit}>
              Fit
            </button>
          </div>
          {activeSlide ? (
            <div className="slide-info">
              <div>{activeSlide.name}</div>
              {viewport ? <div>{(viewport.scale * 100).toFixed(1)}%</div> : null}
            </div>
          ) : null}
        </div>
        {activeSlide ? (
          <div className="minimap" onClick={handleMinimapClick}>
            <img src={activeSlide.thumbnailUrl} alt="Slide minimap" />
            {minimapStyle ? <div className="minimap-viewport" style={minimapStyle} /> : null}
          </div>
        ) : null}
      </main>
    </div>
  );
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}
