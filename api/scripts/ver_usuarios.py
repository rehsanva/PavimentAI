"""Lista os usuários do banco com o papel e a cidade de cada um (sem mostrar senha).
Serve para conferir quem é cidadão, gestor ou admin.

Uso (dentro da pasta api, com a venv ativa):
    python scripts/ver_usuarios.py
"""
import getpass
import os
import sys

import psycopg


def main() -> int:
    conexao = dict(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "pavimentai"),
        user=os.getenv("PGUSER", "postgres"),
    )
    senha = os.getenv("PGPASSWORD") or getpass.getpass(f"Senha do usuário {conexao['user']}: ")
    try:
        with psycopg.connect(**conexao, password=senha) as conn:
            linhas = conn.execute(
                """
                SELECT u.id_usuario, u.email, u.papel, u.status_conta,
                       coalesce(g.nome, '-') AS gestao, coalesce(r.nome, '-') AS reside_em
                FROM usuarios u
                LEFT JOIN areas_atendimento g ON g.id_area = u.id_area_gestao
                LEFT JOIN areas_atendimento r ON r.id_area = u.id_area_residencia
                ORDER BY u.id_usuario
                """
            ).fetchall()
    except psycopg.Error as erro:
        print(f"Não consegui ler o banco: {erro}")
        return 1

    cabecalho = ("id", "e-mail", "papel", "conta", "gestão da cidade", "reside em")
    tabela = [cabecalho] + [tuple(str(c) for c in l) for l in linhas]
    larguras = [max(len(l[i]) for l in tabela) for i in range(len(cabecalho))]
    for n, l in enumerate(tabela):
        print("  ".join(c.ljust(larguras[i]) for i, c in enumerate(l)))
        if n == 0:
            print("  ".join("-" * w for w in larguras))
    return 0


if __name__ == "__main__":
    sys.exit(main())