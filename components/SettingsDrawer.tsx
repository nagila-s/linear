"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type { BookRow } from "@/types";

type SettingsDrawerProps = {
  open: boolean;
  onClose: () => void;
};

export function SettingsDrawer({ open, onClose }: SettingsDrawerProps) {
  const [books, setBooks] = useState<BookRow[]>([]);
  const [booksMessage, setBooksMessage] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    fetch("/api/books")
      .then((response) => response.json())
      .then((data: { books?: BookRow[]; message?: string }) => {
        setBooks(data.books ?? []);
        setBooksMessage(data.message ?? "");
      })
      .finally(() => setLoading(false));
  }, [open]);

  const sortedBooks = useMemo(
    () =>
      [...books].sort(
        (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
      ),
    [books],
  );

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-30 flex justify-end bg-black/40"
      onClick={onClose}
      role="presentation"
    >
      <aside
        className="h-full w-full max-w-2xl overflow-hidden bg-white shadow-2xl"
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
            <p className="text-sm font-semibold text-zinc-900">Área de testes</p>
            <p className="mt-1 text-sm text-zinc-600">
              Edite cópias dos prompts e rode um livro no Supabase (sem worker AWS).
            </p>
            <Link
              href="/testes"
              onClick={onClose}
              className="mt-3 inline-flex rounded-full border-2 border-black bg-amber-400 px-4 py-2 text-sm font-semibold text-black hover:bg-amber-300"
            >
              Abrir área de testes
            </Link>
          </div>

          <h4 className="mb-3 text-sm font-semibold text-zinc-900">Livros processados</h4>
          <div className="overflow-hidden rounded-lg border border-zinc-200">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Lista de livros processados</caption>
              <thead className="bg-zinc-50">
                <tr>
                  <th scope="col" className="px-3 py-2">
                    Título
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Data
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Ações
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Status
                  </th>
                  <th scope="col" className="px-3 py-2">
                    Arquivo
                  </th>
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
                      ) : book.status === "done" ? (
                        <span className="rounded-full bg-green-100 px-2 py-1 text-xs text-green-800">
                          Concluído
                        </span>
                      ) : (
                        <span className="rounded-full bg-red-100 px-2 py-1 text-xs text-red-800">
                          Erro
                        </span>
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
        </div>
      </aside>
    </div>
  );
}
