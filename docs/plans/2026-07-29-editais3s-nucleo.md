# editais3s — Núcleo (Fases 1 e 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Varrer diariamente o catálogo de financiadores de terceiro setor, extrair oportunidades de consultoria, pontuar aderência ao portfólio NOTABC e escrever `data/novas_AAAA-MM-DD.md`.

**Architecture:** Pipeline síncrono por fonte: baixa página → limpa HTML para texto → compara hash com o snapshot anterior (gate que evita chamada de LLM em página que não mudou) → extrai oportunidades com Haiku em structured output → dedup em SQLite → funil de dois passos (Aho-Corasick e depois juiz LLM) → relatório Markdown. Toda fonte falha isolada: erro entra no banco e no bloco Saúde do relatório, nunca aborta o job.

**Tech Stack:** Python 3.12, httpx, selectolax, pyahocorasick, anthropic SDK, sqlite3 (stdlib), pytest.

Spec: `docs/specs/2026-07-29-editais3s-design.md`. Este plano cobre as Fases 1 e 2. Fases 3 (tier 2 + gnews + agregadores), 4 (descoberta mensal + newsletter Gmail) e 5 (cron, systemd, custos, saúde) ganham planos próprios.

## Global Constraints

- Python 3.12. Dependências: `httpx`, `selectolax`, `pyahocorasick`, `anthropic`, `pytest`. Nada além disso nesta fase.
- Playwright fica fora desta fase. Fonte marcada `js: true` no catálogo é registrada como `indisponivel` no relatório, sem tentativa de download.
- User-Agent fixo e identificável: `editais3s/0.1 (monitor de editais de terceiro setor; +notabc)`.
- Um request por segundo por domínio, concorrência global 6, timeout 20 s, duas tentativas com backoff. A pausa entre requests vive no varredor (`pipeline.varrer`), nunca em `coleta.coletar`, para que teste unitário não durma.
- `robots.txt` respeitado antes de baixar qualquer página.
- Nomes de módulo, função e coluna em português, seguindo o padrão de `pncp/monitor_pncp/`.
- Nenhuma credencial no repo. `ANTHROPIC_API_KEY` vem do ambiente. Ausência da chave não quebra o job: extração cai para heurística e o juiz desliga.
- `data/` fica no `.gitignore`. Banco e relatório não são versionados.
- Todo `.md` gerado passa por `python3 /config/workspace/scripts/check_sensivel.py` antes de ser considerado pronto (regra do `CLAUDE.md` do workspace).
- Todo modelo Anthropic referenciado por constante em `config.py`, nunca hardcoded no meio do código.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `requirements.txt` | Dependências fixadas. |
| `fontes.json` | Catálogo curado tier 1. |
| `editais3s/config.py` | Caminhos, constantes de rede, modelos, limiares. Zero lógica. |
| `editais3s/db.py` | Conexão SQLite e DDL idempotente. |
| `editais3s/limpeza.py` | HTML → texto com links inline; hash do texto. |
| `editais3s/fontes.py` | Carga e validação do catálogo. |
| `editais3s/coleta.py` | Download de uma fonte e gate de hash contra `snapshots`. |
| `editais3s/modelos.py` | `Oportunidade` e cálculo de `id` canônico. |
| `editais3s/oportunidades.py` | Persistência, dedup e detecção de atualização. |
| `editais3s/extrai.py` | Texto → `list[Oportunidade]`, via LLM ou heurística. |
| `editais3s/escopo.py` | Dicionário de temas e vetos; scoring Aho-Corasick. |
| `editais3s/juiz.py` | Score 0–10 e justificativa por LLM. |
| `editais3s/relatorio.py` | Banco → Markdown do dia. |
| `editais3s/pipeline.py` | Orquestra fonte a fonte; isola erro; grava `execucoes`. |
| `editais3s/cli.py`, `__main__.py` | Subcomandos `diario`, `relatorio`, `bootstrap`. |
| `tests/` | Suíte pytest com fixtures HTML. |

---

### Task 1: Esqueleto do repo, config e banco

**Files:**
- Create: `requirements.txt`, `.gitignore`, `editais3s/__init__.py`, `editais3s/config.py`, `editais3s/db.py`, `tests/__init__.py`, `tests/test_db.py`

**Interfaces:**
- Consumes: nada.
- Produces: `config` com as constantes usadas por todos os módulos. `db.conectar(caminho: Path | None = None) -> sqlite3.Connection`, idempotente, `row_factory = sqlite3.Row`.

- [ ] **Step 1: Inicializar o repo**

O diretório e o `docs/` já existem. Falta o git.

```bash
cd /config/workspace/editais3s
git init
printf 'data/\n__pycache__/\n*.pyc\n.venv/\n.pytest_cache/\n' > .gitignore
git add .gitignore docs/
git commit -m "chore: repo inicial com spec de design"
```

- [ ] **Step 2: Escrever `requirements.txt`**

Versoes conferidas no ambiente (`.venv` na raiz do repo, use `.venv/bin/python`):

```
httpx==0.28.1
selectolax==0.4.11
pyahocorasick==2.3.1
anthropic==0.120.2
pytest==9.1.1
```

- [ ] **Step 3: Escrever o teste do banco**

`tests/test_db.py`:

```python
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
```

- [ ] **Step 4: Rodar e ver falhar**

Run: `python -m pytest tests/test_db.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'editais3s'`

- [ ] **Step 5: Escrever `editais3s/config.py`**

```python
"""Constantes do monitor. Sem lógica — só valores."""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CFG_FONTES = RAIZ / "fontes.json"
CFG_CANDIDATAS = RAIZ / "fontes_candidatas.json"
DIR_DADOS = RAIZ / "data"
BANCO = DIR_DADOS / "editais3s.sqlite"

UA = "editais3s/0.1 (monitor de editais de terceiro setor; +notabc)"
TIMEOUT = 20.0
TENTATIVAS = 2
CONCORRENCIA = 6
INTERVALO_DOMINIO = 1.0
MAX_CHARS_TEXTO = 40_000

MODELO_EXTRACAO = "claude-haiku-4-5"
MODELO_JUIZ = "claude-haiku-4-5"

SCORE_KW_MINIMO = 4
SCORE_LLM_ADERENTE = 6
SCORE_LLM_OLHAR = 4
PRAZO_APERTADO_DIAS = 10
DIAS_SEM_ITEM_ALERTA = 60


def tem_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
```

- [ ] **Step 6: Escrever `editais3s/db.py`**

```python
"""Conexão e DDL do SQLite. Toda DDL é IF NOT EXISTS — conectar é idempotente."""
import sqlite3
from pathlib import Path

from .config import BANCO

ESQUEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  fonte_id TEXT PRIMARY KEY,
  hash TEXT,
  coletado_em TEXT,
  http_status INTEGER,
  bytes INTEGER,
  erro TEXT,
  erros_seguidos INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS oportunidades (
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
);

CREATE INDEX IF NOT EXISTS ix_oport_visto ON oportunidades (visto_em);
CREATE INDEX IF NOT EXISTS ix_oport_fonte ON oportunidades (fonte_id);

CREATE TABLE IF NOT EXISTS triagem (
  oportunidade_id TEXT NOT NULL,
  rotulo TEXT NOT NULL,
  nota TEXT,
  rotulado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS execucoes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  iniciado_em TEXT,
  terminado_em TEXT,
  fontes_ok INTEGER,
  fontes_erro INTEGER,
  novas INTEGER,
  tokens_in INTEGER,
  tokens_out INTEGER,
  custo_usd REAL
);
"""


def conectar(caminho: Path | None = None) -> sqlite3.Connection:
    caminho = Path(caminho) if caminho else BANCO
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row
    con.executescript(ESQUEMA)
    con.commit()
    return con
```

Criar também `editais3s/__init__.py` e `tests/__init__.py` vazios.

- [ ] **Step 7: Rodar e ver passar**

Run: `python -m pytest tests/test_db.py -v`
Expected: 3 passed

- [ ] **Step 8: Commit**

```bash
git add requirements.txt editais3s/__init__.py editais3s/config.py editais3s/db.py tests/__init__.py tests/test_db.py
git commit -m "feat: config e schema SQLite do monitor"
```

---

### Task 2: Limpeza de HTML e hash

**Files:**
- Create: `editais3s/limpeza.py`, `tests/test_limpeza.py`

**Interfaces:**
- Consumes: `config.MAX_CHARS_TEXTO`.
- Produces: `limpeza.limpar(html: str, max_chars: int | None = None) -> str` e `limpeza.hash_texto(texto: str) -> str` (SHA-1 hex).

O inline de âncora acontece por regex no HTML cru, **antes** do parser. Motivo: preserva a ordem do link junto do título na mesma linha do texto, que é o que o LLM precisa para casar título com URL. Um bloco de links no fim do documento perderia esse pareamento.

- [ ] **Step 1: Escrever o teste**

`tests/test_limpeza.py`:

```python
from editais3s import limpeza

HTML = """
<html><head><style>.a{color:red}</style><script>var x=1</script></head>
<body>
<nav>Home Sobre Contato</nav>
<h1>Oportunidades</h1>
<ul>
  <li><a href="/media/tdr-ouvidoria.pdf">TdR FLWTDR-2026-011 Ouvidoria Restaura Biomas</a>
      Prazo: 13/07/2026</li>
  <li><a href="/sobre">Quem somos</a></li>
</ul>
<footer>Rodape institucional</footer>
</body></html>
"""


def test_limpar_remove_navegacao_e_script():
    texto = limpeza.limpar(HTML)
    assert "Home Sobre Contato" not in texto
    assert "Rodape institucional" not in texto
    assert "var x=1" not in texto
    assert "color:red" not in texto


def test_limpar_inlina_link_junto_do_texto():
    texto = limpeza.limpar(HTML)
    assert "[TdR FLWTDR-2026-011 Ouvidoria Restaura Biomas](/media/tdr-ouvidoria.pdf)" in texto


def test_limpar_preserva_texto_vizinho_do_link():
    texto = limpeza.limpar(HTML)
    assert "13/07/2026" in texto
    assert "Quem somos" in texto


def test_limpar_respeita_limite_de_caracteres():
    assert len(limpeza.limpar("<body>" + "x" * 500 + "</body>", max_chars=100)) == 100


def test_hash_estavel_e_sensivel():
    assert limpeza.hash_texto("a") == limpeza.hash_texto("a")
    assert limpeza.hash_texto("a") != limpeza.hash_texto("b")
    assert len(limpeza.hash_texto("a")) == 40
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_limpeza.py -v`
Expected: FAIL com `ImportError: cannot import name 'limpeza'`

- [ ] **Step 3: Escrever `editais3s/limpeza.py`**

```python
"""HTML -> texto enxuto, com âncora inline no formato [texto](url)."""
import hashlib
import re

from selectolax.parser import HTMLParser

from .config import MAX_CHARS_TEXTO

REMOVER = (
    "script", "style", "noscript", "svg", "nav", "header", "footer",
    "aside", "form", "iframe",
)

RE_ANCORA = re.compile(
    r"<a\b[^>]*\bhref=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S
)
RE_TAG = re.compile(r"<[^>]+>")
RE_ESPACO = re.compile(r"[ \t]+")
RE_LINHAS = re.compile(r"\n{3,}")


def _inline_ancoras(html: str) -> str:
    def troca(m: re.Match) -> str:
        href = m.group(1).strip()
        dentro = RE_ESPACO.sub(" ", RE_TAG.sub(" ", m.group(2))).strip()
        return f" [{dentro}]({href}) " if dentro else " "

    return RE_ANCORA.sub(troca, html)


def limpar(html: str, max_chars: int | None = None) -> str:
    limite = MAX_CHARS_TEXTO if max_chars is None else max_chars
    arvore = HTMLParser(_inline_ancoras(html))
    for tag in REMOVER:
        for no in arvore.css(tag):
            no.decompose()
    raiz = arvore.body or arvore.root
    bruto = raiz.text(separator="\n") if raiz else ""
    linhas = [RE_ESPACO.sub(" ", l).strip() for l in bruto.splitlines()]
    texto = "\n".join(l for l in linhas if l)
    return RE_LINHAS.sub("\n\n", texto)[:limite]


def hash_texto(texto: str) -> str:
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_limpeza.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add editais3s/limpeza.py tests/test_limpeza.py
git commit -m "feat: limpeza de HTML com ancora inline e hash de conteudo"
```

---

### Task 3: Catálogo de fontes

**Files:**
- Create: `fontes.json`, `editais3s/fontes.py`, `tests/test_fontes.py`

**Interfaces:**
- Consumes: `config.CFG_FONTES`.
- Produces: `fontes.carregar(caminho: Path | None = None) -> list[dict]`, `fontes.validar(fonte: dict) -> None` (levanta `fontes.FonteInvalida`), `fontes.filtrar(fontes: list[dict], ids: list[str] | None) -> list[dict]`.

Campos obrigatórios: `id`, `nome`, `tipo`, `dominio`, `tier`. Opcionais: `url`, `query`, `js`, `verificar`, `nota`.

Toda fonte tier 1 entra com `verificar: true`. O `bootstrap` (Task 10) confirma a URL antes do primeiro `diario` valer como cobertura real. Enquanto `verificar` for `true`, a fonte é varrida mas o relatório marca a linha como não confirmada.

- [ ] **Step 1: Escrever `fontes.json` com o tier 1**

```json
{
  "_meta": {
    "descricao": "Financiadores de terceiro setor que contratam consultoria. Escopo: plataforma de dados, ciencia de dados, desenvolvimento de site/portal.",
    "atualizado": "2026-07-29",
    "tiers": {
      "1": "INGO ambiental e fundo ambiental com operacao no Brasil",
      "2": "filantropia brasileira (institutos e fundacoes)"
    },
    "verificar": "true = URL da pagina de oportunidade ainda nao confirmada pelo comando bootstrap"
  },
  "fontes": [
    {"id": "wri-brasil", "nome": "WRI Brasil", "tipo": "html", "dominio": "wribrasil.org.br", "url": "https://www.wribrasil.org.br/oportunidades", "tier": 1, "verificar": true, "nota": "Origem do TdR FLWTDR-2026-011 (Ouvidoria Restaura Biomas). Publica TdR em PDF linkado."},
    {"id": "funbio", "nome": "Funbio", "tipo": "html", "dominio": "funbio.org.br", "url": "https://www.funbio.org.br/editais/", "tier": 1, "verificar": true, "nota": "Alto volume de edital de consultoria; opera Fundo Amazonia e projetos GEF."},
    {"id": "wwf-brasil", "nome": "WWF-Brasil", "tipo": "html", "dominio": "wwf.org.br", "url": "https://www.wwf.org.br/wwf_brasil/editais/", "tier": 1, "verificar": true, "nota": "Parceiro da Uniao pela Restauracao junto com WRI, TNC e CI."},
    {"id": "tnc-brasil", "nome": "The Nature Conservancy Brasil", "tipo": "html", "dominio": "tnc.org.br", "url": "https://www.tnc.org.br/quem-somos/transparencia/", "tier": 1, "verificar": true, "nota": "Verificar se publica edital em pagina propria ou so por convite."},
    {"id": "ci-brasil", "nome": "Conservacao Internacional Brasil", "tipo": "html", "dominio": "conservation.org", "url": "https://www.conservation.org/brasil/oportunidades", "tier": 1, "verificar": true, "nota": "CI-GEF e o financiador do Restaura Biomas."},
    {"id": "ipam", "nome": "IPAM", "tipo": "html", "dominio": "ipam.org.br", "url": "https://ipam.org.br/oportunidades/", "tier": 1, "verificar": true, "nota": "Pesquisa amazonica; contrata dados e geoespacial."},
    {"id": "imazon", "nome": "Imazon", "tipo": "html", "dominio": "imazon.org.br", "url": "https://imazon.org.br/institucional/trabalhe-conosco/", "tier": 1, "verificar": true, "nota": "Forte em sensoriamento remoto; separar vaga de consultoria."},
    {"id": "isa", "nome": "Instituto Socioambiental", "tipo": "html", "dominio": "socioambiental.org", "url": "https://www.socioambiental.org/pt-br/institucional/editais", "tier": 1, "verificar": true, "nota": "Publica edital e chamada de consultoria."},
    {"id": "fas", "nome": "Fundacao Amazonia Sustentavel", "tipo": "html", "dominio": "fas-amazonia.org", "url": "https://fas-amazonia.org/editais/", "tier": 1, "verificar": true, "nota": "Volume alto de cotacao e TdR."},
    {"id": "escolhas", "nome": "Instituto Escolhas", "tipo": "html", "dominio": "escolhas.org", "url": "https://escolhas.org/oportunidades/", "tier": 1, "verificar": true, "nota": "Estudo economico-ambiental; contrata analise de dados."},
    {"id": "talanoa", "nome": "Instituto Talanoa", "tipo": "gnews", "dominio": "institutotalanoa.org", "query": "site:institutotalanoa.org edital OR consultoria OR \"termo de referencia\"", "tier": 1, "verificar": false, "nota": "Sem pagina de oportunidade conhecida; coberto por padrao textual."},
    {"id": "sos-mata-atlantica", "nome": "SOS Mata Atlantica", "tipo": "html", "dominio": "sosma.org.br", "url": "https://www.sosma.org.br/transparencia/", "tier": 1, "verificar": true, "nota": "Verificar secao de contratacao."},
    {"id": "observatorio-do-clima", "nome": "Observatorio do Clima", "tipo": "gnews", "dominio": "oc.eco.br", "query": "site:oc.eco.br edital OR consultoria OR vaga", "tier": 1, "verificar": false, "nota": "Rede; publica pouco edital proprio."},
    {"id": "fundo-casa", "nome": "Fundo Casa Socioambiental", "tipo": "html", "dominio": "casa.org.br", "url": "https://casa.org.br/editais/", "tier": 1, "verificar": true, "nota": "Foco em apoio a projeto; veto suave tende a filtrar. Manter para pegar consultoria de plataforma."}
  ]
}
```

- [ ] **Step 2: Escrever o teste**

`tests/test_fontes.py`:

```python
import json

import pytest

from editais3s import fontes


def test_carregar_catalogo_real_valida_todas_as_fontes():
    lista = fontes.carregar()
    assert len(lista) >= 14
    for fonte in lista:
        fontes.validar(fonte)


def test_ids_sao_unicos():
    ids = [f["id"] for f in fontes.carregar()]
    assert len(ids) == len(set(ids))


def test_validar_rejeita_campo_faltando():
    with pytest.raises(fontes.FonteInvalida, match="dominio"):
        fontes.validar({"id": "x", "nome": "X", "tipo": "html", "tier": 1})


def test_validar_rejeita_tipo_desconhecido():
    with pytest.raises(fontes.FonteInvalida, match="tipo"):
        fontes.validar(
            {"id": "x", "nome": "X", "tipo": "pdf", "dominio": "x.org", "tier": 1}
        )


def test_validar_exige_url_em_fonte_html():
    with pytest.raises(fontes.FonteInvalida, match="url"):
        fontes.validar(
            {"id": "x", "nome": "X", "tipo": "html", "dominio": "x.org", "tier": 1}
        )


def test_validar_exige_query_em_fonte_gnews():
    with pytest.raises(fontes.FonteInvalida, match="query"):
        fontes.validar(
            {"id": "x", "nome": "X", "tipo": "gnews", "dominio": "x.org", "tier": 1}
        )


def test_filtrar_por_ids(tmp_path):
    lista = fontes.carregar()
    assert [f["id"] for f in fontes.filtrar(lista, ["wri-brasil"])] == ["wri-brasil"]
    assert fontes.filtrar(lista, None) == lista


def test_filtrar_rejeita_id_inexistente():
    with pytest.raises(fontes.FonteInvalida, match="nao-existe"):
        fontes.filtrar(fontes.carregar(), ["nao-existe"])


def test_carregar_de_caminho_alternativo(tmp_path):
    caminho = tmp_path / "f.json"
    caminho.write_text(
        json.dumps(
            {
                "fontes": [
                    {
                        "id": "a",
                        "nome": "A",
                        "tipo": "html",
                        "dominio": "a.org",
                        "url": "https://a.org/x",
                        "tier": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert len(fontes.carregar(caminho)) == 1
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `python -m pytest tests/test_fontes.py -v`
Expected: FAIL com `ImportError: cannot import name 'fontes'`

- [ ] **Step 4: Escrever `editais3s/fontes.py`**

```python
"""Carga e validação do catálogo curado."""
import json
from pathlib import Path

from .config import CFG_FONTES

TIPOS = {"html", "rss", "json", "gnews"}
OBRIGATORIOS = ("id", "nome", "tipo", "dominio", "tier")


class FonteInvalida(ValueError):
    pass


def validar(fonte: dict) -> None:
    for campo in OBRIGATORIOS:
        if not fonte.get(campo):
            raise FonteInvalida(f"fonte {fonte.get('id', '?')}: campo {campo} ausente")
    if fonte["tipo"] not in TIPOS:
        raise FonteInvalida(
            f"fonte {fonte['id']}: tipo {fonte['tipo']!r} desconhecido"
        )
    if fonte["tipo"] in {"html", "rss", "json"} and not fonte.get("url"):
        raise FonteInvalida(f"fonte {fonte['id']}: tipo {fonte['tipo']} exige url")
    if fonte["tipo"] == "gnews" and not fonte.get("query"):
        raise FonteInvalida(f"fonte {fonte['id']}: tipo gnews exige query")


def carregar(caminho: Path | None = None) -> list[dict]:
    caminho = Path(caminho) if caminho else CFG_FONTES
    cfg = json.loads(caminho.read_text(encoding="utf-8"))
    lista = cfg["fontes"]
    for fonte in lista:
        validar(fonte)
    return lista


def filtrar(fontes: list[dict], ids: list[str] | None) -> list[dict]:
    if not ids:
        return fontes
    por_id = {f["id"]: f for f in fontes}
    faltando = [i for i in ids if i not in por_id]
    if faltando:
        raise FonteInvalida(f"id desconhecido no catalogo: {', '.join(faltando)}")
    return [por_id[i] for i in ids]
```

- [ ] **Step 5: Rodar e ver passar**

Run: `python -m pytest tests/test_fontes.py -v`
Expected: 9 passed

- [ ] **Step 6: Commit**

```bash
git add fontes.json editais3s/fontes.py tests/test_fontes.py
git commit -m "feat: catalogo tier 1 de financiadores e validacao"
```

---

### Task 4: Coleta com gate de hash

**Files:**
- Create: `editais3s/coleta.py`, `tests/test_coleta.py`

**Interfaces:**
- Consumes: `config.UA`, `config.TIMEOUT`, `config.TENTATIVAS`, `limpeza.limpar`, `limpeza.hash_texto`, `db`.
- Produces:
  - `coleta.Coleta` — dataclass com `fonte_id: str`, `ok: bool`, `mudou: bool`, `texto: str`, `hash: str | None`, `http_status: int | None`, `erro: str | None`.
  - `coleta.coletar(fonte: dict, con, cliente: httpx.Client, forcar: bool = False) -> Coleta`
  - `coleta.robots_permite(fonte: dict, cliente: httpx.Client) -> bool`

`coletar` não dorme e não trata `robots.txt` — quem pauceia e checa robots é `pipeline.varrer` (Task 10). Assim o teste roda sem rede e sem espera.

- [ ] **Step 1: Escrever o teste**

`tests/test_coleta.py`:

```python
import httpx
import pytest

from editais3s import coleta, db

FONTE = {
    "id": "wri-brasil",
    "nome": "WRI Brasil",
    "tipo": "html",
    "dominio": "wribrasil.org.br",
    "url": "https://www.wribrasil.org.br/oportunidades",
    "tier": 1,
}

PAGINA_A = "<body><h1>Oportunidades</h1><p>TdR Ouvidoria</p></body>"
PAGINA_B = "<body><h1>Oportunidades</h1><p>TdR Ouvidoria</p><p>Nova cotacao</p></body>"


def cliente(corpo, status=200, erro=None):
    def handler(request):
        if erro:
            raise erro
        return httpx.Response(status, text=corpo)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_primeira_coleta_marca_mudou(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    r = coleta.coletar(FONTE, con, cliente(PAGINA_A))
    assert r.ok and r.mudou
    assert "TdR Ouvidoria" in r.texto


def test_segunda_coleta_igual_nao_mudou(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    coleta.coletar(FONTE, con, cliente(PAGINA_A))
    r = coleta.coletar(FONTE, con, cliente(PAGINA_A))
    assert r.ok and r.mudou is False


def test_conteudo_diferente_volta_a_mudar(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    coleta.coletar(FONTE, con, cliente(PAGINA_A))
    r = coleta.coletar(FONTE, con, cliente(PAGINA_B))
    assert r.mudou


def test_forcar_ignora_o_gate(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    coleta.coletar(FONTE, con, cliente(PAGINA_A))
    r = coleta.coletar(FONTE, con, cliente(PAGINA_A), forcar=True)
    assert r.mudou


def test_http_erro_nao_levanta_e_conta_erro(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    r = coleta.coletar(FONTE, con, cliente("nao encontrado", status=404))
    assert r.ok is False
    assert r.http_status == 404
    linha = con.execute(
        "SELECT erros_seguidos, erro FROM snapshots WHERE fonte_id=?", (FONTE["id"],)
    ).fetchone()
    assert linha["erros_seguidos"] == 1
    assert "404" in linha["erro"]


def test_erro_de_rede_nao_levanta(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    r = coleta.coletar(
        FONTE, con, cliente("", erro=httpx.ConnectError("sem rota"))
    )
    assert r.ok is False and r.erro


def test_sucesso_zera_contador_de_erro(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    coleta.coletar(FONTE, con, cliente("x", status=500))
    coleta.coletar(FONTE, con, cliente(PAGINA_A))
    linha = con.execute(
        "SELECT erros_seguidos FROM snapshots WHERE fonte_id=?", (FONTE["id"],)
    ).fetchone()
    assert linha["erros_seguidos"] == 0


def test_fonte_js_true_nao_e_baixada(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    fonte = {**FONTE, "js": True}
    r = coleta.coletar(fonte, con, cliente(PAGINA_A))
    assert r.ok is False
    assert r.erro == "indisponivel: requer navegador (js)"


def test_robots_bloqueado(tmp_path):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /oportunidades")
        return httpx.Response(200, text=PAGINA_A)

    c = httpx.Client(transport=httpx.MockTransport(handler))
    assert coleta.robots_permite(FONTE, c) is False


def test_robots_liberado_quando_ausente():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404, text="")
        return httpx.Response(200, text=PAGINA_A)

    c = httpx.Client(transport=httpx.MockTransport(handler))
    assert coleta.robots_permite(FONTE, c) is True
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_coleta.py -v`
Expected: FAIL com `ImportError: cannot import name 'coleta'`

- [ ] **Step 3: Escrever `editais3s/coleta.py`**

```python
"""Download de uma fonte e gate de hash contra a tabela snapshots."""
import sqlite3
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin

import httpx

from . import limpeza
from .config import TENTATIVAS, UA


@dataclass
class Coleta:
    fonte_id: str
    ok: bool
    mudou: bool
    texto: str = ""
    hash: str | None = None
    http_status: int | None = None
    erro: str | None = None


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def robots_permite(fonte: dict, cliente: httpx.Client) -> bool:
    alvo = fonte["url"]
    try:
        resp = cliente.get(urljoin(alvo, "/robots.txt"), headers={"User-Agent": UA})
    except httpx.HTTPError:
        return True
    if resp.status_code != 200:
        return True
    leitor = urllib.robotparser.RobotFileParser()
    leitor.parse(resp.text.splitlines())
    return bool(leitor.can_fetch(UA, alvo))


def _baixar(url: str, cliente: httpx.Client) -> httpx.Response:
    ultimo: Exception | None = None
    for _ in range(TENTATIVAS):
        try:
            return cliente.get(
                url, headers={"User-Agent": UA}, follow_redirects=True
            )
        except httpx.HTTPError as exc:
            ultimo = exc
    raise ultimo  # type: ignore[misc]


def _gravar_erro(con: sqlite3.Connection, fonte_id: str, status, erro: str) -> None:
    con.execute(
        """
        INSERT INTO snapshots (fonte_id, coletado_em, http_status, erro, erros_seguidos)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(fonte_id) DO UPDATE SET
          coletado_em=excluded.coletado_em,
          http_status=excluded.http_status,
          erro=excluded.erro,
          erros_seguidos=snapshots.erros_seguidos + 1
        """,
        (fonte_id, _agora(), status, erro),
    )
    con.commit()


def coletar(
    fonte: dict,
    con: sqlite3.Connection,
    cliente: httpx.Client,
    forcar: bool = False,
) -> Coleta:
    fonte_id = fonte["id"]

    if fonte.get("js"):
        erro = "indisponivel: requer navegador (js)"
        _gravar_erro(con, fonte_id, None, erro)
        return Coleta(fonte_id, ok=False, mudou=False, erro=erro)

    try:
        resp = _baixar(fonte["url"], cliente)
    except httpx.HTTPError as exc:
        erro = f"{type(exc).__name__}: {exc}"
        _gravar_erro(con, fonte_id, None, erro)
        return Coleta(fonte_id, ok=False, mudou=False, erro=erro)

    if resp.status_code >= 400:
        erro = f"HTTP {resp.status_code}"
        _gravar_erro(con, fonte_id, resp.status_code, erro)
        return Coleta(
            fonte_id, ok=False, mudou=False, http_status=resp.status_code, erro=erro
        )

    texto = limpeza.limpar(resp.text)
    novo_hash = limpeza.hash_texto(texto)
    anterior = con.execute(
        "SELECT hash FROM snapshots WHERE fonte_id=?", (fonte_id,)
    ).fetchone()
    mudou = forcar or anterior is None or anterior["hash"] != novo_hash

    con.execute(
        """
        INSERT INTO snapshots (fonte_id, hash, coletado_em, http_status, bytes, erro, erros_seguidos)
        VALUES (?, ?, ?, ?, ?, NULL, 0)
        ON CONFLICT(fonte_id) DO UPDATE SET
          hash=excluded.hash,
          coletado_em=excluded.coletado_em,
          http_status=excluded.http_status,
          bytes=excluded.bytes,
          erro=NULL,
          erros_seguidos=0
        """,
        (fonte_id, novo_hash, _agora(), resp.status_code, len(resp.content)),
    )
    con.commit()

    return Coleta(
        fonte_id,
        ok=True,
        mudou=mudou,
        texto=texto,
        hash=novo_hash,
        http_status=resp.status_code,
    )
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_coleta.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add editais3s/coleta.py tests/test_coleta.py
git commit -m "feat: coleta por fonte com gate de hash e isolamento de erro"
```

---

### Task 5: Modelo de oportunidade, dedup e persistência

**Files:**
- Create: `editais3s/modelos.py`, `editais3s/oportunidades.py`, `tests/test_oportunidades.py`

**Interfaces:**
- Consumes: `db`.
- Produces:
  - `modelos.Oportunidade` — dataclass: `titulo: str`, `objeto: str = ""`, `url: str = ""`, `prazo: str | None = None`, `modalidade: str = "indefinido"`, `valor_texto: str | None = None`, `url_anexo: str | None = None`, `publicado_em: str | None = None`.
  - `modelos.canonizar(url: str) -> str`
  - `modelos.id_oportunidade(fonte_id: str, url: str, titulo: str) -> str`
  - `oportunidades.salvar(con, fonte: dict, trilha: str, ops: list[Oportunidade]) -> tuple[list[str], list[str]]` — devolve `(ids_novas, ids_atualizadas)`.

Regra de atualização: item já visto cujo `prazo` ou `objeto` mudou entra em `ids_atualizadas` e tem `atualizado_em` reescrito. Mudança só de `titulo` não conta como atualização, porque o `id` já depende do título.

- [ ] **Step 1: Escrever o teste**

`tests/test_oportunidades.py`:

```python
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


def test_canonizar_url_lixo_vira_vazio():
    assert canonizar("   ") == ""
    assert canonizar("#") == ""
    assert canonizar("?") == ""
    assert canonizar("/") == ""


def test_canonizar_preserva_caminho_relativo():
    assert canonizar("/media/tdr.pdf") == "/media/tdr.pdf"


def test_id_nao_colide_com_url_lixo():
    assert id_oportunidade("wri-brasil", "   ", "Edital A") != id_oportunidade(
        "wri-brasil", "\t", "Edital B"
    )


def test_id_tolera_titulo_none():
    vazio = id_oportunidade("wri-brasil", "", None)
    assert vazio and vazio != id_oportunidade("wri-brasil", "", "Edital A")


def test_mesma_oportunidade_em_duas_trilhas_gera_um_registro(tmp_path):
    con = db.conectar(tmp_path / "t.sqlite")
    oportunidades.salvar(con, FONTE, "catalogo", [op()])
    oportunidades.salvar(con, FONTE, "gnews", [op()])
    assert con.execute("SELECT count(*) FROM oportunidades").fetchone()[0] == 1
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_oportunidades.py -v`
Expected: FAIL com `ImportError: cannot import name 'oportunidades'`

- [ ] **Step 3: Escrever `editais3s/modelos.py`**

```python
"""Oportunidade e identidade canônica."""
import hashlib
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PARAMS_LIXO = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid",
}


@dataclass
class Oportunidade:
    titulo: str
    objeto: str = ""
    url: str = ""
    prazo: str | None = None
    modalidade: str = "indefinido"
    valor_texto: str | None = None
    url_anexo: str | None = None
    publicado_em: str | None = None


def canonizar(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    partes = urlsplit(url)
    query = urlencode(
        [(k, v) for k, v in parse_qsl(partes.query) if k.lower() not in PARAMS_LIXO]
    )
    caminho = partes.path.rstrip("/") or "/"
    # URL lixo ("   ", "#", "?", "/") parseia para nada mas produziria "/", que e
    # truthy — id_oportunidade nao cairia no fallback do titulo e duas oportunidades
    # distintas da mesma fonte colidiriam no mesmo id. Caminho relativo real
    # ("/media/tdr.pdf") tem que sobreviver.
    if not partes.netloc and not query and caminho in ("", "/"):
        return ""
    return urlunsplit(
        (partes.scheme.lower(), partes.netloc.lower(), caminho, query, "")
    )


def id_oportunidade(fonte_id: str, url: str, titulo: str) -> str:
    chave = canonizar(url) or f"{fonte_id}|{(titulo or '').strip().lower()}"
    return hashlib.sha1(chave.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Escrever `editais3s/oportunidades.py`**

```python
"""Persistência e dedup de oportunidades."""
import sqlite3
from datetime import datetime, timezone

from .modelos import Oportunidade, id_oportunidade


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def salvar(
    con: sqlite3.Connection, fonte: dict, trilha: str, ops: list[Oportunidade]
) -> tuple[list[str], list[str]]:
    novas: list[str] = []
    atualizadas: list[str] = []
    agora = _agora()

    for o in ops:
        oid = id_oportunidade(fonte["id"], o.url, o.titulo)
        atual = con.execute(
            "SELECT prazo, objeto FROM oportunidades WHERE id=?", (oid,)
        ).fetchone()

        if atual is None:
            con.execute(
                """
                INSERT INTO oportunidades (
                  id, fonte_id, fonte_nome, trilha, titulo, objeto, url, url_anexo,
                  prazo, publicado_em, modalidade, valor_texto, visto_em, status
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'nova')
                """,
                (
                    oid, fonte["id"], fonte.get("nome"), trilha, o.titulo, o.objeto,
                    o.url, o.url_anexo, o.prazo, o.publicado_em, o.modalidade,
                    o.valor_texto, agora,
                ),
            )
            novas.append(oid)
            continue

        mudou = (atual["prazo"] or "") != (o.prazo or "") or (
            atual["objeto"] or ""
        ) != (o.objeto or "")
        if mudou:
            con.execute(
                """
                UPDATE oportunidades
                   SET prazo=?, objeto=?, modalidade=?, valor_texto=?,
                       url_anexo=?, atualizado_em=?
                 WHERE id=?
                """,
                (
                    o.prazo, o.objeto, o.modalidade, o.valor_texto, o.url_anexo,
                    agora, oid,
                ),
            )
            atualizadas.append(oid)

    con.commit()
    return novas, atualizadas
```

- [ ] **Step 5: Rodar e ver passar**

Run: `python -m pytest tests/test_oportunidades.py -v`
Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
git add editais3s/modelos.py editais3s/oportunidades.py tests/test_oportunidades.py
git commit -m "feat: modelo de oportunidade com id canonico e dedup"
```

---

### Task 6: Extração — LLM e fallback heurístico

**Files:**
- Create: `editais3s/extrai.py`, `tests/test_extrai.py`

**Interfaces:**
- Consumes: `config.MODELO_EXTRACAO`, `config.tem_api_key`, `modelos.Oportunidade`.
- Produces:
  - `extrai.SCHEMA` — JSON Schema do structured output.
  - `extrai.extrair(texto: str, fonte: dict, chamar=None) -> list[Oportunidade]` — usa `chamar` se passado (injeção para teste), senão decide entre LLM e heurística.
  - `extrai.heuristica(texto: str, fonte: dict) -> list[Oportunidade]`
  - `extrai.chamar_llm(texto: str, fonte: dict) -> dict`

`chamar` é uma callable `(texto: str, fonte: dict) -> dict` que devolve `{"oportunidades": [...]}`. URL relativa devolvida pelo modelo é resolvida com `urljoin` contra `fonte["url"]`.

- [ ] **Step 1: Escrever o teste**

`tests/test_extrai.py`:

```python
from editais3s import extrai

FONTE = {
    "id": "wri-brasil",
    "nome": "WRI Brasil",
    "tipo": "html",
    "url": "https://www.wribrasil.org.br/oportunidades",
}

TEXTO = """Oportunidades
[TdR FLWTDR-2026-011 Ouvidoria Restaura Biomas](/media/tdr-ouvidoria.pdf) Prazo: 13/07/2026
[Quem somos](/sobre)
[Chamada de propostas: plataforma de dados de restauracao](/editais/plataforma) Prazo: 20/08/2026
"""


def test_extrair_converte_payload_em_oportunidades():
    payload = {
        "oportunidades": [
            {
                "titulo": "TdR FLWTDR-2026-011 Ouvidoria Restaura Biomas",
                "objeto": "consultoria para implantacao de ouvidoria",
                "url": "/media/tdr-ouvidoria.pdf",
                "prazo": "2026-07-13",
                "modalidade": "tdr",
            }
        ]
    }
    ops = extrai.extrair(TEXTO, FONTE, chamar=lambda texto, fonte: payload)
    assert len(ops) == 1
    assert ops[0].titulo.startswith("TdR FLWTDR")
    assert ops[0].modalidade == "tdr"


def test_extrair_resolve_url_relativa():
    payload = {"oportunidades": [{"titulo": "T", "url": "/media/x.pdf"}]}
    ops = extrai.extrair(TEXTO, FONTE, chamar=lambda texto, fonte: payload)
    assert ops[0].url == "https://www.wribrasil.org.br/media/x.pdf"


def test_extrair_preserva_url_absoluta():
    payload = {"oportunidades": [{"titulo": "T", "url": "https://outro.org/x.pdf"}]}
    ops = extrai.extrair(TEXTO, FONTE, chamar=lambda texto, fonte: payload)
    assert ops[0].url == "https://outro.org/x.pdf"


def test_extrair_descarta_item_sem_titulo():
    payload = {"oportunidades": [{"titulo": "  ", "url": "/x"}, {"titulo": "Ok"}]}
    ops = extrai.extrair(TEXTO, FONTE, chamar=lambda texto, fonte: payload)
    assert [o.titulo for o in ops] == ["Ok"]


def test_extrair_com_payload_vazio():
    ops = extrai.extrair(TEXTO, FONTE, chamar=lambda texto, fonte: {"oportunidades": []})
    assert ops == []


def test_extrair_tolera_payload_malformado():
    ops = extrai.extrair(TEXTO, FONTE, chamar=lambda texto, fonte: {"lixo": 1})
    assert ops == []


def test_heuristica_pega_ancora_com_palavra_de_edital():
    ops = extrai.heuristica(TEXTO, FONTE)
    titulos = [o.titulo for o in ops]
    assert any("FLWTDR" in t for t in titulos)
    assert any("Chamada de propostas" in t for t in titulos)
    assert not any("Quem somos" in t for t in titulos)


def test_heuristica_resolve_url_relativa():
    ops = extrai.heuristica(TEXTO, FONTE)
    assert all(o.url.startswith("https://www.wribrasil.org.br/") for o in ops)


def test_extrair_sem_api_key_cai_na_heuristica(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ops = extrai.extrair(TEXTO, FONTE)
    assert ops and all(o.modalidade == "indefinido" for o in ops)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_extrai.py -v`
Expected: FAIL com `ImportError: cannot import name 'extrai'`

- [ ] **Step 3: Escrever `editais3s/extrai.py`**

```python
"""Texto de página -> lista de oportunidades.

Caminho principal: Haiku com structured output. Caminho de degradação: regex
sobre as âncoras já inlinadas por limpeza.limpar, quando não há
ANTHROPIC_API_KEY ou o SDK falha.
"""
import re
from urllib.parse import urljoin

from .config import MODELO_EXTRACAO, tem_api_key
from .modelos import Oportunidade

SCHEMA = {
    "type": "object",
    "properties": {
        "oportunidades": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "titulo": {"type": "string"},
                    "objeto": {"type": "string"},
                    "url": {"type": "string"},
                    "prazo": {"type": "string"},
                    "modalidade": {
                        "type": "string",
                        "enum": ["tdr", "chamada", "cotacao", "rfp", "indefinido"],
                    },
                    "valor_texto": {"type": "string"},
                },
                "required": ["titulo"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["oportunidades"],
    "additionalProperties": False,
}

INSTRUCAO = (
    "Você recebe o texto de uma página de um financiador de terceiro setor "
    "brasileiro (instituto, fundação ou ONG internacional). Extraia APENAS "
    "oportunidades de CONTRATAÇÃO DE FORNECEDOR: termo de referência, chamada "
    "de propostas, cotação, RFP, seleção de consultoria. NÃO extraia vaga de "
    "emprego, bolsa, prêmio, chamada de apoio a projeto de terceiros, nem "
    "notícia. Links aparecem no formato [texto](url) — devolva a url do link do "
    "próprio edital. Prazo em ISO AAAA-MM-DD quando houver data; omita se não "
    "houver. Se a página não tiver nenhuma oportunidade, devolva lista vazia."
)

RE_LINK = re.compile(r"\[([^\]]{4,200})\]\(([^)]+)\)")
RE_EDITAL = re.compile(
    r"edital|termo de refer|\btdr\b|chamada|cota[çc][ãa]o|\brfp\b|"
    r"request for proposal|sele[çc][ãa]o de consultor|consultoria",
    re.I,
)


def chamar_llm(texto: str, fonte: dict) -> dict:
    import anthropic

    cliente = anthropic.Anthropic()
    resposta = cliente.messages.create(
        model=MODELO_EXTRACAO,
        max_tokens=4096,
        system=INSTRUCAO,
        tools=[
            {
                "name": "registrar",
                "description": "Registra as oportunidades encontradas.",
                "input_schema": SCHEMA,
            }
        ],
        tool_choice={"type": "tool", "name": "registrar"},
        messages=[
            {
                "role": "user",
                "content": f"Fonte: {fonte['nome']}\n\n{texto}",
            }
        ],
    )
    for bloco in resposta.content:
        if getattr(bloco, "type", None) == "tool_use":
            return bloco.input
    return {"oportunidades": []}


def _monta(item: dict, fonte: dict) -> Oportunidade | None:
    titulo = (item.get("titulo") or "").strip()
    if not titulo:
        return None
    url = (item.get("url") or "").strip()
    if url and fonte.get("url"):
        url = urljoin(fonte["url"], url)
    return Oportunidade(
        titulo=titulo,
        objeto=(item.get("objeto") or "").strip(),
        url=url,
        prazo=(item.get("prazo") or "").strip() or None,
        modalidade=item.get("modalidade") or "indefinido",
        valor_texto=(item.get("valor_texto") or "").strip() or None,
    )


def heuristica(texto: str, fonte: dict) -> list[Oportunidade]:
    achados: list[Oportunidade] = []
    vistos: set[str] = set()
    for titulo, url in RE_LINK.findall(texto):
        titulo = titulo.strip()
        if not RE_EDITAL.search(titulo) or titulo in vistos:
            continue
        vistos.add(titulo)
        achados.append(
            _monta({"titulo": titulo, "url": url.strip()}, fonte)  # type: ignore[arg-type]
        )
    return [o for o in achados if o]


def extrair(texto: str, fonte: dict, chamar=None) -> list[Oportunidade]:
    if chamar is None:
        if not tem_api_key():
            return heuristica(texto, fonte)
        chamar = chamar_llm
    try:
        payload = chamar(texto, fonte)
    except Exception:
        return heuristica(texto, fonte)
    itens = payload.get("oportunidades") if isinstance(payload, dict) else None
    if not isinstance(itens, list):
        return []
    montadas = [_monta(i, fonte) for i in itens if isinstance(i, dict)]
    return [o for o in montadas if o]
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_extrai.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add editais3s/extrai.py tests/test_extrai.py
git commit -m "feat: extracao de oportunidades por LLM com fallback heuristico"
```

---

### Task 7: Escopo — Aho-Corasick e veto suave

**Files:**
- Create: `editais3s/escopo.py`, `tests/test_escopo.py`

**Interfaces:**
- Consumes: `config.SCORE_KW_MINIMO`.
- Produces:
  - `escopo.normalizar(texto: str) -> str`
  - `escopo.pontuar(texto: str) -> tuple[int, list[str]]`
  - `escopo.tem_veto(texto: str) -> bool`
  - `escopo.avaliar(texto: str) -> tuple[bool, int, list[str]]` — `(aprovado, score, temas)`

Regra do veto suave: reprova só quando há hit de veto **e** nenhum tema de peso ≥ 4. Aprovação também exige `score >= SCORE_KW_MINIMO`.

- [ ] **Step 1: Escrever o teste**

`tests/test_escopo.py`:

```python
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_escopo.py -v`
Expected: FAIL com `ImportError: cannot import name 'escopo'`

- [ ] **Step 3: Escrever `editais3s/escopo.py`**

Autômatos construídos uma vez no import, como em `pncp/monitor_pncp/scoring.py`.

```python
"""Dicionário de escopo NOTABC para terceiro setor.

Editado à mão conforme triagem. Marque cada lote com (triagem AAAA-MM-DD).
"""
import re
import unicodedata

import ahocorasick

from .config import SCORE_KW_MINIMO

TEMAS: dict[str, int] = {
    # peso 5 — núcleo do portfólio
    "plataforma de dados": 5,
    "ciencia de dados": 5,
    "engenharia de dados": 5,
    "arquitetura de dados": 5,
    "desenvolvimento web": 5,
    "visualizacao de dados": 5,
    # peso 4
    "dashboard": 4,
    "painel de dados": 4,
    "painel de indicadores": 4,
    "business intelligence": 4,
    "etl": 4,
    "pipeline de dados": 4,
    "geoespacial": 4,
    "geoprocessamento": 4,
    "sensoriamento remoto": 4,
    "mrv": 4,
    "monitoramento e avaliacao": 4,
    "ouvidoria": 4,
    "canal de denuncia": 4,
    "aprendizado de maquina": 4,
    "inteligencia artificial": 4,
    "portal web": 4,
    "aplicacao web": 4,
    "site institucional": 4,
    # peso 3
    "banco de dados": 3,
    "cms": 3,
    "wordpress": 3,
    "ux": 3,
    "design de interface": 3,
    "indicadores": 3,
    "lgpd": 3,
    "protecao de dados": 3,
    "api": 3,
    "integracao de sistemas": 3,
    "automacao": 3,
    "formulario de coleta": 3,
    "transparencia ativa": 3,
}

VETOS: tuple[str, ...] = (
    "vaga de emprego", "processo seletivo de colaborador", "banco de talentos",
    "bolsa de estudo", "bolsa de pesquisa", "premio",
    "chamada de projetos", "apoio a projetos", "edital de fomento",
    "obra", "reforma", "locacao", "servico grafico", "buffet", "coffee break",
    "passagem aerea", "producao de video", "assessoria de imprensa",
    "auditoria contabil", "consultoria juridica", "traducao simultanea",
)

PESO_FORTE = 4


def _automato(termos) -> ahocorasick.Automaton:
    a = ahocorasick.Automaton()
    for termo in termos:
        a.add_word(termo, termo)
    a.make_automaton()
    return a


_TEMAS = _automato(TEMAS)
_VETOS = _automato(VETOS)


def normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return sem_acento.lower()


def _com_fronteira(alvo: str, termo: str) -> bool:
    """O autômato casa substring ('api' dentro de 'rapido'). Confirma fronteira."""
    return re.search(rf"(?<!\w){re.escape(termo)}(?!\w)", alvo) is not None


def pontuar(texto: str) -> tuple[int, list[str]]:
    alvo = normalizar(texto)
    achados = {
        termo for _, termo in _TEMAS.iter(alvo) if _com_fronteira(alvo, termo)
    }
    ordenados = sorted(achados, key=lambda t: (-TEMAS[t], t))
    return sum(TEMAS[t] for t in ordenados), ordenados


def tem_veto(texto: str) -> bool:
    alvo = normalizar(texto)
    return any(_com_fronteira(alvo, termo) for _, termo in _VETOS.iter(alvo))


def avaliar(texto: str) -> tuple[bool, int, list[str]]:
    score, temas = pontuar(texto)
    forte = any(TEMAS[t] >= PESO_FORTE for t in temas)
    if tem_veto(texto) and not forte:
        return False, score, temas
    return score >= SCORE_KW_MINIMO, score, temas
```

O `iter` do `pyahocorasick` casa substring, e é por isso que `_com_fronteira` existe: sem ela, `"api"` pontuaria dentro de `"rapido"` e `"cms"` dentro de qualquer sigla. O autômato fica como pré-filtro O(n) e a regex confirma cada achado.

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_escopo.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add editais3s/escopo.py tests/test_escopo.py
git commit -m "feat: scoring de escopo por Aho-Corasick com veto suave"
```

---

### Task 8: Juiz LLM

**Files:**
- Create: `editais3s/juiz.py`, `tests/test_juiz.py`

**Interfaces:**
- Consumes: `config.MODELO_JUIZ`, `config.tem_api_key`.
- Produces:
  - `juiz.SCHEMA`
  - `juiz.PORTFOLIO` — string com o que a NOTABC entrega.
  - `juiz.julgar(itens: list[dict], chamar=None) -> list[dict]` — cada item de entrada tem `id`, `titulo`, `objeto`, `fonte_nome`; cada item de saída tem `id`, `score_llm`, `justificativa_llm`, `prazo`, `modalidade`, `modelo_llm`.
  - `juiz.aplicar(con, julgados: list[dict]) -> None` — grava no banco e ajusta `status`.

Uma chamada por execução com todos os itens do dia, como `googlerss/rotular.py` faz com os clusters. Item que o modelo não devolver fica com `score_llm = None` e entra no relatório como não julgado, nunca descartado em silêncio.

- [ ] **Step 1: Escrever o teste**

`tests/test_juiz.py`:

```python
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_juiz.py -v`
Expected: FAIL com `ImportError: cannot import name 'juiz'`

- [ ] **Step 3: Escrever `editais3s/juiz.py`**

```python
"""Score de aderência ao portfólio NOTABC, por LLM, em uma chamada por execução."""
import sqlite3

from .config import MODELO_JUIZ, SCORE_LLM_OLHAR, tem_api_key

SCHEMA = {
    "type": "object",
    "properties": {
        "avaliacoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "score": {"type": "integer"},
                    "justificativa": {"type": "string"},
                    "prazo": {"type": "string"},
                    "modalidade": {
                        "type": "string",
                        "enum": ["tdr", "chamada", "cotacao", "rfp", "indefinido"],
                    },
                },
                "required": ["id", "score", "justificativa"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["avaliacoes"],
    "additionalProperties": False,
}

PORTFOLIO = (
    "A NOTABC é uma consultoria pequena que entrega: plataforma e produto de "
    "dados ponta a ponta (pipeline, modelagem, painel), ciência de dados "
    "aplicada a política pública e socioambiental, site e portal institucional "
    "com arquitetura da informação e painel administrador próprio, análise "
    "geoespacial, e desenho de processo com normatização interna. Caso de "
    "referência: para o WRI Brasil entregou o site bilíngue do projeto Restaura "
    "Biomas (arquitetura da informação, acervo de relatórios, radar de notícias, "
    "painel administrador autônomo) e depois concorreu ao TdR de Ouvidoria "
    "Institucional do mesmo projeto. Não faz obra, não faz fornecimento de "
    "material, não coloca mão de obra terceirizada em posto de trabalho."
)

INSTRUCAO = (
    "Você avalia oportunidades de contratação captadas em sites de financiadores "
    "de terceiro setor. Para cada item, dê um score de 0 a 10 de aderência ao "
    "perfil abaixo e uma justificativa de UMA frase, factual, sem elogio. "
    "10 = objeto é exatamente o que a consultoria entrega. 0 = objeto sem "
    "nenhuma relação. Se o item for vaga de emprego, bolsa, prêmio ou apoio a "
    "projeto de terceiro, dê 0. Extraia também o prazo em AAAA-MM-DD e a "
    "modalidade, quando o texto permitir.\n\nPerfil:\n" + PORTFOLIO
)


def _bloco(itens: list[dict]) -> str:
    linhas = []
    for i in itens:
        linhas.append(
            f"id: {i['id']}\nfonte: {i.get('fonte_nome', '')}\n"
            f"titulo: {i.get('titulo', '')}\nobjeto: {i.get('objeto', '')}\n---"
        )
    return "\n".join(linhas)


def chamar_llm(itens: list[dict]) -> dict:
    import anthropic

    cliente = anthropic.Anthropic()
    resposta = cliente.messages.create(
        model=MODELO_JUIZ,
        max_tokens=4096,
        system=INSTRUCAO,
        tools=[
            {
                "name": "avaliar",
                "description": "Registra a avaliação de cada oportunidade.",
                "input_schema": SCHEMA,
            }
        ],
        tool_choice={"type": "tool", "name": "avaliar"},
        messages=[{"role": "user", "content": _bloco(itens)}],
    )
    for bloco in resposta.content:
        if getattr(bloco, "type", None) == "tool_use":
            return bloco.input
    return {"avaliacoes": []}


def julgar(itens: list[dict], chamar=None) -> list[dict]:
    if not itens:
        return []
    if chamar is None:
        if not tem_api_key():
            return [_vazio(i) for i in itens]
        chamar = chamar_llm

    try:
        payload = chamar(itens)
    except Exception:
        return [_vazio(i) for i in itens]

    avaliacoes = payload.get("avaliacoes") if isinstance(payload, dict) else None
    por_id = {}
    if isinstance(avaliacoes, list):
        for a in avaliacoes:
            if isinstance(a, dict) and a.get("id"):
                por_id[a["id"]] = a

    saida = []
    for i in itens:
        a = por_id.get(i["id"])
        if not a:
            saida.append(_vazio(i))
            continue
        score = a.get("score")
        score = None if not isinstance(score, int) else max(0, min(10, score))
        saida.append(
            {
                "id": i["id"],
                "score_llm": score,
                "justificativa_llm": (a.get("justificativa") or "").strip() or None,
                "prazo": (a.get("prazo") or "").strip() or None,
                "modalidade": a.get("modalidade"),
                "modelo_llm": MODELO_JUIZ,
            }
        )
    return saida


def _vazio(item: dict) -> dict:
    return {
        "id": item["id"],
        "score_llm": None,
        "justificativa_llm": None,
        "prazo": None,
        "modalidade": None,
        "modelo_llm": None,
    }


def aplicar(con: sqlite3.Connection, julgados: list[dict]) -> None:
    for j in julgados:
        score = j.get("score_llm")
        if score is None:
            status = "nova"
        elif score < SCORE_LLM_OLHAR:
            status = "descartada_llm"
        else:
            status = "reportada"
        con.execute(
            """
            UPDATE oportunidades
               SET score_llm=?, justificativa_llm=?, modelo_llm=?, status=?,
                   prazo=COALESCE(?, prazo),
                   modalidade=COALESCE(?, modalidade)
             WHERE id=?
            """,
            (
                score, j.get("justificativa_llm"), j.get("modelo_llm"), status,
                j.get("prazo"), j.get("modalidade"), j["id"],
            ),
        )
    con.commit()
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_juiz.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add editais3s/juiz.py tests/test_juiz.py
git commit -m "feat: juiz LLM de aderencia ao portfolio com aplicacao no banco"
```

---

### Task 9: Relatório Markdown

**Files:**
- Create: `editais3s/relatorio.py`, `tests/test_relatorio.py`

**Interfaces:**
- Consumes: `db`, `config.SCORE_LLM_ADERENTE`, `config.SCORE_LLM_OLHAR`, `config.PRAZO_APERTADO_DIAS`, `config.DIAS_SEM_ITEM_ALERTA`, `config.DIR_DADOS`.
- Produces:
  - `relatorio.gerar(con, data: str, execucao: dict | None = None) -> str`
  - `relatorio.escrever(con, data: str, execucao: dict | None = None) -> Path`

`data` no formato `AAAA-MM-DD`. Item entra no relatório do dia se `visto_em` ou `atualizado_em` começam com `data`. Cada linha carrega marcador `[ ]` para triagem manual.

- [ ] **Step 1: Escrever o teste**

`tests/test_relatorio.py`:

```python
from editais3s import db, relatorio

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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_relatorio.py -v`
Expected: FAIL com `ImportError: cannot import name 'relatorio'`

- [ ] **Step 3: Escrever `editais3s/relatorio.py`**

```python
"""Banco -> Markdown do dia."""
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import (
    DIAS_SEM_ITEM_ALERTA,
    DIR_DADOS,
    PRAZO_APERTADO_DIAS,
    SCORE_LLM_ADERENTE,
    SCORE_LLM_OLHAR,
)

CABECALHO_TABELA = (
    "| | Fonte | Título | Objeto | Prazo | Score | Por quê |\n"
    "|---|---|---|---|---|---|---|"
)


def _celula(valor) -> str:
    if valor is None:
        return ""
    return str(valor).replace("|", "/").replace("\n", " ").strip()


def _linha(o: sqlite3.Row) -> str:
    titulo = _celula(o["titulo"])
    url = _celula(o["url"])
    rotulo = f"[{titulo}]({url})" if url else titulo
    return (
        f"| [ ] | {_celula(o['fonte_nome'])} | {rotulo} | {_celula(o['objeto'])[:120]} "
        f"| {_celula(o['prazo'])} | {_celula(o['score_llm'])} "
        f"| {_celula(o['justificativa_llm'])} |"
    )


def _tabela(titulo: str, linhas: list[sqlite3.Row]) -> str:
    if not linhas:
        return ""
    corpo = "\n".join(_linha(o) for o in linhas)
    return f"## {titulo}\n\n{CABECALHO_TABELA}\n{corpo}\n"


def _do_dia(con: sqlite3.Connection, data: str) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT * FROM oportunidades
         WHERE (visto_em LIKE ? OR atualizado_em LIKE ?)
           AND status != 'descartada_llm'
           AND status != 'descartada_kw'
         ORDER BY COALESCE(score_llm, -1) DESC, prazo IS NULL, prazo
        """,
        (f"{data}%", f"{data}%"),
    ).fetchall()


def _prazo_apertado(o: sqlite3.Row, data: str) -> bool:
    if not o["prazo"]:
        return False
    try:
        prazo = datetime.strptime(o["prazo"], "%Y-%m-%d").date()
    except ValueError:
        return False
    hoje = date.fromisoformat(data)
    return hoje <= prazo <= hoje + timedelta(days=PRAZO_APERTADO_DIAS)


def _saude(con: sqlite3.Connection, data: str) -> str:
    linhas = []
    for s in con.execute(
        "SELECT fonte_id, erro, erros_seguidos FROM snapshots "
        "WHERE erro IS NOT NULL AND erros_seguidos > 0 ORDER BY erros_seguidos DESC"
    ):
        linhas.append(
            f"- `{s['fonte_id']}`: {s['erro']} ({s['erros_seguidos']} execuções seguidas)"
        )

    corte = (date.fromisoformat(data) - timedelta(days=DIAS_SEM_ITEM_ALERTA)).isoformat()
    for s in con.execute(
        """
        SELECT s.fonte_id, MAX(o.visto_em) AS ultimo
          FROM snapshots s LEFT JOIN oportunidades o ON o.fonte_id = s.fonte_id
         GROUP BY s.fonte_id
        HAVING ultimo IS NULL OR ultimo < ?
        """,
        (corte,),
    ):
        linhas.append(
            f"- `{s['fonte_id']}`: nenhum item há mais de {DIAS_SEM_ITEM_ALERTA} dias "
            "(possível parser cego ou seção movida)"
        )

    if not linhas:
        return ""
    return "## Saude\n\n" + "\n".join(linhas) + "\n"


def gerar(con: sqlite3.Connection, data: str, execucao: dict | None = None) -> str:
    itens = _do_dia(con, data)
    novas = [o for o in itens if (o["visto_em"] or "").startswith(data)]
    atualizadas = [o for o in itens if o not in novas]

    partes = [f"# Editais de terceiro setor — {data}\n"]

    if execucao:
        partes.append(
            "Fontes ok: {ok} · fontes com erro: {erro} · novas: {novas} · "
            "custo: US$ {custo:.2f}\n".format(
                ok=execucao.get("fontes_ok", 0),
                erro=execucao.get("fontes_erro", 0),
                novas=len(novas),
                custo=float(execucao.get("custo_usd") or 0.0),
            )
        )

    apertadas = [o for o in itens if _prazo_apertado(o, data)]
    aderentes = [
        o for o in novas
        if o["score_llm"] is not None and o["score_llm"] >= SCORE_LLM_ADERENTE
    ]
    olhar = [
        o for o in novas
        if o["score_llm"] is not None
        and SCORE_LLM_OLHAR <= o["score_llm"] < SCORE_LLM_ADERENTE
    ]
    nao_julgadas = [o for o in novas if o["score_llm"] is None]

    for titulo, grupo in (
        (f"Prazo apertado (≤ {PRAZO_APERTADO_DIAS} dias)", apertadas),
        ("Aderentes", aderentes),
        ("Olhar", olhar),
        ("Nao julgadas", nao_julgadas),
        ("Atualizadas", atualizadas),
    ):
        bloco = _tabela(titulo, grupo)
        if bloco:
            partes.append(bloco)

    if not itens:
        partes.append("Nenhuma oportunidade nova hoje.\n")

    saude = _saude(con, data)
    if saude:
        partes.append(saude)

    return "\n".join(partes)


def escrever(con: sqlite3.Connection, data: str, execucao: dict | None = None) -> Path:
    DIR_DADOS.mkdir(parents=True, exist_ok=True)
    caminho = DIR_DADOS / f"novas_{data}.md"
    caminho.write_text(gerar(con, data, execucao), encoding="utf-8")
    return caminho
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_relatorio.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add editais3s/relatorio.py tests/test_relatorio.py
git commit -m "feat: relatorio markdown diario com blocos de prazo e saude"
```

---

### Task 10: Pipeline, CLI e bootstrap

**Files:**
- Create: `editais3s/pipeline.py`, `editais3s/cli.py`, `editais3s/__main__.py`, `tests/test_pipeline.py`, `tests/test_cli.py`, `README.md`

**Interfaces:**
- Consumes: todos os módulos anteriores.
- Produces:
  - `pipeline.varrer(con, lista_fontes: list[dict], cliente, forcar: bool = False, usar_llm: bool = True, pausar=None) -> dict` — devolve `{"fontes_ok", "fontes_erro", "novas", "atualizadas", "ignoradas"}`.
  - `pipeline.diario(ids: list[str] | None = None, forcar: bool = False, usar_llm: bool = True) -> Path`
  - `pipeline.bootstrap(ids: list[str] | None = None, cliente=None) -> list[dict]`
  - `cli.construir_parser() -> argparse.ArgumentParser`, `cli.main(argv=None) -> int`

`pausar` é injetável para que o teste não durma: default é `time.sleep`, teste passa `lambda _: None`.

O funil roda dentro de `varrer`: para cada oportunidade extraída, `escopo.avaliar(titulo + objeto)` decide se vai ao juiz. Reprovada grava com `status='descartada_kw'` e não consome LLM.

- [ ] **Step 1: Escrever o teste do pipeline**

`tests/test_pipeline.py`:

```python
import httpx

from editais3s import db, pipeline

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
    titulos = [
        l["titulo"] for l in con.execute("SELECT titulo, status FROM oportunidades")
    ]
    assert any("TdR Ouvidoria" in t for t in titulos)
    descartadas = con.execute(
        "SELECT titulo FROM oportunidades WHERE status='descartada_kw'"
    ).fetchall()
    assert any("Vaga de emprego" in d["titulo"] for d in descartadas)


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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL com `ImportError: cannot import name 'pipeline'`

- [ ] **Step 3: Escrever `editais3s/pipeline.py`**

```python
"""Orquestra a varredura: coleta -> extração -> funil -> persistência -> relatório."""
import sqlite3
import time
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from . import coleta, db, escopo, extrai, fontes as cat, juiz, oportunidades, relatorio
from .config import INTERVALO_DOMINIO, TIMEOUT, UA

TRILHA = "catalogo"


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cliente() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, headers={"User-Agent": UA})


def varrer(
    con: sqlite3.Connection,
    lista_fontes: list[dict],
    cliente: httpx.Client,
    forcar: bool = False,
    usar_llm: bool = True,
    pausar=None,
) -> dict:
    pausar = time.sleep if pausar is None else pausar
    iniciado = _agora()
    resumo = {
        "fontes_ok": 0, "fontes_erro": 0, "novas": 0,
        "atualizadas": 0, "ignoradas": 0,
    }
    pendentes: list[dict] = []

    for i, fonte in enumerate(lista_fontes):
        if fonte["tipo"] != "html":
            resumo["ignoradas"] += 1
            continue
        if i:
            pausar(INTERVALO_DOMINIO)

        if not coleta.robots_permite(fonte, cliente):
            resumo["ignoradas"] += 1
            continue

        r = coleta.coletar(fonte, con, cliente, forcar=forcar)
        if not r.ok:
            resumo["fontes_erro"] += 1
            continue
        resumo["fontes_ok"] += 1
        if not r.mudou:
            resumo["ignoradas"] += 1
            continue

        ops = extrai.extrair(r.texto, fonte)
        novas, atualizadas = oportunidades.salvar(con, fonte, TRILHA, ops)
        resumo["novas"] += len(novas)
        resumo["atualizadas"] += len(atualizadas)

        for oid in novas + atualizadas:
            linha = con.execute(
                "SELECT id, titulo, objeto, fonte_nome FROM oportunidades WHERE id=?",
                (oid,),
            ).fetchone()
            aprovado, score_kw, temas = escopo.avaliar(
                f"{linha['titulo']} {linha['objeto'] or ''}"
            )
            con.execute(
                "UPDATE oportunidades SET score_kw=?, temas_kw=? WHERE id=?",
                (score_kw, ", ".join(temas), oid),
            )
            if aprovado:
                pendentes.append(dict(linha))
            else:
                con.execute(
                    "UPDATE oportunidades SET status='descartada_kw' WHERE id=?", (oid,)
                )
        con.commit()

    if usar_llm and pendentes:
        juiz.aplicar(con, juiz.julgar(pendentes))

    con.execute(
        """
        INSERT INTO execucoes (iniciado_em, terminado_em, fontes_ok, fontes_erro, novas)
        VALUES (?,?,?,?,?)
        """,
        (
            iniciado, _agora(), resumo["fontes_ok"], resumo["fontes_erro"],
            resumo["novas"],
        ),
    )
    con.commit()
    return resumo


def diario(
    ids: list[str] | None = None, forcar: bool = False, usar_llm: bool = True
) -> Path:
    con = db.conectar()
    lista = cat.filtrar(cat.carregar(), ids)
    with _cliente() as cliente:
        resumo = varrer(con, lista, cliente, forcar=forcar, usar_llm=usar_llm)
    hoje = date.today().isoformat()
    caminho = relatorio.escrever(con, hoje, execucao=resumo)
    print(
        f"{caminho}: {resumo['novas']} novas, {resumo['fontes_ok']} fontes ok, "
        f"{resumo['fontes_erro']} com erro, {resumo['ignoradas']} ignoradas"
    )
    return caminho


def bootstrap(ids: list[str] | None = None, cliente=None) -> list[dict]:
    """Confere a URL de cada fonte e relata o que precisa de ajuste manual."""
    lista = cat.filtrar(cat.carregar(), ids)
    fechar = cliente is None
    cliente = cliente or _cliente()
    achados = []
    try:
        for fonte in lista:
            if fonte["tipo"] != "html":
                achados.append({"id": fonte["id"], "situacao": "sem url (gnews)"})
                continue
            try:
                resp = cliente.get(
                    fonte["url"], headers={"User-Agent": UA}, follow_redirects=True
                )
                situacao = f"HTTP {resp.status_code}"
                final = str(resp.url)
            except httpx.HTTPError as exc:
                situacao = f"{type(exc).__name__}: {exc}"
                final = fonte["url"]
            achados.append(
                {"id": fonte["id"], "situacao": situacao, "url_final": final}
            )
    finally:
        if fechar:
            cliente.close()
    for a in achados:
        print(f"{a['id']}: {a['situacao']} {a.get('url_final', '')}")
    return achados
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: 5 passed

- [ ] **Step 5: Escrever o teste da CLI**

`tests/test_cli.py`:

```python
import pytest

from editais3s import cli


def test_parser_aceita_diario_com_fontes():
    args = cli.construir_parser().parse_args(
        ["diario", "--fontes", "wri-brasil,funbio", "--sem-llm", "--forcar"]
    )
    assert args.comando == "diario"
    assert args.fontes == "wri-brasil,funbio"
    assert args.sem_llm is True and args.forcar is True


def test_parser_aceita_relatorio_com_data():
    args = cli.construir_parser().parse_args(["relatorio", "--data", "2026-07-29"])
    assert args.comando == "relatorio" and args.data == "2026-07-29"


def test_parser_aceita_bootstrap():
    assert cli.construir_parser().parse_args(["bootstrap"]).comando == "bootstrap"


def test_sem_comando_retorna_erro():
    assert cli.main([]) == 2


def test_main_diario_chama_pipeline(monkeypatch):
    chamadas = {}

    def falso(ids=None, forcar=False, usar_llm=True):
        chamadas.update(ids=ids, forcar=forcar, usar_llm=usar_llm)
        return "caminho"

    monkeypatch.setattr(cli.pipeline, "diario", falso)
    assert cli.main(["diario", "--fontes", "wri-brasil", "--sem-llm"]) == 0
    assert chamadas == {"ids": ["wri-brasil"], "forcar": False, "usar_llm": False}
```

- [ ] **Step 6: Rodar e ver falhar**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL com `ImportError: cannot import name 'cli'`

- [ ] **Step 7: Escrever `editais3s/cli.py` e `editais3s/__main__.py`**

`editais3s/cli.py`:

```python
"""Entrypoint de linha de comando."""
import argparse
from datetime import date

from . import db, pipeline, relatorio


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="editais3s", description="Monitor de editais de terceiro setor")
    sub = p.add_subparsers(dest="comando")

    d = sub.add_parser("diario", help="varre o catalogo e escreve o relatorio do dia")
    d.add_argument("--fontes", help="ids separados por virgula")
    d.add_argument("--forcar", action="store_true", help="ignora o gate de hash")
    d.add_argument("--sem-llm", dest="sem_llm", action="store_true", help="so o funil de keyword")

    r = sub.add_parser("relatorio", help="regera o relatorio de uma data")
    r.add_argument("--data", default=date.today().isoformat())

    b = sub.add_parser("bootstrap", help="confere a url de cada fonte do catalogo")
    b.add_argument("--fontes", help="ids separados por virgula")

    return p


def _ids(valor: str | None) -> list[str] | None:
    return [i.strip() for i in valor.split(",") if i.strip()] if valor else None


def main(argv=None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)

    if not args.comando:
        parser.print_help()
        return 2

    if args.comando == "diario":
        pipeline.diario(
            ids=_ids(args.fontes), forcar=args.forcar, usar_llm=not args.sem_llm
        )
        return 0

    if args.comando == "relatorio":
        con = db.conectar()
        print(relatorio.escrever(con, args.data))
        return 0

    if args.comando == "bootstrap":
        pipeline.bootstrap(ids=_ids(args.fontes))
        return 0

    parser.print_help()
    return 2
```

`editais3s/__main__.py`:

```python
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 8: Rodar a suíte inteira**

Run: `python -m pytest -v`
Expected: 80 passed (3 db + 5 limpeza + 9 fontes + 10 coleta + 8 oportunidades + 9 extrai + 8 escopo + 7 juiz + 11 relatório + 5 pipeline + 5 cli)

- [ ] **Step 9: Escrever o `README.md`**

```markdown
# editais3s

Monitor diário de editais de terceiro setor: varre financiadores (INGO ambiental e
filantropia brasileira), extrai oportunidades de consultoria e escreve
`data/novas_AAAA-MM-DD.md` ordenado por aderência ao portfólio NOTABC.

Governo é coberto por outro projeto (`../pncp`).

## Instalar

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

## Usar

Sempre da raiz do repo.

```bash
python -m editais3s bootstrap                 # confere a URL de cada fonte
python -m editais3s diario                    # varredura do dia + relatorio
python -m editais3s diario --sem-llm          # so funil de keyword, sem custo de API
python -m editais3s diario --fontes wri-brasil --forcar
python -m editais3s relatorio --data 2026-07-29
```

`ANTHROPIC_API_KEY` no ambiente habilita extração e juiz por LLM. Sem a chave o
job roda com extração heurística e sem score, e o relatório avisa.

## Como funciona

`fontes.json` é o catálogo curado. Para cada fonte HTML: baixa, limpa para texto,
compara o hash com o snapshot anterior e só chama o LLM se a página mudou. As
oportunidades extraídas passam por `escopo.py` (Aho-Corasick) e o que sobra vai ao
juiz LLM, que dá score 0–10 e justificativa. Estado em `data/editais3s.sqlite`.

Design: `docs/specs/2026-07-29-editais3s-design.md`.
Plano do núcleo: `docs/plans/2026-07-29-editais3s-nucleo.md`.
```

- [ ] **Step 10: Rodar o check de dado sensível no relatório gerado**

Só faz sentido depois de um `diario` real. Registre o comando no README e rode uma vez:

Run: `python3 /config/workspace/scripts/check_sensivel.py data/novas_$(date +%F).md`
Expected: score < 40, exit 0. Fonte é pública, então o esperado é score baixo; se subir, o relatório está capturando dado de pessoa e precisa de anonimização antes de qualquer commit ou envio.

- [ ] **Step 11: Commit**

```bash
git add editais3s/pipeline.py editais3s/cli.py editais3s/__main__.py tests/test_pipeline.py tests/test_cli.py README.md
git commit -m "feat: pipeline diario, CLI e bootstrap do catalogo"
```

---

## Depois deste plano

Fase 3 (tier 2 no catálogo, trilha `gnews`, agregadores Devex e ReliefWeb), Fase 4 (`descoberta.py` mensal e trilha newsletter via Gmail) e Fase 5 (cron, unit systemd, `custos`, `saude`, `rotular_import`) ganham planos próprios. O primeiro `diario` real depende do `bootstrap`: as URLs do tier 1 entraram com `verificar: true` porque foram montadas a partir do padrão de cada domínio e ainda não foram confirmadas contra o site.
