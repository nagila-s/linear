import base64
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx
from openai import APIError, BadRequestError, NotFoundError, OpenAI
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from src.core.config import get_settings
from src.core.errors import IntegrationError
from src.pipeline.steps.image_credits import omit_image_credits
from src.pipeline.steps.page_completeness import (
    editorial_char_count,
    expand_cut_texts_from_plain,
    format_page_text_context,
    has_usable_conteudo,
    is_linearization_incomplete,
    normalize_page_structure,
    scaffold_page_from_plain_text,
    split_plain_text_chunks,
    split_plain_text_for_columns,
)
from src.pipeline.steps.text_gap_fill import (
    analyze_text_gaps,
    build_gap_fill_prompt,
    preserves_classification,
)
from src.services.prompt_router import PromptRouter
from src.utils.json_codec import looks_truncated_json, merge_json_fragments, parse_llm_json

logger = logging.getLogger(__name__)

# gpt-5 Responses: sem max_output_tokens a saída costuma truncar cedo em páginas densas.
_DEFAULT_LINEARIZE_MAX_OUTPUT_TOKENS = 32768

_COMBINED_FIGURE_SUFFIX = (
    "\n\nRetorne JSON com as chaves page_structure e figure_contexts. "
    "page_structure deve seguir a estrutura deste prompt. "
    "figure_contexts deve ser uma lista de objetos com figure_key e context. "
    "Considere apenas estas figuras: {figure_keys}"
)

_JSON_RETRY_SUFFIX = (
    "\n\nRetorne SOMENTE JSON valido e completo. "
    'Use "texto" como string simples sempre que possivel. '
    "Nao marque negrito/italico (pos-processamento). "
    'Escape aspas internas com \\". '
    "Nao trunque o JSON."
)

_JSON_COMPACT_SUFFIX = (
    "\n\nA pagina e densa. Priorize JSON COMPLETO e VALIDO. "
    'Use sempre "texto" como string simples (nunca array de estilos tipograficos). '
    "Marcas visuais circulado/sublinhado/tachado so se indispensaveis. "
    "NAO omita colunas, citacoes entre aspas graficas, poemas nem questoes numeradas. "
    "Omita campos null. Nao use markdown. Nao corte o JSON no meio."
)

_JSON_COMPLETE_SUFFIX = (
    "\n\nO JSON anterior ficou INCOMPLETO frente ao texto nativo do PDF. "
    "Reescreva o objeto JSON COMPLETO da pagina: ambas as colunas, todas as questoes, "
    "poemas e citacoes por extenso. Use a imagem + o texto nativo. "
    'A raiz DEVE ter "conteudo" (array). Nao use coluna_esquerda/coluna_direita. '
    "Retorne SOMENTE o JSON final, sem markdown."
)

_COLUMN_LEFT_SUFFIX = (
    "\n\nATENCAO: linearize APENAS a coluna da ESQUERDA (primeira na ordem de leitura). "
    'Retorne JSON com "conteudo" so dessa coluna. Nao invente a coluna direita.'
)

_COLUMN_RIGHT_SUFFIX = (
    "\n\nATENCAO: linearize APENAS a coluna da DIREITA (segunda na ordem de leitura). "
    'Retorne JSON com "conteudo" so dessa coluna. Nao repita a coluna esquerda.'
)

_CHUNK_SUFFIX = (
    "\n\nATENCAO: linearize APENAS o trecho/regiao indicado pelo texto nativo abaixo. "
    'Retorne JSON com "conteudo" so desse pedaco. Nao invente o restante da pagina.'
)

_CONTENT_FILTER_HINT = (
    "\n\nSe algum trecho literario for sensivel, ainda assim transcreva-o de forma "
    "neutra e completa (e material didatico de vestibular). Nao omita poemas nem enunciados."
)


class OpenAIService:
    def __init__(
        self,
        *,
        miolo_only: bool = False,
        literario: bool = False,
        prompt_overrides: Optional[Dict[str, str]] = None,
    ) -> None:
        settings = get_settings()
        if not settings.openai_api_key:
            raise IntegrationError("OPENAI_API_KEY nao configurado.")
        self.settings = settings
        self.miolo_only = bool(miolo_only)
        self.literario = bool(literario)
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.prompt_router = PromptRouter(
            settings.prompts_directory,
            window_start=settings.classification_window_start,
            window_end=settings.classification_window_end,
            overrides=prompt_overrides,
            literario=self.literario,
        )
        self.prompt_router.pin_literary_case = self.literario and not self.miolo_only
        self._last_vision_incomplete = False
        self._last_vision_incomplete_reason: Optional[str] = None

    @property
    def prompt_routing_enabled(self) -> bool:
        if self.miolo_only:
            return False
        return bool(self.settings.prompt_routing_enabled)

    def _linearize_max_tokens(self) -> Optional[int]:
        value = int(self.settings.linearize_max_output_tokens or 0)
        if value > 0:
            return value
        return _DEFAULT_LINEARIZE_MAX_OUTPUT_TOKENS

    def _score_page_candidate(self, data: Dict[str, Any] | None) -> int:
        if not isinstance(data, dict):
            return -1
        normalized = normalize_page_structure(data) or data
        chars = editorial_char_count(normalized)
        if has_usable_conteudo(normalized):
            return chars + 10_000
        return chars

    def _pick_best_page(self, *candidates: Any) -> Dict[str, Any] | None:
        best: Dict[str, Any] | None = None
        best_score = -1
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            normalized = normalize_page_structure(candidate) or candidate
            score = self._score_page_candidate(normalized)
            if score > best_score:
                best = normalized
                best_score = score
        return best

    def _continue_truncated_json(
        self,
        page_png: bytes,
        partial: str,
        *,
        page_number: Optional[int] = None,
        page_plain_text: Optional[str] = None,
    ) -> str:
        """Pede ao modelo o JSON completo a partir de um rascunho truncado."""
        clip = partial.strip()
        if len(clip) > 60000:
            clip = clip[:2000] + "\n...\n" + clip[-50000:]
        prompt = (
            "O JSON abaixo foi TRUNCADO no meio. "
            "Reescreva o objeto JSON COMPLETO e VALIDO da pagina, "
            "preservando o conteudo ja presente e completando o que faltou. "
            'A raiz DEVE ter "conteudo" (array de blocos). '
            "Retorne SOMENTE o JSON final (um unico objeto), sem markdown.\n\n"
            f"JSON truncado:\n{clip}"
        )
        prompt += format_page_text_context(page_plain_text or "")
        logger.warning(
            "Continuando JSON truncado pagina=%s partial_chars=%s",
            page_number,
            len(partial),
        )
        return self._ask_vision(
            page_png,
            prompt,
            self.settings.openai_model_linearization,
            json_mode=True,
            max_output_tokens=self._linearize_max_tokens(),
        )

    def _complete_incomplete_json(
        self,
        page_png: bytes,
        partial_data: Dict[str, Any],
        *,
        page_number: Optional[int] = None,
        page_plain_text: Optional[str] = None,
        pdf_char_count: int = 0,
    ) -> Dict[str, Any]:
        """Re-pede linearização quando o JSON parseia mas está curto demais vs PDF."""
        try:
            partial_str = json.dumps(partial_data, ensure_ascii=False)
        except (TypeError, ValueError):
            partial_str = str(partial_data)
        if len(partial_str) > 40000:
            partial_str = partial_str[:8000] + "\n...\n" + partial_str[-20000:]
        json_chars = editorial_char_count(partial_data)
        logger.warning(
            "JSON incompleto pagina=%s json_chars=%s pdf_chars=%s — pedindo completude",
            page_number,
            json_chars,
            pdf_char_count,
        )
        # Se o rascunho é minúsculo/sem conteudo, não peça para "preservar" — reconstrua do PDF.
        if (
            pdf_char_count > 0
            and (json_chars < pdf_char_count * 0.25 or not has_usable_conteudo(partial_data))
        ):
            prompt = (
                "A resposta anterior ficou MUITO incompleta para esta pagina densa. "
                "Gere do ZERO o objeto JSON COMPLETO e VALIDO da pagina usando a imagem "
                "e o texto nativo do PDF. Inclua ambas as colunas, todas as questoes, "
                "poemas e citacoes por extenso. Nao resuma. Nao corte no meio. "
                'A raiz DEVE ter "conteudo" (array). Nao use coluna_esquerda/coluna_direita. '
                "Retorne SOMENTE o JSON final, sem markdown."
            )
            prompt += format_page_text_context(page_plain_text or "")
            prompt += _JSON_COMPLETE_SUFFIX
        else:
            prompt = (
                "O JSON abaixo ficou INCOMPLETO em relacao ao texto nativo do PDF "
                f"(cobertura ~{json_chars}/{pdf_char_count} caracteres). "
                "Reescreva o objeto JSON COMPLETO e VALIDO da pagina: "
                "ambas as colunas, todas as questoes numeradas, poemas e citacoes por extenso. "
                "A imagem define a hierarquia; o texto nativo evita omissao. "
                'A raiz DEVE ter "conteudo" (array). '
                "Retorne SOMENTE o JSON final, sem markdown.\n\n"
                f"JSON incompleto:\n{partial_str}"
            )
            prompt += format_page_text_context(page_plain_text or "")
            prompt += _JSON_COMPLETE_SUFFIX
        content = self._ask_vision(
            page_png,
            prompt,
            self.settings.openai_model_linearization,
            json_mode=True,
            max_output_tokens=self._linearize_max_tokens(),
        )
        return self._parse_linearization_content(
            content,
            page_png,
            page_number=page_number,
            page_plain_text=page_plain_text,
            allow_continue=True,
        )

    def _linearize_columns_separately(
        self,
        page_png: bytes,
        prompt: str,
        *,
        page_number: Optional[int] = None,
        page_plain_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Último recurso: lineariza esquerda e direita em chamadas separadas e une conteudo."""
        left_text, right_text = split_plain_text_for_columns(page_plain_text or "")
        logger.warning(
            "Linearizacao por colunas pagina=%s left_chars=%s right_chars=%s",
            page_number,
            len(left_text),
            len(right_text),
        )
        max_tokens = self._linearize_max_tokens()
        left_raw = self._ask_vision(
            page_png,
            prompt + format_page_text_context(left_text) + _COLUMN_LEFT_SUFFIX + _CONTENT_FILTER_HINT,
            self.settings.openai_model_linearization,
            json_mode=True,
            max_output_tokens=max_tokens,
        )
        left_allow = self._last_vision_incomplete_reason != "content_filter"
        right_raw = self._ask_vision(
            page_png,
            prompt + format_page_text_context(right_text) + _COLUMN_RIGHT_SUFFIX + _CONTENT_FILTER_HINT,
            self.settings.openai_model_linearization,
            json_mode=True,
            max_output_tokens=max_tokens,
        )
        right_allow = self._last_vision_incomplete_reason != "content_filter"
        left = normalize_page_structure(
            self._parse_linearization_content(
                left_raw,
                page_png,
                page_number=page_number,
                page_plain_text=left_text,
                allow_continue=left_allow,
            )
        ) or {}
        right = normalize_page_structure(
            self._parse_linearization_content(
                right_raw,
                page_png,
                page_number=page_number,
                page_plain_text=right_text,
                allow_continue=right_allow,
            )
        ) or {}
        merged = dict(left)
        left_blocks = list(left.get("conteudo") or []) if isinstance(left.get("conteudo"), list) else []
        right_blocks = list(right.get("conteudo") or []) if isinstance(right.get("conteudo"), list) else []
        merged["conteudo"] = left_blocks + right_blocks
        if "pagina" not in merged and isinstance(right.get("pagina"), (int, str)):
            merged["pagina"] = right.get("pagina")
        return merged

    def _linearize_in_chunks(
        self,
        page_png: bytes,
        prompt: str,
        *,
        page_number: Optional[int] = None,
        page_plain_text: Optional[str] = None,
        parts: int = 4,
    ) -> Dict[str, Any]:
        """Lineariza pedaços menores do texto nativo (útil quando content_filter corta cedo)."""
        chunks = split_plain_text_chunks(page_plain_text or "", parts=parts)
        logger.warning(
            "Linearizacao em pedacos pagina=%s parts=%s sizes=%s",
            page_number,
            len(chunks),
            [len(c) for c in chunks],
        )
        max_tokens = self._linearize_max_tokens()
        all_blocks: list[Any] = []
        meta: Dict[str, Any] = {}
        for idx, chunk in enumerate(chunks):
            raw = self._ask_vision(
                page_png,
                prompt
                + format_page_text_context(chunk)
                + _CHUNK_SUFFIX
                + _CONTENT_FILTER_HINT
                + f"\n\nPedaco {idx + 1}/{len(chunks)}.",
                self.settings.openai_model_linearization,
                json_mode=True,
                max_output_tokens=max_tokens,
            )
            # Em content_filter, continue só re-dispara o filtro — parse sem continue.
            allow = self._last_vision_incomplete_reason != "content_filter"
            part = normalize_page_structure(
                self._parse_linearization_content(
                    raw,
                    page_png,
                    page_number=page_number,
                    page_plain_text=chunk,
                    allow_continue=allow,
                )
            ) or {}
            if not meta and isinstance(part, dict):
                meta = {k: v for k, v in part.items() if k != "conteudo"}
            blocks = part.get("conteudo") if isinstance(part.get("conteudo"), list) else []
            all_blocks.extend(blocks)
        merged = dict(meta)
        merged["conteudo"] = all_blocks
        return merged

    def _parse_linearization_content(
        self,
        content: str,
        page_png: bytes,
        *,
        page_number: Optional[int] = None,
        page_plain_text: Optional[str] = None,
        force_continue: bool = False,
        allow_continue: bool = True,
    ) -> Dict[str, Any]:
        truncated = force_continue or looks_truncated_json(content)
        parsed: Dict[str, Any] | None = None
        try:
            parsed = normalize_page_structure(
                self._extract_json(content, page_number=page_number)
            )
        except IntegrationError:
            truncated = True

        if parsed is not None and not truncated:
            return parsed

        # content_filter: continuar o mesmo rascunho costuma repetir o corte.
        if self._last_vision_incomplete_reason == "content_filter":
            if parsed is not None:
                return parsed
            raise IntegrationError(
                "OpenAI interrompeu por content_filter na linearizacao."
            )

        if not allow_continue or not content or not str(content).strip():
            if parsed is not None:
                return parsed
            raise IntegrationError("Resposta vazia na linearizacao.")

        try:
            continued = self._continue_truncated_json(
                page_png,
                content,
                page_number=page_number,
                page_plain_text=page_plain_text,
            )
        except IntegrationError:
            if parsed is not None:
                return parsed
            raise

        if self._last_vision_incomplete_reason == "content_filter":
            try:
                cont_parsed = normalize_page_structure(
                    self._extract_json(continued, page_number=page_number)
                )
            except IntegrationError:
                cont_parsed = None
            best = self._pick_best_page(cont_parsed, parsed)
            if best is not None:
                return best
            if parsed is not None:
                return parsed
            raise IntegrationError("OpenAI interrompeu por content_filter na continuacao.")

        # Uma segunda chance se a continuacao ainda veio truncada (sem recursao profunda).
        cont_parsed = None
        try:
            if (
                looks_truncated_json(continued)
                or self._last_vision_incomplete
            ) and self._last_vision_incomplete_reason != "content_filter":
                continued2 = self._continue_truncated_json(
                    page_png,
                    continued,
                    page_number=page_number,
                    page_plain_text=page_plain_text,
                )
                cont_parsed = normalize_page_structure(
                    self._extract_json(continued2, page_number=page_number)
                )
                continued = continued2
            else:
                cont_parsed = normalize_page_structure(
                    self._extract_json(continued, page_number=page_number)
                )
        except IntegrationError:
            cont_parsed = None

        merged = merge_json_fragments(content, continued)
        candidates: list[Any] = [cont_parsed, parsed]
        for candidate in (continued, merged, content):
            try:
                candidates.append(
                    normalize_page_structure(
                        self._extract_json(candidate, page_number=page_number)
                    )
                )
            except IntegrationError:
                continue
        best = self._pick_best_page(*candidates)
        if best is not None:
            return best
        raise IntegrationError("Falha ao reparar JSON truncado na linearizacao.")

    def _recover_if_incomplete(
        self,
        page_png: bytes,
        raw_content: str,
        data: Dict[str, Any],
        *,
        page_number: Optional[int] = None,
        page_plain_text: Optional[str] = None,
        pdf_char_count: int = 0,
        force_continue: bool = False,
        base_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Se o JSON ficou curto, recupera: continue → rebuild → colunas → pedaços → scaffold."""
        data = normalize_page_structure(data) or data
        already_ok = (
            not is_linearization_incomplete(data, pdf_char_count=pdf_char_count)
            and not force_continue
        )
        if already_ok:
            return self._finalize_with_pdf_expand(data, page_plain_text, page_number)

        before = editorial_char_count(data)
        raw = (raw_content or "").strip()
        try:
            dumped = json.dumps(data, ensure_ascii=False)
        except (TypeError, ValueError):
            dumped = ""

        filtered = self._last_vision_incomplete_reason == "content_filter"
        should_continue_raw = (
            not filtered
            and (
                force_continue
                or looks_truncated_json(raw)
                or (len(raw) > max(len(dumped) * 1.3, before + 200))
            )
        )
        if before < max(200, int(pdf_char_count * 0.15)) and not looks_truncated_json(raw):
            should_continue_raw = False

        if should_continue_raw and raw:
            try:
                continued = self._continue_truncated_json(
                    page_png,
                    raw,
                    page_number=page_number,
                    page_plain_text=page_plain_text,
                )
                recovered = self._parse_linearization_content(
                    continued,
                    page_png,
                    page_number=page_number,
                    page_plain_text=page_plain_text,
                    allow_continue=True,
                )
                after = editorial_char_count(recovered)
                if after > before * 1.15 and has_usable_conteudo(recovered):
                    logger.info(
                        "Recuperacao via continue RAW pagina=%s %s→%s chars",
                        page_number,
                        before,
                        after,
                    )
                    data = recovered
                    before = after
            except IntegrationError as exc:
                logger.warning("Continue RAW falhou pagina=%s: %s", page_number, exc)

        try:
            completed = self._complete_incomplete_json(
                page_png,
                data,
                page_number=page_number,
                page_plain_text=page_plain_text,
                pdf_char_count=pdf_char_count,
            )
            after = editorial_char_count(completed)
            if after > before * 1.15 and (
                has_usable_conteudo(completed) or after > before
            ):
                logger.info(
                    "Completude ok pagina=%s %s→%s chars",
                    page_number,
                    before,
                    after,
                )
                data = completed
                before = after
            else:
                logger.warning(
                    "Completude descartada pagina=%s (antes=%s depois=%s) — mantendo original",
                    page_number,
                    before,
                    after,
                )
        except IntegrationError as exc:
            logger.warning(
                "Completude falhou pagina=%s: %s — mantendo JSON parcial",
                page_number,
                exc,
            )

        if base_prompt and is_linearization_incomplete(data, pdf_char_count=pdf_char_count):
            try:
                by_cols = self._linearize_columns_separately(
                    page_png,
                    base_prompt + _CONTENT_FILTER_HINT,
                    page_number=page_number,
                    page_plain_text=page_plain_text,
                )
                after = editorial_char_count(by_cols)
                if after > before * 1.15 and has_usable_conteudo(by_cols):
                    logger.info(
                        "Recuperacao por colunas pagina=%s %s→%s chars",
                        page_number,
                        before,
                        after,
                    )
                    data = by_cols
                    before = after
                else:
                    logger.warning(
                        "Colunas descartadas pagina=%s (antes=%s depois=%s)",
                        page_number,
                        before,
                        after,
                    )
            except IntegrationError as exc:
                logger.warning("Linearizacao por colunas falhou pagina=%s: %s", page_number, exc)

        if base_prompt and is_linearization_incomplete(data, pdf_char_count=pdf_char_count):
            try:
                by_chunks = self._linearize_in_chunks(
                    page_png,
                    base_prompt,
                    page_number=page_number,
                    page_plain_text=page_plain_text,
                    parts=4,
                )
                after = editorial_char_count(by_chunks)
                if after > before * 1.15 and has_usable_conteudo(by_chunks):
                    logger.info(
                        "Recuperacao por pedacos pagina=%s %s→%s chars",
                        page_number,
                        before,
                        after,
                    )
                    data = by_chunks
                    before = after
                else:
                    logger.warning(
                        "Pedacos descartados pagina=%s (antes=%s depois=%s)",
                        page_number,
                        before,
                        after,
                    )
            except IntegrationError as exc:
                logger.warning("Linearizacao em pedacos falhou pagina=%s: %s", page_number, exc)

        if (
            page_plain_text
            and is_linearization_incomplete(data, pdf_char_count=pdf_char_count)
        ):
            filled = self.fill_text_gaps_if_needed(
                page_png,
                data,
                page_plain_text,
                page_number=page_number,
            )
            after = editorial_char_count(filled)
            if after > before and not is_linearization_incomplete(
                filled, pdf_char_count=pdf_char_count
            ):
                logger.info(
                    "Recuperacao via text_gap_fill pagina=%s %s→%s chars",
                    page_number,
                    before,
                    after,
                )
                data = filled
                before = after

        if (
            page_plain_text
            and is_linearization_incomplete(data, pdf_char_count=pdf_char_count)
        ):
            scaffold = scaffold_page_from_plain_text(
                page_plain_text,
                page_number=page_number,
                printed_page=data.get("pagina") if isinstance(data.get("pagina"), int) else None,
            )
            after = editorial_char_count(scaffold)
            if after > before * 1.05:
                logger.warning(
                    "Fallback texto nativo PDF pagina=%s %s→%s chars (reason=%s)",
                    page_number,
                    before,
                    after,
                    self._last_vision_incomplete_reason,
                )
                data = scaffold

        return self._finalize_with_pdf_expand(data, page_plain_text, page_number)

    def _finalize_with_pdf_expand(
        self,
        data: Dict[str, Any],
        page_plain_text: Optional[str],
        page_number: Optional[int],
    ) -> Dict[str, Any]:
        """Último passo: completa strings cortadas com o texto nativo do PDF."""
        if not page_plain_text:
            return data
        before = editorial_char_count(data)
        expanded = expand_cut_texts_from_plain(data, page_plain_text)
        if not isinstance(expanded, dict):
            return data
        after = editorial_char_count(expanded)
        if after > before * 1.05:
            logger.info(
                "Expandiu textos cortados via PDF pagina=%s %s→%s chars",
                page_number,
                before,
                after,
            )
            return expanded
        return data

    def fill_text_gaps_if_needed(
        self,
        page_png: bytes,
        page_structure: Dict[str, Any],
        page_plain_text: Optional[str],
        *,
        page_number: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Insere texto do PDF ausente no JSON, sem reclassificar blocos existentes."""
        if not getattr(self.settings, "text_gap_fill_enabled", True):
            return page_structure
        if not isinstance(page_structure, dict) or not (page_plain_text or "").strip():
            return page_structure

        report = analyze_text_gaps(page_structure, page_plain_text or "")
        if not report.needs_fill:
            return page_structure

        prompt = build_gap_fill_prompt(page_structure, page_plain_text or "", report.missing_spans)
        max_tokens = int(getattr(self.settings, "text_gap_fill_max_output_tokens", 0) or 16384)
        logger.info(
            "text_gap_fill pagina=%s missing_spans=%s missing_chars=%s json_chars=%s pdf_chars=%s",
            page_number,
            len(report.missing_spans),
            report.missing_chars,
            report.json_chars,
            report.pdf_chars,
        )
        try:
            raw = self._ask_vision(
                page_png,
                prompt,
                self.settings.openai_model_classifier,
                json_mode=True,
                max_output_tokens=max_tokens,
                use_reasoning=False,
            )
            patched = normalize_page_structure(
                self._extract_json(raw, page_number=page_number)
            )
        except Exception as exc:
            logger.warning("text_gap_fill falhou pagina=%s: %s — mantendo JSON original", page_number, exc)
            return page_structure

        if not isinstance(patched, dict) or not has_usable_conteudo(patched):
            logger.warning("text_gap_fill descartado pagina=%s: JSON sem conteudo", page_number)
            return page_structure
        if not preserves_classification(page_structure, patched):
            logger.warning(
                "text_gap_fill descartado pagina=%s: classificacao dos blocos foi alterada",
                page_number,
            )
            return page_structure

        before = editorial_char_count(page_structure)
        after = editorial_char_count(patched)
        if after < before:
            logger.warning(
                "text_gap_fill descartado pagina=%s: texto encolheu %s→%s",
                page_number,
                before,
                after,
            )
            return page_structure

        for key in ("tipo_pagina", "pagina", "prompt_version", "prompt_file", "prompt_hash"):
            if key in page_structure and key not in patched:
                patched[key] = page_structure[key]
            elif key in page_structure and key == "tipo_pagina":
                patched[key] = page_structure[key]

        logger.info(
            "text_gap_fill ok pagina=%s %s→%s chars spans=%s",
            page_number,
            before,
            after,
            len(report.missing_spans),
        )
        return patched

    @retry(
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_not_exception_type(IntegrationError),
        reraise=True,
    )
    def linearize_page(
        self,
        page_png: bytes,
        prompt_version: str,
        *,
        page_number: Optional[int] = None,
        total_pages: Optional[int] = None,
        page_type: Optional[str] = None,
        page_plain_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        if page_type is None:
            prompt, page_type = self._resolve_linearization(page_png, page_number, total_pages)
        else:
            prompt = self.prompt_router.get_prompt(page_type)

        text_block = format_page_text_context(page_plain_text or "")
        pdf_char_count = len((page_plain_text or "").strip())
        base = prompt + text_block
        attempt_prompts = (
            base,
            base + _JSON_RETRY_SUFFIX,
            base + _JSON_COMPACT_SUFFIX,
        )
        last_error: IntegrationError | None = None
        max_tokens = self._linearize_max_tokens()
        for attempt, extra in enumerate(attempt_prompts):
            try:
                content = self._ask_vision(
                    page_png,
                    extra,
                    self.settings.openai_model_linearization,
                    json_mode=True,
                    max_output_tokens=max_tokens,
                )
            except IntegrationError as exc:
                last_error = exc
                logger.warning(
                    "Falha na chamada OpenAI pagina=%s attempt=%s: %s",
                    page_number,
                    attempt + 1,
                    exc,
                )
                continue
            api_incomplete = bool(self._last_vision_incomplete)
            try:
                data = self._parse_linearization_content(
                    content,
                    page_png,
                    page_number=page_number,
                    page_plain_text=page_plain_text,
                    force_continue=api_incomplete,
                )
            except IntegrationError as exc:
                last_error = exc
                logger.warning(
                    "JSON invalido na pagina %s (attempt=%s); retry com prompt reforcado/compacto.",
                    page_number,
                    attempt + 1,
                )
                continue

            data = self._recover_if_incomplete(
                page_png,
                content,
                data,
                page_number=page_number,
                page_plain_text=page_plain_text,
                pdf_char_count=pdf_char_count,
                force_continue=api_incomplete,
                base_prompt=prompt,
            )

            self._apply_page_metadata(data, page_type, prompt_version)
            data = self.fill_text_gaps_if_needed(
                page_png,
                data,
                page_plain_text,
                page_number=page_number,
            )
            if attempt > 0:
                logger.info(
                    "pagina=%s linearizada apos retry attempt=%s",
                    page_number,
                    attempt + 1,
                )
            cleaned = omit_image_credits(data)
            return cleaned if isinstance(cleaned, dict) else data

        if last_error is not None:
            raise last_error
        raise IntegrationError("Falha ao linearizar pagina.")

    @retry(
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_not_exception_type(IntegrationError),
        reraise=True,
    )
    def extract_context(
        self,
        page_png: bytes,
        figure_keys: List[str],
        prompt_version: str,
    ) -> Dict[str, str]:
        prompt = (
            "Para cada figura desta pagina, gere contexto textual util para descricao acessivel. "
            f'Retorne JSON no formato {{"figures": [{{"figure_key": "...", "context": "..."}}]}}. '
            f"Considere apenas estas figuras: {figure_keys}"
        )
        content = self._ask_vision(page_png, prompt, self.settings.openai_model_context, json_mode=True)
        data = self._extract_json(content)
        figures = data.get("figures", [])
        output: Dict[str, str] = {}
        for item in figures:
            key = item.get("figure_key")
            context = item.get("context", "")
            if key:
                output[key] = context
        for key in figure_keys:
            output.setdefault(key, "")
        return output

    def resolve_page_type(
        self,
        page_png: bytes,
        *,
        page_number: Optional[int] = None,
        total_pages: Optional[int] = None,
    ) -> str:
        _, page_type = self._resolve_linearization(page_png, page_number, total_pages)
        return page_type

    def linearize_and_extract_context(
        self,
        page_png: bytes,
        figure_keys: List[str],
        prompt_version: str,
        *,
        page_number: Optional[int] = None,
        total_pages: Optional[int] = None,
        page_type: Optional[str] = None,
        page_plain_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        if page_type is None:
            page_type = self.resolve_page_type(
                page_png,
                page_number=page_number,
                total_pages=total_pages,
            )
        if self.prompt_router.should_skip_figure_pipeline(page_type):
            return {
                "page_structure": self.linearize_page(
                    page_png,
                    prompt_version,
                    page_number=page_number,
                    total_pages=total_pages,
                    page_type=page_type,
                    page_plain_text=page_plain_text,
                ),
                "figure_contexts": {},
            }

        if not self.settings.openai_combined_mode:
            return {
                "page_structure": self.linearize_page(
                    page_png,
                    prompt_version,
                    page_number=page_number,
                    total_pages=total_pages,
                    page_type=page_type,
                    page_plain_text=page_plain_text,
                ),
                "figure_contexts": self.extract_context(page_png, figure_keys, prompt_version),
            }

        prompt = self.prompt_router.get_prompt(page_type)
        combined_prompt = (
            prompt
            + format_page_text_context(page_plain_text or "")
            + _COMBINED_FIGURE_SUFFIX.format(figure_keys=figure_keys)
        )
        content = self._ask_vision(
            page_png,
            combined_prompt,
            self.settings.openai_model_linearization,
            json_mode=True,
        )
        data = self._extract_json(content, page_number=page_number)
        page_structure = data.get("page_structure")
        contexts_raw = data.get("figure_contexts", [])
        if not isinstance(page_structure, dict) or not isinstance(contexts_raw, list):
            return {
                "page_structure": self.linearize_page(
                    page_png,
                    prompt_version,
                    page_number=page_number,
                    total_pages=total_pages,
                    page_type=page_type,
                    page_plain_text=page_plain_text,
                ),
                "figure_contexts": self.extract_context(page_png, figure_keys, prompt_version),
            }

        contexts: Dict[str, str] = {}
        for item in contexts_raw:
            if not isinstance(item, dict):
                continue
            key = str(item.get("figure_key", "")).strip()
            if key:
                contexts[key] = str(item.get("context", ""))
        for key in figure_keys:
            contexts.setdefault(key, "")

        pdf_char_count = len((page_plain_text or "").strip())
        page_structure = self._recover_if_incomplete(
            page_png,
            content,
            page_structure if isinstance(page_structure, dict) else {},
            page_number=page_number,
            page_plain_text=page_plain_text,
            pdf_char_count=pdf_char_count,
            base_prompt=prompt,
        )

        self._apply_page_metadata(page_structure, page_type, prompt_version)
        page_structure = self.fill_text_gaps_if_needed(
            page_png,
            page_structure,
            page_plain_text,
            page_number=page_number,
        )
        cleaned = omit_image_credits(page_structure)
        if isinstance(cleaned, dict):
            page_structure = cleaned
        return {"page_structure": page_structure, "figure_contexts": contexts}

    def _resolve_linearization(
        self,
        page_png: bytes,
        page_number: Optional[int],
        total_pages: Optional[int],
    ) -> Tuple[str, str]:
        if (
            not self.prompt_routing_enabled
            or page_number is None
            or total_pages is None
            or total_pages <= 0
        ):
            return self.prompt_router.get_prompt("conteudo"), "conteudo"

        if not self.prompt_router.should_classify(page_number, total_pages):
            page_type = "conteudo"
        else:
            classified = self._classify_page_type(page_png)
            page_type = self.prompt_router.resolve_page_type(page_number, total_pages, classified)
            logger.info(
                "page=%s/%s classified=%s routed=%s",
                page_number,
                total_pages,
                classified,
                page_type,
            )

        return self.prompt_router.get_prompt(page_type), page_type

    def _classify_page_type(self, page_png: bytes) -> str:
        content = self._ask_vision(
            page_png,
            self.prompt_router.classifier_prompt,
            self.settings.openai_model_classifier,
            max_output_tokens=self.settings.classifier_max_output_tokens,
        )
        return self.prompt_router.normalize_page_type(content)

    def _apply_page_metadata(self, data: Dict[str, Any], page_type: str, prompt_version: str) -> None:
        if self.literario and not self.miolo_only and page_type:
            data["tipo_pagina"] = page_type
        else:
            data.setdefault("tipo_pagina", page_type)
        data["prompt_version"] = prompt_version

    def _ask_vision(
        self,
        png_bytes: bytes,
        prompt: str,
        model: str,
        *,
        max_output_tokens: Optional[int] = None,
        json_mode: bool = False,
        use_reasoning: Optional[bool] = None,
    ) -> str:
        self._last_vision_incomplete = False
        self._last_vision_incomplete_reason = None
        image_b64 = base64.b64encode(png_bytes).decode("utf-8")
        reasoning = json_mode if use_reasoning is None else use_reasoning
        if self.settings.openai_prefer_responses_api:
            content = self._ask_vision_with_responses(
                image_b64,
                prompt,
                model,
                max_output_tokens=max_output_tokens,
                json_mode=json_mode,
                use_reasoning=reasoning,
            )
            if not content:
                raise IntegrationError("OpenAI retornou resposta vazia.")
            return content

        try:
            kwargs: Dict[str, Any] = {
                "model": model,
                "temperature": 0.1,
                "messages": [
                    {"role": "system", "content": "Voce responde em JSON valido, sem markdown."},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{image_b64}", "detail": "high"},
                            },
                        ],
                    },
                ],
            }
            if max_output_tokens is not None:
                kwargs["max_tokens"] = max_output_tokens
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            response = self.client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            finish = str(getattr(response.choices[0], "finish_reason", "") or "").lower()
            if finish in {"length", "max_tokens", "content_filter"}:
                self._last_vision_incomplete = True
                self._last_vision_incomplete_reason = finish
        except (BadRequestError, NotFoundError, APIError) as exc:
            message = str(exc)
            if "not a chat model" not in message:
                raise
            content = self._ask_vision_with_responses(
                image_b64,
                prompt,
                model,
                max_output_tokens=max_output_tokens,
                json_mode=json_mode,
                use_reasoning=reasoning,
            )

        if not content:
            raise IntegrationError("OpenAI retornou resposta vazia.")
        return content

    def _reasoning_kwargs(self, *, use_reasoning: bool) -> Dict[str, Any]:
        if not use_reasoning:
            return {}
        effort = (self.settings.openai_reasoning_effort or "").strip().lower()
        if not effort or effort == "none":
            return {"reasoning": {"effort": "none"}}
        return {"reasoning": {"effort": effort}}

    def _ask_vision_with_responses(
        self,
        image_b64: str,
        prompt: str,
        model: str,
        *,
        max_output_tokens: Optional[int] = None,
        json_mode: bool = False,
        use_reasoning: bool = False,
    ) -> str:
        responses = getattr(self.client, "responses", None)
        create = getattr(responses, "create", None) if responses is not None else None
        if callable(create):
            try:
                kwargs: Dict[str, Any] = {
                    "model": model,
                    "input": [
                        {
                            "role": "system",
                            "content": [{"type": "input_text", "text": "Voce responde em JSON valido, sem markdown."}],
                        },
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": prompt},
                                {"type": "input_image", "image_url": f"data:image/png;base64,{image_b64}"},
                            ],
                        },
                    ],
                }
                if max_output_tokens is not None:
                    kwargs["max_output_tokens"] = max_output_tokens
                if json_mode:
                    kwargs["text"] = {"format": {"type": "json_object"}}
                kwargs.update(self._reasoning_kwargs(use_reasoning=use_reasoning))
                response = create(**kwargs)
                status = str(getattr(response, "status", "") or "").lower()
                if status == "incomplete":
                    self._last_vision_incomplete = True
                    details = getattr(response, "incomplete_details", None)
                    reason = getattr(details, "reason", None) if details is not None else None
                    if isinstance(details, dict):
                        reason = details.get("reason", reason)
                    self._last_vision_incomplete_reason = str(reason or "incomplete")
                    logger.warning(
                        "OpenAI responses incomplete model=%s reason=%s",
                        model,
                        reason,
                    )
                output_text = getattr(response, "output_text", None)
                if output_text:
                    return str(output_text).strip()

                output = getattr(response, "output", [])
                texts: List[str] = []
                for item in output:
                    content = getattr(item, "content", [])
                    for part in content:
                        if getattr(part, "type", "") in ("output_text", "text"):
                            text_value = getattr(part, "text", "")
                            if text_value:
                                texts.append(text_value)
                merged = "\n".join(texts).strip()
                if merged:
                    return merged
                if status == "incomplete":
                    raise IntegrationError(
                        f"OpenAI retornou resposta incompleta (reason={reason or 'unknown'})."
                    )
            except AttributeError:
                pass

        return self._ask_vision_with_responses_http(
            image_b64,
            prompt,
            model,
            max_output_tokens=max_output_tokens,
            json_mode=json_mode,
            use_reasoning=use_reasoning,
        )

    def _ask_vision_with_responses_http(
        self,
        image_b64: str,
        prompt: str,
        model: str,
        *,
        max_output_tokens: Optional[int] = None,
        json_mode: bool = False,
        use_reasoning: bool = False,
    ) -> str:
        """Chama POST /v1/responses quando o SDK OpenAI instalado nao expoe client.responses."""
        url = "https://api.openai.com/v1/responses"
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": model,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": "Voce responde em JSON valido, sem markdown."}],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": f"data:image/png;base64,{image_b64}"},
                    ],
                },
            ],
        }
        if max_output_tokens is not None:
            payload["max_output_tokens"] = max_output_tokens
        if json_mode:
            payload["text"] = {"format": {"type": "json_object"}}
        payload.update(self._reasoning_kwargs(use_reasoning=use_reasoning))
        timeout = httpx.Timeout(600.0, connect=30.0)
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            raw = (response.text or "").strip()
            if not raw:
                raise IntegrationError("OpenAI responses API (HTTP) retornou corpo vazio.")
            try:
                data = response.json()
            except ValueError as exc:
                raise IntegrationError(
                    f"OpenAI responses API (HTTP) retornou JSON invalido: {raw[:300]}"
                ) from exc
        status = str(data.get("status") or "").lower()
        if status == "incomplete":
            self._last_vision_incomplete = True
            details = data.get("incomplete_details") or {}
            reason = details.get("reason") if isinstance(details, dict) else None
            self._last_vision_incomplete_reason = str(reason or "incomplete")
            logger.warning(
                "OpenAI responses incomplete (HTTP) model=%s reason=%s",
                model,
                reason,
            )
        text = self._parse_responses_api_json(data)
        if text:
            return text
        if status == "incomplete":
            details = data.get("incomplete_details") or {}
            reason = details.get("reason") if isinstance(details, dict) else None
            raise IntegrationError(
                f"OpenAI responses API incompleta (reason={reason or 'unknown'})."
            )
        raise IntegrationError("OpenAI responses API (HTTP) retornou saida vazia ou nao reconhecida.")

    @staticmethod
    def _parse_responses_api_json(data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        for key in ("output_text", "text"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        out = data.get("output")
        if not isinstance(out, list):
            return ""
        parts: List[str] = []
        for block in out:
            if not isinstance(block, dict):
                continue
            content = block.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") in ("output_text", "text"):
                    txt = part.get("text")
                    if isinstance(txt, str) and txt.strip():
                        parts.append(txt.strip())
        return "\n".join(parts).strip()

    @staticmethod
    def _extract_json(
        content: str,
        *,
        page_number: Optional[int] = None,
    ) -> Dict[str, Any]:
        try:
            return parse_llm_json(content)
        except json.JSONDecodeError as exc:
            page_hint = f" (pagina {page_number})" if page_number is not None else ""
            preview = content.strip().replace("\n", " ")[:240]
            logger.warning(
                "Falha ao parsear JSON da OpenAI%s: %s | preview=%r",
                page_hint,
                exc,
                preview,
            )
            raise IntegrationError(
                f"A IA retornou JSON invalido na linearizacao{page_hint}. "
                "Reprocesse o job; se persistir, revise o prompt da pagina."
            ) from exc
