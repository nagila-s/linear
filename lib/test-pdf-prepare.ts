/**
 * Renderização de páginas e extração de figuras no navegador (PDF.js).
 * Estratégia alinhada a src/pipeline/steps/pdf_images.py:
 * ocorrências raster via operator list + CTM, recorte da página renderizada,
 * merge de tiles próximos e fallback de página inteira.
 */

export type BBox = { x0: number; y0: number; x1: number; y1: number };

export type ExtractedFigure = {
  figureIndex: number;
  figureKey: string;
  bbox: BBox;
  widthPx: number;
  heightPx: number;
  pngBlob: Blob;
  kind: "raster" | "page_fallback";
};

export type PreparedPage = {
  pageNumber: number;
  widthPx: number;
  heightPx: number;
  pagePngBlob: Blob;
  figures: ExtractedFigure[];
};

export type PreparePdfOptions = {
  dpi?: number;
  maxPages?: number;
  onProgress?: (done: number, total: number) => void;
};

type PdfJsLib = typeof import("pdfjs-dist");

let pdfjsPromise: Promise<PdfJsLib> | null = null;

async function loadPdfJs(): Promise<PdfJsLib> {
  if (!pdfjsPromise) {
    pdfjsPromise = (async () => {
      const pdfjs = await import("pdfjs-dist");
      // Worker via CDN versionado — evita bundling ESM do worker no Next/Webpack.
      pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;
      return pdfjs;
    })();
  }
  return pdfjsPromise;
}

function multiplyMatrices(a: number[], b: number[]): number[] {
  return [
    a[0] * b[0] + a[2] * b[1],
    a[1] * b[0] + a[3] * b[1],
    a[0] * b[1] + a[2] * b[3],
    a[1] * b[1] + a[3] * b[3],
    a[0] * b[4] + a[2] * b[5] + a[4],
    a[1] * b[4] + a[3] * b[5] + a[5],
  ];
}

function transformPoint(ctm: number[], x: number, y: number): [number, number] {
  return [ctm[0] * x + ctm[2] * y + ctm[4], ctm[1] * x + ctm[3] * y + ctm[5]];
}

function bboxFromUnitSquare(ctm: number[]): BBox {
  const corners = [
    transformPoint(ctm, 0, 0),
    transformPoint(ctm, 1, 0),
    transformPoint(ctm, 0, 1),
    transformPoint(ctm, 1, 1),
  ];
  const xs = corners.map((c) => c[0]);
  const ys = corners.map((c) => c[1]);
  return {
    x0: Math.min(...xs),
    y0: Math.min(...ys),
    x1: Math.max(...xs),
    y1: Math.max(...ys),
  };
}

function bboxTooSmall(bbox: BBox, pageWidth: number, pageHeight: number): boolean {
  const w = bbox.x1 - bbox.x0;
  const h = bbox.y1 - bbox.y0;
  if (w < 24 || h < 24) return true;
  if (w / pageWidth > 0.98 && h / pageHeight > 0.98) return true;
  return false;
}

function mergeNearbyBBoxes(boxes: BBox[], gapPt = 14, minCount = 5): BBox[] {
  if (boxes.length < minCount) return boxes;
  const sorted = [...boxes].sort((a, b) => a.y0 - b.y0 || a.x0 - b.x0);
  const used = new Set<number>();
  const merged: BBox[] = [];

  for (let i = 0; i < sorted.length; i++) {
    if (used.has(i)) continue;
    let group = { ...sorted[i] };
    const members = [i];
    for (let j = i + 1; j < sorted.length; j++) {
      if (used.has(j)) continue;
      const other = sorted[j];
      const gapX = Math.max(0, Math.max(group.x0, other.x0) - Math.min(group.x1, other.x1));
      const gapY = Math.max(0, Math.max(group.y0, other.y0) - Math.min(group.y1, other.y1));
      const sameRow = Math.abs((group.y0 + group.y1) / 2 - (other.y0 + other.y1) / 2) < gapPt * 2;
      if ((gapX <= gapPt && sameRow) || (gapY <= gapPt && gapX <= gapPt * 3)) {
        group = {
          x0: Math.min(group.x0, other.x0),
          y0: Math.min(group.y0, other.y0),
          x1: Math.max(group.x1, other.x1),
          y1: Math.max(group.y1, other.y1),
        };
        members.push(j);
      }
    }
    if (members.length >= minCount) {
      for (const m of members) used.add(m);
      merged.push(group);
    } else {
      used.add(i);
      merged.push(sorted[i]);
    }
  }
  return merged;
}

async function canvasToPngBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("Falha ao gerar PNG."))),
      "image/png",
    );
  });
}

function cropCanvas(
  source: HTMLCanvasElement,
  bboxPdf: BBox,
  scale: number,
  pageHeightPdf: number,
): { canvas: HTMLCanvasElement; width: number; height: number } | null {
  // PDF y cresce para cima; canvas y cresce para baixo.
  const x = Math.max(0, Math.floor(bboxPdf.x0 * scale));
  const y = Math.max(0, Math.floor((pageHeightPdf - bboxPdf.y1) * scale));
  const w = Math.min(source.width - x, Math.ceil((bboxPdf.x1 - bboxPdf.x0) * scale));
  const h = Math.min(source.height - y, Math.ceil((bboxPdf.y1 - bboxPdf.y0) * scale));
  if (w < 8 || h < 8) return null;

  const out = document.createElement("canvas");
  out.width = w;
  out.height = h;
  const ctx = out.getContext("2d");
  if (!ctx) return null;
  ctx.drawImage(source, x, y, w, h, 0, 0, w, h);
  return { canvas: out, width: w, height: h };
}

async function extractRasterBBoxes(page: import("pdfjs-dist").PDFPageProxy): Promise<BBox[]> {
  const opList = await page.getOperatorList();
  const OPS = (await loadPdfJs()).OPS;
  let ctm = [1, 0, 0, 1, 0, 0];
  const stack: number[][] = [];
  const boxes: BBox[] = [];

  for (let i = 0; i < opList.fnArray.length; i++) {
    const fn = opList.fnArray[i];
    const args = opList.argsArray[i] as unknown[];

    if (fn === OPS.save) {
      stack.push([...ctm]);
    } else if (fn === OPS.restore) {
      ctm = stack.pop() ?? [1, 0, 0, 1, 0, 0];
    } else if (fn === OPS.transform && Array.isArray(args) && args.length >= 6) {
      ctm = multiplyMatrices(ctm, args as number[]);
    } else if (
      fn === OPS.paintImageXObject ||
      fn === OPS.paintImageMaskXObject ||
      fn === OPS.paintInlineImageXObject ||
      fn === OPS.paintImageXObjectRepeat ||
      fn === OPS.paintXObject
    ) {
      boxes.push(bboxFromUnitSquare(ctm));
    }
  }
  return boxes;
}

export async function preparePdfPages(
  file: File | ArrayBuffer,
  options: PreparePdfOptions = {},
): Promise<PreparedPage[]> {
  const dpi = options.dpi ?? 120;
  const scale = dpi / 72;
  const maxPages = options.maxPages ?? 30;
  const pdfjs = await loadPdfJs();
  const data = file instanceof File ? await file.arrayBuffer() : file;
  const doc = await pdfjs.getDocument({ data }).promise;
  const total = Math.min(doc.numPages, maxPages);
  const pages: PreparedPage[] = [];

  for (let pageNumber = 1; pageNumber <= total; pageNumber++) {
    const page = await doc.getPage(pageNumber);
    const viewport = page.getViewport({ scale });
    const canvas = document.createElement("canvas");
    canvas.width = Math.ceil(viewport.width);
    canvas.height = Math.ceil(viewport.height);
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Canvas 2D indisponivel.");
    await page.render({ canvasContext: ctx, viewport, canvas }).promise;

    const pageHeightPdf = page.getViewport({ scale: 1 }).height;
    const pageWidthPdf = page.getViewport({ scale: 1 }).width;
    let boxes = await extractRasterBBoxes(page);
    boxes = boxes.filter((b) => !bboxTooSmall(b, pageWidthPdf, pageHeightPdf));
    boxes = mergeNearbyBBoxes(boxes);

    const figures: ExtractedFigure[] = [];
    let figureIndex = 0;
    for (const bbox of boxes) {
      const cropped = cropCanvas(canvas, bbox, scale, pageHeightPdf);
      if (!cropped) continue;
      // Descarta faixas minúsculas / quase página inteira já filtradas; área mínima em px
      if (cropped.width * cropped.height < 3600) continue;
      figureIndex += 1;
      figures.push({
        figureIndex,
        figureKey: `fig${figureIndex}`,
        bbox,
        widthPx: cropped.width,
        heightPx: cropped.height,
        pngBlob: await canvasToPngBlob(cropped.canvas),
        kind: "raster",
      });
    }

    if (figures.length === 0) {
      figures.push({
        figureIndex: 1,
        figureKey: "fig1",
        bbox: { x0: 0, y0: 0, x1: pageWidthPdf, y1: pageHeightPdf },
        widthPx: canvas.width,
        heightPx: canvas.height,
        pngBlob: await canvasToPngBlob(canvas),
        kind: "page_fallback",
      });
    }

    pages.push({
      pageNumber,
      widthPx: canvas.width,
      heightPx: canvas.height,
      pagePngBlob: await canvasToPngBlob(canvas),
      figures,
    });

    options.onProgress?.(pageNumber, total);
    page.cleanup();
  }

  await doc.destroy();
  return pages;
}
