import httpx

from editais3s import db, pipeline

FONTE = {
    "id": "wri-brasil",
    "nome": "WRI Brasil",
    "tipo": "html",
    "dominio": "wribrasil.org.br",
    "url": "https://www.wribrasil.org.br/oportunidades",
    "tier": 1,
}

PAGINA = """<body><h1>Oportunidades</h1>
<ul><li><a href="/media/tdr.pdf">TdR Ouvidoria: plataforma de dados e painel de indicadores</a> Prazo: 30/09/2026</li>
<li><a href="/editais/apoio">Chamada de projetos para apoio a iniciativas comunitarias</a></li>
<li><a href="/vagas/analista">Vaga de emprego: analista administrativo</a></li></ul>
</body>"""


def cliente_falso():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404, text="")
        return httpx.Response(200, text=PAGINA)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_varrer_grava_novas_e_descarta_por_keyword(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")
    resumo = pipeline.varrer(
        con, [FONTE], cliente_falso(), usar_llm=False, pausar=lambda _: None
    )
    assert resumo["fontes_ok"] == 1
    assert resumo["novas"] >= 1

    linhas = {
        l["titulo"]: l["status"]
        for l in con.execute("SELECT titulo, status FROM oportunidades")
    }

    # aderente sobrevive ao funil
    tdr = [t for t in linhas if "TdR Ouvidoria" in t]
    assert tdr, "TdR nao chegou ao banco"
    assert linhas[tdr[0]] != "descartada_kw"

    # passa a extracao (RE_EDITAL casa "chamada") e morre no veto do escopo,
    # sem gastar chamada de LLM
    chamada = [t for t in linhas if "Chamada de projetos" in t]
    assert chamada, "chamada de projetos nao chegou ao banco"
    assert linhas[chamada[0]] == "descartada_kw"

    # vaga de emprego nao casa RE_EDITAL: e descartada na extracao,
    # nunca vira Oportunidade
    assert not any("Vaga de emprego" in t for t in linhas)


def test_varrer_segunda_vez_nao_encontra_novas(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")
    pipeline.varrer(con, [FONTE], cliente_falso(), usar_llm=False, pausar=lambda _: None)
    resumo = pipeline.varrer(
        con, [FONTE], cliente_falso(), usar_llm=False, pausar=lambda _: None
    )
    assert resumo["novas"] == 0
    assert resumo["ignoradas"] == 1


def test_varrer_conta_fonte_com_erro(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")

    def handler(request):
        return httpx.Response(500, text="erro")

    c = httpx.Client(transport=httpx.MockTransport(handler))
    resumo = pipeline.varrer(con, [FONTE], c, usar_llm=False, pausar=lambda _: None)
    assert resumo["fontes_erro"] == 1 and resumo["novas"] == 0


def test_varrer_pula_fonte_gnews_nesta_fase(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    fonte = {
        "id": "talanoa", "nome": "Talanoa", "tipo": "gnews",
        "dominio": "institutotalanoa.org", "query": "x", "tier": 1,
    }
    resumo = pipeline.varrer(
        con, [fonte], cliente_falso(), usar_llm=False, pausar=lambda _: None
    )
    assert resumo["ignoradas"] == 1


def test_varrer_registra_execucao(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")
    pipeline.varrer(con, [FONTE], cliente_falso(), usar_llm=False, pausar=lambda _: None)
    assert con.execute("SELECT count(*) FROM execucoes").fetchone()[0] == 1
