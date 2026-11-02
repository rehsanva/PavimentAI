-- =====================================================================
-- PavimentAI - migração v4 (residência do cidadão + isolamento por município)
-- Não apaga nada. Pode ser rodada mais de uma vez.
-- =====================================================================
BEGIN;

-- 1) Onde o cidadão mora. Guardamos só o CEP e a cidade (sem número nem complemento).
--    Tudo pode ficar vazio: quem se cadastrou antes completa depois.
ALTER TABLE public.usuarios
    ADD COLUMN IF NOT EXISTS cep                      char(8),
    ADD COLUMN IF NOT EXISTS codigo_ibge_residencia   varchar(7),
    ADD COLUMN IF NOT EXISTS municipio_residencia     varchar(120),
    ADD COLUMN IF NOT EXISTS uf_residencia            char(2),
    ADD COLUMN IF NOT EXISTS id_area_residencia       integer REFERENCES public.areas_atendimento (id_area),
    ADD COLUMN IF NOT EXISTS residencia_atualizada_em timestamptz;

CREATE INDEX IF NOT EXISTS idx_usuarios_area_residencia ON public.usuarios (id_area_residencia);
CREATE INDEX IF NOT EXISTS idx_usuarios_area_gestao     ON public.usuarios (id_area_gestao);

-- 2) Regras que o próprio banco garante
--    (NOT VALID = vale para cadastros novos e alterações; não reclama de linhas antigas)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_usuarios_cep') THEN
        ALTER TABLE public.usuarios ADD CONSTRAINT ck_usuarios_cep
            CHECK (cep IS NULL OR cep ~ '^[0-9]{8}$');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_gestor_tem_area') THEN
        ALTER TABLE public.usuarios ADD CONSTRAINT ck_gestor_tem_area
            CHECK (papel <> 'gestor' OR id_area_gestao IS NOT NULL) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_area_gestao_so_gestor') THEN
        ALTER TABLE public.usuarios ADD CONSTRAINT ck_area_gestao_so_gestor
            CHECK (papel = 'gestor' OR id_area_gestao IS NULL) NOT VALID;
    END IF;
END $$;

-- 3) Cada município decide se só aceita ocorrências de moradores.
--    Por padrão desligado; Ribeirão Pires já nasce ligado (e só na primeira vez que isto roda).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = 'areas_atendimento'
                     AND column_name = 'exige_residencia') THEN
        ALTER TABLE public.areas_atendimento
            ADD COLUMN exige_residencia boolean NOT NULL DEFAULT false;
        UPDATE public.areas_atendimento SET exige_residencia = true WHERE codigo_ibge = '3543303';
    END IF;
END $$;

-- 4) A API pode gravar a residência do próprio usuário (e nada além disso)
GRANT UPDATE (cep, codigo_ibge_residencia, municipio_residencia, uf_residencia,
              id_area_residencia, residencia_atualizada_em)
    ON public.usuarios TO pavimentai_app;

-- 5) Liga à área os moradores que já tinham informado a cidade
UPDATE public.usuarios u
SET id_area_residencia = a.id_area
FROM public.areas_atendimento a
WHERE u.id_area_residencia IS NULL
  AND u.codigo_ibge_residencia = a.codigo_ibge;

COMMIT;

-- Conferência: deve listar as 6 colunas novas
SELECT column_name FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'usuarios'
  AND column_name IN ('cep','codigo_ibge_residencia','municipio_residencia',
                      'uf_residencia','id_area_residencia','residencia_atualizada_em')
ORDER BY column_name;
