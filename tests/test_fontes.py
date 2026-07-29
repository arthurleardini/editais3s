import json

import pytest

from editais3s import fontes


def test_carregar_catalogo_real_valida_todas_as_fontes():
    lista = fontes.carregar()
    assert len(lista) >= 14
    for fonte in lista:
        fontes.validar(fonte)


def test_ids_sao_unicos():
    ids = [f["id"] for f in fontes.carregar()]
    assert len(ids) == len(set(ids))


def test_validar_rejeita_campo_faltando():
    with pytest.raises(fontes.FonteInvalida, match="dominio"):
        fontes.validar({"id": "x", "nome": "X", "tipo": "html", "tier": 1})


def test_validar_rejeita_tipo_desconhecido():
    with pytest.raises(fontes.FonteInvalida, match="tipo"):
        fontes.validar(
            {"id": "x", "nome": "X", "tipo": "pdf", "dominio": "x.org", "tier": 1}
        )


def test_validar_exige_url_em_fonte_html():
    with pytest.raises(fontes.FonteInvalida, match="url"):
        fontes.validar(
            {"id": "x", "nome": "X", "tipo": "html", "dominio": "x.org", "tier": 1}
        )


def test_validar_exige_query_em_fonte_gnews():
    with pytest.raises(fontes.FonteInvalida, match="query"):
        fontes.validar(
            {"id": "x", "nome": "X", "tipo": "gnews", "dominio": "x.org", "tier": 1}
        )


def test_filtrar_por_ids(tmp_path):
    lista = fontes.carregar()
    assert [f["id"] for f in fontes.filtrar(lista, ["wri-brasil"])] == ["wri-brasil"]
    assert fontes.filtrar(lista, None) == lista


def test_filtrar_rejeita_id_inexistente():
    with pytest.raises(fontes.FonteInvalida, match="nao-existe"):
        fontes.filtrar(fontes.carregar(), ["nao-existe"])


def test_carregar_de_caminho_alternativo(tmp_path):
    caminho = tmp_path / "f.json"
    caminho.write_text(
        json.dumps(
            {
                "fontes": [
                    {
                        "id": "a",
                        "nome": "A",
                        "tipo": "html",
                        "dominio": "a.org",
                        "url": "https://a.org/x",
                        "tier": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert len(fontes.carregar(caminho)) == 1
