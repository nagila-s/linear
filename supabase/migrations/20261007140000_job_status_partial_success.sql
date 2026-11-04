-- worker_complete_job (e worker_fail_job, quando a cobertura ja foi publicada)
-- atribuem 'partial_success'::public.job_status. Sem esse valor no enum, o CASE
-- quebra na conclusao de qualquer job — inclusive quando o status pedido e 'done' —
-- e o worker grava a falha mesmo com o final.json ja salvo.

ALTER TYPE public.job_status ADD VALUE IF NOT EXISTS 'partial_success';
