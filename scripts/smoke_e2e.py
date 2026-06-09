"""Smoke test da API publica (health + upload opcional)."""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def get(url: str, timeout: int = 30) -> tuple[int, dict | str]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body


def post_multipart(url: str, pdf_path: Path, isbn: str) -> tuple[int, dict]:
    import mimetypes

    boundary = "----linearSmokeBoundary"
    pdf_bytes = pdf_path.read_bytes()
    parts: list[bytes] = []

    def add_field(name: str, value: str) -> None:
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        )

    add_field("job_type", "linearizar")
    add_field("prompt_version", "v1")
    add_field("isbn", isbn)
    mime = mimetypes.guess_type(pdf_path.name)[0] or "application/pdf"
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="pdf_file"; filename="{pdf_path.name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode()
    )
    parts.append(pdf_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)

    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke E2E da API Linear")
    parser.add_argument("--api-url", required=True, help="Base HTTPS da API (sem barra final)")
    parser.add_argument("--pdf", type=Path, help="PDF pequeno para upload de teste")
    parser.add_argument("--isbn", default="9780306406157")
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--max-wait", type=int, default=600)
    args = parser.parse_args()

    base = args.api_url.rstrip("/")
    prefix = "/api/v1"

    print(f"GET {base}/health")
    status, body = get(f"{base}/health")
    if status != 200:
        print(f"FALHOU health: {status} {body}")
        return 1
    print("OK: health")

    if not args.pdf:
        print("Sem --pdf: smoke parou no health. Use --pdf para testar upload.")
        return 0

    if not args.pdf.is_file():
        print(f"PDF nao encontrado: {args.pdf}")
        return 1

    upload_url = f"{base}{prefix}/jobs/upload"
    print(f"POST {upload_url}")
    status, payload = post_multipart(upload_url, args.pdf, args.isbn)
    if status not in (200, 201) or not payload.get("id"):
        print(f"FALHOU upload: {status} {payload}")
        return 1
    job_id = payload["id"]
    print(f"OK: job {job_id}")

    deadline = time.time() + args.max_wait
    while time.time() < deadline:
        status, job = get(f"{base}{prefix}/jobs/{job_id}")
        if status != 200:
            print(f"FALHOU status: {status}")
            return 1
        raw = str(job.get("status", "")).lower()
        print(f"  status={raw} etapa={job.get('etapa_atual', '')}")
        if raw in ("done", "failed"):
            if raw == "failed":
                print("Job falhou:", job.get("error_message"))
                return 1
            print("OK: job concluido")
            return 0
        time.sleep(args.poll_seconds)

    print("TIMEOUT aguardando job")
    return 1


if __name__ == "__main__":
    sys.exit(main())
