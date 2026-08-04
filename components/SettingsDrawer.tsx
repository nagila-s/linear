"use client";

import Link from "next/link";

type SettingsDrawerProps = {
  open: boolean;
  onClose: () => void;
};

export function SettingsDrawer({ open, onClose }: SettingsDrawerProps) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-30 flex justify-end bg-black/40"
      onClick={onClose}
      role="presentation"
    >
      <aside
        className="h-full w-full max-w-md overflow-hidden bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-drawer-title"
      >
        <div className="flex h-14 items-center justify-between border-b px-5">
          <h3 id="settings-drawer-title" className="text-lg font-semibold text-zinc-900">
            Configurações
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="text-zinc-700 hover:text-zinc-900"
            aria-label="Fechar configurações"
          >
            Fechar
          </button>
        </div>

        <div className="h-[calc(100%-3.5rem)] overflow-auto p-5">
          <div className="mb-5 rounded-lg border border-zinc-200 p-4">
            <p className="text-sm font-semibold text-zinc-900">Fila de processamento</p>
            <p className="mt-1 text-sm text-zinc-600">
              Veja os livros em aberto, estimativas de tempo e os finalizados com download do JSON.
            </p>
            <Link
              href="/fila"
              onClick={onClose}
              className="mt-3 inline-flex rounded-full border-2 border-black bg-amber-400 px-4 py-2 text-sm font-semibold text-black hover:bg-amber-300"
            >
              Abrir fila de processamento
            </Link>
          </div>

          <div className="rounded-lg border border-zinc-200 p-4">
            <p className="text-sm font-semibold text-zinc-900">Área de testes</p>
            <p className="mt-1 text-sm text-zinc-600">
              Edite cópias dos prompts e rode um livro no Supabase (sem worker AWS).
            </p>
            <Link
              href="/testes"
              onClick={onClose}
              className="mt-3 inline-flex rounded-full border-2 border-black bg-white px-4 py-2 text-sm font-semibold text-black hover:bg-zinc-50"
            >
              Abrir área de testes
            </Link>
          </div>
        </div>
      </aside>
    </div>
  );
}
