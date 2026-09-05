import { useEffect } from "react";
import { createPortal } from "react-dom";
import { X, Download } from "lucide-react";

/**
 * Full-screen click-to-enlarge viewer for an evidence/detection frame.
 * Portaled to document.body so it always renders above everything —
 * including Leaflet popups/panes, which have their own stacking and
 * overflow contexts that would otherwise clip a plain fixed-position div.
 */
export default function Lightbox({
  src, alt, caption, onClose,
}: {
  src: string; alt?: string; caption?: string; onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    // Prevent the page behind the overlay from scrolling while it's open.
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  return createPortal(
    <div
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/85 backdrop-blur-sm animate-fade-in"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={alt || "Enlarged image"}
    >
      <button
        className="absolute top-4 right-4 btn-icon bg-black/40 hover:bg-black/60 text-white w-9 h-9"
        onClick={onClose}
        title="Close (Esc)"
      >
        <X size={18} />
      </button>
      <a
        href={src}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
        className="absolute top-4 right-16 btn-icon bg-black/40 hover:bg-black/60 text-white w-9 h-9"
        title="Open original in a new tab"
      >
        <Download size={16} />
      </a>
      <img
        src={src}
        alt={alt || ""}
        onClick={(e) => e.stopPropagation()}
        className="max-w-[92vw] max-h-[88vh] object-contain rounded-lg shadow-2xl"
      />
      {caption && (
        <div
          onClick={(e) => e.stopPropagation()}
          className="absolute bottom-6 left-1/2 -translate-x-1/2 px-4 py-2 rounded-lg bg-black/60 text-white text-xs font-mono max-w-[90vw] truncate"
        >
          {caption}
        </div>
      )}
    </div>,
    document.body
  );
}

/** Small reusable "click to enlarge" hint badge, shown on hover over a thumbnail. */
export function ExpandHint() {
  return (
    <div className="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/30 transition-colors opacity-0 group-hover:opacity-100 pointer-events-none">
      <div className="w-6 h-6 rounded-full bg-black/60 flex items-center justify-center">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-white">
          <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
        </svg>
      </div>
    </div>
  );
}
