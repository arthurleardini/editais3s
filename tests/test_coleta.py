import httpx
import pytest

from editais3s import coleta, db

FONTE = {
    "id": "wri-brasil",
    "nome": "WRI Brasil",
    "tipo": "html",
    "dominio": "wribrasil.org.br",
    "url": "https://www.wribrasil.org.br/oportunidades",
    "tier": 1,
}

PAGINA_A = "<body><h1>Oportunidades</h1><p>TdR Ouvidoria</p></body>"
PAGINA_B = "<body><h1>Oportunidades</h1><p>TdR Ouvidoria</p><p>Nova cotacao</p></body>"


def cliente(corpo, status=200, erro=None):
    def handler(request):
        if erro:
            raise erro
        return httpx.Response(status, text=corpo)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_primeira_coleta_marca_mudou(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    r = coleta.coletar(FONTE, con, cliente(PAGINA_A))
    assert r.ok and r.mudou
    assert "TdR Ouvidoria" in r.texto


def test_segunda_coleta_igual_nao_mudou(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    coleta.coletar(FONTE, con, cliente(PAGINA_A))
    r = coleta.coletar(FONTE, con, cliente(PAGINA_A))
    assert r.ok and r.mudou is False


def test_conteudo_diferente_volta_a_mudar(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    coleta.coletar(FONTE, con, cliente(PAGINA_A))
    r = coleta.coletar(FONTE, con, cliente(PAGINA_B))
    assert r.mudou


def test_forcar_ignora_o_gate(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    coleta.coletar(FONTE, con, cliente(PAGINA_A))
    r = coleta.coletar(FONTE, con, cliente(PAGINA_A), forcar=True)
    assert r.mudou


def test_http_erro_nao_levanta_e_conta_erro(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    r = coleta.coletar(FONTE, con, cliente("nao encontrado", status=404))
    assert r.ok is False
    assert r.http_status == 404
    linha = con.execute(
        "SELECT erros_seguidos, erro FROM snapshots WHERE fonte_id=?", (FONTE["id"],)
    ).fetchone()
    assert linha["erros_seguidos"] == 1
    assert "404" in linha["erro"]


def test_erro_de_rede_nao_levanta(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    r = coleta.coletar(
        FONTE, con, cliente("", erro=httpx.ConnectError("sem rota"))
    )
    assert r.ok is False and r.erro


def test_sucesso_zera_contador_de_erro(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    coleta.coletar(FONTE, con, cliente("x", status=500))
    coleta.coletar(FONTE, con, cliente(PAGINA_A))
    linha = con.execute(
        "SELECT erros_seguidos FROM snapshots WHERE fonte_id=?", (FONTE["id"],)
    ).fetchone()
    assert linha["erros_seguidos"] == 0


def test_fonte_js_true_nao_e_baixada(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    fonte = {**FONTE, "js": True}
    r = coleta.coletar(fonte, con, cliente(PAGINA_A))
    assert r.ok is False
    assert r.erro == "indisponivel: requer navegador (js)"


def test_robots_bloqueado(tmp_path):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /oportunidades")
        return httpx.Response(200, text=PAGINA_A)

    c = httpx.Client(transport=httpx.MockTransport(handler))
    assert coleta.robots_permite(FONTE, c) is False


def test_robots_liberado_quando_ausente():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404, text="")
        return httpx.Response(200, text=PAGINA_A)

    c = httpx.Client(transport=httpx.MockTransport(handler))
    assert coleta.robots_permite(FONTE, c) is True


def test_retry_recupera_de_falha_transitoria(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    tentativas = {"n": 0}

    def handler(request):
        tentativas["n"] += 1
        if tentativas["n"] == 1:
            raise httpx.ConnectError("falha transitoria")
        return httpx.Response(200, text=PAGINA_A)

    c = httpx.Client(transport=httpx.MockTransport(handler))
    r = coleta.coletar(FONTE, con, c)
    assert r.ok is True
    assert r.mudou is True
    assert tentativas["n"] == 2


def test_erros_seguidos_incrementa_em_falhas_consecutivas(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    for _ in range(3):
        coleta.coletar(FONTE, con, cliente("erro", status=500))
    linha = con.execute(
        "SELECT erros_seguidos FROM snapshots WHERE fonte_id=?", (FONTE["id"],)
    ).fetchone()
    assert linha["erros_seguidos"] == 3
