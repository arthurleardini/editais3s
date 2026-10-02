from datetime import date, timedelta
from editais3s import db, relatorio
from editais3s.config import DIAS_TOLERANCIA_VENCIDO, PRAZO_APERTADO_DIAS

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
    # Contrato novo: so descartada_kw (veto de keyword) fica de fora do
    # relatorio. descartada_llm nao e' mais produzida (juiz.aplicar agora
    # manda score baixo para 'triagem', que E' visivel) — este teste passou
    # a cobrir o unico status de descarte que sobrou.
    con = db.conectar(tmp_path / "t.sqlite")
    semear(con, id="i3", score_llm=1, status="descartada_kw", titulo="Locacao de van")
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


def test_prazo_apertado_aparece_mesmo_visto_ha_dias(tmp_path):
    """Achado 5: item visto ha 10 dias com prazo daqui a 4 dias tem que
    aparecer no bloco de prazo apertado do relatorio de hoje — o bloco nao
    pode depender de visto_em/atualizado_em serem de hoje."""
    con = db.conectar(tmp_path / "t.sqlite")
    visto = (date.fromisoformat(HOJE) - timedelta(days=10)).isoformat()
    prazo = (date.fromisoformat(HOJE) + timedelta(days=4)).isoformat()
    semear(
        con,
        id="i11",
        titulo="TdR visto ha dias com prazo proximo",
        visto_em=f"{visto}T10:00:00+00:00",
        prazo=prazo,
    )
    bloco = relatorio.gerar(con, HOJE).split("## Prazo apertado")[1].split("##")[0]
    assert "TdR visto ha dias com prazo proximo" in bloco


def test_prazo_apertado_ignora_descartada_kw(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    prazo = (date.fromisoformat(HOJE) + timedelta(days=2)).isoformat()
    semear(
        con,
        id="i12",
        titulo="Vaga com prazo iminente",
        prazo=prazo,
        status="descartada_kw",
        score_llm=None,
        justificativa_llm=None,
    )
    md = relatorio.gerar(con, HOJE)
    assert "Vaga com prazo iminente" not in md


def test_fonte_a_verificar_ganha_marcador_no_relatorio(tmp_path):
    """Achado 8: fonte com verificar=true no catalogo (URL nao confirmada
    contra o site) tem que aparecer marcada no relatorio, senao a primeira
    rodada real apresenta toda fonte como se fosse confirmada."""
    con = db.conectar(tmp_path / "t.sqlite")
    semear(con, id="i13", titulo="TdR de fonte nao confirmada", fonte_verificar=1)
    semear(con, id="i14", titulo="TdR de fonte confirmada", fonte_verificar=0)
    md = relatorio.gerar(con, HOJE)
    linha_nao_confirmada = [l for l in md.splitlines() if "TdR de fonte nao confirmada" in l][0]
    linha_confirmada = [l for l in md.splitlines() if "TdR de fonte confirmada" in l][0]
    assert "⚠" in linha_nao_confirmada
    assert "⚠" not in linha_confirmada
    assert "⚠" in md.split("## Aderentes")[0]  # legenda antes das tabelas


def test_triagem_score_baixo_aparece_e_nao_e_escondida(tmp_path):
    """Contrato novo: score de juiz abaixo do corte vira status 'triagem',
    visivel no relatorio (bloco proprio), nao mais 'descartada_llm'
    (escondida)."""
    con = db.conectar(tmp_path / "t.sqlite")
    semear(
        con, id="i15", titulo="TdR fraco julgado", score_llm=2,
        status="triagem", justificativa_llm="fora do escopo mas nao vetado",
    )
    md = relatorio.gerar(con, HOJE)
    assert "## Triagem" in md
    bloco = md.split("## Triagem")[1]
    assert "TdR fraco julgado" in bloco


def test_marcador_forte_aparece_quando_score_kw_bate_o_minimo(tmp_path):
    # Contrato novo: o marcador segue score_kw >= SCORE_KW_MINIMO (o mesmo
    # limiar que escopo.triar usa para chamar de 'forte'), nao mais "algum
    # tema isolado de peso 5". Um item cujo peso vem de varios temas menores
    # somados (ex: "plataforma" 4 + outro termo) tambem tem que marcar.
    con = db.conectar(tmp_path / "t.sqlite")
    semear(con, id="i16", titulo="TdR com tema forte", score_kw=9, temas_kw="plataforma de dados")
    md = relatorio.gerar(con, HOJE)
    linha = [l for l in md.splitlines() if "TdR com tema forte" in l][0]
    assert "★" in linha
    assert "★ = match forte" in md


def test_marcador_forte_ausente_quando_score_kw_abaixo_do_minimo(tmp_path):
    # Peso 3 sozinho (score_kw=3) continua sem marcar: 3 < SCORE_KW_MINIMO (4).
    con = db.conectar(tmp_path / "t.sqlite")
    semear(con, id="i17", titulo="TdR so com tema fraco", score_kw=3, temas_kw="api")
    md = relatorio.gerar(con, HOJE)
    linha = [l for l in md.splitlines() if "TdR so com tema fraco" in l][0]
    assert "★" not in linha


def test_legenda_forte_so_aparece_quando_ha_marcador(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    semear(con, id="i18", titulo="TdR sem tema forte", score_kw=3, temas_kw="api")
    md = relatorio.gerar(con, HOJE)
    assert "★ = match forte" not in md


def test_cabecalho_novas_bate_com_execucao(tmp_path):
    """Achado do incidente CI-Brasil: o cabecalho recontava linhas
    renderizadas (que o funil ja tinha escondido) em vez de usar o contador
    real da execucao, e imprimia 'novas: 0' no mesmo run cujo stdout dizia
    '5 novas'. Semeia 1 linha so' (contagem local seria 1) e pede
    execucao['novas']=5 para provar que o cabecalho usa o contador real."""
    con = db.conectar(tmp_path / "t.sqlite")
    semear(con)
    md = relatorio.gerar(
        con, HOJE, execucao={"fontes_ok": 3, "fontes_erro": 0, "novas": 5}
    )
    assert "novas: 5" in md


def _sem_bloco_prazo_apertado(md: str) -> str:
    """Remove o bloco 'Prazo apertado' do texto — sua redundancia com os
    blocos de classificacao e' deliberada (test_aderente_com_prazo_curto_
    aparece_nos_dois_blocos fixa isso) e nao entra na contagem de
    exclusividade abaixo."""
    if "## Prazo apertado" not in md:
        return md
    antes, resto = md.split("## Prazo apertado", 1)
    partes = resto.split("\n## ", 1)
    depois = "\n## " + partes[1] if len(partes) > 1 else ""
    return antes + depois


def test_prazo_vencido_prazo_passado_alem_da_tolerancia_e_vencido():
    # Correcao 2: janela de tolerancia de DIAS_TOLERANCIA_VENCIDO (7) dias —
    # 1 dia de atraso NAO e' mais vencido (era, antes desta correcao; teste
    # atualizado porque encodava a regra antiga de tolerancia zero). So'
    # confirma vencido quem passou da janela de tolerancia.
    hoje = date.fromisoformat(HOJE)
    passado = (hoje - timedelta(days=DIAS_TOLERANCIA_VENCIDO + 1)).isoformat()
    assert relatorio.prazo_vencido(passado, hoje) is True


def test_prazo_vencido_dentro_da_tolerancia_nao_e_vencido():
    # 3 dias de atraso: dentro da janela de 7 dias de tolerancia — prazo
    # divulgado costuma ser prorrogado, entao continua visivel no relatorio.
    hoje = date.fromisoformat(HOJE)
    passado = (hoje - timedelta(days=3)).isoformat()
    assert relatorio.prazo_vencido(passado, hoje) is False


def test_prazo_vencido_no_limite_da_tolerancia_nao_e_vencido():
    # Boundary exato: atraso == DIAS_TOLERANCIA_VENCIDO (7) ainda NAO e'
    # vencido — so' vence quando o atraso passa da tolerancia.
    hoje = date.fromisoformat(HOJE)
    passado = (hoje - timedelta(days=DIAS_TOLERANCIA_VENCIDO)).isoformat()
    assert relatorio.prazo_vencido(passado, hoje) is False


def test_prazo_vencido_oito_dias_de_atraso_e_vencido():
    hoje = date.fromisoformat(HOJE)
    passado = (hoje - timedelta(days=8)).isoformat()
    assert relatorio.prazo_vencido(passado, hoje) is True


def test_prazo_vencido_none_nao_e_vencido():
    # Critico: prazo NULL nao pode ser tratado como vencido — muitos
    # financiadores (ex: WRI) nunca publicam data, e o item tem que
    # continuar fluindo para o juiz e o relatorio.
    hoje = date.fromisoformat(HOJE)
    assert relatorio.prazo_vencido(None, hoje) is False


def test_prazo_vencido_malformado_nao_levanta_e_nao_e_vencido():
    hoje = date.fromisoformat(HOJE)
    assert relatorio.prazo_vencido("a definir", hoje) is False


def test_prazo_vencido_hoje_nao_e_vencido():
    # Boundary: prazo == hoje ainda nao venceu (venceu e' estritamente antes).
    hoje = date.fromisoformat(HOJE)
    assert relatorio.prazo_vencido(hoje.isoformat(), hoje) is False


def test_vencida_nao_aparece_em_nenhum_bloco(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    semear(
        con, id="i19", titulo="Edital ja vencido em 2019", status="vencida",
        prazo="2019-09-02", score_llm=8, justificativa_llm="aderente",
    )
    md = relatorio.gerar(con, HOJE)
    assert "Edital ja vencido em 2019" not in md


def test_blocos_de_classificacao_sao_mutuamente_exclusivos(tmp_path):
    """Achado do coordenador: com Nao julgadas (populacao 'novas') e Triagem
    (populacao 'itens', que inclui 'novas') usando bases diferentes, um item
    sem nota caia nos dois — 6 editais viravam 15 linhas. Um item de cada
    faixa (Aderentes/Olhar/Triagem/Nao julgadas) tem que aparecer exatamente
    uma vez no relatorio, fora do bloco Prazo apertado (essa redundancia e'
    deliberada e tem teste proprio)."""
    con = db.conectar(tmp_path / "t.sqlite")
    semear(con, id="e1", titulo="Item aderente unico", score_llm=9)
    semear(con, id="e2", titulo="Item olhar unico", score_llm=5)
    semear(con, id="e3", titulo="Item triagem unico", score_llm=1)
    semear(
        con, id="e4", titulo="Item sem nota unico",
        score_llm=None, justificativa_llm=None,
    )

    md = relatorio.gerar(con, HOJE)
    fora = _sem_bloco_prazo_apertado(md)
    for titulo in (
        "Item aderente unico", "Item olhar unico",
        "Item triagem unico", "Item sem nota unico",
    ):
        assert fora.count(titulo) == 1, (
            f"{titulo!r} apareceu {fora.count(titulo)}x fora de Prazo apertado"
        )


def test_saude_ignora_snapshot_de_fonte_fora_do_catalogo(tmp_path):
    from editais3s import db as _db

    con = _db.conectar(tmp_path / "t.sqlite")
    con.execute(
        "INSERT INTO snapshots (fonte_id, coletado_em, http_status, erro, erros_seguidos) "
        "VALUES ('removida', '2026-07-30', 404, 'HTTP 404', 3), "
        "('ativa', '2026-10-02', 403, 'HTTP 403', 1)"
    )
    con.commit()
    md = relatorio._saude(con, "2026-10-02", ids={"ativa"})
    assert "`ativa`" in md
    assert "removida" not in md
