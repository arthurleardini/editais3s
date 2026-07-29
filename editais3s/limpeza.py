"""HTML -> texto enxuto, com âncora inline no formato [texto](url)."""
import hashlib
import re

from selectolax.parser import HTMLParser

from .config import MAX_CHARS_TEXTO

REMOVER = (
    "script", "style", "noscript", "svg", "nav", "header", "footer",
    "aside", "form", "iframe",
)

RE_ANCORA = re.compile(
    r"<a\b[^>]*\bhref=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S
)
RE_TAG = re.compile(r"<[^>]+>")
RE_ESPACO = re.compile(r"[ \t]+")
RE_LINHAS = re.compile(r"\n{3,}")


def _inline_ancoras(html: str) -> str:
    def troca(m: re.Match) -> str:
        href = m.group(1).strip()
        dentro = RE_ESPACO.sub(" ", RE_TAG.sub(" ", m.group(2))).strip()
        return f" [{dentro}]({href}) " if dentro else " "

    return RE_ANCORA.sub(troca, html)


def limpar(html: str, max_chars: int | None = None) -> str:
    limite = MAX_CHARS_TEXTO if max_chars is None else max_chars
    arvore = HTMLParser(_inline_ancoras(html))
    for tag in REMOVER:
        for no in arvore.css(tag):
            no.decompose()
    raiz = arvore.body or arvore.root
    bruto = raiz.text(separator="\n") if raiz else ""
    linhas = [RE_ESPACO.sub(" ", l).strip() for l in bruto.splitlines()]
    texto = "\n".join(l for l in linhas if l)
    return RE_LINHAS.sub("\n\n", texto)[:limite]


def hash_texto(texto: str) -> str:
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()
