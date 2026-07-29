"""Oportunidade e identidade canônica."""
import hashlib
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PARAMS_LIXO = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid",
}


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
    if not url:
        return ""
    partes = urlsplit(url.strip())
    query = urlencode(
        [(k, v) for k, v in parse_qsl(partes.query) if k.lower() not in PARAMS_LIXO]
    )
    caminho = partes.path.rstrip("/") or "/"
    return urlunsplit(
        (partes.scheme.lower(), partes.netloc.lower(), caminho, query, "")
    )


def id_oportunidade(fonte_id: str, url: str, titulo: str) -> str:
    chave = canonizar(url) or f"{fonte_id}|{titulo.strip().lower()}"
    return hashlib.sha1(chave.encode("utf-8")).hexdigest()
