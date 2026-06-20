/**
 * DocumentPreview renders the original uploaded PDF and draws bounding boxes
 * around the passages that grounded each extracted field. Unlike an <iframe>
 * PDF embed, rendering each page to a <canvas> via pdf.js lets us overlay boxes
 * at the normalized coordinates LandingAI returns (left/top/right/bottom in
 * 0..1 of the page), so reviewers can *see* exactly where a value came from.
 *
 * Boxes are positioned as percentages of the rendered page, which keeps them
 * correct at any zoom level without pixel math. The box matching `activeKey`
 * is emphasized and scrolled into view; clicking any box reports it back so the
 * corresponding form field can highlight in tandem.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Minimize2,
  Loader2,
  FileWarning,
} from 'lucide-react';
import * as pdfjsLib from 'pdfjs-dist';
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist';
import { documentApi, type DocumentFileSource } from '@/services/api';
// Vite resolves this to a bundled URL for the pdf.js web worker.
import PdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

pdfjsLib.GlobalWorkerOptions.workerSrc = PdfWorkerUrl;

/** A field's grounding passage to draw over the page. */
export interface GroundedBox {
  /** Matches ReviewForm's `activeKey` — e.g. "contract:premium_description". */
  key: string;
  label: string;
  /** 1-indexed page the box lives on. */
  page: number;
  bbox: { left: number; top: number; right: number; bottom: number };
}

interface DocumentPreviewProps {
  documentSource: DocumentFileSource;
  boxes: GroundedBox[];
  activeKey: string | null;
  /** Bump to re-jump to the active box's page (e.g. when its Source link is
      clicked again after the reviewer paged elsewhere). */
  jumpSignal?: number;
  onSelectBox?: (key: string) => void;
  /** Larger styling + taller page area for the enlarge modal. */
  fullscreen?: boolean;
  /** Toggle handler for the enlarge/restore button. */
  onToggleFullscreen?: () => void;
}

export const DocumentPreview: React.FC<DocumentPreviewProps> = ({
  documentSource,
  boxes,
  activeKey,
  jumpSignal,
  onSelectBox,
  fullscreen = false,
  onToggleFullscreen,
}) => {
  const protectedJobId =
    documentSource.kind === 'protected' ? documentSource.jobId : null;
  const publicUrl = documentSource.kind === 'public' ? documentSource.url : null;
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pageWrapRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const activeBoxRef = useRef<HTMLButtonElement>(null);
  const pdfRef = useRef<PDFDocumentProxy | null>(null);
  const renderTaskRef = useRef<RenderTask | null>(null);

  const [numPages, setNumPages] = useState(0);
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [containerWidth, setContainerWidth] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // --- Load the document once per source -----------------------------------
  useEffect(() => {
    let cancelled = false;
    let task: ReturnType<typeof pdfjsLib.getDocument> | null = null;
    setLoading(true);
    setError(null);

    const loadDocument = async () => {
      try {
        const source = protectedJobId
          ? { data: await documentApi.getFileData(protectedJobId) }
          : publicUrl;
        if (cancelled) return;
        if (!source) throw new Error('Document source is unavailable.');

        task = pdfjsLib.getDocument(source);
        const pdf = await task.promise;
        if (cancelled) {
          await pdf.destroy();
          return;
        }
        pdfRef.current = pdf;
        setNumPages(pdf.numPages);
        setLoading(false);
      } catch (err: any) {
        if (cancelled) return;
        console.error('Failed to load document for preview:', err);
        const detail = err?.message ? ` (${err.name ?? 'Error'}: ${err.message})` : '';
        setError(`This document could not be rendered for preview.${detail}`);
        setLoading(false);
      }
    };

    void loadDocument();
    return () => {
      cancelled = true;
      void task?.destroy();
      void pdfRef.current?.destroy();
      pdfRef.current = null;
    };
  }, [protectedJobId, publicUrl]);

  // --- Track the available width so the page fits the column ---------------
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const measure = () => setContainerWidth(el.clientWidth);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [fullscreen]);

  // --- Jump to the page of the active box ----------------------------------
  // Fires when the selection changes (or a Source link is re-clicked via
  // jumpSignal) — deliberately NOT on every page change, so manual paging
  // with the arrows isn't snapped back to the active box. numPages is a dep
  // so a jump requested while the document is still loading lands (clamped)
  // once the page count is known.
  useEffect(() => {
    if (!activeKey) return;
    const target = boxes.find((b) => b.key === activeKey);
    if (!target) return;
    setPage(Math.min(Math.max(target.page, 1), numPages || target.page));
  }, [activeKey, jumpSignal, boxes, numPages]);

  // --- Render the current page ---------------------------------------------
  const renderPage = useCallback(async () => {
    const pdf = pdfRef.current;
    const canvas = canvasRef.current;
    if (!pdf || !canvas || containerWidth === 0) return;

    renderTaskRef.current?.cancel();

    const pdfPage = await pdf.getPage(page);
    const base = pdfPage.getViewport({ scale: 1 });
    // Fit page width to the column, then apply the user's zoom.
    const fitScale = (containerWidth / base.width) * zoom;
    const viewport = pdfPage.getViewport({ scale: fitScale });
    const dpr = window.devicePixelRatio || 1;

    canvas.width = Math.floor(viewport.width * dpr);
    canvas.height = Math.floor(viewport.height * dpr);
    canvas.style.width = `${Math.floor(viewport.width)}px`;
    canvas.style.height = `${Math.floor(viewport.height)}px`;
    if (pageWrapRef.current) {
      pageWrapRef.current.style.width = `${Math.floor(viewport.width)}px`;
      pageWrapRef.current.style.height = `${Math.floor(viewport.height)}px`;
    }

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const task = pdfPage.render({ canvasContext: ctx, viewport });
    renderTaskRef.current = task;
    try {
      await task.promise;
    } catch (err: any) {
      if (err?.name !== 'RenderingCancelledException') {
        console.error('Page render failed:', err);
      }
    }
  }, [page, zoom, containerWidth]);

  useEffect(() => {
    if (!loading && !error) void renderPage();
  }, [loading, error, renderPage]);

  // --- Keep the active box visible -----------------------------------------
  useEffect(() => {
    activeBoxRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [activeKey, page, zoom, loading]);

  const pageBoxes = boxes.filter((b) => b.page === page);

  const clampPage = (next: number) => setPage(Math.min(Math.max(next, 1), numPages || 1));

  return (
    <div className={`doc-preview ${fullscreen ? 'doc-preview--fullscreen' : ''}`}>
      <div className="doc-preview__toolbar">
        <div className="doc-preview__pager">
          <button
            type="button"
            className="doc-preview__btn"
            onClick={() => clampPage(page - 1)}
            disabled={page <= 1 || loading}
            aria-label="Previous page"
          >
            <ChevronLeft size={16} />
          </button>
          <span className="doc-preview__page-label">
            {loading ? '—' : `Page ${page} / ${numPages}`}
          </span>
          <button
            type="button"
            className="doc-preview__btn"
            onClick={() => clampPage(page + 1)}
            disabled={page >= numPages || loading}
            aria-label="Next page"
          >
            <ChevronRight size={16} />
          </button>
        </div>
        <div className="doc-preview__tools">
          <button
            type="button"
            className="doc-preview__btn"
            onClick={() => setZoom((z) => Math.max(0.5, +(z - 0.2).toFixed(2)))}
            disabled={loading || zoom <= 0.5}
            aria-label="Zoom out"
          >
            <ZoomOut size={16} />
          </button>
          <span className="doc-preview__zoom-label">{Math.round(zoom * 100)}%</span>
          <button
            type="button"
            className="doc-preview__btn"
            onClick={() => setZoom((z) => Math.min(3, +(z + 0.2).toFixed(2)))}
            disabled={loading || zoom >= 3}
            aria-label="Zoom in"
          >
            <ZoomIn size={16} />
          </button>
          {onToggleFullscreen && (
            <button
              type="button"
              className="doc-preview__btn doc-preview__btn--accent"
              onClick={onToggleFullscreen}
              aria-label={fullscreen ? 'Exit full screen' : 'Enlarge'}
            >
              {fullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
            </button>
          )}
        </div>
      </div>

      <div className="doc-preview__stage" ref={scrollRef}>
        {loading && (
          <div className="doc-preview__status">
            <Loader2 size={20} className="doc-preview__spinner" />
            <span>Loading document…</span>
          </div>
        )}
        {error && (
          <div className="doc-preview__status doc-preview__status--error">
            <FileWarning size={20} />
            <span>{error}</span>
          </div>
        )}
        {!loading && !error && (
          <div className="doc-preview__page-wrap" ref={pageWrapRef}>
            <canvas ref={canvasRef} className="doc-preview__canvas" />
            {pageBoxes.map((b) => {
              const isActive = b.key === activeKey;
              const left = `${b.bbox.left * 100}%`;
              const top = `${b.bbox.top * 100}%`;
              const width = `${(b.bbox.right - b.bbox.left) * 100}%`;
              const height = `${(b.bbox.bottom - b.bbox.top) * 100}%`;
              return (
                <button
                  type="button"
                  key={b.key}
                  ref={isActive ? activeBoxRef : undefined}
                  className={`doc-box ${isActive ? 'doc-box--active' : ''}`}
                  style={{ left, top, width, height }}
                  onClick={() => onSelectBox?.(b.key)}
                  title={b.label}
                >
                  <span className="doc-box__tag">{b.label}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
