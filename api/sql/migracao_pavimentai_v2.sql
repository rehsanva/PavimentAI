-- =====================================================================
-- PavimentAI - migração v2 (antifraude das fotos)
-- Não apaga nada: só acrescenta uma coluna e um índice.
-- Pode ser rodada mais de uma vez sem dar erro.
-- =====================================================================
BEGIN;

-- "Impressão digital" visual da foto (para achar fotos parecidas)
ALTER TABLE public.midias ADD COLUMN IF NOT EXISTS hash_perceptual bigint;

-- Para achar rápido a mesma foto (hash exato) já enviada em qualquer ocorrência
CREATE INDEX IF NOT EXISTS idx_midias_hash_arquivo ON public.midias (hash_arquivo);

COMMIT;
