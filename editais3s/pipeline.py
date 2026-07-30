"""Orquestra a varredura: coleta -> extração -> funil -> persistência -> relatório."""
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import coleta, db, escopo, extrai, fontes as cat, juiz, oportunidades, relatorio
from .config import INTERVALO_DOMINIO, SCORE_LLM_OLHAR, TIMEOUT, UA, tem_api_key

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
    # base UTC — mesma usada em oportunidades._agora/diario, nao date.today()
    # local (rodada noturna em America/Sao_Paulo julgaria "vencido" um prazo
    # de amanha).
    hoje = datetime.now(timezone.utc).date()
    resumo = {
        "fontes_ok": 0, "fontes_erro": 0, "novas": 0,
        "atualizadas": 0,
        "sem_mudanca": 0, "bloqueadas": 0, "fora_de_fase": 0,
        "sem_llm": not usar_llm or not tem_api_key(),
    }
    pendentes: list[dict] = []

    for i, fonte in enumerate(lista_fontes):
        if fonte["tipo"] != "html":
            # gnews e outros tipos ainda nao cobertos nesta fase do pipeline —
            # nao e erro nem bloqueio, e so um tipo de fonte fora da fase atual.
            resumo["fora_de_fase"] += 1
            continue
        if i:
            pausar(INTERVALO_DOMINIO)

        if not coleta.robots_permite(fonte, cliente):
            resumo["bloqueadas"] += 1
            # Sem isso a fonte some de snapshots e o bloco Saude nunca aponta
            # o bloqueio: se um financiador publicar Disallow amanha, o
            # monitor para de olhar pra ele e nenhum relatorio avisa.
            coleta._gravar_erro(con, fonte["id"], None, "indisponivel: robots.txt")
            continue

        r = coleta.coletar(fonte, con, cliente, forcar=forcar)
        if not r.ok:
            resumo["fontes_erro"] += 1
            continue
        resumo["fontes_ok"] += 1
        if not r.mudou:
            resumo["sem_mudanca"] += 1
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
                "SELECT id, titulo, objeto, fonte_nome, score_llm, prazo "
                "FROM oportunidades WHERE id=?",
                (oid,),
            ).fetchone()
            if relatorio.prazo_vencido(linha["prazo"], hoje):
                # prazo confirmado no passado: nao julga (economiza a
                # chamada de LLM, que e o ponto) nem entra em pendentes.
                # prazo NULL/malformado nao cai aqui — prazo_vencido so'
                # confirma data ISO estritamente anterior a hoje.
                con.execute(
                    "UPDATE oportunidades SET status='vencida' WHERE id=?", (oid,)
                )
                continue
            classe, score_kw, temas = escopo.triar(
                f"{linha['titulo']} {linha['objeto'] or ''}"
            )
            con.execute(
                "UPDATE oportunidades SET score_kw=?, temas_kw=? WHERE id=?",
                (score_kw, ", ".join(temas), oid),
            )
            if classe != "vetado":
                # forte ou fraco: o funil ranqueia, nao esconde. Ambos vao ao
                # juiz — um item fraco (titulo curto sem objeto, por exemplo)
                # so foi provado "fora de escopo" se o veto disser isso, e
                # veto sem tema forte e' vetado, nao fraco.
                pendentes.append(dict(linha))
            elif linha["score_llm"] is None:
                # so descarta por keyword quem o juiz nunca viu. Um item ja
                # julgado nao pode ser rebaixado so porque o objeto (prosa da
                # LLM de extracao) mudou de um jeito que o funil nao gosta —
                # o score_llm que o juiz deu prevalece.
                con.execute(
                    "UPDATE oportunidades SET status='descartada_kw' WHERE id=?", (oid,)
                )
        con.commit()

    if usar_llm and pendentes:
        juiz.aplicar(con, juiz.julgar(pendentes))

    resumo["ignoradas"] = (
        resumo["sem_mudanca"] + resumo["bloqueadas"] + resumo["fora_de_fase"]
    )

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
    ids: list[str] | None = None,
    forcar: bool = False,
    usar_llm: bool = True,
    data: str | None = None,
) -> Path:
    con = db.conectar()
    lista = cat.filtrar(cat.carregar(), ids)
    with _cliente() as cliente:
        resumo = varrer(con, lista, cliente, forcar=forcar, usar_llm=usar_llm)
    # visto_em/atualizado_em sao gravados em UTC (oportunidades._agora); usar
    # date.today() (local) faria o relatorio de uma rodada noturna em
    # America/Sao_Paulo procurar a data errada e sair vazio.
    data = data or datetime.now(timezone.utc).date().isoformat()
    caminho = relatorio.escrever(con, data, execucao=resumo)
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


def retriar(con: sqlite3.Connection, usar_llm: bool = True) -> int:
    """Reclassifica pelo funil atual toda linha que o juiz nunca viu
    (score_llm IS NULL). Migra linhas presas em status antigo (ex:
    descartada_kw de uma classificacao de veto que a regra atual nao
    reproduz mais) e manda as nao vetadas para o juiz. Tambem migra para
    'vencida' toda linha (julgada ou nao, de qualquer rodada anterior) cujo
    prazo confirmado ja passou — e' o que move os itens historicos com
    prazo 2019/2021/2023 (ja julgados e rankeados numa rodada antiga) para
    fora do relatorio. Devolve quantas linhas mudaram de status, do inicio
    ao fim (inclui o efeito do juiz)."""
    hoje = datetime.now(timezone.utc).date()

    candidatas_prazo = con.execute(
        "SELECT id, prazo, status, score_llm FROM oportunidades WHERE prazo IS NOT NULL"
    ).fetchall()
    vencidas = [
        l["id"] for l in candidatas_prazo if relatorio.prazo_vencido(l["prazo"], hoje)
    ]

    linhas = con.execute(
        "SELECT id, titulo, objeto, fonte_nome, status FROM oportunidades "
        "WHERE score_llm IS NULL"
    ).fetchall()

    original = {l["id"]: l["status"] for l in linhas}
    for l in candidatas_prazo:
        original.setdefault(l["id"], l["status"])

    if vencidas:
        marcador = ",".join("?" * len(vencidas))
        con.execute(
            f"UPDATE oportunidades SET status='vencida' WHERE id IN ({marcador})",
            tuple(vencidas),
        )
        con.commit()

    vencidas_set = set(vencidas)

    # DIAS_TOLERANCIA_VENCIDO pode ter mudado desde a ultima varredura/retriar:
    # uma linha ja julgada (score_llm setado) que uma rodada anterior marcou
    # 'vencida' sob uma janela menor (ou zero) pode nao ser mais vencida sob a
    # janela atual. Essa linha nao passa pelo loop de 'linhas' abaixo (que so
    # pega score_llm IS NULL), entao sem isto ficaria presa em 'vencida' para
    # sempre. Reverte para o status que o score_llm ja julgado indica — mesmo
    # corte que juiz.aplicar usa.
    for l in candidatas_prazo:
        if (
            l["status"] == "vencida"
            and l["id"] not in vencidas_set
            and l["score_llm"] is not None
        ):
            novo_status = "reportada" if l["score_llm"] >= SCORE_LLM_OLHAR else "triagem"
            con.execute(
                "UPDATE oportunidades SET status=? WHERE id=?", (novo_status, l["id"])
            )
    con.commit()

    pendentes: list[dict] = []

    for linha in linhas:
        if linha["id"] in vencidas_set:
            # ja marcada vencida acima: nao gasta juiz num item expirado.
            continue
        classe, score_kw, temas = escopo.triar(
            f"{linha['titulo']} {linha['objeto'] or ''}"
        )
        novo_status = "descartada_kw" if classe == "vetado" else "nova"
        con.execute(
            "UPDATE oportunidades SET score_kw=?, temas_kw=?, status=? WHERE id=?",
            (score_kw, ", ".join(temas), novo_status, linha["id"]),
        )
        if classe != "vetado":
            pendentes.append(dict(linha))
    con.commit()

    if usar_llm and pendentes:
        juiz.aplicar(con, juiz.julgar(pendentes))

    if not original:
        return 0
    marcador = ",".join("?" * len(original))
    finais = con.execute(
        f"SELECT id, status FROM oportunidades WHERE id IN ({marcador})",
        tuple(original),
    ).fetchall()
    return sum(1 for f in finais if f["status"] != original[f["id"]])
