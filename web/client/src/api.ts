import type { SlideMetadata, SlideSummary } from "./types";

const API_BASE = import.meta.env.VITE_FASTPATH_API_BASE ?? "";

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export function fetchSlides(): Promise<SlideSummary[]> {
  return fetchJson<SlideSummary[]>(`${API_BASE}/api/slides`);
}

export function fetchMetadata(slideId: string): Promise<SlideMetadata> {
  return fetchJson<SlideMetadata>(`${API_BASE}/api/slides/${slideId}/metadata`);
}

export function slideBaseUrl(slideId: string): string {
  return `${API_BASE}/slides/${slideId}`;
}
