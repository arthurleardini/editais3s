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


def test_conectar_migra_banco_antigo_sem_fonte_verificar(tmp_path):
    """Achado 8 (residual): CREATE TABLE IF NOT EXISTS nunca adiciona coluna
    nova a uma tabela ja existente. Um banco criado por uma versao anterior
    (sem fonte_verificar) tem que ganhar a coluna na proxima conectar(),
    senao o primeiro INSERT depois do deploy quebra em produção, uma vez,
    no escuro, num cron."""
    import sqlite3

    caminho = tmp_path / "antigo.sqlite"
    con_cru = sqlite3.connect(caminho)
    con_cru.execute(
        """
        CREATE TABLE oportunidades (
          id TEXT PRIMARY KEY,
          fonte_id TEXT NOT NULL,
          fonte_nome TEXT,
          trilha TEXT NOT NULL,
          titulo TEXT NOT NULL,
          objeto TEXT,
          url TEXT,
          url_anexo TEXT,
          prazo TEXT,
          publicado_em TEXT,
          modalidade TEXT,
          valor_texto TEXT,
          visto_em TEXT NOT NULL,
          atualizado_em TEXT,
          hash_conteudo TEXT,
          score_kw INTEGER,
          temas_kw TEXT,
          score_llm INTEGER,
          justificativa_llm TEXT,
          modelo_llm TEXT,
          status TEXT NOT NULL DEFAULT 'nova'
        )
        """
    )
    con_cru.commit()
    con_cru.close()

    con = db.conectar(caminho)
    colunas = {
        linha[1] for linha in con.execute("PRAGMA table_info(oportunidades)")
    }
    assert "fonte_verificar" in colunas

    from editais3s import oportunidades
    from editais3s.modelos import Oportunidade

    novas, _ = oportunidades.salvar(
        con,
        {"id": "wri-brasil", "nome": "WRI Brasil", "verificar": True},
        "catalogo",
        [Oportunidade(titulo="TdR migracao", url="https://a.org/migracao")],
    )
    assert len(novas) == 1
    linha = con.execute(
        "SELECT fonte_verificar FROM oportunidades WHERE id=?", (novas[0],)
    ).fetchone()
    assert linha["fonte_verificar"] == 1
