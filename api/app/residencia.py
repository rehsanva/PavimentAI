from .cep import consultar_cep


def resolver(conn, cep: str) -> dict:
    """CEP -> cidade (IBGE) -> área de atendimento correspondente, se existir.
    Quem mora numa cidade ainda não atendida também passa: id_area fica vazio."""
    info = consultar_cep(cep)
    area = conn.execute(
        "SELECT id_area, exige_residencia FROM areas_atendimento WHERE codigo_ibge = %s AND ativa",
        (info["codigo_ibge"],),
    ).fetchone()
    return {
        **info,
        "cep": cep,
        "id_area": area["id_area"] if area else None,
        "atendido": area is not None,
        "exige_residencia": area["exige_residencia"] if area else False,
    }
