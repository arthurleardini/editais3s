from editais3s import db, juiz, oportunidades
from editais3s.modelos import Oportunidade

FONTE = {"id": "wri-brasil", "nome": "WRI Brasil"}


def test_julgar_devolve_score_e_justificativa():
    itens = [
        {"id": "a1", "titulo": "TdR Ouvidoria", "objeto": "consultoria", "fonte_nome": "WRI"}
    ]
    payload = {
        "avaliacoes": [
            {"id": "a1", "score": 8, "justificativa": "casa com o caso WRI", "modalidade": "tdr"}
        ]
    }
    saida = juiz.julgar(itens, chamar=lambda itens_: payload)
    assert saida[0]["score_llm"] == 8
    assert saida[0]["justificativa_llm"] == "casa com o caso WRI"
    assert saida[0]["modelo_llm"]


def test_item_nao_julgado_fica_com_score_nulo():
    itens = [
        {"id": "a1", "titulo": "T", "objeto": "", "fonte_nome": "X"},
        {"id": "a2", "titulo": "U", "objeto": "", "fonte_nome": "X"},
    ]
    payload = {"avaliacoes": [{"id": "a1", "score": 7, "justificativa": "ok"}]}
    saida = {s["id"]: s for s in juiz.julgar(itens, chamar=lambda itens_: payload)}
    assert saida["a2"]["score_llm"] is None


def test_score_fora_da_faixa_e_normalizado():
    itens = [{"id": "a1", "titulo": "T", "objeto": "", "fonte_nome": "X"}]
    payload = {"avaliacoes": [{"id": "a1", "score": 42, "justificativa": "x"}]}
    assert juiz.julgar(itens, chamar=lambda itens_: payload)[0]["score_llm"] == 10


def test_falha_do_modelo_nao_levanta():
    itens = [{"id": "a1", "titulo": "T", "objeto": "", "fonte_nome": "X"}]

    def explode(itens_):
        raise RuntimeError("sem rede")

    saida = juiz.julgar(itens, chamar=explode)
    assert saida[0]["score_llm"] is None


def test_lista_vazia_nao_chama_o_modelo():
    chamadas = []
    juiz.julgar([], chamar=lambda itens_: chamadas.append(1) or {})
    assert chamadas == []


def test_aplicar_grava_no_banco(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    novas, _ = oportunidades.salvar(
        con, FONTE, "catalogo",
        [Oportunidade(titulo="TdR Ouvidoria", url="https://a.org/x")],
    )
    juiz.aplicar(
        con,
        [
            {
                "id": novas[0],
                "score_llm": 8,
                "justificativa_llm": "aderente",
                "modelo_llm": "claude-haiku-4-5",
                "prazo": "2026-07-13",
                "modalidade": "tdr",
            }
        ],
    )
    linha = con.execute("SELECT * FROM oportunidades WHERE id=?", (novas[0],)).fetchone()
    assert linha["score_llm"] == 8
    assert linha["prazo"] == "2026-07-13"
    assert linha["status"] == "reportada"


def test_aplicar_marca_descarte_abaixo_da_faixa(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    novas, _ = oportunidades.salvar(
        con, FONTE, "catalogo", [Oportunidade(titulo="T", url="https://a.org/y")]
    )
    juiz.aplicar(
        con,
        [{"id": novas[0], "score_llm": 1, "justificativa_llm": "fora", "modelo_llm": "m"}],
    )
    linha = con.execute("SELECT status FROM oportunidades WHERE id=?", (novas[0],)).fetchone()
    assert linha["status"] == "descartada_llm"


def test_score_negativo_e_normalizado_para_zero():
    itens = [{"id": "a1", "titulo": "T", "objeto": "", "fonte_nome": "X"}]
    payload = {"avaliacoes": [{"id": "a1", "score": -5, "justificativa": "x"}]}
    assert juiz.julgar(itens, chamar=lambda itens_: payload)[0]["score_llm"] == 0


def test_aplicar_preserva_prazo_existente_quando_llm_nao_extrai(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    novas, _ = oportunidades.salvar(
        con, FONTE, "catalogo", [Oportunidade(titulo="T", url="https://a.org/z")]
    )
    con.execute(
        "UPDATE oportunidades SET prazo=?, modalidade=? WHERE id=?",
        ("2026-08-01", "chamada", novas[0]),
    )
    con.commit()
    juiz.aplicar(
        con,
        [
            {
                "id": novas[0],
                "score_llm": 8,
                "justificativa_llm": "ok",
                "modelo_llm": "m",
                "prazo": None,
                "modalidade": None,
            }
        ],
    )
    linha = con.execute(
        "SELECT prazo, modalidade FROM oportunidades WHERE id=?", (novas[0],)
    ).fetchone()
    assert linha["prazo"] == "2026-08-01"
    assert linha["modalidade"] == "chamada"


def test_aplicar_preserva_score_existente_em_falha_transitoria(tmp_path):
    """Achado 2: uma falha transitoria do juiz (score_llm=None) nao pode
    apagar um score que uma rodada anterior ja tinha gravado."""
    con = db.conectar(tmp_path / "t.sqlite")
    novas, _ = oportunidades.salvar(
        con, FONTE, "catalogo", [Oportunidade(titulo="TdR Ouvidoria", url="https://a.org/falha")]
    )
    juiz.aplicar(
        con,
        [
            {
                "id": novas[0],
                "score_llm": 9,
                "justificativa_llm": "casa com o caso WRI",
                "modelo_llm": "claude-haiku-4-5",
                "prazo": "2026-07-13",
                "modalidade": "tdr",
            }
        ],
    )
    linha = con.execute("SELECT * FROM oportunidades WHERE id=?", (novas[0],)).fetchone()
    assert (linha["score_llm"], linha["justificativa_llm"], linha["modelo_llm"], linha["status"]) == (
        9, "casa com o caso WRI", "claude-haiku-4-5", "reportada",
    )

    # rodada seguinte: o juiz falhou de forma transitoria (_vazio) para o
    # mesmo item, ja com score gravado.
    juiz.aplicar(
        con,
        [
            {
                "id": novas[0],
                "score_llm": None,
                "justificativa_llm": None,
                "modelo_llm": None,
                "prazo": None,
                "modalidade": None,
            }
        ],
    )
    linha = con.execute("SELECT * FROM oportunidades WHERE id=?", (novas[0],)).fetchone()
    assert linha["score_llm"] == 9
    assert linha["justificativa_llm"] == "casa com o caso WRI"
    assert linha["modelo_llm"] == "claude-haiku-4-5"
    assert linha["status"] == "reportada"
