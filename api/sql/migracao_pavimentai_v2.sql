-- =====================================================================
-- PavimentAI - migração v2 (antifraude das fotos)
-- Rodar como o usuário DONO do banco (postgres), no banco "pavimentai".
-- Não apaga nada: só acrescenta uma coluna e um índice.
-- =====================================================================
BEGIN;

-- "Impressão digital" visual da foto (para achar fotos parecidas)
ALTER TABLE public.midias ADD COLUMN hash_perceptual bigint;

-- Para achar rápido a mesma foto (hash exato) já enviada em qualquer ocorrência
CREATE INDEX idx_midias_hash_arquivo ON public.midias (hash_arquivo);

COMMIT;

-- Conferência: deve listar a coluna nova
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'midias' AND column_name = 'hash_perceptual';
