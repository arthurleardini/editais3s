import pytest

from editais3s.modelos import normalizar_prazo


@pytest.mark.parametrize(
    "valor, esperado",
    [
        ("<UNKNOWN>", None),
        ("N/A", None),
        ("a definir", None),
        ("", None),
        (None, None),
        ("2026-08-10", "2026-08-10"),
        ("10/08/2026", "2026-08-10"),
        ("10-08-2026", "2026-08-10"),
        ("2026-13-45", None),
        ("31/02/2026", None),
        ("assim que possivel, sujeito a aprovacao do conselho", None),
    ],
)
def test_normalizar_prazo(valor, esperado):
    assert normalizar_prazo(valor) == esperado


def test_normalizar_prazo_ambiguo_trata_como_dia_mes():
    # 03/04/2026 e' genuinamente ambiguo entre DD/MM e MM/DD. Paginas de
    # financiador brasileiro escrevem DD/MM — e' a leitura adotada.
    assert normalizar_prazo("03/04/2026") == "2026-04-03"


def test_normalizar_prazo_nunca_levanta():
    # Entrada arbitraria nao pode derrubar o chamador.
    for lixo in ["99/99/9999", "----", "2026/08/10", "10/13/2026", "0/0/2026"]:
        normalizar_prazo(lixo)  # nao deve levantar
