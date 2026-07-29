"use client";

import { useCallback, useId, useRef } from "react";
import { formatBytes } from "@/lib/utils";

type UploadDropzoneProps = {
  file: File | null;
  onFileSelected: (file: File) => void;
};

function isPdf(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

export function UploadDropzone({ file, onFileSelected }: UploadDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const labelId = useId();
  const hintId = useId();

  const readFile = useCallback(
    (selected: File | null) => {
      if (!selected || !isPdf(selected)) return;
      onFileSelected(selected);
    },
    [onFileSelected],
  );

  const openFilePicker = useCallback(() => inputRef.current?.click(), []);

  return (
    <div
      role="button"
      tabIndex={0}
      aria-labelledby={labelId}
      aria-describedby={hintId}
      className="group flex h-full min-h-full w-full flex-1 cursor-pointer flex-col items-center justify-center border-2 border-black bg-white p-6 text-center transition hover:bg-zinc-50 focus:outline-none focus:ring-2 focus:ring-black focus:ring-offset-2"
      onClick={openFilePicker}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openFilePicker();
        }
      }}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        readFile(event.dataTransfer.files?.[0] ?? null);
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,application/pdf"
        className="sr-only"
        aria-labelledby={labelId}
        onChange={(event) => readFile(event.target.files?.[0] ?? null)}
      />
      {!file ? (
        <p id={labelId} className="text-2xl font-medium text-black">
          Upload do PDF
        </p>
      ) : (
        <div className="w-full border-2 border-black bg-white px-3 py-2 text-left">
          <p id={labelId} className="truncate text-sm font-semibold text-black">
            Arquivo selecionado: {file.name}
          </p>
          <p className="text-xs text-zinc-700">{formatBytes(file.size)}</p>
        </div>
      )}
      <p id={hintId} className="mt-4 max-w-[220px] text-sm text-zinc-700">
        Arraste, clique ou cole (Ctrl+V)
      </p>
    </div>
  );
}
