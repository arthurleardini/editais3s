"""Download de uma fonte e gate de hash contra a tabela snapshots."""
import sqlite3
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin

import httpx

from . import limpeza
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

    return _processar(
        fonte_id, con, resp.status_code, resp.text, len(resp.content), forcar
    )
