"""Texto de página -> lista de oportunidades.

Caminho principal: Haiku com structured output. Caminho de degradação: regex
sobre as âncoras já inlinadas por limpeza.limpar, quando não há
ANTHROPIC_API_KEY ou o SDK falha.
"""
import re
from urllib.parse import urljoin

from .config import MODELO_EXTRACAO, tem_api_key
from .modelos import Oportunidade

SCHEMA = {
    "type": "object",
    "properties": {
        "oportunidades": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "titulo": {"type": "string"},
                    "objeto": {"type": "string"},
                    "url": {"type": "string"},
                    "prazo": {"type": "string"},
                    "modalidade": {
                        "type": "string",
                        "enum": ["tdr", "chamada", "cotacao", "rfp", "indefinido"],
                    },
                    "valor_texto": {"type": "string"},
                },
                "required": ["titulo"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["oportunidades"],
    "additionalProperties": False,
}

INSTRUCAO = (
    "Você recebe o texto de uma página de um financiador de terceiro setor "
    "brasileiro (instituto, fundação ou ONG internacional). Extraia APENAS "
    "oportunidades de CONTRATAÇÃO DE FORNECEDOR: termo de referência, chamada "
    "de propostas, cotação, RFP, seleção de consultoria. NÃO extraia vaga de "
    "emprego, bolsa, prêmio, chamada de apoio a projeto de terceiros, nem "
    "notícia. Links aparecem no formato [texto](url) — devolva a url do link do "
    "próprio edital. Prazo em ISO AAAA-MM-DD quando houver data; omita se não "
    "houver. Se a página não tiver nenhuma oportunidade, devolva lista vazia."
)

RE_LINK = re.compile(r"\[([^\]]{4,200})\]\(([^)]+)\)")
RE_EDITAL = re.compile(
    r"edital|termo de refer|\btdr\b|chamada|cota[çc][ãa]o|\brfp\b|"
    r"request for proposal|sele[çc][ãa]o de consultor|consultoria",
    re.I,
)


def chamar_llm(texto: str, fonte: dict) -> dict:
    import anthropic

    cliente = anthropic.Anthropic()
    resposta = cliente.messages.create(
        model=MODELO_EXTRACAO,
        max_tokens=4096,
        system=INSTRUCAO,
        tools=[
            {
                "name": "registrar",
                "description": "Registra as oportunidades encontradas.",
                "input_schema": SCHEMA,
            }
        ],
        tool_choice={"type": "tool", "name": "registrar"},
        messages=[
            {
                "role": "user",
                "content": f"Fonte: {fonte['nome']}\n\n{texto}",
            }
        ],
    )
    for bloco in resposta.content:
        if getattr(bloco, "type", None) == "tool_use":
            return bloco.input
    return {"oportunidades": []}


def _monta(item: dict, fonte: dict) -> Oportunidade | None:
    titulo = (item.get("titulo") or "").strip()
    if not titulo:
        return None
    url = (item.get("url") or "").strip()
    if url and fonte.get("url"):
        url = urljoin(fonte["url"], url)
    return Oportunidade(
        titulo=titulo,
        objeto=(item.get("objeto") or "").strip(),
        url=url,
        prazo=(item.get("prazo") or "").strip() or None,
        modalidade=item.get("modalidade") or "indefinido",
        valor_texto=(item.get("valor_texto") or "").strip() or None,
    )


def heuristica(texto: str, fonte: dict) -> list[Oportunidade]:
    achados: list[Oportunidade] = []
    vistos: set[str] = set()
    for titulo, url in RE_LINK.findall(texto):
        titulo = titulo.strip()
        if not RE_EDITAL.search(titulo) or titulo in vistos:
            continue
        vistos.add(titulo)
        achados.append(
            _monta({"titulo": titulo, "url": url.strip()}, fonte)  # type: ignore[arg-type]
        )
    return [o for o in achados if o]


def extrair(texto: str, fonte: dict, chamar=None) -> list[Oportunidade]:
    if chamar is None:
        if not tem_api_key():
            return heuristica(texto, fonte)
        chamar = chamar_llm
    try:
        payload = chamar(texto, fonte)
    except Exception:
        return heuristica(texto, fonte)
    itens = payload.get("oportunidades") if isinstance(payload, dict) else None
    if not isinstance(itens, list):
        return []
    montadas = [_monta(i, fonte) for i in itens if isinstance(i, dict)]
    return [o for o in montadas if o]
