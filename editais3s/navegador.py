"""Coleta de paginas via Chromium headless, para fontes que bloqueiam
requisicao HTTP simples (403 por nginx/CloudFront) mas servem navegador real."""
from .config import TIMEOUT_NAVEGADOR, UA_NAVEGADOR


class ErroNavegador(Exception):
    pass


def baixar(url: str, timeout: float | None = None) -> tuple[int, str]:
    """Busca a pagina com Chromium headless. Devolve (status_http, html)."""
    timeout = TIMEOUT_NAVEGADOR if timeout is None else timeout
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ErroNavegador(f"playwright nao instalado: {exc}") from exc

    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch(headless=True)
            try:
                pagina = navegador.new_page(user_agent=UA_NAVEGADOR)
                resposta = pagina.goto(
                    url, wait_until="domcontentloaded", timeout=timeout * 1000
                )
                if resposta is None:
                    raise ErroNavegador(f"navegador: sem resposta para {url}")
                status = resposta.status
                html = pagina.content()
            finally:
                navegador.close()
    except ErroNavegador:
        raise
    except Exception as exc:
        raise ErroNavegador(f"{type(exc).__name__}: {exc}") from exc

    return status, html
