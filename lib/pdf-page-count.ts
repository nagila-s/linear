/**
 * Contagem leve de páginas do PDF no navegador (sem renderizar).
 */
export async function countPdfPages(file: File | ArrayBuffer): Promise<number> {
  const pdfjs = await import("pdfjs-dist");
  pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;
  const data = file instanceof File ? await file.arrayBuffer() : file;
  const doc = await pdfjs.getDocument({ data }).promise;
  try {
    return doc.numPages;
  } finally {
    await doc.destroy();
  }
}
