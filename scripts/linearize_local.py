"""Lineariza um PDF localmente (sem upload ao Supabase)."""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import get_settings
from src.pipeline.steps.preprocess import preprocess_pdf
from src.services.openai_client import OpenAIService


def _load_checkpoint(path: Path, prompt_version: str) -> dict[int, dict]:
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    if str(doc.get("prompt_version")) != prompt_version:
        return {}
    out: dict[int, dict] = {}
    for item in doc.get("pages", []):
        pn = item.get("page_number")
        if isinstance(pn, int) and pn > 0:
            out[pn] = item
    return out


def _save_checkpoint(path: Path, prompt_version: str, pages_by_num: dict[int, dict]) -> None:
    ordered = [pages_by_num[n] for n in sorted(pages_by_num)]
    path.write_text(
        json.dumps({"prompt_version": prompt_version, "pages": ordered}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def linearize_pdf(
    pdf_path: Path,
    output_dir: Path,
    *,
    prompt_version: str | None = None,
    dpi: int | None = None,
    concurrency: int | None = None,
) -> Path:
    settings = get_settings()
    prompt_version = prompt_version or settings.linear_prompt_version
    dpi = dpi or settings.pdf_render_dpi
    concurrency = max(1, concurrency or settings.linearize_page_concurrency)

    output_dir.mkdir(parents=True, exist_ok=True)
    pages_dir = output_dir / "pages"
    pages_dir.mkdir(exist_ok=True)

    checkpoint_path = output_dir / "linear_checkpoint.json"
    final_path = output_dir / "linear.json"

    pdf_bytes = pdf_path.read_bytes()
    pages = preprocess_pdf(pdf_bytes, dpi=dpi)
    for page in pages:
        (pages_dir / page.page_name).write_bytes(page.page_png)

    pages_done = _load_checkpoint(checkpoint_path, prompt_version)
    openai = OpenAIService()

    pending = [p for p in pages if p.page_number not in pages_done]
    if not pending:
        print(f"Todas as {len(pages)} paginas ja estao no checkpoint.")
    else:
        print(f"Linearizando {len(pending)} pagina(s) de {len(pages)} (concorrencia={concurrency})...")

        def _linearize(page):
            content = openai.linearize_page(page.page_png, prompt_version)
            return {"page_number": page.page_number, "content": content}

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(_linearize, p): p.page_number for p in pending}
            done_count = len(pages_done)
            for fut in as_completed(futures):
                entry = fut.result()
                pages_done[entry["page_number"]] = entry
                done_count += 1
                _save_checkpoint(checkpoint_path, prompt_version, pages_done)
                print(f"  [{done_count}/{len(pages)}] pagina {entry['page_number']} ok")

    linearized_pages = [pages_done[n] for n in sorted(pages_done)]
    final_payload = {
        "source_pdf": str(pdf_path.resolve()),
        "isbn": output_dir.name,
        "job_type": "linearizar",
        "prompt_version": prompt_version,
        "dpi": dpi,
        "pages": linearized_pages,
    }
    final_path.write_text(json.dumps(final_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return final_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Lineariza PDF localmente via OpenAI.")
    parser.add_argument("pdf", type=Path, help="Caminho do PDF")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Pasta de saida (padrao: output/<nome-do-pdf>)",
    )
    parser.add_argument("--prompt-version", default=None)
    parser.add_argument("--dpi", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=None)
    args = parser.parse_args()

    pdf_path = args.pdf.resolve()
    if not pdf_path.is_file():
        raise SystemExit(f"PDF nao encontrado: {pdf_path}")

    output_dir = args.output or (ROOT / "output" / pdf_path.stem)
    final = linearize_pdf(
        pdf_path,
        output_dir,
        prompt_version=args.prompt_version,
        dpi=args.dpi,
        concurrency=args.concurrency,
    )
    print(f"Resultado: {final}")


if __name__ == "__main__":
    main()
