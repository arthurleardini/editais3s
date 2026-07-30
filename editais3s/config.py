"""Constantes do monitor. Sem lógica — só valores."""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CFG_FONTES = RAIZ / "fontes.json"
CFG_CANDIDATAS = RAIZ / "fontes_candidatas.json"
DIR_DADOS = RAIZ / "data"
BANCO = DIR_DADOS / "editais3s.sqlite"

UA = (
    "editais3s/0.1 (monitor de editais de terceiro setor; "
    "+mailto:arthurlorenzoleardini@gmail.com)"
)
TIMEOUT = 20.0
TIMEOUT_NAVEGADOR = 45.0
UA_NAVEGADOR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
TENTATIVAS = 2
CONCORRENCIA = 6
INTERVALO_DOMINIO = 1.0
MAX_CHARS_TEXTO = 40_000

MODELO_EXTRACAO = "claude-haiku-4-5"
MODELO_JUIZ = "claude-haiku-4-5"
MAX_TOKENS_EXTRACAO = 16_000

SCORE_KW_MINIMO = 4
SCORE_LLM_ADERENTE = 6
SCORE_LLM_OLHAR = 4
PRAZO_APERTADO_DIAS = 10
DIAS_SEM_ITEM_ALERTA = 60
DIAS_TOLERANCIA_VENCIDO = 7


def tem_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
