import httpx
import pytest

from editais3s import busca

RSS = """<rss><channel>
<item><title>B</title><link>https://b.org/2</link><pubDate>Wed, 01 Oct 2026</pubDate></item>
<item><title>A</title><link>https://a.org/1</link><pubDate>Tue, 30 Sep 2026</pubDate></item>
</channel></rss>"""

FONTE = {"id": "x", "nome": "X", "query": "site:x.org consultoria"}


def cliente(corpo, status=200):
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, text=corpo)))


def test_google_news_le_itens_e_aplica_janela():
    pedidos = []

    def handler(request):
        pedidos.append(request.url)
        return httpx.Response(200, text=RSS)

    itens = busca.google_news("site:x.org", httpx.Client(transport=httpx.MockTransport(handler)))
    assert [i["titulo"] for i in itens] == ["B", "A"]
    assert "when:60d" in pedidos[0].params["q"]


def test_buscar_mescla_ddgs_sem_duplicar(monkeypatch):
    monkeypatch.setattr(busca, "ddgs", lambda q: [
        {"titulo": "A dup", "url": "https://a.org/1", "data": "", "resumo": ""},
        {"titulo": "C", "url": "https://c.org/3", "data": "", "resumo": "TdR"},
    ])
    itens = busca.buscar("q", cliente(RSS))
    assert [i["url"] for i in itens] == ["https://b.org/2", "https://a.org/1", "https://c.org/3"]


def test_buscar_so_falha_se_ddgs_tambem_vazio(monkeypatch):
    monkeypatch.setattr(busca, "ddgs", lambda q: [])
    with pytest.raises(busca.ErroBusca):
        busca.buscar("q", cliente("", status=503))
    monkeypatch.setattr(busca, "ddgs", lambda q: [{"titulo": "C", "url": "https://c.org/3", "data": "", "resumo": ""}])
    assert len(busca.buscar("q", cliente("", status=503))) == 1


def test_como_html_ordem_estavel_para_hash():
    a = busca.como_html(FONTE, busca.google_news("q", cliente(RSS)))
    itens = list(reversed(busca.google_news("q", cliente(RSS))))
    assert a == busca.como_html(FONTE, itens)
    assert "link: https://a.org/1" in a
