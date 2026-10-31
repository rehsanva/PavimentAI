from psycopg.types.json import Jsonb


def registrar(conn, acao, id_usuario=None, entidade=None, id_registro=None, detalhes=None):
    """Grava uma linha na tabela auditoria (a API só pode inserir, nunca alterar)."""
    conn.execute(
        """
        INSERT INTO auditoria (id_usuario, acao, entidade_afetada, id_registro_afetado, detalhes)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (id_usuario, acao, entidade, id_registro,
         Jsonb(detalhes) if detalhes is not None else None),
    )
