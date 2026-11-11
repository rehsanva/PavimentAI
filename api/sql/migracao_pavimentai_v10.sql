-- PavimentAI - migração v10: recuperação de senha
-- Rodar no pgAdmin (Query Tool) conectado ao banco pavimentai, como DONO do banco.
-- Pode rodar mais de uma vez sem estragar nada.

BEGIN;

-- 1) Códigos de recuperação de senha (guardamos só o hash do código, nunca o código)
CREATE TABLE IF NOT EXISTS recuperacoes_senha (
    id_recuperacao bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_usuario     bigint NOT NULL REFERENCES usuarios (id_usuario) ON DELETE CASCADE,
    hash_codigo    text   NOT NULL,
    tentativas     integer NOT NULL DEFAULT 0 CHECK (tentativas >= 0),
    criado_em      timestamptz NOT NULL DEFAULT now(),
    expira_em      timestamptz NOT NULL,
    usado_em       timestamptz
);

CREATE INDEX IF NOT EXISTS ix_recuperacoes_senha_usuario
    ON recuperacoes_senha (id_usuario, criado_em DESC);

-- A API pode ler, criar e atualizar (marcar como usado, contar tentativa). Não apaga.
GRANT SELECT, INSERT, UPDATE ON recuperacoes_senha TO pavimentai_app;

-- 2) Função da v9 (encerrar conta). Repetida aqui para garantir que existe.
CREATE OR REPLACE FUNCTION anonimizar_usuario(p_id bigint, p_hash_senha text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_papel text;
BEGIN
    SELECT papel INTO v_papel FROM usuarios WHERE id_usuario = p_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'usuario inexistente';
    END IF;
    IF v_papel <> 'cidadao' THEN
        RAISE EXCEPTION 'apenas contas de cidadao podem ser anonimizadas por aqui';
    END IF;

    UPDATE usuarios SET
        nome = 'Conta removida',
        email = 'anonimizado-' || id_usuario || '@anonimizado.invalid',
        telefone = 'anon' || id_usuario,
        hash_senha = p_hash_senha,
        email_verificado = false, email_verificado_em = NULL,
        telefone_verificado = false, telefone_verificado_em = NULL,
        status_conta = 'desativada',
        cep = NULL, codigo_ibge_residencia = NULL, municipio_residencia = NULL,
        uf_residencia = NULL, id_area_residencia = NULL, residencia_atualizada_em = NULL
    WHERE id_usuario = p_id;

    DELETE FROM verificacoes_contato WHERE id_usuario = p_id;
    DELETE FROM recuperacoes_senha WHERE id_usuario = p_id;
END $$;

REVOKE ALL ON FUNCTION anonimizar_usuario(bigint, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION anonimizar_usuario(bigint, text) TO pavimentai_app;

COMMIT;

-- 3) Conferência: deve voltar 1 linha com as duas colunas "true"
SELECT to_regclass('public.recuperacoes_senha') IS NOT NULL AS tabela_recuperacao,
       EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'anonimizar_usuario') AS funcao_anonimizar;