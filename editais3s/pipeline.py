"""Orquestra a varredura: coleta -> extração -> funil -> persistência -> relatório."""
import sqlite3
import time
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from . import coleta, db, escopo, extrai, fontes as cat, juiz, oportunidades, relatorio
from .config import INTERVALO_DOMINIO, TIMEOUT, UA

TRILHA = "catalogo"


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cliente() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, headers={"User-Agent": UA})


def varrer(
    con: sqlite3.Connection,
    lista_fontes: list[dict],
    cliente: httpx.Client,
    forcar: bool = False,
    usar_llm: bool = True,
    pausar=None,
) -> dict:
    pausar = time.sleep if pausar is None else pausar
    iniciado = _agora()
    resumo = {
        "fontes_ok": 0, "fontes_erro": 0, "novas": 0,
        "atualizadas": 0, "ignoradas": 0, "sem_llm": not usar_llm,
    }
    pendentes: list[dict] = []

    for i, fonte in enumerate(lista_fontes):
        if fonte["tipo"] != "html":
            resumo["ignoradas"] += 1
            continue
        if i:
            pausar(INTERVALO_DOMINIO)

        if not coleta.robots_permite(fonte, cliente):
            resumo["ignoradas"] += 1
            continue

        r = coleta.coletar(fonte, con, cliente, forcar=forcar)
        if not r.ok:
            resumo["fontes_erro"] += 1
            continue
        resumo["fontes_ok"] += 1
        if not r.mudou:
            resumo["ignoradas"] += 1
            continue

        try:
            ops = extrai.extrair(r.texto, fonte)
            novas, atualizadas = oportunidades.salvar(con, fonte, TRILHA, ops)
        except Exception as exc:
            # Uma fonte com HTML patologico ou conflito no banco nao pode derrubar a
            # varredura das outras. Conta como erro e segue. Note que a fonte ja foi
            # contada em fontes_ok pela coleta bem-sucedida, entao ela aparece nos dois
            # contadores: coletou, mas nao rendeu item.
            resumo["fontes_erro"] += 1
            con.execute(
                "UPDATE snapshots SET erro=?, erros_seguidos=erros_seguidos+1 "
                "WHERE fonte_id=?",
                (f"extracao/persistencia: {type(exc).__name__}: {exc}", fonte["id"]),
            )
            con.commit()
            continue
        resumo["novas"] += len(novas)
        resumo["atualizadas"] += len(atualizadas)

        for oid in novas + atualizadas:
            linha = con.execute(
                "SELECT id, titulo, objeto, fonte_nome FROM oportunidades WHERE id=?",
                (oid,),
            ).fetchone()
            aprovado, score_kw, temas = escopo.avaliar(
                f"{linha['titulo']} {linha['objeto'] or ''}"
            )
            con.execute(
                "UPDATE oportunidades SET score_kw=?, temas_kw=? WHERE id=?",
                (score_kw, ", ".join(temas), oid),
            )
            if aprovado:
                pendentes.append(dict(linha))
            else:
                con.execute(
                    "UPDATE oportunidades SET status='descartada_kw' WHERE id=?", (oid,)
                )
        con.commit()

    if usar_llm and pendentes:
        juiz.aplicar(con, juiz.julgar(pendentes))

    con.execute(
        """
        INSERT INTO execucoes (iniciado_em, terminado_em, fontes_ok, fontes_erro, novas)
        VALUES (?,?,?,?,?)
        """,
        (
            iniciado, _agora(), resumo["fontes_ok"], resumo["fontes_erro"],
            resumo["novas"],
        ),
    )
    con.commit()
    return resumo


def diario(
    ids: list[str] | None = None, forcar: bool = False, usar_llm: bool = True
) -> Path:
    con = db.conectar()
    lista = cat.filtrar(cat.carregar(), ids)
    with _cliente() as cliente:
        resumo = varrer(con, lista, cliente, forcar=forcar, usar_llm=usar_llm)
    hoje = date.today().isoformat()
    caminho = relatorio.escrever(con, hoje, execucao=resumo)
    print(
        f"{caminho}: {resumo['novas']} novas, {resumo['fontes_ok']} fontes ok, "
        f"{resumo['fontes_erro']} com erro, {resumo['ignoradas']} ignoradas"
    )
    return caminho


def bootstrap(ids: list[str] | None = None, cliente=None) -> list[dict]:
    """Confere a URL de cada fonte e relata o que precisa de ajuste manual."""
    lista = cat.filtrar(cat.carregar(), ids)
    fechar = cliente is None
    cliente = cliente or _cliente()
    achados = []
    try:
        for fonte in lista:
            if fonte["tipo"] != "html":
                achados.append({"id": fonte["id"], "situacao": "sem url (gnews)"})
                continue
            try:
                resp = cliente.get(
                    fonte["url"], headers={"User-Agent": UA}, follow_redirects=True
                )
                situacao = f"HTTP {resp.status_code}"
                final = str(resp.url)
            except httpx.HTTPError as exc:
                situacao = f"{type(exc).__name__}: {exc}"
                final = fonte["url"]
            achados.append(
                {"id": fonte["id"], "situacao": situacao, "url_final": final}
            )
    finally:
        if fechar:
            cliente.close()
    for a in achados:
        print(f"{a['id']}: {a['situacao']} {a.get('url_final', '')}")
    return achados
