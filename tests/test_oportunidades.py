from editais3s import db, oportunidades
from editais3s.modelos import Oportunidade, canonizar, id_oportunidade

FONTE = {"id": "wri-brasil", "nome": "WRI Brasil"}


def op(**kw):
    base = {
        "titulo": "TdR Ouvidoria Restaura Biomas",
        "objeto": "consultoria para implantacao de ouvidoria",
        "url": "https://www.wribrasil.org.br/media/tdr.pdf",
        "prazo": "2026-07-13",
    }
    return Oportunidade(**{**base, **kw})


def test_canonizar_remove_utm_e_barra_final():
    assert canonizar("https://A.org/x/?utm_source=news&id=3") == "https://a.org/x?id=3"


def test_canonizar_ignora_fragmento():
    assert canonizar("https://a.org/x#topo") == "https://a.org/x"


def test_id_estavel_para_mesma_url():
    a = id_oportunidade("wri-brasil", "https://a.org/x/", "T")
    b = id_oportunidade("wri-brasil", "https://a.org/x?utm_medium=rss", "Outro")
    assert a == b


def test_id_usa_titulo_quando_url_ausente():
    a = id_oportunidade("wri-brasil", "", "TdR Ouvidoria")
    b = id_oportunidade("wri-brasil", "", "TdR Outro")
    assert a != b


def test_salvar_grava_nova(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    novas, atualizadas = oportunidades.salvar(con, FONTE, "catalogo", [op()])
    assert len(novas) == 1 and atualizadas == []
    linha = con.execute("SELECT * FROM oportunidades").fetchone()
    assert linha["fonte_nome"] == "WRI Brasil"
    assert linha["trilha"] == "catalogo"
    assert linha["status"] == "nova"


def test_salvar_duas_vezes_nao_duplica(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    oportunidades.salvar(con, FONTE, "catalogo", [op()])
    novas, atualizadas = oportunidades.salvar(con, FONTE, "catalogo", [op()])
    assert novas == [] and atualizadas == []
    assert con.execute("SELECT count(*) FROM oportunidades").fetchone()[0] == 1


def test_mudanca_de_prazo_conta_como_atualizacao(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    oportunidades.salvar(con, FONTE, "catalogo", [op()])
    novas, atualizadas = oportunidades.salvar(
        con, FONTE, "catalogo", [op(prazo="2026-07-25")]
    )
    assert novas == [] and len(atualizadas) == 1
    linha = con.execute("SELECT prazo, atualizado_em FROM oportunidades").fetchone()
    assert linha["prazo"] == "2026-07-25"
    assert linha["atualizado_em"]


def test_mesma_oportunidade_em_duas_trilhas_gera_um_registro(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    oportunidades.salvar(con, FONTE, "catalogo", [op()])
    oportunidades.salvar(con, FONTE, "gnews", [op()])
    assert con.execute("SELECT count(*) FROM oportunidades").fetchone()[0] == 1
