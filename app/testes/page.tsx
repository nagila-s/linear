"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Header } from "@/components/Header";
import { SettingsDrawer } from "@/components/SettingsDrawer";
import { UploadDropzone } from "@/components/UploadDropzone";
import { extractIsbnFromFilename, isValidIsbn, normalizeIsbn } from "@/lib/isbn";
import { type PromptTestResult, runPromptTest } from "@/lib/upload-job";
import { slugify } from "@/lib/utils";
import { buildZipStore, downloadBlob } from "@/lib/zip-download";

type PromptFile = { name: string; content: string };

export default function TestesPage() {
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<string>("");
  const [loadingPrompts, setLoadingPrompts] = useState(true);
  const [promptsError, setPromptsError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [isbn, setIsbn] = useState("");
  const [mioloOnly, setMioloOnly] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState("");
  const [result, setResult] = useState<PromptTestResult | null>(null);

  const names = useMemo(() => Object.keys(prompts).sort((a, b) => a.localeCompare(b, "pt-BR")), [prompts]);

  useEffect(() => {
    let cancelled = false;
    setLoadingPrompts(true);
    fetch("/api/prompts")
      .then(async (response) => {
        const payload = (await response.json()) as { prompts?: PromptFile[]; error?: string };
        if (!response.ok) throw new Error(payload.error || "Falha ao carregar prompts.");
        if (cancelled) return;
        const map: Record<string, string> = {};
        for (const item of payload.prompts ?? []) {
          map[item.name] = item.content;
        }
        setPrompts(map);
        const first = Object.keys(map).sort((a, b) => a.localeCompare(b, "pt-BR"))[0] ?? "";
        setSelected(first);
        setPromptsError("");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setPromptsError(error instanceof Error ? error.message : "Falha ao carregar prompts.");
      })
      .finally(() => {
        if (!cancelled) setLoadingPrompts(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!file || isbn.trim()) return;
    const guess = extractIsbnFromFilename(file.name);
    if (guess) setIsbn(guess);
  }, [file, isbn]);

  const canSubmit = Boolean(file && !running && names.length > 0);
  const resultBaseName = slugify(file?.name?.replace(/\.pdf$/i, "") || "teste-prompts");

  async function runTest() {
    if (!file || running) return;
    if (isbn.trim() && !isValidIsbn(normalizeIsbn(isbn))) {
      window.alert("ISBN inválido.");
      return;
    }
    setRunning(true);
    setRunError("");
    setResult(null);
    try {
      const payload = await runPromptTest(file, {
        isbn: isbn.trim() ? normalizeIsbn(isbn) : undefined,
        mioloOnly,
        promptOverrides: prompts,
      });
      setResult(payload);
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Falha ao rodar o teste.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <main className="min-h-screen bg-white">
      <Header onOpenSettings={() => setSettingsOpen(true)} />
      <section className="mx-auto max-w-6xl px-8 pb-10 pt-28" aria-label="Área de testes de prompts">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-sm text-zinc-600">
              <Link href="/" className="underline hover:text-black">
                ← Voltar
              </Link>
            </p>
            <h1 className="mt-2 text-3xl font-semibold text-black">Área de testes</h1>
            <p className="mt-1 max-w-2xl text-sm text-zinc-700">
              Edite cópias dos prompts do sistema e rode um livro pequeno na hora, direto na OpenAI e
              na Dorina. Nada aqui sobrescreve os prompts de produção nem passa pela fila principal.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!selected || !prompts[selected]}
              onClick={() => {
                if (!selected) return;
                downloadBlob(
                  new Blob([prompts[selected] ?? ""], { type: "text/plain;charset=utf-8" }),
                  selected,
                );
              }}
              className="rounded-lg border-2 border-black px-4 py-2 text-sm font-semibold hover:bg-zinc-100 disabled:opacity-50"
            >
              Baixar atual
            </button>
            <button
              type="button"
              disabled={names.length === 0}
              onClick={() => {
                const zip = buildZipStore(names.map((name) => ({ name, content: prompts[name] ?? "" })));
                downloadBlob(zip, "prompts-teste.zip");
              }}
              className="rounded-lg border-2 border-black px-4 py-2 text-sm font-semibold hover:bg-zinc-100 disabled:opacity-50"
            >
              Baixar todos
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
          <aside className="border-2 border-black">
            <p className="border-b-2 border-black bg-zinc-50 px-3 py-2 text-sm font-semibold">Prompts</p>
            {loadingPrompts ? <p className="p-3 text-sm text-zinc-600">Carregando...</p> : null}
            {promptsError ? <p className="p-3 text-sm text-red-700">{promptsError}</p> : null}
            <ul className="max-h-[420px] overflow-auto">
              {names.map((name) => (
                <li key={name}>
                  <button
                    type="button"
                    onClick={() => setSelected(name)}
                    className={`block w-full px-3 py-2 text-left text-sm ${
                      selected === name ? "bg-black text-white" : "hover:bg-zinc-100"
                    }`}
                  >
                    {name}
                  </button>
                </li>
              ))}
            </ul>
          </aside>

          <div className="flex min-h-[420px] flex-col border-2 border-black">
            <label htmlFor="prompt-editor" className="border-b-2 border-black bg-zinc-50 px-3 py-2 text-sm font-semibold">
              {selected || "Selecione um prompt"}
            </label>
            <textarea
              id="prompt-editor"
              value={selected ? (prompts[selected] ?? "") : ""}
              onChange={(event) => {
                if (!selected) return;
                setPrompts((prev) => ({ ...prev, [selected]: event.target.value }));
              }}
              disabled={!selected}
              className="min-h-[420px] flex-1 resize-y p-3 font-mono text-sm outline-none"
              spellCheck={false}
            />
          </div>
        </div>

        <div className="mt-10 grid grid-cols-1 gap-8 lg:grid-cols-[minmax(280px,38%)_minmax(0,1fr)]">
          <UploadDropzone
            file={file}
            onFileSelected={(selectedFile) => {
              setFile(selectedFile);
              setResult(null);
              setRunError("");
            }}
          />
          <div className="flex flex-col">
            <label htmlFor="test-isbn" className="mb-2 block text-xl font-semibold text-black">
              ISBN
            </label>
            <input
              id="test-isbn"
              type="text"
              value={isbn}
              onChange={(event) => setIsbn(event.target.value)}
              placeholder="ISBN (opcional)"
              className="w-full border-2 border-black px-3 py-2 text-lg outline-none focus:ring-2 focus:ring-black focus:ring-offset-1"
            />
            <label className="mt-4 flex items-start gap-2.5 text-base text-zinc-800">
              <input
                type="checkbox"
                checked={mioloOnly}
                onChange={(event) => setMioloOnly(event.target.checked)}
                className="mt-0.5 h-5 w-5 shrink-0 appearance-none border-2 border-black bg-white checked:bg-black"
              />
              <span>
                Apenas miolo
                <span className="mt-0.5 block text-xs font-normal text-zinc-600">
                  Usa só o prompt base em todas as páginas (ainda com o texto editado desta área).
                </span>
              </span>
            </label>
            <p className="mt-3 text-xs text-zinc-500">
              O teste roda na hora e pode demorar alguns segundos por página. Use PDFs pequenos.
            </p>
            <button
              type="button"
              disabled={!canSubmit}
              onClick={runTest}
              className={
                running
                  ? "mt-6 cursor-not-allowed rounded-2xl border-2 border-black bg-zinc-400 px-10 py-4 text-xl font-bold text-zinc-800"
                  : "mt-6 rounded-2xl border-2 border-black bg-amber-400 px-10 py-4 text-xl font-bold text-black hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-50"
              }
            >
              {running ? "Rodando teste..." : "Rodar livro com estes prompts"}
            </button>
            {runError ? <p className="mt-3 text-sm text-red-700">{runError}</p> : null}
          </div>
        </div>

        {result ? (
          <div className="mt-10 border-2 border-black">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b-2 border-black bg-zinc-50 px-4 py-3">
              <div className="text-sm text-zinc-700">
                Resultado — {result.stats?.pages ?? 0} página(s), {result.stats?.figures ?? 0} figura(s),{" "}
                {result.stats?.described_ok ?? 0} descrição(ões) ok
                {result.stats?.dorina_failed ? `, ${result.stats.dorina_failed} falha(s) na Dorina` : ""}
              </div>
              <button
                type="button"
                onClick={() =>
                  downloadBlob(
                    new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }),
                    `${resultBaseName}.json`,
                  )
                }
                className="rounded-lg border-2 border-black bg-amber-400 px-4 py-2 text-sm font-semibold hover:bg-amber-300"
              >
                Baixar JSON
              </button>
            </div>
            <pre className="max-h-[520px] overflow-auto p-4 text-xs leading-relaxed">
              {JSON.stringify(result, null, 2)}
            </pre>
          </div>
        ) : null}
      </section>

      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </main>
  );
}
