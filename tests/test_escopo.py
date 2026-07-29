from editais3s import escopo
from editais3s.config import SCORE_KW_MINIMO


def test_normalizar_remove_acento_e_caixa():
    assert escopo.normalizar("Ciência de Dados") == "ciencia de dados"


def test_tdr_ouvidoria_do_wri_pontua_acima_do_minimo():
    texto = (
        "Consultoria tecnica para diagnostico, desenho metodologico e implantacao "
        "dos canais fisicos e digitais da Ouvidoria Institucional, com painel de "
        "indicadores e plataforma de dados"
    )
    score, temas = escopo.pontuar(texto)
    assert score >= SCORE_KW_MINIMO
    assert "ouvidoria" in temas
    assert "plataforma de dados" in temas


def test_cada_tema_conta_uma_vez():
    score_um, _ = escopo.pontuar("plataforma de dados")
    score_repetido, temas = escopo.pontuar(
        "plataforma de dados, plataforma de dados, plataforma de dados"
    )
    assert score_um == score_repetido
    assert temas == ["plataforma de dados"]


def test_texto_irrelevante_pontua_zero():
    score, temas = escopo.pontuar("locacao de veiculo e fornecimento de combustivel")
    assert score == 0 and temas == []


def test_vaga_de_emprego_reprovada():
    aprovado, score, _ = escopo.avaliar(
        "Vaga de emprego: analista administrativo. Processo seletivo de colaborador."
    )
    assert aprovado is False


def test_veto_nao_mata_item_com_tema_forte():
    aprovado, score, temas = escopo.avaliar(
        "Chamada de projetos para desenvolvimento de plataforma de dados socioambientais"
    )
    assert aprovado is True
    assert "plataforma de dados" in temas


def test_item_fraco_sem_veto_tambem_reprova():
    aprovado, score, _ = escopo.avaliar("Contratacao de servico de API de correios")
    assert score < SCORE_KW_MINIMO
    assert aprovado is False


def test_desenvolvimento_de_site_aprovado():
    aprovado, score, temas = escopo.avaliar(
        "Termo de referencia para desenvolvimento web do portal institucional bilingue"
    )
    assert aprovado is True
    assert "desenvolvimento web" in temas
