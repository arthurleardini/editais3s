from editais3s import db


def test_conectar_cria_tabelas(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    nomes = {
        linha["name"]
        for linha in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"snapshots", "oportunidades", "triagem", "execucoes"} <= nomes


def test_conectar_e_idempotente(tmp_path):
    caminho = tmp_path / "t.sqlite"
    db.conectar(caminho).close()
    con = db.conectar(caminho)
    assert con.execute("SELECT count(*) FROM oportunidades").fetchone()[0] == 0


def test_row_factory_permite_acesso_por_nome(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    con.execute(
        "INSERT INTO snapshots (fonte_id, hash) VALUES ('wri-brasil', 'abc')"
    )
    linha = con.execute("SELECT fonte_id, hash FROM snapshots").fetchone()
    assert linha["fonte_id"] == "wri-brasil"
