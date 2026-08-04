"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Header } from "@/components/Header";
import { SettingsDrawer } from "@/components/SettingsDrawer";
import { slugify } from "@/lib/utils";
import type { QueueItem, QueueResponse } from "@/types";

type Tab = "open" | "finished";

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || seconds < 0) return "—";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}min`;
  if (m > 0) return `${m} min`;
  return `${s} s`;
}

function statusBadge(status: string): { label: string; className: string } {
  const normalized = status.toLowerCase();
  if (normalized === "running") {
    return { label: "Em andamento", className: "bg-amber-100 text-amber-900" };
  }
  if (normalized === "queued") {
    return { label: "Na fila", className: "bg-zinc-100 text-zinc-800" };
  }
  if (normalized === "retrying") {
    return { label: "Reprocessando", className: "bg-orange-100 text-orange-900" };
  }
  if (normalized === "done" || normalized === "partial_success") {
    return { label: "Concluído", className: "bg-green-100 text-green-900" };
  }
  if (normalized === "failed") {
    return { label: "Erro", className: "bg-red-100 text-red-900" };
  }
  return { label: status || "—", className: "bg-zinc-100 text-zinc-700" };
}

export default function FilaPage() {
  const [tab, setTab] = useState<Tab>("open");
  const [items, setItems] = useState<QueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);

  const load = useCallback(async (activeTab: Tab) => {
    try {
      const response = await fetch(`/api/queue?tab=${activeTab}&limit=100`);
      const raw = await response.text();
      if (!raw.trim()) {
        throw new Error(`Resposta vazia ao consultar a fila (HTTP ${response.status}).`);
      }
      const payload = JSON.parse(raw) as QueueResponse;
      if (!response.ok) {
        throw new Error(payload.error || "Falha ao carregar a fila.");
      }
      setItems(payload.items ?? []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao carregar a fila.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    void load(tab);
    const interval = window.setInterval(() => {
      void load(tab);
    }, 12000);
    return () => window.clearInterval(interval);
  }, [tab, load]);

  return (
    <main className="min-h-screen bg-white">
      <Header onOpenSettings={() => setSettingsOpen(true)} />
      <section className="mx-auto max-w-6xl px-8 pb-16 pt-28">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-zinc-500">
              <Link href="/" className="underline-offset-2 hover:underline">
                Início
              </Link>
              <span aria-hidden> / </span>
              Fila
            </p>
            <h1 className="mt-1 text-3xl font-bold text-black">Fila de processamento</h1>
            {tab === "open" ? (
              <p className="mt-2 text-sm text-zinc-600">
                Estimativa com base em testes anteriores: 25 s por página.
              </p>
            ) : null}
          </div>
          <Link
            href="/"
            className="rounded-2xl border-2 border-black bg-amber-400 px-5 py-2.5 text-sm font-bold text-black hover:bg-amber-300"
          >
            Enviar outro livro
          </Link>
        </div>

        <div className="mb-4 flex gap-2 border-b-2 border-black" role="tablist" aria-label="Abas da fila">
          {(
            [
              { id: "open", label: "Em aberto" },
              { id: "finished", label: "Finalizados" },
            ] as const
          ).map((option) => {
            const selected = tab === option.id;
            return (
              <button
                key={option.id}
                type="button"
                role="tab"
                aria-selected={selected}
                onClick={() => setTab(option.id)}
                className={
                  selected
                    ? "-mb-0.5 border-b-4 border-black px-4 py-2 text-sm font-bold text-black"
                    : "px-4 py-2 text-sm font-semibold text-zinc-500 hover:text-black"
                }
              >
                {option.label}
              </button>
            );
          })}
        </div>

        {error ? (
          <div className="mb-4 border-2 border-red-700 bg-red-50 px-4 py-3 text-sm text-red-900">
            {error}
          </div>
        ) : null}

        <div className="overflow-hidden border-2 border-black">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">
              {tab === "open" ? "Livros em aberto na fila" : "Livros finalizados"}
            </caption>
            <thead className="bg-zinc-50">
              <tr>
                {tab === "open" ? (
                  <th scope="col" className="px-3 py-3 font-semibold">
                    #
                  </th>
                ) : null}
                <th scope="col" className="px-3 py-3 font-semibold">
                  Livro
                </th>
                <th scope="col" className="px-3 py-3 font-semibold">
                  Status
                </th>
                <th scope="col" className="px-3 py-3 font-semibold">
                  Páginas
                </th>
                {tab === "open" ? (
                  <>
                    <th scope="col" className="px-3 py-3 font-semibold">
                      Duração est.
                    </th>
                    <th scope="col" className="px-3 py-3 font-semibold">
                      Início est.
                    </th>
                    <th scope="col" className="px-3 py-3 font-semibold">
                      Fim est.
                    </th>
                  </>
                ) : (
                  <>
                    <th scope="col" className="px-3 py-3 font-semibold">
                      Início
                    </th>
                    <th scope="col" className="px-3 py-3 font-semibold">
                      Fim
                    </th>
                    <th scope="col" className="px-3 py-3 font-semibold">
                      Durou
                    </th>
                    <th scope="col" className="px-3 py-3 font-semibold">
                      Arquivo
                    </th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td className="px-3 py-4 text-zinc-500" colSpan={tab === "open" ? 7 : 7}>
                    Carregando fila...
                  </td>
                </tr>
              ) : null}
              {!loading && items.length === 0 ? (
                <tr>
                  <td className="px-3 py-4 text-zinc-500" colSpan={7}>
                    {tab === "open"
                      ? "Nenhum livro na fila. Envie um PDF na tela principal."
                      : "Nenhum livro finalizado ainda."}
                  </td>
                </tr>
              ) : null}
              {!loading
                ? items.map((item) => {
                    const badge = statusBadge(item.status);
                    return (
                      <tr key={item.id} className="border-t border-zinc-200 align-top">
                        {tab === "open" ? (
                          <td className="px-3 py-3 font-mono text-xs text-zinc-500">
                            {item.queuePosition ?? "—"}
                          </td>
                        ) : null}
                        <td className="px-3 py-3">
                          <div className="font-semibold text-black">{item.title}</div>
                          <div className="mt-0.5 font-mono text-xs text-zinc-500">{item.isbn || item.id}</div>
                          <div className="mt-1 text-xs text-zinc-600">{item.message}</div>
                        </td>
                        <td className="px-3 py-3">
                          <span className={`inline-block rounded px-2 py-1 text-xs font-semibold ${badge.className}`}>
                            {badge.label}
                          </span>
                        </td>
                        <td className="px-3 py-3">{item.pageCount ?? "—"}</td>
                        {tab === "open" ? (
                          <>
                            <td className="px-3 py-3">
                              {formatDuration(item.estimatedDurationSeconds)}
                            </td>
                            <td className="px-3 py-3">{formatDateTime(item.estimatedStartAt)}</td>
                            <td className="px-3 py-3">{formatDateTime(item.estimatedEndAt)}</td>
                          </>
                        ) : (
                          <>
                            <td className="px-3 py-3">{formatDateTime(item.startedAt)}</td>
                            <td className="px-3 py-3">{formatDateTime(item.finishedAt)}</td>
                            <td className="px-3 py-3">
                              {formatDuration(item.estimatedDurationSeconds)}
                            </td>
                            <td className="px-3 py-3">
                              {item.canDownload ? (
                                <a
                                  href={`/api/books/${item.id}/download?filename=${encodeURIComponent(slugify(item.title) || "livro")}.json`}
                                  className="inline-block border-2 border-black px-2 py-1 text-xs font-semibold hover:bg-zinc-100"
                                >
                                  Baixar JSON
                                </a>
                              ) : (
                                <span className="text-xs text-zinc-400">Indisponível</span>
                              )}
                            </td>
                          </>
                        )}
                      </tr>
                    );
                  })
                : null}
            </tbody>
          </table>
        </div>
      </section>
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </main>
  );
}
