"""Aplica um ou mais arquivos .sql no banco, usando o usuário dono (postgres).
Serve no lugar do pgAdmin/psql.

Uso (dentro da pasta api, com a venv ativa):
    python scripts/aplicar_sql.py sql/migracao_pavimentai_v2.sql sql/migracao_pavimentai_v3.sql

Ele pede a senha do usuário postgres (ao digitar, nada aparece: é normal).
Se der erro em um arquivo, ele para e mostra o motivo.
"""
import getpass
import os
import sys
from pathlib import Path

import psycopg


def main() -> int:
    arquivos = [Path(a) for a in sys.argv[1:]]
    if not arquivos:
        print("Uso: python scripts/aplicar_sql.py arquivo1.sql [arquivo2.sql ...]")
        return 1
    faltando = [str(a) for a in arquivos if not a.is_file()]
    if faltando:
        print("Não encontrei estes arquivos (confira se está na pasta api):")
        for f in faltando:
            print("  -", f)
        return 1

    conexao = dict(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "pavimentai"),
        user=os.getenv("PGUSER", "postgres"),
    )
    senha = os.getenv("PGPASSWORD") or getpass.getpass(f"Senha do usuário {conexao['user']}: ")

    try:
        with psycopg.connect(**conexao, password=senha, autocommit=True) as conn:
            for arquivo in arquivos:
                print(f"Aplicando {arquivo} ... ", end="", flush=True)
                try:
                    conn.execute(arquivo.read_text(encoding="utf-8"))
                except psycopg.Error as erro:
                    print("ERRO")
                    print(f"\n{erro}\n\nParei aqui. Nada depois deste arquivo foi aplicado.")
                    return 1
                print("ok")
    except psycopg.OperationalError as erro:
        print(f"\nNão consegui conectar no banco: {erro}")
        print("Confira se o PostgreSQL está ligado e se a senha do postgres está certa.")
        return 1

    print("\nTudo aplicado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
