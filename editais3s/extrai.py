"""Texto de página -> lista de oportunidades.

Caminho principal: Haiku com structured output. Caminho de degradação: regex
sobre as âncoras já inlinadas por limpeza.limpar, quando não há
ANTHROPIC_API_KEY ou o SDK falha.

Páginas grandes (catálogo com dezenas de itens: título longo, prazo,
contato, url) estouram o orçamento de tokens de saída numa chamada só — o
modelo, sem conseguir terminar o JSON, devolve lista vazia em vez de erro.
Por isso o texto é dividido em pedaços sobrepostos antes de chamar o
modelo, e os resultados são mesclados com dedup — ver `_dividir_em_chunks`
e `extrair`.
"""
import re
from urllib.parse import urljoin

from .config import MAX_TOKENS_EXTRACAO, MODELO_EXTRACAO, tem_api_key
from .modelos import Oportunidade, normalizar_prazo

# ~8.000 caracteres por chamada com ~500 de sobreposição: grande o bastante
# pra manter contexto por chamada, pequeno o bastante pra sobrar orçamento de
# saída para dezenas de itens com título+prazo+contato+url. A sobreposição
# evita perder um item cujo bloco de texto cai bem na borda de um pedaço.
TAMANHO_CHUNK = 8_000
SOBREPOSICAO_CHUNK = 500

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
        max_tokens=MAX_TOKENS_EXTRACAO,
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
        prazo=normalizar_prazo(item.get("prazo")),
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


def _dividir_em_chunks(
    texto: str, tamanho: int = TAMANHO_CHUNK, sobreposicao: int = SOBREPOSICAO_CHUNK
) -> list[str]:
    """Pedaços sobrepostos de `texto`. Texto que já cabe no tamanho vira um
    único pedaço (caso comum: a maioria das fontes é pequena e isto vira uma
    chamada só, igual ao comportamento anterior à divisão)."""
    n = len(texto)
    if n <= tamanho:
        return [texto]
    passo = tamanho - sobreposicao
    pedacos = []
    inicio = 0
    while inicio < n:
        fim = min(inicio + tamanho, n)
        pedacos.append(texto[inicio:fim])
        if fim >= n:
            break
        inicio += passo
    return pedacos


def _itens_do_payload(payload) -> list[dict]:
    """Extrai a lista de itens brutos de um payload de um pedaço. Payload
    malformado (sem 'oportunidades' ou nao-lista) contribui nada, sem
    levantar — cada pedaco e' isolado dos outros."""
    if not isinstance(payload, dict):
        return []
    itens = payload.get("oportunidades")
    if not isinstance(itens, list):
        return []
    return [i for i in itens if isinstance(i, dict)]


def extrair(texto: str, fonte: dict, chamar=None) -> list[Oportunidade]:
    if chamar is None:
        if not tem_api_key():
            return heuristica(texto, fonte)
        chamar = chamar_llm

    try:
        brutos: list[dict] = []
        for pedaco in _dividir_em_chunks(texto):
            payload = chamar(pedaco, fonte)
            brutos.extend(_itens_do_payload(payload))
    except Exception:
        # Qualquer pedaço que falhe (rede, SDK, o que for) descarta a
        # extração inteira desta página para a heurística — nao mistura
        # itens de LLM parciais com itens de regex.
        return heuristica(texto, fonte)

    montadas = [o for o in (_monta(i, fonte) for i in brutos) if o]
    vistos: set[tuple[str, str]] = set()
    mescladas: list[Oportunidade] = []
    for o in montadas:
        chave = (o.titulo, o.url)
        if chave in vistos:
            continue
        vistos.add(chave)
        mescladas.append(o)
    return mescladas
