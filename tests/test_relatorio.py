from datetime import date, timedelta
from editais3s import db, relatorio
from editais3s.config import PRAZO_APERTADO_DIAS

HOJE = "2026-07-29"


def semear(con, **kw):
    base = {
        "id": "i1",
        "fonte_id": "wri-brasil",
        "fonte_nome": "WRI Brasil",
        "trilha": "catalogo",
        "titulo": "TdR Ouvidoria Restaura Biomas",
        "objeto": "consultoria de ouvidoria",
        "url": "https://a.org/x",
        "prazo": "2026-09-30",
        "visto_em": f"{HOJE}T10:00:00+00:00",
        "atualizado_em": None,
        "score_kw": 9,
        "temas_kw": "ouvidoria",
        "score_llm": 8,
        "justificativa_llm": "casa com o caso WRI",
        "status": "reportada",
    }
    d = {**base, **kw}
    con.execute(
        f"INSERT INTO oportunidades ({','.join(d)}) VALUES ({','.join('?' * len(d))})",
        tuple(d.values()),
    )
    con.commit()


def test_aderente_aparece_no_bloco_principal(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    semear(con)
    md = relatorio.gerar(con, HOJE)
    assert "## Aderentes" in md
    assert "TdR Ouvidoria Restaura Biomas" in md
    assert "casa com o caso WRI" in md


def test_score_intermediario_vai_para_olhar(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    semear(con, id="i2", score_llm=5, titulo="Cotacao painel")
    md = relatorio.gerar(con, HOJE)
    bloco_olhar = md.split("## Olhar")[1]
    assert "Cotacao painel" in bloco_olhar


def test_descartada_nao_aparece(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    semear(con, id="i3", score_llm=1, status="descartada_llm", titulo="Locacao de van")
    assert "Locacao de van" not in relatorio.gerar(con, HOJE)


def test_prazo_apertado_tem_bloco_proprio(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    semear(con, id="i4", prazo="2026-08-02", titulo="Cotacao urgente", score_llm=5)
    md = relatorio.gerar(con, HOJE)
    bloco = md.split("## Prazo apertado")[1].split("##")[0]
    assert "Cotacao urgente" in bloco


def test_atualizada_tem_bloco_proprio(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    semear(
        con,
        id="i5",
        titulo="TdR prorrogado",
        visto_em="2026-07-01T10:00:00+00:00",
        atualizado_em=f"{HOJE}T11:00:00+00:00",
    )
    md = relatorio.gerar(con, HOJE)
    assert "## Atualizadas" in md
    assert "TdR prorrogado" in md.split("## Atualizadas")[1]


def test_item_de_outro_dia_nao_entra(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    semear(con, id="i6", titulo="Velho", visto_em="2026-01-01T10:00:00+00:00")
    assert "Velho" not in relatorio.gerar(con, HOJE)


def test_bloco_saude_lista_fonte_com_erro(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    con.execute(
        "INSERT INTO snapshots (fonte_id, erro, erros_seguidos, coletado_em) "
        "VALUES ('funbio', 'HTTP 503', 4, ?)",
        (f"{HOJE}T10:00:00+00:00",),
    )
    con.commit()
    md = relatorio.gerar(con, HOJE)
    assert "## Saude" in md
    assert "funbio" in md.split("## Saude")[1]
    assert "HTTP 503" in md


def test_linha_tem_marcador_de_triagem(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    semear(con)
    assert "[ ]" in relatorio.gerar(con, HOJE)


def test_cabecalho_registra_execucao(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    semear(con)
    md = relatorio.gerar(
        con, HOJE, execucao={"fontes_ok": 12, "fontes_erro": 2, "custo_usd": 0.07}
    )
    assert "12" in md and "0.07" in md


def test_escrever_salva_arquivo(tmp_path, monkeypatch):
    monkeypatch.setattr(relatorio, "DIR_DADOS", tmp_path)
    con = db.conectar(tmp_path / "t.sqlite")
    semear(con)
    caminho = relatorio.escrever(con, HOJE)
    assert caminho.name == f"novas_{HOJE}.md"
    assert "Aderentes" in caminho.read_text(encoding="utf-8")


def test_relatorio_vazio_nao_quebra(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    md = relatorio.gerar(con, HOJE)
    assert "Nenhuma oportunidade nova" in md


def test_descartada_kw_sem_score_nao_aparece(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    semear(
        con,
        id="i7",
        titulo="Vaga de analista administrativo",
        score_llm=None,
        justificativa_llm=None,
        status="descartada_kw",
    )
    assert "Vaga de analista administrativo" not in relatorio.gerar(con, HOJE)


def test_escrever_usa_dir_dados_e_cria_diretorio(tmp_path, monkeypatch):
    destino = tmp_path / "saida" / "aninhado"
    monkeypatch.setattr(relatorio, "DIR_DADOS", destino)
    con = db.conectar(tmp_path / "t.sqlite")
    semear(con)
    caminho = relatorio.escrever(con, HOJE)
    assert caminho.parent == destino
    assert destino.is_dir()


def test_prazo_exatamente_no_limite_entra_no_bloco(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    limite = (
        date.fromisoformat(HOJE) + timedelta(days=PRAZO_APERTADO_DIAS)
    ).isoformat()
    semear(con, id="i8", titulo="Cotacao no limite", prazo=limite, score_llm=5)
    bloco = relatorio.gerar(con, HOJE).split("## Prazo apertado")[1].split("##")[0]
    assert "Cotacao no limite" in bloco


def test_prazo_malformado_nao_quebra_o_relatorio(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    semear(con, id="i9", titulo="TdR com prazo bagunçado", prazo="a definir")
    assert "TdR com prazo bagunçado" in relatorio.gerar(con, HOJE)


def test_saude_lista_fonte_silenciosa(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    con.execute(
        "INSERT INTO snapshots (fonte_id, hash, coletado_em, erros_seguidos) "
        "VALUES ('imazon', 'abc', ?, 0)",
        (f"{HOJE}T10:00:00+00:00",),
    )
    con.commit()
    bloco = relatorio.gerar(con, HOJE).split("## Saude")[1]
    assert "imazon" in bloco


def test_aviso_quando_rodada_sem_llm(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    semear(con)
    md = relatorio.gerar(con, HOJE, execucao={"fontes_ok": 1, "fontes_erro": 0, "sem_llm": True})
    assert "sem juiz LLM" in md
    limpo = relatorio.gerar(con, HOJE, execucao={"fontes_ok": 1, "fontes_erro": 0})
    assert "sem juiz LLM" not in limpo


def test_aderente_com_prazo_curto_aparece_nos_dois_blocos(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    semear(
        con, id="i10", titulo="TdR urgente e aderente", prazo="2026-08-02", score_llm=9
    )
    md = relatorio.gerar(con, HOJE)
    apertado = md.split("## Prazo apertado")[1].split("##")[0]
    aderentes = md.split("## Aderentes")[1].split("##")[0]
    assert "TdR urgente e aderente" in apertado
    assert "TdR urgente e aderente" in aderentes
