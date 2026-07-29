"""Dicionário de escopo NOTABC para terceiro setor.

Editado à mão conforme triagem. Marque cada lote com (triagem AAAA-MM-DD).
"""
import re
import unicodedata

import ahocorasick

from .config import SCORE_KW_MINIMO

TEMAS: dict[str, int] = {
    # peso 5 — núcleo do portfólio
    "plataforma de dados": 5,
    "ciencia de dados": 5,
    "engenharia de dados": 5,
    "arquitetura de dados": 5,
    "desenvolvimento web": 5,
    "visualizacao de dados": 5,
    # peso 4
    "dashboard": 4,
    "painel de dados": 4,
    "painel de indicadores": 4,
    "business intelligence": 4,
    "etl": 4,
    "pipeline de dados": 4,
    "geoespacial": 4,
    "geoprocessamento": 4,
    "sensoriamento remoto": 4,
    "mrv": 4,
    "monitoramento e avaliacao": 4,
    "ouvidoria": 4,
    "canal de denuncia": 4,
    "aprendizado de maquina": 4,
    "inteligencia artificial": 4,
    "portal web": 4,
    "aplicacao web": 4,
    "site institucional": 4,
    # peso 3
    "banco de dados": 3,
    "cms": 3,
    "wordpress": 3,
    "ux": 3,
    "design de interface": 3,
    "indicadores": 3,
    "lgpd": 3,
    "protecao de dados": 3,
    "api": 3,
    "integracao de sistemas": 3,
    "automacao": 3,
    "formulario de coleta": 3,
    "transparencia ativa": 3,
}

VETOS: tuple[str, ...] = (
    "vaga de emprego", "processo seletivo de colaborador", "banco de talentos",
    "bolsa de estudo", "bolsa de pesquisa", "premio",
    "chamada de projetos", "apoio a projetos", "edital de fomento",
    "obra", "reforma", "locacao", "servico grafico", "buffet", "coffee break",
    "passagem aerea", "producao de video", "assessoria de imprensa",
    "auditoria contabil", "consultoria juridica", "traducao simultanea",
)

PESO_FORTE = 4


def _automato(termos) -> ahocorasick.Automaton:
    a = ahocorasick.Automaton()
    for termo in termos:
        a.add_word(termo, termo)
    a.make_automaton()
    return a


_TEMAS = _automato(TEMAS)
_VETOS = _automato(VETOS)


def normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return sem_acento.lower()


def _com_fronteira(alvo: str, termo: str) -> bool:
    """O autômato casa substring ('api' dentro de 'rapido'). Confirma fronteira."""
    return re.search(rf"(?<!\w){re.escape(termo)}(?!\w)", alvo) is not None


def pontuar(texto: str) -> tuple[int, list[str]]:
    alvo = normalizar(texto)
    achados = {
        termo for _, termo in _TEMAS.iter(alvo) if _com_fronteira(alvo, termo)
    }
    ordenados = sorted(achados, key=lambda t: (-TEMAS[t], t))
    return sum(TEMAS[t] for t in ordenados), ordenados


def tem_veto(texto: str) -> bool:
    alvo = normalizar(texto)
    return any(_com_fronteira(alvo, termo) for _, termo in _VETOS.iter(alvo))


def avaliar(texto: str) -> tuple[bool, int, list[str]]:
    score, temas = pontuar(texto)
    forte = any(TEMAS[t] >= PESO_FORTE for t in temas)
    if tem_veto(texto) and not forte:
        return False, score, temas
    return score >= SCORE_KW_MINIMO, score, temas
