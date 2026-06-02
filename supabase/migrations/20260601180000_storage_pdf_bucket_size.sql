-- Limite por bucket para PDFs (livros didaticos costumam ter 100-500 MB).
-- O teto efetivo ainda depende do "Global file size limit" no dashboard do Supabase:
--   Free: max 50 MB global (use PDF_STORAGE_STRATEGY=auto para cache local)
--   Pro/Team: ate 500 GB global — ajuste em Project Settings > Storage

UPDATE storage.buckets
SET file_size_limit = 524288000
WHERE id = 'pdf';
