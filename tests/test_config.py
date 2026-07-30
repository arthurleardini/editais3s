from editais3s import config


def test_user_agent_tem_contato_alcancavel():
    """Achado 9: o fragmento de contato do UA precisa ser um e-mail ou URL de
    verdade — este crawler bate em robots.txt de organizacoes reais e a
    convencao de bot exige um contato alcancavel, nao um placeholder."""
    assert "+notabc" not in config.UA
    assert "+mailto:arthurlorenzoleardini@gmail.com" in config.UA
