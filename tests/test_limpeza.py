from editais3s import limpeza

HTML = """
<html><head><style>.a{color:red}</style><script>var x=1</script></head>
<body>
<nav>Home Sobre Contato</nav>
<h1>Oportunidades</h1>
<ul>
  <li><a href="/media/tdr-ouvidoria.pdf">TdR FLWTDR-2026-011 Ouvidoria Restaura Biomas</a>
      Prazo: 13/07/2026</li>
  <li><a href="/sobre">Quem somos</a></li>
</ul>
<footer>Rodape institucional</footer>
</body></html>
"""

HTML_MULTILINHA = """<body><ul><li><a href="/media/tdr.pdf">TdR Ouvidoria
      Restaura Biomas</a> Prazo: 13/07/2026</li></ul></body>"""


def test_limpar_remove_navegacao_e_script():
    texto = limpeza.limpar(HTML)
    assert "Home Sobre Contato" not in texto
    assert "Rodape institucional" not in texto
    assert "var x=1" not in texto
    assert "color:red" not in texto


def test_limpar_inlina_link_junto_do_texto():
    texto = limpeza.limpar(HTML)
    assert "[TdR FLWTDR-2026-011 Ouvidoria Restaura Biomas](/media/tdr-ouvidoria.pdf)" in texto


def test_limpar_preserva_texto_vizinho_do_link():
    texto = limpeza.limpar(HTML)
    assert "13/07/2026" in texto
    assert "Quem somos" in texto


def test_limpar_respeita_limite_de_caracteres():
    assert len(limpeza.limpar("<body>" + "x" * 500 + "</body>", max_chars=100)) == 100


def test_hash_estavel_e_sensivel():
    assert limpeza.hash_texto("a") == limpeza.hash_texto("a")
    assert limpeza.hash_texto("a") != limpeza.hash_texto("b")
    assert len(limpeza.hash_texto("a")) == 40


def test_ancora_multilinha_fica_em_uma_linha():
    texto = limpeza.limpar(HTML_MULTILINHA)
    assert "[TdR Ouvidoria Restaura Biomas](/media/tdr.pdf)" in texto
    linhas = [l for l in texto.splitlines() if "tdr.pdf" in l]
    assert len(linhas) == 1
    # achado 11: len(linhas) == 1 sozinho nao e load-bearing — se a quebra de
    # linha no meio do titulo nao for colapsada, "TdR Ouvidoria" fica isolado
    # numa linha anterior que nao contem "tdr.pdf", e essa mesma asserção
    # passaria do mesmo jeito. Confirma que o titulo inteiro esta na mesma
    # linha do link.
    assert "TdR Ouvidoria" in linhas[0]
