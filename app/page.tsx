"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Header } from "@/components/Header";
import { ProgressModal } from "@/components/ProgressModal";
import { SettingsDrawer } from "@/components/SettingsDrawer";
import { UploadDropzone } from "@/components/UploadDropzone";
import { extractIsbnFromFilename, isValidIsbn, normalizeIsbn } from "@/lib/isbn";
import { slugify } from "@/lib/utils";
import type { IsbnLookupResponse, ProcessStatusResponse } from "@/types";

type LookupState = {
  loading: boolean;
  data: IsbnLookupResponse | null;
};

export default function HomePage() {
  const [file, setFile] = useState<File | null>(null);
  const [isbn, setIsbn] = useState("");
  const [linearize, setLinearize] = useState(true);
  const contextualize = false;
  const [lookup, setLookup] = useState<LookupState>({ loading: false, data: null });
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<ProcessStatusResponse>({
    status: "processing",
    progress: 0,
    message: "Preparando processamento...",
  });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [progressOpen, setProgressOpen] = useState(false);
  const uploadColumnRef = useRef<HTMLDivElement>(null);
  const formColumnRef = useRef<HTMLDivElement>(null);

  const canSubmit = useMemo(() => Boolean(file && linearize), [file, linearize]);

  useEffect(() => {
    const formColumn = formColumnRef.current;
    const uploadColumn = uploadColumnRef.current;
    if (!formColumn || !uploadColumn) return;

    const syncUploadHeight = () => {
      uploadColumn.style.minHeight = `${formColumn.offsetHeight}px`;
    };

    syncUploadHeight();
    const observer = new ResizeObserver(syncUploadHeight);
    observer.observe(formColumn);
    window.addEventListener("resize", syncUploadHeight);

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", syncUploadHeight);
    };
  }, [lookup.loading, lookup.data, file]);

  useEffect(() => {
    const onPaste = (event: ClipboardEvent) => {
      const pastedFile = event.clipboardData?.files?.[0];
      if (!pastedFile) return;
      if (!pastedFile.name.toLowerCase().endsWith(".pdf")) return;
      setFile(pastedFile);
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, []);

  useEffect(() => {
    if (!file || isbn.trim()) return;
    const guess = extractIsbnFromFilename(file.name);
    if (guess) setIsbn(guess);
  }, [file, isbn]);

  useEffect(() => {
    if (!jobId || status.status !== "processing") return;

    const poll = async () => {
      const response = await fetch(`/api/process/${jobId}/status`);
      if (!response.ok) return;
      const payload = (await response.json()) as ProcessStatusResponse;
      setStatus((prev) => ({
        ...payload,
        title: payload.title ?? prev.title,
      }));
    };

    void poll();
    const interval = window.setInterval(poll, 10000);
    return () => window.clearInterval(interval);
  }, [jobId, status.status]);

  return (
    <main className="min-h-screen bg-white">
      <Header onOpenSettings={() => setSettingsOpen(true)} />
      <section className="mx-auto grid max-w-6xl grid-cols-[minmax(320px,38%)_minmax(0,1fr)] items-stretch gap-10 px-8 pb-10 pt-28">
        <div ref={uploadColumnRef} className="flex min-h-0 flex-col">
          <UploadDropzone
            file={file}
            onFileSelected={(selected) => {
              setFile(selected);
              setLookup({ loading: false, data: null });
            }}
          />
        </div>

        <div ref={formColumnRef} className="flex w-full max-w-xl flex-col">
          <div className="mb-4">
            <label className="mb-2 block text-2xl font-semibold text-black">ISBN</label>
            <input
              type="text"
              value={isbn}
              onChange={(event) => setIsbn(event.target.value)}
              onBlur={async () => {
                const normalized = normalizeIsbn(isbn);
                if (!normalized || !isValidIsbn(normalized)) {
                  setLookup({ loading: false, data: null });
                  return;
                }
                setLookup({ loading: true, data: null });
                const response = await fetch(`/api/isbn?isbn=${encodeURIComponent(normalized)}`);
                const payload = (await response.json()) as IsbnLookupResponse;
                setLookup({ loading: false, data: payload });
              }}
              placeholder="ISBN (opcional)"
              className="w-full border-2 border-black px-3 py-2 text-lg outline-none focus:ring-2 focus:ring-black focus:ring-offset-1"
            />
          </div>

          <div className="min-h-[72px] text-sm text-black">
            {lookup.loading ? <p>Consultando ISBN...</p> : null}
            {!lookup.loading && lookup.data?.found ? (
              <div>
                <p className="font-semibold">{lookup.data.title}</p>
                <p>{lookup.data.authors?.join(", ")}</p>
                <p>{lookup.data.publisher}</p>
              </div>
            ) : null}
            {!lookup.loading && lookup.data && !lookup.data.found ? <p>ISBN não encontrado.</p> : null}
          </div>

          <h2 className="mt-4 text-3xl font-semibold leading-tight text-black">
            O que quer fazer com este livro?
          </h2>

          <div className="mt-6 space-y-4 text-xl text-black">
            <label className="flex items-start gap-3">
              <input
                type="checkbox"
                checked={linearize}
                onChange={(event) => setLinearize(event.target.checked)}
                className="mt-0.5 h-6 w-6 shrink-0 appearance-none border-2 border-black bg-white checked:bg-black focus:outline-none focus:ring-2 focus:ring-black focus:ring-offset-1"
              />
              <span>Linearizar e enviar para a Plataforma Braille</span>
            </label>
            <label
              className="flex items-start gap-3 opacity-50"
              title="Ainda não disponível na API"
            >
              <input
                type="checkbox"
                checked={contextualize}
                disabled
                readOnly
                className="mt-0.5 h-6 w-6 shrink-0 appearance-none border-2 border-black bg-white"
              />
              <span>Extrair imagens e contexto e enviar para o Avalia (em breve)</span>
            </label>
          </div>

          <div className="mt-auto pt-8">
          <button
            type="button"
            disabled={!canSubmit}
            onClick={async () => {
              if (!file) return;
              const formData = new FormData();
              formData.append("pdf", file);
              if (isbn.trim()) formData.append("isbn", normalizeIsbn(isbn));
              formData.append("linearize", "true");
              formData.append("contextualize", "false");

              const response = await fetch("/api/process", { method: "POST", body: formData });
              const payload = (await response.json()) as {
                jobId?: string;
                message?: string;
                error?: string;
              };
              if (!response.ok || !payload.jobId) {
                window.alert(payload.error ?? "Não foi possível iniciar o processamento.");
                return;
              }
              setJobId(payload.jobId);
              setProgressOpen(true);
              setStatus({
                status: "processing",
                progress: 5,
                message: payload.message ?? "Processamento iniciado...",
                title: lookup.data?.title ?? file.name.replace(/\.pdf$/i, ""),
              });
            }}
            className="rounded-2xl border-2 border-black bg-amber-400 px-10 py-4 text-xl font-bold text-black hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Linearizar 
          </button>
          </div>
        </div>
      </section>

      <ProgressModal
        open={progressOpen}
        title={status.title || file?.name || "Processando livro"}
        progress={status.progress}
        message={status.message}
        status={status.status}
        onClose={() => setProgressOpen(false)}
        onDownload={() => {
          if (!jobId) return;
          const baseName = slugify(status.title || file?.name?.replace(/\.pdf$/i, "") || "livro");
          const link = document.createElement("a");
          link.href = `/api/process/${jobId}/download?filename=${encodeURIComponent(baseName)}.json`;
          link.click();
        }}
      />

      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </main>
  );
}
