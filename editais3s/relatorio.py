"""Banco -> Markdown do dia."""
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import (
    DIAS_SEM_ITEM_ALERTA,
    DIR_DADOS,
    PRAZO_APERTADO_DIAS,
    SCORE_KW_MINIMO,
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


def _match_forte(o: sqlite3.Row) -> bool:
    """True quando score_kw bate o mesmo limiar que escopo.triar usa para
    chamar um item de 'forte' — um conceito so' de match forte no sistema
    inteiro (score agregado), em vez de dois (esse e mais 'algum tema de
    peso 5'), que deixava sem marcador um item aderente cujo peso vem de
    varios temas menores somados."""
    score_kw = o["score_kw"]
    return score_kw is not None and score_kw >= SCORE_KW_MINIMO


def _linha(o: sqlite3.Row) -> str:
    titulo = _celula(o["titulo"])
    if _match_forte(o):
        titulo = f"★ {titulo}"
    url = _celula(o["url"])
    rotulo = f"[{titulo}]({url})" if url else titulo
    fonte_nome = _celula(o["fonte_nome"])
    if o["fonte_verificar"]:
        fonte_nome += " ⚠"
    return (
        f"| [ ] | {fonte_nome} | {rotulo} | {_celula(o['objeto'])[:120]} "
        f"| {_celula(o['prazo'])} | {_celula(o['score_llm'])} "
        f"| {_celula(o['justificativa_llm'])} |"
    )


def _tabela(titulo: str, linhas: list[sqlite3.Row]) -> str:
    if not linhas:
        return ""
    corpo = "\n".join(_linha(o) for o in linhas)
    return f"## {titulo}\n\n{CABECALHO_TABELA}\n{corpo}\n"


def _do_dia(con: sqlite3.Connection, data: str) -> list[sqlite3.Row]:
    # so 'descartada_kw' (veto — provadamente fora de escopo) e 'vencida'
    # (prazo confirmado no passado) ficam de fora. 'triagem' (score de juiz
    # abaixo do corte) tem que aparecer: o funil ranqueia, nao esconde.
    return con.execute(
        """
        SELECT * FROM oportunidades
         WHERE (visto_em LIKE ? OR atualizado_em LIKE ?)
           AND status NOT IN ('descartada_kw', 'vencida')
         ORDER BY COALESCE(score_llm, -1) DESC, prazo IS NULL, prazo
        """,
        (f"{data}%", f"{data}%"),
    ).fetchall()


def _parsear_prazo(prazo) -> date | None:
    """Parser defensivo unico para 'prazo': None ou string que nao bate o
    formato AAAA-MM-DD (ex: 'a definir') vira None, nunca levanta. Usado por
    _prazo_apertado e por prazo_vencido para nao ter dois parsers com bordas
    diferentes."""
    if not prazo:
        return None
    try:
        return datetime.strptime(prazo, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _prazo_apertado(o: sqlite3.Row, data: str) -> bool:
    prazo = _parsear_prazo(o["prazo"])
    if prazo is None:
        return False
    hoje = date.fromisoformat(data)
    return hoje <= prazo <= hoje + timedelta(days=PRAZO_APERTADO_DIAS)


def prazo_vencido(prazo, hoje: date) -> bool:
    """True somente quando 'prazo' e' uma data ISO valida e estritamente
    anterior a 'hoje'. NULL ou string malformada ('a definir') NAO e'
    vencido — prazo desconhecido continua fluindo para o juiz e o
    relatorio (o unico jeito de saber que uma oportunidade sem data
    publicada, tipo a maioria dos itens do WRI, nao morreu)."""
    data_prazo = _parsear_prazo(prazo)
    if data_prazo is None:
        return False
    return data_prazo < hoje


def _apertadas(con: sqlite3.Connection, data: str) -> list[sqlite3.Row]:
    """Prazo apertado independe de quando o item foi visto: um item captado
    ha semanas com prazo se aproximando tem que continuar aparecendo aqui
    todo dia ate o prazo passar. So exclui descartada_kw (veto de keyword —
    genuinamente fora do escopo) e vencida (prazo confirmado no passado);
    nova/reportada/triagem continuam, porque este bloco ignora score de
    proposito."""
    linhas = con.execute(
        "SELECT * FROM oportunidades WHERE status NOT IN ('descartada_kw', 'vencida') "
        "AND prazo IS NOT NULL"
    ).fetchall()
    return [o for o in linhas if _prazo_apertado(o, data)]


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
    apertadas = _apertadas(con, data)
    novas = [o for o in itens if (o["visto_em"] or "").startswith(data)]
    atualizadas = [o for o in itens if o not in novas]

    partes = [f"# Editais de terceiro setor — {data}\n"]

    if any(o["fonte_verificar"] for o in list(itens) + list(apertadas)):
        partes.append(
            "> ⚠ = fonte cuja URL ainda não foi confirmada contra o site do "
            "financiador (catálogo marcado `verificar`).\n"
        )

    if any(_match_forte(o) for o in list(itens) + list(apertadas)):
        partes.append(
            f"> ★ = match forte no funil de palavra-chave "
            f"(score_kw ≥ {SCORE_KW_MINIMO}, o mesmo limiar que classifica "
            "'forte' em escopo.triar).\n"
        )

    if execucao:
        # execucao['novas'] e' o contador real da varredura. len(novas) so
        # conta o que sobreviveu ate aqui (_do_dia ja filtrou descartada_kw),
        # entao usar o contador local aqui e' o que fazia o cabecalho dizer
        # "novas: 0" no mesmo run cujo stdout dizia "5 novas".
        novas_no_cabecalho = execucao.get("novas")
        if novas_no_cabecalho is None:
            novas_no_cabecalho = len(novas)
        partes.append(
            "Fontes ok: {ok} · fontes com erro: {erro} · novas: {novas} · "
            "custo: US$ {custo:.2f}\n".format(
                ok=execucao.get("fontes_ok", 0),
                erro=execucao.get("fontes_erro", 0),
                novas=novas_no_cabecalho,
                custo=float(execucao.get("custo_usd") or 0.0),
            )
        )
        if execucao.get("sem_llm"):
            partes.append(
                "> Aviso: rodada sem juiz LLM (--sem-llm ou ANTHROPIC_API_KEY "
                "ausente). Itens sem score aparecem no bloco Nao julgadas.\n"
            )

    # Blocos de classificacao (Aderentes/Olhar/Triagem/Nao julgadas) sao
    # mutuamente exclusivos por construcao: cada um deles particiona o mesmo
    # universo (novas) por uma faixa de score_llm que nao se sobrepoe com
    # nenhuma outra (None e' um caso a parte de qualquer faixa numerica).
    # 'Triagem' aqui e' "julgado e ficou abaixo do corte" (score_llm nao
    # nulo); 'Nao julgadas' e' "sem nota" (score_llm nulo) — antes as duas
    # usavam populacoes diferentes (novas vs. itens) e um item sem nota podia
    # cair nas duas ao mesmo tempo.
    aderentes = [
        o for o in novas
        if o["score_llm"] is not None and o["score_llm"] >= SCORE_LLM_ADERENTE
    ]
    olhar = [
        o for o in novas
        if o["score_llm"] is not None
        and SCORE_LLM_OLHAR <= o["score_llm"] < SCORE_LLM_ADERENTE
    ]
    triagem = [
        o for o in novas
        if o["score_llm"] is not None and o["score_llm"] < SCORE_LLM_OLHAR
    ]
    nao_julgadas = [o for o in novas if o["score_llm"] is None]

    for titulo, grupo in (
        (f"Prazo apertado (≤ {PRAZO_APERTADO_DIAS} dias)", apertadas),
        ("Aderentes", aderentes),
        ("Olhar", olhar),
        ("Nao julgadas", nao_julgadas),
        ("Atualizadas", atualizadas),
        ("Triagem", triagem),
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
