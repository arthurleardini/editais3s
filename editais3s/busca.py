"""Fontes sem pagina colhivel (WAF por IP, robots.txt Disallow, TdR solto como
post): a coleta passa por indice de busca em vez do site de origem.

Google News RSS e a rota principal — respeita `site:` e o filtro `when:` e
devolve titulo, data e link. DDGS (DuckDuckGo) entra como complemento quando
o pacote esta instalado: cobre dominio que o Google News nao indexa como
noticia (PNUD, UNESCO). O resultado vira um HTML sintetico de lista, que segue
pelo mesmo caminho de limpeza -> hash -> extracao das fontes html.
"""
import html
import urllib.parse
import xml.etree.ElementTree as ET

import httpx

from .config import BUSCA_JANELA_DIAS, BUSCA_MAX_DDGS, UA_NAVEGADOR

GNEWS_RSS = "https://news.google.com/rss/search"


class ErroBusca(Exception):
    pass


def google_news(query: str, cliente: httpx.Client) -> list[dict]:
    params = {
        "q": f"{query} when:{BUSCA_JANELA_DIAS}d",
        "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419",
    }
    resp = cliente.get(
        GNEWS_RSS + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": UA_NAVEGADOR},
        follow_redirects=True,
    )
    if resp.status_code >= 400:
        raise ErroBusca(f"google news HTTP {resp.status_code}")
    try:
        raiz = ET.fromstring(resp.text)
    except ET.ParseError as exc:
        raise ErroBusca(f"google news: RSS invalido: {exc}") from exc
    itens = []
    for item in raiz.iter("item"):
        itens.append({
            "titulo": (item.findtext("title") or "").strip(),
            "url": (item.findtext("link") or "").strip(),
            "data": (item.findtext("pubDate") or "").strip(),
            "resumo": "",
        })
    return itens


def ddgs(query: str) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:
        return []
    try:
        # timelimit "m": sem ele o DDGS devolve TdR de 2024 (Talanoa) que o
        # Google News ja filtra pelo when:.
        brutos = DDGS().text(query, max_results=BUSCA_MAX_DDGS, timelimit="m")
    except Exception:
        # "No results found" tambem chega como excecao.
        return []
    return [
        {"titulo": r.get("title", ""), "url": r.get("href", ""),
         "data": "", "resumo": r.get("body", "")}
        for r in brutos if r.get("href")
    ]


def buscar(query: str, cliente: httpx.Client) -> list[dict]:
    """Google News + DDGS, sem duplicar URL. Erro do Google News so propaga
    se o DDGS tambem nao trouxe nada."""
    erro = None
    try:
        itens = google_news(query, cliente)
    except (ErroBusca, httpx.HTTPError) as exc:
        itens, erro = [], exc
    vistos = {i["url"] for i in itens}
    for r in ddgs(query):
        if r["url"] not in vistos:
            vistos.add(r["url"])
            itens.append(r)
    if not itens and erro is not None:
        raise ErroBusca(f"{type(erro).__name__}: {erro}")
    return itens


def como_html(fonte: dict, itens: list[dict]) -> str:
    """Lista em HTML para o extrator. Ordem estavel (por URL) para o hash
    nao mudar so porque o buscador reordenou."""
    linhas = [f"<h1>{html.escape(fonte['nome'])} (via busca: {html.escape(fonte['query'])})</h1>", "<ul>"]
    for i in sorted(itens, key=lambda x: x["url"]):
        partes = [f'<a href="{html.escape(i["url"])}">{html.escape(i["titulo"])}</a>']
        if i["data"]:
            partes.append(f"publicado {html.escape(i['data'])}")
        if i["resumo"]:
            partes.append(html.escape(i["resumo"]))
        partes.append(f"link: {html.escape(i['url'])}")
        linhas.append("<li>" + " — ".join(partes) + "</li>")
    linhas.append("</ul>")
    return "\n".join(linhas)
