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
        "Termo de referencia para desenvolvimento de site institucional bilingue"
    )
    assert aprovado is True
    assert "desenvolvimento de site" in temas


def test_termo_nao_pontua_como_substring_de_palavra_maior():
    score, temas = escopo.pontuar("atendimento muito rapido e eficiente")
    assert score == 0
    assert temas == []


def test_score_igual_ao_minimo_e_aprovado():
    aprovado, score, temas = escopo.avaliar(
        "Desenvolvimento de dashboard gerencial para acompanhamento"
    )
    assert score == SCORE_KW_MINIMO
    assert aprovado is True


def test_titulos_reais_do_flagship_agora_pontuam():
    """Achado 4: titulos reais que hoje sao invisiveis por falta de termo ou
    por exigirem forma exata singular. O residual (titulo com contracao "do
    site" em vez de "de site", e plural na PRIMEIRA palavra do termo
    composto) foi fechado com variantes explicitas no dicionario em vez de
    regex mais esperto — Aho-Corasick e O(n) no texto independente de
    quantos termos o automato carrega, entao entradas extras sao de graca."""
    casos = [
        "Selecao de consultoria para construcao de website bilingue",
        "Cotacao para reformulacao do portal institucional",
        "TdR: painel de monitoramento de indicadores socioambientais",
        "Termo de referencia - implantacao de canal de denuncias",
        "Termo de referencia para desenvolvimento do site do projeto",
        "Implantacao de canais de denuncia",
        "Consultoria para plataformas de dados abertos",
    ]
    for texto in casos:
        score, temas = escopo.pontuar(texto)
        assert score >= SCORE_KW_MINIMO, f"{texto!r} pontuou {score}, temas={temas}"


def test_termo_de_uma_palavra_casa_no_plural():
    score, temas = escopo.pontuar("dashboards de gestao para acompanhamento")
    assert score >= SCORE_KW_MINIMO
    assert "dashboard" in temas


def test_termo_composto_casa_plural_da_ultima_palavra():
    # "canal de denuncia" (peso 4) — a forma comum em titulo real e o plural
    # do substantivo final: "canal de denuncias".
    score, temas = escopo.pontuar("implantacao de canal de denuncias institucional")
    assert score >= SCORE_KW_MINIMO
    assert "canal de denuncia" in temas


def test_triar_vaga_de_emprego_e_vetado():
    classe, score, temas = escopo.triar(
        "Vaga de emprego: analista administrativo"
    )
    assert classe == "vetado"


def test_triar_chamada_de_projetos_sem_tema_forte_e_vetado():
    classe, score, temas = escopo.triar(
        "Chamada de projetos para apoio a iniciativas comunitarias"
    )
    assert classe == "vetado"


def test_triar_titulo_curto_sem_objeto_e_sem_veto_e_fraco_nunca_vetado():
    """O caso CI-Brasil generico: titulo curto, sem 'objeto' (pagina do
    financiador so' lista links), sem nenhum termo do dicionario -> score 0.
    Nao ha veto aqui, entao a classe tem que ser 'fraco', nunca 'vetado' —
    'fraco' ainda vai ao juiz e ao relatorio; 'vetado' e' descarte definitivo."""
    classe, score, temas = escopo.triar(
        "Contratação de consultoria de pessoa jurídica para apoio administrativo"
    )
    assert classe == "fraco"
    assert score == 0
    assert classe != "vetado"


def test_triar_fixture_ci_brasil_nao_e_vetado():
    """Fixture literal do incidente real (seis editais da Conservacao
    Internacional gravados e depois escondidos). Nota: com 'plataforma'
    (peso 4) adicionado ao dicionario nesta mudanca, este titulo especifico
    pontua 4 e classifica 'forte', nao 'fraco' como a especificacao original
    presumia — a preposicao no titulo real e' 'desenvolvimento DA plataforma'
    (nao 'DE plataforma', que so' bateria no termo composto de peso 5) mas
    'plataforma' sozinha ja basta. O invariante que importa continua valendo
    e e' o que este teste prova: nunca vira 'vetado', entao nunca
    descartada_kw, entao nunca some do relatorio."""
    classe, score, temas = escopo.triar(
        "Contratação de consultoria de pessoa jurídica para o desenvolvimento "
        "da plataforma da Aceleradora de Impacto"
    )
    assert classe != "vetado"


def test_avaliar_continua_equivalente_a_triar_forte():
    aprovado, score, temas = escopo.avaliar("Desenvolvimento de dashboard gerencial")
    classe, score2, temas2 = escopo.triar("Desenvolvimento de dashboard gerencial")
    assert aprovado == (classe == "forte")
    assert (score, temas) == (score2, temas2)
