import pytest

from editais3s import cli


def test_parser_aceita_diario_com_fontes():
    args = cli.construir_parser().parse_args(
        ["diario", "--fontes", "wri-brasil,funbio", "--sem-llm", "--forcar"]
    )
    assert args.comando == "diario"
    assert args.fontes == "wri-brasil,funbio"
    assert args.sem_llm is True and args.forcar is True


def test_parser_aceita_relatorio_com_data():
    args = cli.construir_parser().parse_args(["relatorio", "--data", "2026-07-29"])
    assert args.comando == "relatorio" and args.data == "2026-07-29"


def test_parser_aceita_bootstrap():
    assert cli.construir_parser().parse_args(["bootstrap"]).comando == "bootstrap"


def test_sem_comando_retorna_erro():
    assert cli.main([]) == 2


def test_main_diario_chama_pipeline(monkeypatch):
    chamadas = {}

    def falso(ids=None, forcar=False, usar_llm=True):
        chamadas.update(ids=ids, forcar=forcar, usar_llm=usar_llm)
        return "caminho"

    monkeypatch.setattr(cli.pipeline, "diario", falso)
    assert cli.main(["diario", "--fontes", "wri-brasil", "--sem-llm"]) == 0
    assert chamadas == {"ids": ["wri-brasil"], "forcar": False, "usar_llm": False}


def test_parser_aceita_retriar_com_sem_llm():
    args = cli.construir_parser().parse_args(["retriar", "--sem-llm"])
    assert args.comando == "retriar"
    assert args.sem_llm is True


def test_parser_aceita_retriar_sem_flags():
    args = cli.construir_parser().parse_args(["retriar"])
    assert args.comando == "retriar"
    assert args.sem_llm is False


def test_main_retriar_chama_pipeline(monkeypatch):
    chamadas = {}
    monkeypatch.setattr(cli.db, "conectar", lambda: "CON-FALSO")

    def falso(con, usar_llm=True):
        chamadas.update(con=con, usar_llm=usar_llm)
        return 3

    monkeypatch.setattr(cli.pipeline, "retriar", falso)
    assert cli.main(["retriar", "--sem-llm"]) == 0
    assert chamadas == {"con": "CON-FALSO", "usar_llm": False}
