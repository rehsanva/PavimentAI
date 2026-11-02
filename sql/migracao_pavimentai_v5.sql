-- =====================================================================
-- PavimentAI - migração v5 (painel do gestor)
-- Não apaga nada. Pode ser rodada mais de uma vez.
-- =====================================================================
BEGIN;

-- Um cidadão não pode sinalizar a mesma coisa duas vezes na mesma ocorrência
-- enquanto a primeira sinalização ainda estiver esperando análise.
CREATE UNIQUE INDEX IF NOT EXISTS uq_sinalizacao_pendente
    ON public.sinalizacoes (id_ocorrencia, id_usuario, motivo)
    WHERE status_analise = 'pendente';

-- Deixa rápida a lista do gestor (ocorrências da cidade, por status, da mais antiga para a mais nova)
CREATE INDEX IF NOT EXISTS idx_ocorrencias_area_status
    ON public.ocorrencias (id_area, status, criado_em);

COMMIT;

-- Conferência: devem aparecer os 2 índices
SELECT indexname FROM pg_indexes
WHERE schemaname = 'public' AND indexname IN ('uq_sinalizacao_pendente', 'idx_ocorrencias_area_status')
ORDER BY indexname;
