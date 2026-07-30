import httpx

from editais3s import db, pipeline
from editais3s.config import INTERVALO_DOMINIO

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


def test_varrer_isola_falha_de_extracao(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")
    fonte_ruim = dict(FONTE, id="ruim", dominio="ruim.org", url="https://ruim.org/x")
    fonte_boa = dict(FONTE, id="boa", dominio="boa.org", url="https://boa.org/x")
    original = pipeline.extrai.extrair

    def extrair_falha(texto, fonte, chamar=None):
        if fonte["id"] == "ruim":
            raise RuntimeError("html impossivel")
        return original(texto, fonte, chamar)

    monkeypatch.setattr(pipeline.extrai, "extrair", extrair_falha)
    resumo = pipeline.varrer(
        con, [fonte_ruim, fonte_boa], cliente_falso(),
        usar_llm=False, pausar=lambda _: None,
    )
    assert resumo["fontes_erro"] >= 1
    assert resumo["novas"] >= 1
    titulos = [l["titulo"] for l in con.execute("SELECT titulo FROM oportunidades")]
    assert any("TdR Ouvidoria" in t for t in titulos)
    assert con.execute("SELECT count(*) FROM execucoes").fetchone()[0] == 1


def test_varrer_nao_chama_juiz_quando_usar_llm_false(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")
    chamado = []
    monkeypatch.setattr(
        pipeline.juiz, "julgar", lambda itens: chamado.append(itens) or []
    )
    pipeline.varrer(
        con, [FONTE], cliente_falso(), usar_llm=False, pausar=lambda _: None
    )
    assert chamado == []


def test_varrer_pausa_entre_fontes_mas_nao_antes_da_primeira(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")
    chamadas = []
    fonte2 = dict(
        FONTE, id="wri-brasil-2", dominio="outro.org.br",
        url="https://outro.org.br/oportunidades",
    )
    pipeline.varrer(
        con, [FONTE, fonte2], cliente_falso(), usar_llm=False,
        pausar=lambda segundos: chamadas.append(segundos),
    )
    assert chamadas == [INTERVALO_DOMINIO]


def test_varrer_grava_contadores_reais_em_execucoes(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")
    resumo = pipeline.varrer(
        con, [FONTE], cliente_falso(), usar_llm=False, pausar=lambda _: None
    )
    linha = con.execute(
        "SELECT fontes_ok, fontes_erro, novas FROM execucoes"
    ).fetchone()
    assert (linha["fontes_ok"], linha["fontes_erro"], linha["novas"]) == (
        resumo["fontes_ok"], resumo["fontes_erro"], resumo["novas"],
    )
    assert linha["novas"] >= 1


def test_varrer_respeita_robots_txt_disallow(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        return httpx.Response(200, text=PAGINA)

    c = httpx.Client(transport=httpx.MockTransport(handler))
    resumo = pipeline.varrer(
        con, [FONTE], c, usar_llm=False, pausar=lambda _: None
    )
    assert resumo["ignoradas"] == 1
    assert resumo["fontes_ok"] == 0
    assert con.execute("SELECT count(*) FROM oportunidades").fetchone()[0] == 0
