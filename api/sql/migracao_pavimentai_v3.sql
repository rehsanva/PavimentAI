-- =====================================================================
-- PavimentAI - migração v3 (áreas de atendimento / cerca geográfica)
-- Cria a tabela com os limites das cidades atendidas e liga cada
-- ocorrência à sua cidade. Não apaga nada. Pode ser rodada mais de uma vez.
-- =====================================================================
BEGIN;

CREATE TABLE IF NOT EXISTS public.areas_atendimento (
    id_area      integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome         varchar(120) NOT NULL,
    codigo_ibge  varchar(7)   UNIQUE,
    geometria    geography(MultiPolygon, 4326) NOT NULL,
    ativa        boolean      NOT NULL DEFAULT true,
    criado_em    timestamptz  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_areas_atendimento_geom
    ON public.areas_atendimento USING gist (geometria);

-- A API só LÊ as áreas. Quem cadastra ou desativa área é você (como postgres).
GRANT SELECT ON public.areas_atendimento TO pavimentai_app;

-- Cada ocorrência guarda em qual cidade/área foi registrada
ALTER TABLE public.ocorrencias
    ADD COLUMN IF NOT EXISTS id_area integer REFERENCES public.areas_atendimento (id_area);
CREATE INDEX IF NOT EXISTS idx_ocorrencias_area ON public.ocorrencias (id_area);

-- Cada gestor pertence a uma cidade/área (usado na parte do gestor)
ALTER TABLE public.usuarios
    ADD COLUMN IF NOT EXISTS id_area_gestao integer REFERENCES public.areas_atendimento (id_area);

-- View do mapa: agora com a área no final (permite filtrar por cidade)
CREATE OR REPLACE VIEW public.vw_mapa_ocorrencias AS
SELECT
    o.id_ocorrencia,
    o.tipo,
    o.categoria,
    o.status,
    o.canal_registro,
    o.latitude,
    o.longitude,
    o.localizacao,
    COALESCE(o.gravidade_verificada, o.gravidade_cidadao, ia.gravidade_ia) AS gravidade,
    ia.confianca_max,
    o.criado_em,
    o.id_area
FROM public.ocorrencias o
LEFT JOIN LATERAL (
    SELECT
        (ARRAY_AGG(d.gravidade_estimada ORDER BY
            CASE d.gravidade_estimada
                WHEN 'grave'    THEN 3
                WHEN 'moderado' THEN 2
                WHEN 'leve'     THEN 1
                ELSE 0
            END DESC))[1] AS gravidade_ia,
        MAX(d.confianca) AS confianca_max
    FROM public.deteccoes_ia d
    WHERE d.id_ocorrencia = o.id_ocorrencia
) ia ON true
WHERE o.status = 'aberta';

GRANT SELECT ON public.vw_mapa_ocorrencias TO pavimentai_app;

COMMIT;
