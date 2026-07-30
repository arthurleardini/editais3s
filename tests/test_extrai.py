import inspect

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


# --- Correcao 1: chunking + merge para paginas grandes -----------------

# len == 20_000: com TAMANHO_CHUNK=8_000 e SOBREPOSICAO_CHUNK=500 (passo de
# 7_500), a divisao produz exatamente 3 pedacos: [0:8000], [7500:15500],
# [15000:20000]. Numero fixado aqui para nao depender de introspeccao da
# funcao de divisao.
TEXTO_LONGO = "x" * 20_000
CHUNKS_ESPERADOS = 3


def test_extrair_chunka_pagina_grande_e_mescla_um_item_por_pedaco():
    chamadas = []

    def chamar_contador(pedaco, fonte):
        chamadas.append(pedaco)
        i = len(chamadas)
        return {
            "oportunidades": [
                {"titulo": f"Item {i}", "url": f"https://x.org/item-{i}"}
            ]
        }

    ops = extrai.extrair(TEXTO_LONGO, FONTE, chamar=chamar_contador)

    assert len(chamadas) == CHUNKS_ESPERADOS
    assert len(ops) == CHUNKS_ESPERADOS
    assert {o.titulo for o in ops} == {
        f"Item {i}" for i in range(1, CHUNKS_ESPERADOS + 1)
    }


def test_extrair_deduplica_item_repetido_entre_pedacos_sobrepostos():
    # Simula o item que aparece em dois pedacos consecutivos por causa da
    # sobreposicao: mesmo titulo+url em toda chamada, so' pode sobreviver
    # uma vez apos o merge.
    def chamar_repete(pedaco, fonte):
        return {
            "oportunidades": [
                {"titulo": "TdR duplicado na sobreposicao", "url": "/media/dup.pdf"}
            ]
        }

    ops = extrai.extrair(TEXTO_LONGO, FONTE, chamar=chamar_repete)

    assert len(ops) == 1
    assert ops[0].titulo == "TdR duplicado na sobreposicao"


def test_extrair_um_pedaco_falhando_cai_na_heuristica_da_pagina_inteira():
    # Texto grande (varios pedacos) mas com as ancoras da heuristica
    # preservadas no comeco — a segunda chamada (segundo pedaco) falha, e o
    # fallback tem que usar a heuristica sobre o texto ORIGINAL inteiro, nao
    # travar nem misturar itens parciais de LLM com itens de regex.
    texto_grande = TEXTO + ("\nlorem ipsum dolor sit amet " * 1000)
    assert len(texto_grande) > extrai.TAMANHO_CHUNK

    contador = {"n": 0}

    def chamar_com_falha_no_segundo_pedaco(pedaco, fonte):
        contador["n"] += 1
        if contador["n"] == 2:
            raise RuntimeError("falha de rede no segundo pedaco")
        return {"oportunidades": []}

    ops = extrai.extrair(texto_grande, FONTE, chamar=chamar_com_falha_no_segundo_pedaco)

    assert ops
    assert all(o.modalidade == "indefinido" for o in ops)
    assert any("FLWTDR" in o.titulo for o in ops)


def test_max_tokens_extracao_lido_do_config_nao_hardcoded():
    fonte = inspect.getsource(extrai.chamar_llm)
    assert "MAX_TOKENS_EXTRACAO" in fonte
    assert "4096" not in fonte
