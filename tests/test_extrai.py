from editais3s import extrai

FONTE = {
    "id": "wri-brasil",
    "nome": "WRI Brasil",
    "tipo": "html",
    "url": "https://www.wribrasil.org.br/oportunidades",
}

TEXTO = """Oportunidades
[TdR FLWTDR-2026-011 Ouvidoria Restaura Biomas](/media/tdr-ouvidoria.pdf) Prazo: 13/07/2026
[Quem somos](/sobre)
[Chamada de propostas: plataforma de dados de restauracao](/editais/plataforma) Prazo: 20/08/2026
"""


def test_extrair_converte_payload_em_oportunidades():
    payload = {
        "oportunidades": [
            {
                "titulo": "TdR FLWTDR-2026-011 Ouvidoria Restaura Biomas",
                "objeto": "consultoria para implantacao de ouvidoria",
                "url": "/media/tdr-ouvidoria.pdf",
                "prazo": "2026-07-13",
                "modalidade": "tdr",
            }
        ]
    }
    ops = extrai.extrair(TEXTO, FONTE, chamar=lambda texto, fonte: payload)
    assert len(ops) == 1
    assert ops[0].titulo.startswith("TdR FLWTDR")
    assert ops[0].modalidade == "tdr"


def test_extrair_resolve_url_relativa():
    payload = {"oportunidades": [{"titulo": "T", "url": "/media/x.pdf"}]}
    ops = extrai.extrair(TEXTO, FONTE, chamar=lambda texto, fonte: payload)
    assert ops[0].url == "https://www.wribrasil.org.br/media/x.pdf"


def test_extrair_preserva_url_absoluta():
    payload = {"oportunidades": [{"titulo": "T", "url": "https://outro.org/x.pdf"}]}
    ops = extrai.extrair(TEXTO, FONTE, chamar=lambda texto, fonte: payload)
    assert ops[0].url == "https://outro.org/x.pdf"


def test_extrair_descarta_item_sem_titulo():
    payload = {"oportunidades": [{"titulo": "  ", "url": "/x"}, {"titulo": "Ok"}]}
    ops = extrai.extrair(TEXTO, FONTE, chamar=lambda texto, fonte: payload)
    assert [o.titulo for o in ops] == ["Ok"]


def test_extrair_com_payload_vazio():
    ops = extrai.extrair(TEXTO, FONTE, chamar=lambda texto, fonte: {"oportunidades": []})
    assert ops == []


def test_extrair_tolera_payload_malformado():
    ops = extrai.extrair(TEXTO, FONTE, chamar=lambda texto, fonte: {"lixo": 1})
    assert ops == []


def test_heuristica_pega_ancora_com_palavra_de_edital():
    ops = extrai.heuristica(TEXTO, FONTE)
    titulos = [o.titulo for o in ops]
    assert any("FLWTDR" in t for t in titulos)
    assert any("Chamada de propostas" in t for t in titulos)
    assert not any("Quem somos" in t for t in titulos)


def test_heuristica_resolve_url_relativa():
    ops = extrai.heuristica(TEXTO, FONTE)
    assert all(o.url.startswith("https://www.wribrasil.org.br/") for o in ops)


def test_extrair_sem_api_key_cai_na_heuristica(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ops = extrai.extrair(TEXTO, FONTE)
    assert ops and all(o.modalidade == "indefinido" for o in ops)

def test_extrair_chamar_lanca_excecao_cai_na_heuristica():
    def boom(texto, fonte):
        raise RuntimeError("falha de rede")

    ops = extrai.extrair(TEXTO, FONTE, chamar=boom)
    assert ops
    assert all(o.modalidade == "indefinido" for o in ops)
    assert any("FLWTDR" in o.titulo for o in ops)
