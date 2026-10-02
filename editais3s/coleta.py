"""Download de uma fonte e gate de hash contra a tabela snapshots."""
import sqlite3
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin

import httpx

import json

from . import busca, limpeza
from . import navegador as nav
from .config import TENTATIVAS, UA


@dataclass
class Coleta:
    fonte_id: str
    ok: bool
    mudou: bool
    texto: str = ""
    hash: str | None = None
    http_status: int | None = None
    erro: str | None = None


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def robots_permite(fonte: dict, cliente: httpx.Client) -> bool:
    alvo = fonte["url"]
    try:
        resp = cliente.get(urljoin(alvo, "/robots.txt"), headers={"User-Agent": UA})
    except httpx.HTTPError:
        return True
    if resp.status_code != 200:
        return True
    leitor = urllib.robotparser.RobotFileParser()
    leitor.parse(resp.text.splitlines())
    return bool(leitor.can_fetch(UA, alvo))


def _baixar(url: str, cliente: httpx.Client) -> httpx.Response:
    ultimo: Exception | None = None
    for _ in range(TENTATIVAS):
        try:
            return cliente.get(
                url, headers={"User-Agent": UA}, follow_redirects=True
            )
        except httpx.HTTPError as exc:
            ultimo = exc
    raise ultimo  # type: ignore[misc]


def _wb_procnotices(texto: str) -> str:
    """JSON da API search.worldbank.org/api/v2/procnotices -> lista HTML."""
    dados = json.loads(texto)
    linhas = ["<ul>"]
    for n in dados.get("procnotices", []):
        url = f"https://projects.worldbank.org/en/projects-operations/procurement-detail/{n.get('id', '')}"
        campos = [
            n.get("notice_type"), n.get("bid_description"), n.get("project_name"),
            n.get("procurement_method_name"), n.get("contact_organization"),
            f"publicado {n.get('noticedate')}" if n.get("noticedate") else None,
            f"prazo {n['submission_deadline_date'][:10]}" if n.get("submission_deadline_date") else None,
            f"link: {url}",
        ]
        linhas.append("<li>" + " — ".join(str(c) for c in campos if c) + "</li>")
    linhas.append("</ul>")
    return "\n".join(linhas)


def _wp_json(texto: str) -> str:
    """Resposta da REST API do WordPress (/wp-json/wp/v2/pages?slug=...) ->
    HTML da pagina. Serve site cuja pagina publica fica atras de desafio do
    Cloudflare mas cuja API nao (C40)."""
    paginas = json.loads(texto)
    if isinstance(paginas, dict):
        paginas = [paginas]
    return "\n".join(
        f"<h1>{p['title']['rendered']}</h1>\n{p['content']['rendered']}" for p in paginas
    )


FORMATOS = {"wb-procnotices": _wb_procnotices, "wp-json": _wp_json}


def _gravar_erro(con: sqlite3.Connection, fonte_id: str, status, erro: str) -> None:
    con.execute(
        """
        INSERT INTO snapshots (fonte_id, coletado_em, http_status, erro, erros_seguidos)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(fonte_id) DO UPDATE SET
          coletado_em=excluded.coletado_em,
          http_status=excluded.http_status,
          erro=excluded.erro,
          erros_seguidos=snapshots.erros_seguidos + 1
        """,
        (fonte_id, _agora(), status, erro),
    )
    con.commit()


def _processar(
    fonte_id: str,
    con: sqlite3.Connection,
    status: int,
    texto_bruto: str,
    tamanho_bytes: int,
    forcar: bool,
) -> Coleta:
    if status >= 400:
        erro = f"HTTP {status}"
        _gravar_erro(con, fonte_id, status, erro)
        return Coleta(fonte_id, ok=False, mudou=False, http_status=status, erro=erro)

    texto = limpeza.limpar(texto_bruto)
    novo_hash = limpeza.hash_texto(texto)
    anterior = con.execute(
        "SELECT hash FROM snapshots WHERE fonte_id=?", (fonte_id,)
    ).fetchone()
    mudou = forcar or anterior is None or anterior["hash"] != novo_hash

    con.execute(
        """
        INSERT INTO snapshots (fonte_id, hash, coletado_em, http_status, bytes, erro, erros_seguidos)
        VALUES (?, ?, ?, ?, ?, NULL, 0)
        ON CONFLICT(fonte_id) DO UPDATE SET
          hash=excluded.hash,
          coletado_em=excluded.coletado_em,
          http_status=excluded.http_status,
          bytes=excluded.bytes,
          erro=NULL,
          erros_seguidos=0
        """,
        (fonte_id, novo_hash, _agora(), status, tamanho_bytes),
    )
    con.commit()

    return Coleta(
        fonte_id,
        ok=True,
        mudou=mudou,
        texto=texto,
        hash=novo_hash,
        http_status=status,
    )


def coletar(
    fonte: dict,
    con: sqlite3.Connection,
    cliente: httpx.Client,
    forcar: bool = False,
) -> Coleta:
    fonte_id = fonte["id"]

    if fonte["tipo"] == "gnews":
        try:
            itens = busca.buscar(fonte["query"], cliente)
        except busca.ErroBusca as exc:
            erro = f"busca: {exc}"
            _gravar_erro(con, fonte_id, None, erro)
            return Coleta(fonte_id, ok=False, mudou=False, erro=erro)
        html = busca.como_html(fonte, itens)
        return _processar(fonte_id, con, 200, html, len(html.encode("utf-8")), forcar)

    # "js" e o nome antigo do flag, mantido como sinonimo para nao quebrar
    # entradas ja curadas no catalogo.
    if fonte.get("navegador") or fonte.get("js"):
        try:
            status, html = nav.baixar(fonte["url"])
        except nav.ErroNavegador as exc:
            msg = str(exc)
            if msg.startswith("playwright nao instalado"):
                erro = "indisponivel: playwright nao instalado"
            else:
                erro = f"indisponivel: navegador: {msg}"
            _gravar_erro(con, fonte_id, None, erro)
            return Coleta(fonte_id, ok=False, mudou=False, erro=erro)
        return _processar(
            fonte_id, con, status, html, len(html.encode("utf-8")), forcar
        )

    try:
        resp = _baixar(fonte["url"], cliente)
    except httpx.HTTPError as exc:
        erro = f"{type(exc).__name__}: {exc}"
        _gravar_erro(con, fonte_id, None, erro)
        return Coleta(fonte_id, ok=False, mudou=False, erro=erro)

    texto = resp.text
    conversor = FORMATOS.get(fonte.get("formato", ""))
    if conversor and resp.status_code < 400:
        try:
            texto = conversor(texto)
        except ValueError as exc:
            erro = f"formato {fonte['formato']}: {exc}"
            _gravar_erro(con, fonte_id, resp.status_code, erro)
            return Coleta(fonte_id, ok=False, mudou=False, http_status=resp.status_code, erro=erro)
    return _processar(
        fonte_id, con, resp.status_code, texto, len(resp.content), forcar
    )
