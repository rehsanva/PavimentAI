BEGIN;

ALTER TABLE ocorrencias
    ADD COLUMN IF NOT EXISTS triagem_decisao varchar(10),
    ADD COLUMN IF NOT EXISTS triagem_por     bigint REFERENCES usuarios(id_usuario),
    ADD COLUMN IF NOT EXISTS triagem_em      timestamptz,
    ADD COLUMN IF NOT EXISTS triagem_motivo  text;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_ocorrencias_triagem_decisao') THEN
        ALTER TABLE ocorrencias ADD CONSTRAINT ck_ocorrencias_triagem_decisao
            CHECK (triagem_decisao IS NULL OR triagem_decisao IN ('aprovada', 'recusada'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_ocorrencias_fila_triagem
    ON ocorrencias (id_area, criado_em)
    WHERE situacao_ia = 'triagem' AND triagem_decisao IS NULL;

GRANT UPDATE (triagem_decisao, triagem_por, triagem_em, triagem_motivo)
    ON ocorrencias TO pavimentai_app;

COMMIT;