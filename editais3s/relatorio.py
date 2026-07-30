"""Banco -> Markdown do dia."""
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import (
    DIAS_SEM_ITEM_ALERTA,
    DIR_DADOS,
    PRAZO_APERTADO_DIAS,
    SCORE_LLM_ADERENTE,
    SCORE_LLM_OLHAR,
)

CABECALHO_TABELA = (
    "| | Fonte | Título | Objeto | Prazo | Score | Por quê |\n"
    "|---|---|---|---|---|---|---|"
)


def _celula(valor) -> str:
    if valor is None:
        return ""
    return str(valor).replace("|", "/").replace("\n", " ").strip()


def _linha(o: sqlite3.Row) -> str:
    titulo = _celula(o["titulo"])
    url = _celula(o["url"])
    rotulo = f"[{titulo}]({url})" if url else titulo
    return (
        f"| [ ] | {_celula(o['fonte_nome'])} | {rotulo} | {_celula(o['objeto'])[:120]} "
        f"| {_celula(o['prazo'])} | {_celula(o['score_llm'])} "
        f"| {_celula(o['justificativa_llm'])} |"
    )


def _tabela(titulo: str, linhas: list[sqlite3.Row]) -> str:
    if not linhas:
        return ""
    corpo = "\n".join(_linha(o) for o in linhas)
    return f"## {titulo}\n\n{CABECALHO_TABELA}\n{corpo}\n"


def _do_dia(con: sqlite3.Connection, data: str) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT * FROM oportunidades
         WHERE (visto_em LIKE ? OR atualizado_em LIKE ?)
           AND status != 'descartada_llm'
           AND status != 'descartada_kw'
         ORDER BY COALESCE(score_llm, -1) DESC, prazo IS NULL, prazo
        """,
        (f"{data}%", f"{data}%"),
    ).fetchall()


def _prazo_apertado(o: sqlite3.Row, data: str) -> bool:
    if not o["prazo"]:
        return False
    try:
        prazo = datetime.strptime(o["prazo"], "%Y-%m-%d").date()
    except ValueError:
        return False
    hoje = date.fromisoformat(data)
    return hoje <= prazo <= hoje + timedelta(days=PRAZO_APERTADO_DIAS)


def _saude(con: sqlite3.Connection, data: str) -> str:
    linhas = []
    for s in con.execute(
        "SELECT fonte_id, erro, erros_seguidos FROM snapshots "
        "WHERE erro IS NOT NULL AND erros_seguidos > 0 ORDER BY erros_seguidos DESC"
    ):
        linhas.append(
            f"- `{s['fonte_id']}`: {s['erro']} ({s['erros_seguidos']} execuções seguidas)"
        )

    corte = (date.fromisoformat(data) - timedelta(days=DIAS_SEM_ITEM_ALERTA)).isoformat()
    for s in con.execute(
        """
        SELECT s.fonte_id, MAX(o.visto_em) AS ultimo
          FROM snapshots s LEFT JOIN oportunidades o ON o.fonte_id = s.fonte_id
         GROUP BY s.fonte_id
        HAVING ultimo IS NULL OR ultimo < ?
        """,
        (corte,),
    ):
        linhas.append(
            f"- `{s['fonte_id']}`: nenhum item há mais de {DIAS_SEM_ITEM_ALERTA} dias "
            "(possível parser cego ou seção movida)"
        )

    if not linhas:
        return ""
    return "## Saude\n\n" + "\n".join(linhas) + "\n"


def gerar(con: sqlite3.Connection, data: str, execucao: dict | None = None) -> str:
    itens = _do_dia(con, data)
    novas = [o for o in itens if (o["visto_em"] or "").startswith(data)]
    atualizadas = [o for o in itens if o not in novas]

    partes = [f"# Editais de terceiro setor — {data}\n"]

    if execucao:
        partes.append(
            "Fontes ok: {ok} · fontes com erro: {erro} · novas: {novas} · "
            "custo: US$ {custo:.2f}\n".format(
                ok=execucao.get("fontes_ok", 0),
                erro=execucao.get("fontes_erro", 0),
                novas=len(novas),
                custo=float(execucao.get("custo_usd") or 0.0),
            )
        )
        if execucao.get("sem_llm"):
            partes.append(
                "> Aviso: rodada sem juiz LLM (--sem-llm ou ANTHROPIC_API_KEY "
                "ausente). Itens sem score aparecem no bloco Nao julgadas.\n"
            )

    apertadas = [o for o in itens if _prazo_apertado(o, data)]
    aderentes = [
        o for o in novas
        if o["score_llm"] is not None and o["score_llm"] >= SCORE_LLM_ADERENTE
    ]
    olhar = [
        o for o in novas
        if o["score_llm"] is not None
        and SCORE_LLM_OLHAR <= o["score_llm"] < SCORE_LLM_ADERENTE
    ]
    nao_julgadas = [o for o in novas if o["score_llm"] is None]

    for titulo, grupo in (
        (f"Prazo apertado (≤ {PRAZO_APERTADO_DIAS} dias)", apertadas),
        ("Aderentes", aderentes),
        ("Olhar", olhar),
        ("Nao julgadas", nao_julgadas),
        ("Atualizadas", atualizadas),
    ):
        bloco = _tabela(titulo, grupo)
        if bloco:
            partes.append(bloco)

    if not itens:
        partes.append("Nenhuma oportunidade nova hoje.\n")

    saude = _saude(con, data)
    if saude:
        partes.append(saude)

    return "\n".join(partes)


def escrever(con: sqlite3.Connection, data: str, execucao: dict | None = None) -> Path:
    DIR_DADOS.mkdir(parents=True, exist_ok=True)
    caminho = DIR_DADOS / f"novas_{data}.md"
    caminho.write_text(gerar(con, data, execucao), encoding="utf-8")
    return caminho
