from datetime import datetime, timedelta, timezone

import httpx

from editais3s import db, pipeline, relatorio
from editais3s.config import INTERVALO_DOMINIO
from editais3s.modelos import Oportunidade

FONTE = {
    "id": "wri-brasil",
    "nome": "WRI Brasil",
    "tipo": "html",
    "dominio": "wribrasil.org.br",
    "url": "https://www.wribrasil.org.br/oportunidades",
    "tier": 1,
}

PAGINA = """<body><h1>Oportunidades</h1>
<ul><li><a href="/media/tdr.pdf">TdR Ouvidoria: plataforma de dados e painel de indicadores</a> Prazo: 30/09/2026</li>
<li><a href="/editais/apoio">Chamada de projetos para apoio a iniciativas comunitarias</a></li>
<li><a href="/vagas/analista">Vaga de emprego: analista administrativo</a></li></ul>
</body>"""


def cliente_falso():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404, text="")
        return httpx.Response(200, text=PAGINA)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_varrer_grava_novas_e_descarta_por_keyword(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")
    resumo = pipeline.varrer(
        con, [FONTE], cliente_falso(), usar_llm=False, pausar=lambda _: None
    )
    assert resumo["fontes_ok"] == 1
    assert resumo["novas"] >= 1

    linhas = {
        l["titulo"]: l["status"]
        for l in con.execute("SELECT titulo, status FROM oportunidades")
    }

    # aderente sobrevive ao funil
    tdr = [t for t in linhas if "TdR Ouvidoria" in t]
    assert tdr, "TdR nao chegou ao banco"
    assert linhas[tdr[0]] != "descartada_kw"

    # passa a extracao (RE_EDITAL casa "chamada") e morre no veto do escopo,
    # sem gastar chamada de LLM
    chamada = [t for t in linhas if "Chamada de projetos" in t]
    assert chamada, "chamada de projetos nao chegou ao banco"
    assert linhas[chamada[0]] == "descartada_kw"

    # vaga de emprego nao casa RE_EDITAL: e descartada na extracao,
    # nunca vira Oportunidade
    assert not any("Vaga de emprego" in t for t in linhas)


def test_varrer_segunda_vez_nao_encontra_novas(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")
    pipeline.varrer(con, [FONTE], cliente_falso(), usar_llm=False, pausar=lambda _: None)
    resumo = pipeline.varrer(
        con, [FONTE], cliente_falso(), usar_llm=False, pausar=lambda _: None
    )
    assert resumo["novas"] == 0
    assert resumo["ignoradas"] == 1


def test_varrer_conta_fonte_com_erro(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")

    def handler(request):
        return httpx.Response(500, text="erro")

    c = httpx.Client(transport=httpx.MockTransport(handler))
    resumo = pipeline.varrer(con, [FONTE], c, usar_llm=False, pausar=lambda _: None)
    assert resumo["fontes_erro"] == 1 and resumo["novas"] == 0


def test_varrer_pula_fonte_gnews_nesta_fase(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    fonte = {
        "id": "talanoa", "nome": "Talanoa", "tipo": "gnews",
        "dominio": "institutotalanoa.org", "query": "x", "tier": 1,
    }
    resumo = pipeline.varrer(
        con, [fonte], cliente_falso(), usar_llm=False, pausar=lambda _: None
    )
    assert resumo["ignoradas"] == 1


def test_varrer_registra_execucao(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")
    pipeline.varrer(con, [FONTE], cliente_falso(), usar_llm=False, pausar=lambda _: None)
    assert con.execute("SELECT count(*) FROM execucoes").fetchone()[0] == 1


def test_varrer_isola_falha_de_extracao(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")
    fonte_ruim = dict(FONTE, id="ruim", dominio="ruim.org", url="https://ruim.org/x")
    fonte_boa = dict(FONTE, id="boa", dominio="boa.org", url="https://boa.org/x")
    original = pipeline.extrai.extrair

    def extrair_falha(texto, fonte, chamar=None):
        if fonte["id"] == "ruim":
            raise RuntimeError("html impossivel")
        return original(texto, fonte, chamar)

    monkeypatch.setattr(pipeline.extrai, "extrair", extrair_falha)
    resumo = pipeline.varrer(
        con, [fonte_ruim, fonte_boa], cliente_falso(),
        usar_llm=False, pausar=lambda _: None,
    )
    assert resumo["fontes_erro"] >= 1
    assert resumo["novas"] >= 1
    titulos = [l["titulo"] for l in con.execute("SELECT titulo FROM oportunidades")]
    assert any("TdR Ouvidoria" in t for t in titulos)
    assert con.execute("SELECT count(*) FROM execucoes").fetchone()[0] == 1


def test_varrer_nao_chama_juiz_quando_usar_llm_false(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")
    chamado = []
    monkeypatch.setattr(
        pipeline.juiz, "julgar", lambda itens: chamado.append(itens) or []
    )
    pipeline.varrer(
        con, [FONTE], cliente_falso(), usar_llm=False, pausar=lambda _: None
    )
    assert chamado == []


def test_varrer_pausa_entre_fontes_mas_nao_antes_da_primeira(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")
    chamadas = []
    fonte2 = dict(
        FONTE, id="wri-brasil-2", dominio="outro.org.br",
        url="https://outro.org.br/oportunidades",
    )
    pipeline.varrer(
        con, [FONTE, fonte2], cliente_falso(), usar_llm=False,
        pausar=lambda segundos: chamadas.append(segundos),
    )
    assert chamadas == [INTERVALO_DOMINIO]


def test_varrer_grava_contadores_reais_em_execucoes(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")
    resumo = pipeline.varrer(
        con, [FONTE], cliente_falso(), usar_llm=False, pausar=lambda _: None
    )
    linha = con.execute(
        "SELECT fontes_ok, fontes_erro, novas FROM execucoes"
    ).fetchone()
    assert (linha["fontes_ok"], linha["fontes_erro"], linha["novas"]) == (
        resumo["fontes_ok"], resumo["fontes_erro"], resumo["novas"],
    )
    assert linha["novas"] >= 1


def test_varrer_respeita_robots_txt_disallow(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        return httpx.Response(200, text=PAGINA)

    c = httpx.Client(transport=httpx.MockTransport(handler))
    resumo = pipeline.varrer(
        con, [FONTE], c, usar_llm=False, pausar=lambda _: None
    )
    assert resumo["ignoradas"] == 1
    assert resumo["fontes_ok"] == 0
    assert con.execute("SELECT count(*) FROM oportunidades").fetchone()[0] == 0


def test_varrer_nao_demove_item_ja_julgado_pelo_juiz(tmp_path, monkeypatch):
    """Achado 1: entre duas rodadas o 'objeto' extraido (prosa da LLM) muda e
    o novo score_kw cai abaixo do minimo. O item ja tinha sido julgado com
    score_llm alto na primeira rodada — o loop de escopo da segunda rodada
    nao pode rebaixa-lo a descartada_kw e faze-lo sumir do relatorio."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")

    # paginas com hash diferente para passar do gate de "mudou" em coleta,
    # mas o conteudo extraido de fato vem do extrai.extrair mockado abaixo.
    paginas = iter(["<body>pagina 1</body>", "<body>pagina 2 diferente</body>"])

    def cliente_falso():
        def handler(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(404, text="")
            return httpx.Response(200, text=next(paginas))

        return httpx.Client(transport=httpx.MockTransport(handler))

    objetos = iter(
        [
            "plataforma de dados e painel de indicadores para ouvidoria institucional",
            "texto generico sem nenhum termo de escopo relevante para o portfolio",
        ]
    )

    def extrair_falso(texto, fonte, chamar=None):
        return [
            Oportunidade(
                titulo="Consultoria eventual",
                objeto=next(objetos),
                url="https://www.wribrasil.org.br/media/tdr.pdf",
                prazo="2026-09-30",
            )
        ]

    monkeypatch.setattr(pipeline.extrai, "extrair", extrair_falso)

    def julgar_alto(itens):
        return [
            {
                "id": i["id"],
                "score_llm": 9,
                "justificativa_llm": "aderente",
                "prazo": None,
                "modalidade": None,
                "modelo_llm": "m",
            }
            for i in itens
        ]

    monkeypatch.setattr(pipeline.juiz, "julgar", julgar_alto)

    pipeline.varrer(con, [FONTE], cliente_falso(), usar_llm=True, pausar=lambda _: None)
    linha = con.execute("SELECT status, score_llm FROM oportunidades").fetchone()
    assert linha["status"] == "reportada"
    assert linha["score_llm"] == 9

    pipeline.varrer(con, [FONTE], cliente_falso(), usar_llm=True, pausar=lambda _: None)
    linha = con.execute("SELECT status, score_llm, score_kw FROM oportunidades").fetchone()
    assert linha["status"] == "reportada", (
        f"item ja julgado (score_llm=9) foi rebaixado para {linha['status']!r} "
        "so porque o novo objeto nao bateu o funil de keyword"
    )
    assert linha["score_llm"] == 9

    hoje = datetime.now(timezone.utc).date().isoformat()
    md = relatorio.gerar(con, hoje)
    assert "Aderentes" in md
    assert "Consultoria eventual" in md


def test_varrer_sinaliza_sem_llm_quando_falta_api_key(tmp_path, monkeypatch):
    """Achado 3: usar_llm=True (cron normal) mas sem ANTHROPIC_API_KEY deve
    acender o mesmo aviso 'sem_llm' que --sem-llm, senao uma chave revogada
    fica indistinguivel de um dia tranquilo no relatorio."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")
    resumo = pipeline.varrer(
        con, [FONTE], cliente_falso(), usar_llm=True, pausar=lambda _: None
    )
    assert resumo["sem_llm"] is True


def test_robots_bloqueado_grava_snapshot_e_conta_bloqueadas(tmp_path):
    """Achado 6: uma fonte bloqueada por robots.txt precisa deixar rastro em
    snapshots (como o caminho js:true ja faz) para nao desaparecer do bloco
    Saude para sempre, e o contador tem que ser especifico ('bloqueadas'),
    nao misturado em 'ignoradas'."""
    con = db.conectar(tmp_path / "t.sqlite")

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        return httpx.Response(200, text=PAGINA)

    c = httpx.Client(transport=httpx.MockTransport(handler))
    resumo = pipeline.varrer(con, [FONTE], c, usar_llm=False, pausar=lambda _: None)

    assert resumo["bloqueadas"] == 1
    assert resumo["ignoradas"] == 1
    linha = con.execute(
        "SELECT erro FROM snapshots WHERE fonte_id=?", (FONTE["id"],)
    ).fetchone()
    assert linha is not None
    assert linha["erro"] == "indisponivel: robots.txt"


def test_pagina_sem_mudanca_incrementa_sem_mudanca(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")
    pipeline.varrer(con, [FONTE], cliente_falso(), usar_llm=False, pausar=lambda _: None)
    resumo = pipeline.varrer(
        con, [FONTE], cliente_falso(), usar_llm=False, pausar=lambda _: None
    )
    assert resumo["sem_mudanca"] == 1
    assert resumo["ignoradas"] == 1


def test_fonte_gnews_incrementa_fora_de_fase(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    fonte = {
        "id": "talanoa", "nome": "Talanoa", "tipo": "gnews",
        "dominio": "institutotalanoa.org", "query": "x", "tier": 1,
    }
    resumo = pipeline.varrer(
        con, [fonte], cliente_falso(), usar_llm=False, pausar=lambda _: None
    )
    assert resumo["fora_de_fase"] == 1
    assert resumo["ignoradas"] == 1


def test_diario_aceita_data_explicita_e_usa_no_caminho_do_relatorio(
    tmp_path, monkeypatch
):
    """Achado 7: visto_em e gravado em UTC (oportunidades._agora), entao
    diario() nao pode derivar a data do relatorio de date.today() (local) —
    precisa aceitar uma data explicita para ser testavel e usar UTC por
    padrao, senao toda rodada depois de 21h em America/Sao_Paulo escreve o
    item com data de amanha e o relatorio de hoje sai vazio."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    conectar_original = db.conectar
    monkeypatch.setattr(
        pipeline.db, "conectar", lambda: conectar_original(tmp_path / "t.sqlite")
    )
    monkeypatch.setattr(pipeline.cat, "carregar", lambda: [FONTE])
    monkeypatch.setattr(pipeline.cat, "filtrar", lambda fontes, ids: fontes)
    monkeypatch.setattr(pipeline, "_cliente", cliente_falso)
    monkeypatch.setattr(relatorio, "DIR_DADOS", tmp_path)

    data_explicita = "2026-08-15"
    caminho = pipeline.diario(usar_llm=False, data=data_explicita)
    assert caminho.name == f"novas_{data_explicita}.md"
    assert caminho.exists()


def test_varrer_item_fraco_sem_veto_nao_e_escondido(tmp_path, monkeypatch):
    """Contrato novo: o funil ranqueia, nunca esconde quem nao e' vetado.
    Fixture literal do incidente real CI-Brasil (titulo bare, sem 'objeto' —
    a pagina do financiador so' lista links) junto com um segundo titulo
    puramente fraco (score 0, sem nenhum termo do dicionario), para cobrir os
    dois casos sem veto: 'forte' (o titulo real, que agora pontua 4 por causa
    do termo 'plataforma' adicionado nesta mudanca) e 'fraco' (score 0)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")

    pagina = """<body><h1>Oportunidades</h1>
<ul>
<li><a href="/oport/aceleradora">Contratação de consultoria de pessoa jurídica para o desenvolvimento da plataforma da Aceleradora de Impacto</a></li>
<li><a href="/oport/generico">Contratação de consultoria de pessoa jurídica para apoio administrativo</a></li>
</ul></body>"""

    def cliente():
        def handler(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(404, text="")
            return httpx.Response(200, text=pagina)
        return httpx.Client(transport=httpx.MockTransport(handler))

    pipeline.varrer(con, [FONTE], cliente(), usar_llm=False, pausar=lambda _: None)
    linhas = {l["titulo"]: dict(l) for l in con.execute("SELECT * FROM oportunidades")}

    forte = [t for t in linhas if "Aceleradora de Impacto" in t]
    assert forte, "titulo CI-Brasil (real) nao chegou ao banco"
    assert linhas[forte[0]]["status"] == "nova"
    assert linhas[forte[0]]["status"] != "descartada_kw"

    fraco = [t for t in linhas if "apoio administrativo" in t]
    assert fraco, "titulo fraco (score 0) nao chegou ao banco"
    assert linhas[fraco[0]]["score_kw"] == 0
    assert linhas[fraco[0]]["status"] == "nova"
    assert linhas[fraco[0]]["status"] != "descartada_kw"

    hoje = datetime.now(timezone.utc).date().isoformat()
    md = relatorio.gerar(con, hoje)
    assert "Aceleradora de Impacto" in md
    assert "apoio administrativo" in md


def test_varrer_vetado_sem_tema_forte_fica_descartada_kw_e_fora_do_relatorio(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")

    def extrair_falso(texto, fonte, chamar=None):
        return [
            Oportunidade(
                titulo="Vaga de emprego: analista administrativo",
                url="https://www.wribrasil.org.br/vagas/analista",
            )
        ]

    monkeypatch.setattr(pipeline.extrai, "extrair", extrair_falso)
    pipeline.varrer(con, [FONTE], cliente_falso(), usar_llm=True, pausar=lambda _: None)

    linha = con.execute("SELECT status FROM oportunidades").fetchone()
    assert linha["status"] == "descartada_kw"

    hoje = datetime.now(timezone.utc).date().isoformat()
    md = relatorio.gerar(con, hoje)
    assert "Vaga de emprego" not in md


def test_varrer_marca_vencida_item_com_prazo_passado_e_nao_gasta_juiz(
    tmp_path, monkeypatch
):
    """Correcao 1: um item cujo prazo e' uma data ISO confirmada no passado
    (2019-09-02, do incidente real) tem que virar 'vencida', nao entrar em
    pendentes (economiza a chamada de LLM) e nao aparecer no relatorio."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")

    def extrair_falso(texto, fonte, chamar=None):
        return [
            Oportunidade(
                titulo="Consultoria em Comunicacao para Plataforma de Restauracao",
                objeto="comunicacao institucional",
                url="https://www.wribrasil.org.br/media/comunicacao.pdf",
                prazo="2019-09-02",
            )
        ]

    monkeypatch.setattr(pipeline.extrai, "extrair", extrair_falso)

    chamado = []
    monkeypatch.setattr(
        pipeline.juiz, "julgar", lambda itens: chamado.append(itens) or []
    )

    pipeline.varrer(con, [FONTE], cliente_falso(), usar_llm=True, pausar=lambda _: None)

    linha = con.execute("SELECT status FROM oportunidades").fetchone()
    assert linha["status"] == "vencida"
    assert chamado == [], "juiz foi chamado para um item com prazo ja vencido"

    hoje = datetime.now(timezone.utc).date().isoformat()
    md = relatorio.gerar(con, hoje)
    assert "Consultoria em Comunicacao" not in md


def test_varrer_prazo_none_nao_e_vencida_e_continua_ate_o_juiz(tmp_path, monkeypatch):
    """Critico: prazo=None (o caso real do melhor match do WRI) NAO pode ser
    tratado como vencido — tem que continuar ate o juiz e aparecer no
    relatorio."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")

    def extrair_falso(texto, fonte, chamar=None):
        return [
            Oportunidade(
                titulo="Consultoria em plataforma de dados sem prazo publicado",
                objeto="plataforma de dados e painel de indicadores",
                url="https://www.wribrasil.org.br/media/sem-prazo.pdf",
                prazo=None,
            )
        ]

    monkeypatch.setattr(pipeline.extrai, "extrair", extrair_falso)

    def julgar_alto(itens):
        return [
            {
                "id": i["id"], "score_llm": 9, "justificativa_llm": "aderente",
                "prazo": None, "modalidade": None, "modelo_llm": "m",
            }
            for i in itens
        ]

    monkeypatch.setattr(pipeline.juiz, "julgar", julgar_alto)

    pipeline.varrer(con, [FONTE], cliente_falso(), usar_llm=True, pausar=lambda _: None)

    linha = con.execute("SELECT status, score_llm FROM oportunidades").fetchone()
    assert linha["status"] != "vencida"
    assert linha["score_llm"] == 9

    hoje = datetime.now(timezone.utc).date().isoformat()
    md = relatorio.gerar(con, hoje)
    assert "sem prazo publicado" in md


def test_varrer_prazo_malformado_nao_quebra_e_nao_e_vencida(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")

    def extrair_falso(texto, fonte, chamar=None):
        return [
            Oportunidade(
                titulo="Consultoria com prazo a definir",
                objeto="plataforma de dados",
                url="https://www.wribrasil.org.br/media/a-definir.pdf",
                prazo="a definir",
            )
        ]

    monkeypatch.setattr(pipeline.extrai, "extrair", extrair_falso)
    pipeline.varrer(con, [FONTE], cliente_falso(), usar_llm=False, pausar=lambda _: None)

    linha = con.execute("SELECT status FROM oportunidades").fetchone()
    assert linha["status"] != "vencida"


def test_retriar_move_prazo_ja_vencido_para_vencida(tmp_path, monkeypatch):
    """Correcao 1: retriar tem que migrar para 'vencida' um item historico
    JA JULGADO (score_llm setado, como o item real da Abong com prazo
    2021-03-10 que uma rodada antiga rankeou score 6) — nao so' os itens
    nunca julgados."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")
    novas, _ = pipeline.oportunidades.salvar(
        con, {"id": "abong", "nome": "Abong"}, "catalogo",
        [
            Oportunidade(
                titulo="Abong contrata consultoria em comunicacao para "
                "criacao de campanha digital",
                url="https://abong.org.br/oportunidades/campanha",
                prazo="2021-03-10",
            )
        ],
    )
    con.execute(
        "UPDATE oportunidades SET score_llm=6, justificativa_llm='ok', "
        "modelo_llm='m', status='reportada' WHERE id=?",
        (novas[0],),
    )
    con.commit()

    mudou = pipeline.retriar(con, usar_llm=False)

    linha = con.execute(
        "SELECT status FROM oportunidades WHERE id=?", (novas[0],)
    ).fetchone()
    assert linha["status"] == "vencida"
    assert mudou == 1


def test_retriar_revive_vencida_dentro_da_nova_tolerancia(tmp_path, monkeypatch):
    """Correcao 2: linha marcada 'vencida' numa rodada anterior (regra de
    tolerancia zero, ou qualquer rodada anterior a uma mudanca de
    DIAS_TOLERANCIA_VENCIDO) cujo atraso, sob a janela atual, ja nao
    configura mais vencida — tem que sair de 'vencida' e voltar ao status
    que o score_llm ja julgado indica, nao ficar presa para sempre (ela nao
    passa pelo loop de reclassificacao normal, que so pega score_llm NULL)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")
    hoje = datetime.now(timezone.utc).date()
    prazo_3_dias_atras = (hoje - timedelta(days=3)).isoformat()
    novas, _ = pipeline.oportunidades.salvar(
        con, {"id": "abong", "nome": "Abong"}, "catalogo",
        [
            Oportunidade(
                titulo="Abong contrata consultoria em comunicacao para "
                "criacao de campanha digital",
                url="https://abong.org.br/oportunidades/campanha-2",
                prazo=prazo_3_dias_atras,
            )
        ],
    )
    con.execute(
        "UPDATE oportunidades SET score_llm=8, justificativa_llm='ok', "
        "modelo_llm='m', status='vencida' WHERE id=?",
        (novas[0],),
    )
    con.commit()

    pipeline.retriar(con, usar_llm=False)

    linha = con.execute(
        "SELECT status FROM oportunidades WHERE id=?", (novas[0],)
    ).fetchone()
    assert linha["status"] == "reportada"


def test_retriar_move_descartada_kw_nao_vetada_para_nova(tmp_path, monkeypatch):
    """Migra linha presa em descartada_kw por classificacao antiga (score
    kw baixo sem veto, que a regra velha escondia e a regra nova nao
    esconde mais). Fixture: o titulo real do CI-Brasil, gravado
    descartada_kw numa rodada anterior ao fix."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    con = db.conectar(tmp_path / "t.sqlite")
    novas, _ = pipeline.oportunidades.salvar(
        con, {"id": "ci-brasil", "nome": "CI Brasil"}, "catalogo",
        [
            Oportunidade(
                titulo=(
                    "Contratação de consultoria de pessoa jurídica para o "
                    "desenvolvimento da plataforma da Aceleradora de Impacto"
                ),
                url="https://ci-brasil.org/oportunidades/x",
            )
        ],
    )
    con.execute("UPDATE oportunidades SET status='descartada_kw' WHERE id=?", (novas[0],))
    con.commit()

    mudou = pipeline.retriar(con, usar_llm=False)

    linha = con.execute("SELECT status FROM oportunidades WHERE id=?", (novas[0],)).fetchone()
    assert linha["status"] == "nova"
    assert mudou == 1
