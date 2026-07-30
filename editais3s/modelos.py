"""Oportunidade e identidade canônica."""
import hashlib
import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PARAMS_LIXO = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid",
}

_RE_PRAZO_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_PRAZO_BR = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$")


@dataclass
class Oportunidade:
    titulo: str
    objeto: str = ""
    url: str = ""
    prazo: str | None = None
    modalidade: str = "indefinido"
    valor_texto: str | None = None
    url_anexo: str | None = None
    publicado_em: str | None = None


def canonizar(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    partes = urlsplit(url)
    query = urlencode(
        [(k, v) for k, v in parse_qsl(partes.query) if k.lower() not in PARAMS_LIXO]
    )
    caminho = partes.path.rstrip("/") or "/"
    if not partes.netloc and not query and caminho in ("", "/"):
        return ""
    return urlunsplit(
        (partes.scheme.lower(), partes.netloc.lower(), caminho, query, "")
    )


def id_oportunidade(fonte_id: str, url: str, titulo: str) -> str:
    chave = canonizar(url) or f"{fonte_id}|{(titulo or '').strip().lower()}"
    return hashlib.sha1(chave.encode("utf-8")).hexdigest()


def normalizar_prazo(valor: str | None) -> str | None:
    """Normaliza prazo para ISO AAAA-MM-DD. Devolve None para qualquer coisa que
    nao seja data reconhecivel — inclusive placeholders do modelo.

    Aceita por allowlist de formato (ISO AAAA-MM-DD ou BR DD/MM/AAAA e
    DD-MM-AAAA), nunca por denylist de placeholder: e' a unica forma de
    cobrir '<UNKNOWN>', 'N/A', 'a definir' e qualquer placeholder futuro que
    o modelo inventar sem precisar listar cada um. DD/MM/AAAA e' tratado
    como dia/mes (paginas de financiador brasileiro), nunca mes/dia — mesmo
    quando ambiguo (ex: 03/04/2026)."""
    if valor is None:
        return None
    texto = valor.strip()
    if not texto:
        return None

    if _RE_PRAZO_ISO.match(texto):
        try:
            date.fromisoformat(texto)
        except ValueError:
            return None
        return texto

    m = _RE_PRAZO_BR.match(texto)
    if m:
        dia, mes, ano = (int(g) for g in m.groups())
        try:
            return date(ano, mes, dia).isoformat()
        except ValueError:
            return None

    return None
