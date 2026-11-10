BEGIN;

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
END $$;

REVOKE ALL ON FUNCTION anonimizar_usuario(bigint, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION anonimizar_usuario(bigint, text) TO pavimentai_app;

COMMIT;