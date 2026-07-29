"""Score de aderência ao portfólio NOTABC, por LLM, em uma chamada por execução."""
import sqlite3

from .config import MODELO_JUIZ, SCORE_LLM_OLHAR, tem_api_key

SCHEMA = {
    "type": "object",
    "properties": {
        "avaliacoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "score": {"type": "integer"},
                    "justificativa": {"type": "string"},
                    "prazo": {"type": "string"},
                    "modalidade": {
                        "type": "string",
                        "enum": ["tdr", "chamada", "cotacao", "rfp", "indefinido"],
                    },
                },
                "required": ["id", "score", "justificativa"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["avaliacoes"],
    "additionalProperties": False,
}

PORTFOLIO = (
    "A NOTABC é uma consultoria pequena que entrega: plataforma e produto de "
    "dados ponta a ponta (pipeline, modelagem, painel), ciência de dados "
    "aplicada a política pública e socioambiental, site e portal institucional "
    "com arquitetura da informação e painel administrador próprio, análise "
    "geoespacial, e desenho de processo com normatização interna. Caso de "
    "referência: para o WRI Brasil entregou o site bilíngue do projeto Restaura "
    "Biomas (arquitetura da informação, acervo de relatórios, radar de notícias, "
    "painel administrador autônomo) e depois concorreu ao TdR de Ouvidoria "
    "Institucional do mesmo projeto. Não faz obra, não faz fornecimento de "
    "material, não coloca mão de obra terceirizada em posto de trabalho."
)

INSTRUCAO = (
    "Você avalia oportunidades de contratação captadas em sites de financiadores "
    "de terceiro setor. Para cada item, dê um score de 0 a 10 de aderência ao "
    "perfil abaixo e uma justificativa de UMA frase, factual, sem elogio. "
    "10 = objeto é exatamente o que a consultoria entrega. 0 = objeto sem "
    "nenhuma relação. Se o item for vaga de emprego, bolsa, prêmio ou apoio a "
    "projeto de terceiro, dê 0. Extraia também o prazo em AAAA-MM-DD e a "
    "modalidade, quando o texto permitir.\n\nPerfil:\n" + PORTFOLIO
)


def _bloco(itens: list[dict]) -> str:
    linhas = []
    for i in itens:
        linhas.append(
            f"id: {i['id']}\nfonte: {i.get('fonte_nome', '')}\n"
            f"titulo: {i.get('titulo', '')}\nobjeto: {i.get('objeto', '')}\n---"
        )
    return "\n".join(linhas)


def chamar_llm(itens: list[dict]) -> dict:
    import anthropic

    cliente = anthropic.Anthropic()
    resposta = cliente.messages.create(
        model=MODELO_JUIZ,
        max_tokens=4096,
        system=INSTRUCAO,
        tools=[
            {
                "name": "avaliar",
                "description": "Registra a avaliação de cada oportunidade.",
                "input_schema": SCHEMA,
            }
        ],
        tool_choice={"type": "tool", "name": "avaliar"},
        messages=[{"role": "user", "content": _bloco(itens)}],
    )
    for bloco in resposta.content:
        if getattr(bloco, "type", None) == "tool_use":
            return bloco.input
    return {"avaliacoes": []}


def julgar(itens: list[dict], chamar=None) -> list[dict]:
    if not itens:
        return []
    if chamar is None:
        if not tem_api_key():
            return [_vazio(i) for i in itens]
        chamar = chamar_llm

    try:
        payload = chamar(itens)
    except Exception:
        return [_vazio(i) for i in itens]

    avaliacoes = payload.get("avaliacoes") if isinstance(payload, dict) else None
    por_id = {}
    if isinstance(avaliacoes, list):
        for a in avaliacoes:
            if isinstance(a, dict) and a.get("id"):
                por_id[a["id"]] = a

    saida = []
    for i in itens:
        a = por_id.get(i["id"])
        if not a:
            saida.append(_vazio(i))
            continue
        score = a.get("score")
        score = None if not isinstance(score, int) else max(0, min(10, score))
        saida.append(
            {
                "id": i["id"],
                "score_llm": score,
                "justificativa_llm": (a.get("justificativa") or "").strip() or None,
                "prazo": (a.get("prazo") or "").strip() or None,
                "modalidade": a.get("modalidade"),
                "modelo_llm": MODELO_JUIZ,
            }
        )
    return saida


def _vazio(item: dict) -> dict:
    return {
        "id": item["id"],
        "score_llm": None,
        "justificativa_llm": None,
        "prazo": None,
        "modalidade": None,
        "modelo_llm": None,
    }


def aplicar(con: sqlite3.Connection, julgados: list[dict]) -> None:
    for j in julgados:
        score = j.get("score_llm")
        if score is None:
            status = "nova"
        elif score < SCORE_LLM_OLHAR:
            status = "descartada_llm"
        else:
            status = "reportada"
        con.execute(
            """
            UPDATE oportunidades
               SET score_llm=?, justificativa_llm=?, modelo_llm=?, status=?,
                   prazo=COALESCE(?, prazo),
                   modalidade=COALESCE(?, modalidade)
             WHERE id=?
            """,
            (
                score, j.get("justificativa_llm"), j.get("modelo_llm"), status,
                j.get("prazo"), j.get("modalidade"), j["id"],
            ),
        )
    con.commit()
