"use client";

type ProgressModalProps = {
  open: boolean;
  title: string;
  progress: number;
  message: string;
  status: "processing" | "done" | "error";
  onClose: () => void;
  onDownload: () => void;
};

export function ProgressModal({
  open,
  title,
  progress,
  message,
  status,
  onClose,
  onDownload,
}: ProgressModalProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-2xl">
        <h2 className="text-xl font-semibold text-zinc-900">{title}</h2>
        <div className="mt-5 h-3 w-full overflow-hidden rounded-full bg-zinc-200">
          <div
            className="h-full rounded-full bg-amber-400 transition-all duration-500"
            style={{ width: `${Math.max(0, Math.min(progress, 100))}%` }}
          />
        </div>
        <p className="mt-3 text-sm text-zinc-700">{message}</p>
        <p className="mt-1 text-xs text-zinc-500">Progresso: {Math.round(progress)}%</p>

        <div className="mt-6 flex justify-end gap-3">
          {status === "done" ? (
            <button
              type="button"
              onClick={onDownload}
              className="rounded-full bg-amber-400 px-5 py-2 text-sm font-semibold text-zinc-900 hover:bg-amber-300"
            >
              Baixar JSON
            </button>
          ) : null}
          {status === "error" ? (
            <button
              type="button"
              onClick={onClose}
              className="rounded-full border border-zinc-300 px-4 py-2 text-sm text-zinc-700 hover:bg-zinc-100"
            >
              Voltar
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
