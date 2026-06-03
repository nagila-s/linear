"use client";

import { useEffect, useMemo, useState } from "react";
import type { BookRow } from "@/types";

type SettingsDrawerProps = {
  open: boolean;
  onClose: () => void;
};

type Tab = "prompt" | "books";

export function SettingsDrawer({ open, onClose }: SettingsDrawerProps) {
  const [tab, setTab] = useState<Tab>("prompt");
  const [prompt, setPrompt] = useState("");
  const [books, setBooks] = useState<BookRow[]>([]);
  const [booksMessage, setBooksMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [savingPrompt, setSavingPrompt] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (tab === "prompt") {
      setLoading(true);
      fetch("/api/settings/prompt")
        .then((response) => response.json())
        .then((data: { prompt?: string }) => setPrompt(data.prompt ?? ""))
        .finally(() => setLoading(false));
      return;
    }

    setLoading(true);
    fetch("/api/books")
      .then((response) => response.json())
      .then((data: { books?: BookRow[]; message?: string }) => {
        setBooks(data.books ?? []);
        setBooksMessage(data.message ?? "");
      })
      .finally(() => setLoading(false));
  }, [open, tab]);

  const sortedBooks = useMemo(
    () =>
      [...books].sort(
        (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
      ),
    [books],
  );

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-30 flex justify-end bg-black/40" onClick={onClose}>
      <aside
        className="h-full w-full max-w-2xl overflow-hidden bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex h-14 items-center justify-between border-b px-5">
          <h3 className="text-lg font-semibold text-zinc-900">Configurações</h3>
          <button type="button" onClick={onClose} className="text-zinc-700 hover:text-zinc-900">
            Fechar
          </button>
        </div>

        <div className="flex border-b">
          <button
            type="button"
            onClick={() => setTab("prompt")}
            className={`px-5 py-3 text-sm font-medium ${tab === "prompt" ? "border-b-2 border-zinc-900 text-zinc-900" : "text-zinc-500"}`}
          >
            Prompt
          </button>
          <button
            type="button"
            onClick={() => setTab("books")}
            className={`px-5 py-3 text-sm font-medium ${tab === "books" ? "border-b-2 border-zinc-900 text-zinc-900" : "text-zinc-500"}`}
          >
            Livros processados
          </button>
        </div>

        <div className="h-[calc(100%-7rem)] overflow-auto p-5">
          {tab === "prompt" ? (
            <div className="space-y-4">
              <textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                className="h-[420px] w-full rounded-lg border border-zinc-300 p-3 text-sm outline-none focus:border-zinc-500"
              />
              <button
                type="button"
                disabled={savingPrompt}
                onClick={async () => {
                  setSavingPrompt(true);
                  await fetch("/api/settings/prompt", {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ prompt }),
                  });
                  setSavingPrompt(false);
                }}
                className="rounded-full bg-amber-400 px-5 py-2 text-sm font-semibold text-zinc-900 hover:bg-amber-300 disabled:opacity-60"
              >
                Salvar prompt
              </button>
              {loading ? <p className="text-sm text-zinc-500">Carregando...</p> : null}
            </div>
          ) : null}

          {tab === "books" ? (
            <div className="overflow-hidden rounded-lg border border-zinc-200">
              <table className="w-full text-left text-sm">
                <thead className="bg-zinc-50">
                  <tr>
                    <th className="px-3 py-2">Título</th>
                    <th className="px-3 py-2">Data</th>
                    <th className="px-3 py-2">Ações</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Arquivo</th>
                  </tr>
                </thead>
                <tbody>
                  {loading ? (
                    <tr>
                      <td className="px-3 py-3 text-zinc-500" colSpan={5}>
                        Carregando...
                      </td>
                    </tr>
                  ) : null}
                  {!loading && sortedBooks.length === 0 ? (
                    <tr>
                      <td className="px-3 py-3 text-zinc-500" colSpan={5}>
                        {booksMessage || "Nenhum livro listado. Use o upload na tela principal."}
                      </td>
                    </tr>
                  ) : null}
                  {sortedBooks.map((book) => (
                    <tr key={book.id} className="border-t">
                      <td className="px-3 py-2">{book.title}</td>
                      <td className="px-3 py-2">{new Date(book.createdAt).toLocaleString("pt-BR")}</td>
                      <td className="px-3 py-2">{book.actions.join(", ") || "-"}</td>
                      <td className="px-3 py-2">
                        {book.status === "processing" ? (
                          <span className="rounded-full bg-amber-100 px-2 py-1 text-xs text-amber-800">
                            Em andamento
                          </span>
                        ) : (
                          <span className="text-zinc-700">{book.status}</span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <a
                          href={`/api/books/${book.id}/download`}
                          className="rounded border border-zinc-300 px-2 py-1 text-xs hover:bg-zinc-100"
                        >
                          Baixar JSON
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
