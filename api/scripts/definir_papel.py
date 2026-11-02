"""Define o papel de um usuário: cidadao, gestor ou admin. Usa o usuário dono (postgres).
É assim que, por enquanto, se cria um gestor (depois isso vai para um painel de admin).

Uso (dentro da pasta api, com a venv ativa):
    python scripts/definir_papel.py carla@email.com gestor 3543303
    python scripts/definir_papel.py joao@email.com admin
    python scripts/definir_papel.py carla@email.com cidadao

O gestor precisa do código IBGE do município que ele vai administrar
(o município precisa estar cadastrado em areas_atendimento).
"""
import getpass
import os
import sys

import psycopg


def main() -> int:
    args = sys.argv[1:]
    if len(args) not in (2, 3) or args[1] not in ("cidadao", "gestor", "admin"):
        print(__doc__)
        return 1
    email, papel = args[0].strip().lower(), args[1]
    codigo = args[2] if len(args) == 3 else None
    if papel == "gestor" and not codigo:
        print("Para gestor, informe também o código IBGE do município (ex.: 3543303).")
        return 1
    if papel != "gestor" and codigo:
        print("O código do município só se usa para gestor.")
        return 1

    conexao = dict(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        dbname=os.getenv("PGDATABASE", "pavimentai"),
        user=os.getenv("PGUSER", "postgres"),
    )
    senha = os.getenv("PGPASSWORD") or getpass.getpass(f"Senha do usuário {conexao['user']}: ")

    try:
        with psycopg.connect(**conexao, password=senha) as conn:
            usuario = conn.execute("SELECT id_usuario, papel FROM usuarios WHERE email = %s", (email,)).fetchone()
            if usuario is None:
                print(f"Não achei nenhum usuário com o e-mail {email}.")
                return 1
            id_area = None
            if papel == "gestor":
                area = conn.execute(
                    "SELECT id_area, nome FROM areas_atendimento WHERE codigo_ibge = %s AND ativa", (codigo,)
                ).fetchone()
                if area is None:
                    print(f"O município {codigo} não está cadastrado (ou está desativado) em areas_atendimento.")
                    return 1
                id_area = area[0]
            conn.execute(
                "UPDATE usuarios SET papel = %s, id_area_gestao = %s WHERE id_usuario = %s",
                (papel, id_area, usuario[0]),
            )
            print(f"Pronto: {email} agora é {papel}" + (f" do município {codigo}." if codigo else "."))
    except psycopg.Error as erro:
        print(f"Não consegui alterar: {erro}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
