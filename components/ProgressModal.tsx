"use client";

type ProgressModalProps = {
  open: boolean;
  title: string;
  progress: number;
  message: string;
  status: "processing" | "done" | "error";
  onClose: () => void;
  onDownload: () => void;
  onRetry?: () => void;
  retrying?: boolean;
};

export function ProgressModal({
  open,
  title,
  progress,
  message,
  status,
  onClose,
  onDownload,
  onRetry,
  retrying = false,
}: ProgressModalProps) {
  if (!open) return null;

  const canDismiss = status === "done" || status === "error";

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/50 p-4"
      onClick={canDismiss ? onClose : undefined}
      role="presentation"
    >
      <div
        className="w-full max-w-lg rounded-xl bg-white p-6 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="progress-modal-title"
      >
        <div className="flex items-start justify-between gap-4">
          <h2 id="progress-modal-title" className="text-xl font-semibold text-zinc-900">
            {title}
          </h2>
          {canDismiss ? (
            <button
              type="button"
              onClick={onClose}
              className="rounded-full p-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800"
              aria-label="Fechar"
            >
              ✕
            </button>
          ) : null}
        </div>
        <div className="mt-5 h-3 w-full overflow-hidden rounded-full bg-zinc-200">
          <div
            className="h-full rounded-full bg-amber-400 transition-all duration-500"
            style={{ width: `${Math.max(0, Math.min(progress, 100))}%` }}
          />
        </div>
        <p className={`mt-3 text-sm ${status === "error" ? "text-red-700" : "text-zinc-700"}`}>
          {status === "error" ? `Erro: ${message}` : message}
        </p>
        <p className="mt-1 text-xs text-zinc-500">Progresso: {Math.round(progress)}%</p>

        <div className="mt-6 flex justify-end gap-3">
          {status === "done" ? (
            <>
              <button
                type="button"
                onClick={onClose}
                className="rounded-full border border-zinc-300 px-4 py-2 text-sm text-zinc-700 hover:bg-zinc-100"
              >
                Fechar
              </button>
              <button
                type="button"
                onClick={onDownload}
                className="rounded-full bg-amber-400 px-5 py-2 text-sm font-semibold text-zinc-900 hover:bg-amber-300"
              >
                Baixar JSON
              </button>
            </>
          ) : null}
          {status === "error" ? (
            <>
              <button
                type="button"
                onClick={onClose}
                className="rounded-full border border-zinc-300 px-4 py-2 text-sm text-zinc-700 hover:bg-zinc-100"
              >
                Fechar
              </button>
              {onRetry ? (
                <button
                  type="button"
                  onClick={onRetry}
                  disabled={retrying}
                  className="rounded-full bg-amber-400 px-5 py-2 text-sm font-semibold text-zinc-900 hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {retrying ? "Reenfileirando..." : "Tentar novamente"}
                </button>
              ) : null}
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
