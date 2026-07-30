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


def test_canonizar_url_lixo_vira_vazio():
    assert canonizar("   ") == ""
    assert canonizar("#") == ""
    assert canonizar("?") == ""
    assert canonizar("/") == ""


def test_canonizar_preserva_caminho_relativo():
    assert canonizar("/media/tdr.pdf") == "/media/tdr.pdf"


def test_id_nao_colide_com_url_lixo(tmp_path):
    a = id_oportunidade("wri-brasil", "   ", "Edital A")
    b = id_oportunidade("wri-brasil", "\t", "Edital B")
    assert a != b


def test_id_tolera_titulo_none():
    vazio = id_oportunidade("wri-brasil", "", None)
    real = id_oportunidade("wri-brasil", "", "Edital A")
    assert vazio and vazio != real


def test_salvar_grava_fonte_verificar_a_partir_da_fonte(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    fonte_nao_confirmada = {**FONTE, "verificar": True}
    oportunidades.salvar(con, fonte_nao_confirmada, "catalogo", [op()])
    linha = con.execute("SELECT fonte_verificar FROM oportunidades").fetchone()
    assert linha["fonte_verificar"] == 1


def test_salvar_fonte_verificar_ausente_vira_zero(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    oportunidades.salvar(con, FONTE, "catalogo", [op()])
    linha = con.execute("SELECT fonte_verificar FROM oportunidades").fetchone()
    assert linha["fonte_verificar"] == 0
