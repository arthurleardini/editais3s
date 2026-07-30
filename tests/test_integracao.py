"""Achado 10: os testes de pipeline.py todos rodam com usar_llm=False, entao
o caminho varrer -> juiz.julgar -> juiz.aplicar -> relatorio.gerar nunca era
exercitado ponta a ponta, e pipeline.diario nao tinha teste nenhum. Este
arquivo cobre esse buraco estrutural com MockTransport + juiz injetado."""
from datetime import datetime, timezone

import httpx

from editais3s import db, pipeline, relatorio
from editais3s.modelos import Oportunidade

FONTE = {
    "id": "wri-brasil",
    "nome": "WRI Brasil",
    "tipo": "html",
    "dominio": "wribrasil.org.br",
    "url": "https://www.wribrasil.org.br/oportunidades",
    "tier": 1,
}

PAGINA = (
    '<body><h1>Oportunidades</h1><ul><li>'
    '<a href="/media/tdr.pdf">TdR Ouvidoria: plataforma de dados e painel de '
    "indicadores</a> Prazo: 30/09/2026</li></ul></body>"
)


def cliente_falso(pagina=PAGINA):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404, text="")
        return httpx.Response(200, text=pagina)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_caminho_feliz_ponta_a_ponta_com_juiz_ligado(tmp_path, monkeypatch):
    """varrer com usar_llm=True e juiz.julgar mockado julgando 8: o item tem
    que sair como 'reportada', aparecer em Aderentes com score e
    justificativa quando o relatorio e gerado para a mesma data."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")

    def julgar_oito(itens):
        return [
            {
                "id": i["id"],
                "score_llm": 8,
                "justificativa_llm": "casa com o caso WRI",
                "prazo": None,
                "modalidade": "tdr",
                "modelo_llm": "claude-haiku-4-5",
            }
            for i in itens
        ]

    monkeypatch.setattr(pipeline.juiz, "julgar", julgar_oito)

    resumo = pipeline.varrer(
        con, [FONTE], cliente_falso(), usar_llm=True, pausar=lambda _: None
    )
    assert resumo["novas"] >= 1

    linha = con.execute(
        "SELECT status, score_llm FROM oportunidades WHERE titulo LIKE 'TdR Ouvidoria%'"
    ).fetchone()
    assert linha["status"] == "reportada"
    assert linha["score_llm"] == 8

    hoje = con.execute(
        "SELECT substr(visto_em, 1, 10) AS d FROM oportunidades LIMIT 1"
    ).fetchone()["d"]
    md = relatorio.gerar(con, hoje)
    bloco = md.split("## Aderentes")[1].split("##")[0]
    assert "TdR Ouvidoria" in bloco
    assert "8" in bloco
    assert "casa com o caso WRI" in bloco


def test_item_julgado_nao_some_apos_segunda_varredura_com_objeto_fraco(
    tmp_path, monkeypatch
):
    """Achado 1 revisitado ponta a ponta: primeira rodada julga alto via
    juiz.julgar mockado; segunda rodada extrai um objeto que sozinho nao
    bateria o funil de keyword. O item nao pode ser rebaixado a
    descartada_kw nem sumir do relatorio."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")

    paginas = iter(["<body>rodada 1</body>", "<body>rodada 2, hash diferente</body>"])

    def cliente():
        def handler(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(404, text="")
            return httpx.Response(200, text=next(paginas))

        return httpx.Client(transport=httpx.MockTransport(handler))

    objetos = iter(
        [
            "plataforma de dados e painel de indicadores para ouvidoria",
            "texto qualquer sem nenhum termo de escopo relevante",
        ]
    )

    def extrair_falso(texto, fonte, chamar=None):
        return [
            Oportunidade(
                titulo="Consultoria eventual",
                objeto=next(objetos),
                url="https://www.wribrasil.org.br/media/tdr.pdf",
                prazo="2026-09-30",
            )
        ]

    monkeypatch.setattr(pipeline.extrai, "extrair", extrair_falso)

    def julgar_nove(itens):
        return [
            {
                "id": i["id"],
                "score_llm": 9,
                "justificativa_llm": "aderente",
                "prazo": None,
                "modalidade": None,
                "modelo_llm": "m",
            }
            for i in itens
        ]

    monkeypatch.setattr(pipeline.juiz, "julgar", julgar_nove)

    pipeline.varrer(con, [FONTE], cliente(), usar_llm=True, pausar=lambda _: None)
    pipeline.varrer(con, [FONTE], cliente(), usar_llm=True, pausar=lambda _: None)

    linha = con.execute("SELECT status, score_llm FROM oportunidades").fetchone()
    assert linha["status"] == "reportada"
    assert linha["score_llm"] == 9

    hoje = con.execute(
        "SELECT substr(visto_em, 1, 10) AS d FROM oportunidades LIMIT 1"
    ).fetchone()["d"]
    md = relatorio.gerar(con, hoje)
    assert "Consultoria eventual" in md
    assert "descartada" not in linha["status"]


def test_diario_com_data_explicita_escreve_md_no_caminho_esperado(
    tmp_path, monkeypatch
):
    """pipeline.diario precisa aceitar uma data explicita (achado 7) para ser
    testavel sem depender do relogio, e escrever o .md no caminho esperado
    com o conteudo esperado. Usa a data real de hoje em UTC porque
    oportunidades.salvar grava visto_em com o relogio de verdade — o que o
    achado 7 corrige e o relatorio poder pedir essa mesma data
    explicitamente, em vez de recalcula-la localmente."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    caminho_banco = tmp_path / "t.sqlite"
    conectar_original = db.conectar
    monkeypatch.setattr(
        pipeline.db, "conectar", lambda: conectar_original(caminho_banco)
    )
    monkeypatch.setattr(pipeline.cat, "carregar", lambda: [FONTE])
    monkeypatch.setattr(pipeline.cat, "filtrar", lambda fontes, ids: fontes)
    monkeypatch.setattr(pipeline, "_cliente", cliente_falso)
    monkeypatch.setattr(relatorio, "DIR_DADOS", tmp_path)

    data = datetime.now(timezone.utc).date().isoformat()
    caminho = pipeline.diario(usar_llm=False, data=data)

    assert caminho == tmp_path / f"novas_{data}.md"
    assert caminho.exists()
    conteudo = caminho.read_text(encoding="utf-8")
    assert f"Editais de terceiro setor — {data}" in conteudo
    assert "TdR Ouvidoria" in conteudo
