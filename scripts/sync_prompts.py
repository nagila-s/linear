"""Sincroniza prompts/*.txt a partir de prompts_especializados.txt."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.prompt_router import PROMPT_FILES, parse_consolidated_prompts

CONSOLIDATED = ROOT / "prompts_especializados.txt"
PROMPTS_DIR = ROOT / "prompts"


def main() -> None:
    sections = parse_consolidated_prompts(CONSOLIDATED.read_text(encoding="utf-8"))
    for key, body in sections.items():
        if key == "classificador":
            (PROMPTS_DIR / "classificador.txt").write_text(body + "\n", encoding="utf-8")
            continue
        filename = PROMPT_FILES.get(key)
        if filename and filename != "base.txt":
            (PROMPTS_DIR / filename).write_text(body + "\n", encoding="utf-8")
    print(f"Sincronizados {len(sections)} blocos em {PROMPTS_DIR}")


if __name__ == "__main__":
    main()
