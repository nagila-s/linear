# Supabase schema assumptions

Este backend assume que as tabelas abaixo existem com colunas compativeis:

- `books`: `isbn` (unique), `metadata` (jsonb), `updated_at`
- `jobs`: `id`, `isbn`, `job_type`, `status`, `etapa_atual`, `tentativas`, `prompt_version`, `metadata`, `error_message`, `final_payload`, `final_json_storage_path`, `created_at`, `updated_at`
- `pages`: `isbn`, `page_number`, `storage_path`, `updated_at`, unique `(isbn, page_number)`
- `figures`: `isbn`, `page_number`, `figure_key`, `storage_path`, `context`, `context_prompt_version`, `updated_at`, unique `(isbn, figure_key)`
- `descriptions`: `figure_key`, `prompt_version`, `payload`, `updated_at`, unique `(figure_key, prompt_version)`
- `exports_pb`: `job_id`, `payload`, `status`
- `exports_avalia`: `job_id`, `payload`, `status`

Se o nome de alguma coluna estiver diferente no banco atual, ajuste os SQLs em:

- `src/repositories/books.py`
- `src/repositories/jobs.py`
- `src/repositories/artifacts.py`
