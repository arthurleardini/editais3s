"""Carga e validação do catálogo curado."""
import json
from pathlib import Path

from .config import CFG_FONTES

TIPOS = {"html", "rss", "json", "gnews"}
OBRIGATORIOS = ("id", "nome", "tipo", "dominio", "tier")


class FonteInvalida(ValueError):
    pass


def validar(fonte: dict) -> None:
    for campo in OBRIGATORIOS:
        if not fonte.get(campo):
            raise FonteInvalida(f"fonte {fonte.get('id', '?')}: campo {campo} ausente")
    if fonte["tipo"] not in TIPOS:
        raise FonteInvalida(
            f"fonte {fonte['id']}: tipo {fonte['tipo']!r} desconhecido"
        )
    if fonte["tipo"] in {"html", "rss", "json"} and not fonte.get("url"):
        raise FonteInvalida(f"fonte {fonte['id']}: tipo {fonte['tipo']} exige url")
    if fonte["tipo"] == "gnews" and not fonte.get("query"):
        raise FonteInvalida(f"fonte {fonte['id']}: tipo gnews exige query")


def carregar(caminho: Path | None = None) -> list[dict]:
    caminho = Path(caminho) if caminho else CFG_FONTES
    cfg = json.loads(caminho.read_text(encoding="utf-8"))
    lista = cfg["fontes"]
    for fonte in lista:
        validar(fonte)
    return lista


def filtrar(fontes: list[dict], ids: list[str] | None) -> list[dict]:
    if not ids:
        return fontes
    por_id = {f["id"]: f for f in fontes}
    faltando = [i for i in ids if i not in por_id]
    if faltando:
        raise FonteInvalida(f"id desconhecido no catalogo: {', '.join(faltando)}")
    return [por_id[i] for i in ids]
