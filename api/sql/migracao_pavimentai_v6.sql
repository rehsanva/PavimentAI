BEGIN;

ALTER TABLE midias
    ADD COLUMN IF NOT EXISTS hash_perceptual bigint,
    ADD COLUMN IF NOT EXISTS fonte_captura varchar(10) NOT NULL DEFAULT 'camera',
    ADD COLUMN IF NOT EXISTS exif_latitude double precision,
    ADD COLUMN IF NOT EXISTS exif_longitude double precision;

-- garante que hash_perceptual seja bigint, mesmo se já existia com outro tipo
ALTER TABLE midias ALTER COLUMN hash_perceptual TYPE bigint USING hash_perceptual::bigint;

ALTER TABLE midias DROP CONSTRAINT IF EXISTS midias_fonte_captura_check;
ALTER TABLE midias
    ADD CONSTRAINT midias_fonte_captura_check
    CHECK (fonte_captura IN ('camera', 'galeria'));

ALTER TABLE ocorrencias
    ADD COLUMN IF NOT EXISTS situacao_ia varchar(12);

ALTER TABLE ocorrencias DROP CONSTRAINT IF EXISTS ocorrencias_situacao_ia_check;
ALTER TABLE ocorrencias
    ADD CONSTRAINT ocorrencias_situacao_ia_check
    CHECK (situacao_ia IN ('confirmada', 'triagem'));

CREATE INDEX IF NOT EXISTS ix_deteccoes_ia_ocorrencia ON deteccoes_ia (id_ocorrencia);

GRANT SELECT, INSERT ON deteccoes_ia TO pavimentai_app;
GRANT UPDATE (situacao_ia) ON ocorrencias TO pavimentai_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO pavimentai_app;

COMMIT;