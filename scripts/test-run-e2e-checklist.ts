/**
 * Smoke/manual checklist da area de testes serverless.
 *
 * Nao roda automaticamente (depende de Supabase + secrets).
 * Use apos aplicar a migration e deploy da Edge Function.
 *
 * 1) Login no site (cookie assinado).
 * 2) Em /testes, altere base.txt com um marcador unico (ex.: "MARCA_TESTE_XYZ").
 * 3) Rode PDF de 2 paginas e de 15 paginas.
 * 4) No final.json:
 *    - test_run === true
 *    - prompt_hash preenchido
 *    - pages[].prompt_hash / prompt_file presentes
 *    - cada pages[].content tem tipo_pagina, pagina, conteudo[]
 * 5) Confirme no Supabase que NAO houve insert em public.jobs.
 * 6) Pare o worker AWS e confirme que o teste ainda completa.
 */

export const TEST_RUN_E2E_CHECKLIST = [
  "cookie assinado",
  "snapshot de prompts",
  "pdf 2 paginas",
  "pdf 15 paginas",
  "final.json com prompt_hash",
  "schema raiz obrigatorio",
  "isolamento de public.jobs",
] as const;
