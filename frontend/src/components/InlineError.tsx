import { AlertTriangle, RefreshCw, X } from "lucide-react";

/**
 * A small, dismissible inline error banner for a page section.
 * Use this instead of silently rendering an error as "no data" —
 * pass `onRetry` where a re-fetch makes sense.
 */
export default function InlineError({
  message,
  onRetry,
  onDismiss,
  className = "",
}: {
  message: string;
  onRetry?: () => void;
  onDismiss?: () => void;
  className?: string;
}) {
  return (
    <div
      className={`flex items-start gap-2.5 rounded-xl border border-red-500/25 bg-red-500/10 px-3.5 py-2.5 text-xs text-red-300 ${className}`}
      role="alert"
    >
      <AlertTriangle size={14} className="shrink-0 mt-0.5 text-red-400" />
      <div className="flex-1 min-w-0 leading-snug">{message}</div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="shrink-0 flex items-center gap-1 text-red-300 hover:text-white font-medium transition-colors"
        >
          <RefreshCw size={11} /> Retry
        </button>
      )}
      {onDismiss && (
        <button onClick={onDismiss} className="shrink-0 text-red-400/70 hover:text-red-300 transition-colors" title="Dismiss">
          <X size={13} />
        </button>
      )}
    </div>
  );
}
