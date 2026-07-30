import http.server
import threading

import pytest

pytest.importorskip("playwright")

from editais3s import navegador  # noqa: E402  (importorskip precisa vir antes)

# A string abaixo nao aparece contigua em nenhum lugar do HTML bruto: e
# montada por JS depois do load, juntando pedacos de um array. Se ela
# aparecer no HTML devolvido por navegador.baixar, prova que o Chromium
# executou o script — uma busca HTTP simples devolveria so o <script> cru,
# sem o textContent do <div> alterado.
FIXTURE = """<!doctype html>
<html><body>
<div id="alvo">vazio</div>
<script>
  var partes = ["RENDER", "IZADO", "-PELO-", "NAVEGADOR"];
  document.getElementById("alvo").textContent = partes.join("");
</script>
</body></html>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        corpo = FIXTURE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, format, *args):
        pass  # silencia log de acesso no stdout dos testes


@pytest.fixture
def servidor_local():
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    porta = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{porta}/"
    finally:
        httpd.shutdown()
        t.join()


def test_baixar_renderiza_js_da_pagina(servidor_local):
    status, html = navegador.baixar(servidor_local)
    assert status == 200
    assert "RENDERIZADO-PELO-NAVEGADOR" in html
    assert "vazio" not in html


def test_baixar_url_que_nao_responde_levanta_erro_navegador():
    with pytest.raises(navegador.ErroNavegador):
        navegador.baixar("http://127.0.0.1:1/", timeout=5.0)
