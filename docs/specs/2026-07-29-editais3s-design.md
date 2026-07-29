# Spec — editais3s: monitor de editais de terceiro setor

Data: 2026-07-29
Status: aprovado para plano de implementação
Repo: `/config/workspace/editais3s/` (standalone, Python 3 + SQLite)

---

## 1. Problema

A NOTABC ganhou entrada no WRI Brasil por um TdR (FLWTDR-2026-011, Ouvidoria do Restaura Biomas) que só apareceu porque alguém viu a página do WRI na hora certa. Editais desse perfil têm prazo curto, o do WRI deu doze dias entre publicação e submissão original, e não passam por nenhum canal que a gente já monitora.

O monitor de PNCP (`/config/workspace/pncp/`) resolve o lado governo: existe API única, formato padronizado, 27 UFs. Terceiro setor não tem equivalente. Cada financiador publica onde quer: página de "oportunidades", página de "transparência", post no blog, PDF solto, newsletter. Não há API nem padrão de URL ou de nome de seção. Layout muda sem aviso.

Resultado hoje: descoberta por acaso e por rede pessoal. Editais aderentes ao portfólio (plataforma de dados, ciência de dados, desenvolvimento de site/portal) passam sem ser vistos.

## 2. Objetivo

Um job diário que varre financiadores de terceiro setor brasileiro, extrai oportunidades de contratação de consultoria, pontua aderência ao portfólio NOTABC e entrega um `.md` com as novas do dia, ordenado por aderência, com prazo em destaque.

Critério de sucesso: um edital do perfil do WRI Ouvidoria aparece no relatório do dia em que é publicado, sem que ninguém precise abrir site nenhum.

## 3. Escopo

**Dentro:**

- Filantropia brasileira (institutos e fundações que contratam consultoria).
- INGO ambiental com operação no Brasil.
- Objeto de interesse: plataforma de dados, ciência de dados, engenharia de dados, painel/dashboard, desenvolvimento de site e portal, geoespacial, MRV, monitoramento e avaliação, ouvidoria e canal de denúncia, automação, integração de sistemas.

**Fora (decisão explícita, não esquecimento):**

- Multilateral e ONU (UNGM, PNUD, Banco Mundial, BID). Volume alto e formato padronizado, daria pra tratar como fonte tipo API depois, mas fica fora da primeira versão.
- Filantropia internacional (Ford, Open Society, Hewlett, Mozilla). Lógica é de grant, não de licitação, e o funil de decisão é outro.
- Governo em qualquer esfera, já coberto pelo PNCP.
- Kanban web de triagem. A entrega é `.md`. O banco guarda o rótulo manual, mas a interface é o arquivo.
- Geração de proposta e submissão. O monitor para na descoberta.

## 4. Arquitetura

Repo novo, sem dependência de código do `pncp/`. Reaproveita ideias que já funcionam nos dois projetos existentes (catálogo em JSON como o `googlerss/portais.json`, Aho-Corasick sobre dicionário de escopo, rótulo manual realimentando o dicionário), sem importar módulo.

```
editais3s/
  fontes.json                # catálogo curado
  fontes_candidatas.json     # fila de aprovação da descoberta automática
  editais3s/
    __main__.py  cli.py  config.py
    coleta.py                # fetch por fonte
    limpeza.py               # HTML -> texto
    extrai.py                # texto -> oportunidades (LLM)
    escopo.py                # dicionário Aho-Corasick
    juiz.py                  # scoring LLM + justificativa
    gnews.py                 # trilha de padrão textual
    agregadores.py           # Devex / ReliefWeb
    newsletter.py            # label Gmail (opcional, degradável)
    descoberta.py            # job mensal de fontes novas
    db.py  modelos.py
    relatorio.py
  data/
    editais3s.sqlite
    novas_AAAA-MM-DD.md
  tests/fixtures/            # HTML salvo por fonte
  cron_diario.sh
  systemd/
```

### 4.1 Decisão central: extração genérica por LLM, não seletor por site

Escrever CSS selector para quarenta financiadores é manutenção infinita: cada troca de tema WordPress quebra um parser, e o sintoma é silencioso (zero itens, que parece "nada novo hoje").

Fluxo por fonte:

1. `coleta.py` baixa a página.
2. `limpeza.py` converte para texto: `selectolax`, remove `nav`/`header`/`footer`/`script`/`style`, colapsa espaço, preserva o texto de âncora junto do `href` no formato `[texto](url)`. Corta em 40 000 caracteres.
3. Hash SHA-1 do texto limpo. Se igual ao snapshot anterior da fonte, encerra ali, com custo zero de LLM. Esse gate é o que torna o job barato.
4. Se mudou, `extrai.py` manda o texto ao Haiku com structured output e recebe uma lista de oportunidades.

Fonte com RSS ou JSON nativo salta a etapa de LLM. Fonte marcada `js: true` no catálogo é buscada com Playwright antes da limpeza.

Ganho: layout novo não quebra a extração, e o custo real cai para o punhado de páginas que mudou de verdade no dia.

### 4.2 Catálogo (`fontes.json`)

Mesma forma do `googlerss/portais.json`, com `_meta` documentando escopo e tiers.

```json
{
  "id": "wri-brasil",
  "nome": "WRI Brasil",
  "tipo": "html",
  "dominio": "wribrasil.org.br",
  "url": "https://www.wribrasil.org.br/oportunidades",
  "tier": 1,
  "js": false,
  "verificar": true,
  "nota": "Origem do TdR FLWTDR-2026-011 (Ouvidoria Restaura Biomas). Publica TdR em PDF linkado na página."
}
```

`tipo ∈ html | rss | json | gnews`. `verificar: true` marca URL que ainda não foi confirmada; o comando `bootstrap` (§6) resolve antes de a fonte entrar em produção.

Tier 1 (INGO ambiental e fundo ambiental, alta chance de contratar consultoria de dados):
WRI Brasil, Funbio, WWF-Brasil, The Nature Conservancy Brasil, Conservação Internacional Brasil, IPAM, Imazon, Instituto Socioambiental, Fundação Amazônia Sustentável, Instituto Escolhas, Instituto Talanoa, SOS Mata Atlântica, Observatório do Clima, Fundo Casa Socioambiental.

Tier 2 (filantropia BR):
Itaú Social, Fundação Lemann, Fundação Grupo Boticário, Instituto Arapyaú, Instituto Clima e Sociedade (iCS), Instituto Ibirapitanga, Instituto Serrapilheira, Fundação Tide Setubal, Fundação Banco do Brasil, Instituto Unibanco, Fundação Maria Cecília Souto Vidigal, Instituto Alana, Fundação Telefônica Vivo, Fundo Baobá, Movimento Bem Maior, GIFE, ABONG.

Nenhuma URL de página de oportunidade entra no catálogo sem passar pelo `bootstrap`. As que não tiverem seção própria de oportunidade ficam como `tipo: gnews`, cobertas pela trilha de padrão textual.

### 4.3 Funil de relevância, dois passos

**Passo 1: `escopo.py`, Aho-Corasick sobre texto normalizado** (minúscula, sem acento). Barato, roda em tudo.

Temas com peso:

| Peso | Termos |
|---|---|
| 5 | plataforma de dados, ciência de dados, engenharia de dados, desenvolvimento web, visualização de dados, arquitetura de dados |
| 4 | dashboard, painel de dados, business intelligence, ETL, pipeline de dados, geoespacial, geoprocessamento, sensoriamento remoto, MRV, monitoramento e avaliação, ouvidoria, canal de denúncia, aprendizado de máquina, inteligência artificial, portal web, aplicação web |
| 3 | banco de dados, CMS, WordPress, UX, design de interface, indicadores, LGPD, proteção de dados, API, integração de sistemas, automação, formulário de coleta, transparência ativa |

Veto suave (não é kill duro): vaga de emprego, processo seletivo de colaborador, bolsa, prêmio, chamada de projetos socioambientais, apoio a projetos, obra, reforma, locação, serviço gráfico, catering, passagem aérea, produção de vídeo, assessoria de imprensa, auditoria contábil, consultoria jurídica, tradução.

Regra: item com hit de veto **e** nenhum tema de peso ≥ 4 é descartado. Com tema forte presente, segue para o juiz. No PNCP a kill list é veto duro; aqui o volume é baixo o suficiente para pagar o risco de falso negativo com uma chamada de LLM.

`SCORE_KW_MINIMO = 4` para passar ao passo 2.

**Passo 2: `juiz.py`, LLM com o portfólio NOTABC no prompt.** Devolve `score` 0–10, `justificativa` em uma frase, `prazo` normalizado e `modalidade`. O prompt carrega um resumo do que a NOTABC entrega, incluindo o caso WRI (site bilíngue do Restaura Biomas, acervo, radar de notícias, painel administrador) como referência de fit.

Faixas: `score ≥ 6` entra no bloco principal do relatório; `4–5` vai para o bloco "olhar"; `< 4` fica gravado no banco e fora do relatório.

Todo item pontuado guarda `modelo_llm`, então quando o modelo mudar dá para reprocessar sem confundir safras.

### 4.4 Trilhas de descoberta

Quatro trilhas diárias buscam oportunidade, mais um job mensal que busca fonte nova para o catálogo.

| Trilha | Módulo | Cadência | Papel |
|---|---|---|---|
| Catálogo curado | `coleta.py` | diária | Base. Determinístico, cobre quem já conhecemos. |
| Padrão textual | `gnews.py` | diária | Pega edital de fonte fora do catálogo. |
| Agregador | `agregadores.py` | diária | Devex e ReliefWeb por feed. |
| Newsletter | `newsletter.py` | diária, opcional | Label Gmail `editais3s`. |
| Fonte nova | `descoberta.py` | mensal | Propõe entradas em `fontes_candidatas.json`. |

**Padrão textual.** Queries no RSS do Google News, no molde do `googlerss/ingest.py`:

- `"termo de referência" consultoria (plataforma de dados OR ciência de dados)`
- `"chamada de propostas" consultoria dados site:org.br`
- `"seleção de consultoria" painel OR dashboard OR plataforma`
- `edital OR TdR consultoria "desenvolvimento de site" instituto OR fundação`
- `"request for proposals" consultoria dados Brasil`

Ruído alto e esperado. O funil do §4.3 é o que segura.

**Newsletter.** Você cria um filtro no Gmail que aplica a label `editais3s` em remetente de financiador. `newsletter.py` lê essa label via MCP Gmail. Limitação real: em execução headless por cron o MCP claude.ai pode não estar disponível. Nesse caso a trilha registra `indisponivel` no relatório e o job segue, sem exceção e sem job quebrado.

**Fonte nova.** Job mensal: um agente busca na web financiador brasileiro do nicho que ainda não esteja no catálogo, confere se tem página de oportunidade e grava candidata em `fontes_candidatas.json` com nome, URL, evidência e justificativa. Nada entra em `fontes.json` sem sua aprovação. O catálogo continua curado à mão, e a automação só enche a fila.

## 5. Modelo de dados

SQLite em `data/editais3s.sqlite`.

```sql
CREATE TABLE snapshots (
  fonte_id TEXT PRIMARY KEY,
  hash TEXT, coletado_em TEXT, http_status INTEGER,
  bytes INTEGER, erro TEXT, erros_seguidos INTEGER DEFAULT 0
);

CREATE TABLE oportunidades (
  id TEXT PRIMARY KEY,           -- sha1(url canônica) ou sha1(fonte_id + slug(titulo))
  fonte_id TEXT, fonte_nome TEXT, trilha TEXT,   -- catalogo|gnews|agregador|newsletter
  titulo TEXT, objeto TEXT, url TEXT, url_anexo TEXT,
  prazo TEXT, publicado_em TEXT,
  modalidade TEXT,               -- tdr|chamada|cotacao|rfp|indefinido
  valor_texto TEXT,
  visto_em TEXT, atualizado_em TEXT, hash_conteudo TEXT,
  score_kw INTEGER, temas_kw TEXT,
  score_llm INTEGER, justificativa_llm TEXT, modelo_llm TEXT,
  status TEXT                    -- nova|reportada|descartada_kw|descartada_llm
);

CREATE TABLE triagem (
  oportunidade_id TEXT, rotulo TEXT,   -- aderente|nao_aderente|talvez
  nota TEXT, rotulado_em TEXT
);

CREATE TABLE execucoes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  iniciado_em TEXT, terminado_em TEXT,
  fontes_ok INTEGER, fontes_erro INTEGER, novas INTEGER,
  tokens_in INTEGER, tokens_out INTEGER, custo_usd REAL
);
```

Dedup por `id`. Reaparição de oportunidade já vista atualiza `atualizado_em` e `hash_conteudo`; se prazo ou objeto mudarem, o relatório do dia lista em bloco "atualizadas". Prorrogação de prazo é informação útil, e o TdR do WRI foi prorrogado.

`triagem` é alimentada por `rotular_import`, lendo o `.md` do relatório onde você marcou os itens. O rótulo serve para ajustar `escopo.py` e o prompt do juiz, com o mesmo hábito de comentário `(triagem AAAA-MM-DD)` que o `pncp/monitor_pncp/escopo.py` já usa.

## 6. CLI

Entrypoint `python -m editais3s`, rodado da raiz do repo.

| Comando | Função |
|---|---|
| `bootstrap [--fontes a,b]` | Resolve e valida URL de cada fonte marcada `verificar`. Testa HTTP, detecta se precisa de JS, sugere `tipo`, grava de volta em `fontes.json`. |
| `diario [--fontes a,b] [--sem-llm] [--forcar]` | Pipeline completo do dia. `--forcar` ignora o hash gate. `--sem-llm` roda só o funil de keyword. |
| `gnews [--dias 2]` | Só a trilha de padrão textual. |
| `descobrir` | Job mensal de fonte nova. |
| `relatorio --data AAAA-MM-DD` | Regera o `.md` a partir do banco. |
| `rotular_import --md <path>` | Importa rótulo manual do relatório. |
| `custos [--mes AAAA-MM]` | Tokens e gasto por execução. |
| `saude` | Fontes com erro acumulado e fontes sem item há muito tempo. |

## 7. Relatório

`data/novas_AAAA-MM-DD.md`:

1. **Cabeçalho** — data, fontes varridas, fontes com erro, quantas mudaram, novas encontradas, custo da execução.
2. **Prazo apertado** — tudo com prazo em até dez dias, independente de score. Perder prazo é o pior modo de falha.
3. **Aderentes** (`score_llm ≥ 6`) — tabela: fonte, título, objeto em uma linha, prazo, score, link, justificativa do juiz.
4. **Olhar** (`score_llm` 4–5) — mesma tabela, mais enxuta.
5. **Atualizadas** — já vistas, com mudança de prazo ou objeto.
6. **Saúde** — fonte que falhou, fonte sem item há mais de sessenta dias (sinal de parser cego ou seção movida), trilhas indisponíveis.

Cada linha traz um marcador `[ ]` para você rotular no próprio arquivo; `rotular_import` lê de volta.

## 8. Degradação e limites

O job diário nunca aborta por causa de uma fonte.

- Fonte com erro: registra, incrementa `erros_seguidos`, segue. Três execuções seguidas com erro viram linha no bloco Saúde.
- Sem `ANTHROPIC_API_KEY`: extração cai para heurística de regex sobre âncora (`edital|termo de referência|chamada|cotação|RFP|TdR|consultoria`), juiz desliga, relatório sai com aviso no cabeçalho. Mesmo padrão de fallback gracioso do `googlerss/rotular.py`.
- MCP Gmail ausente: trilha newsletter marcada indisponível.
- Playwright ausente: fonte `js: true` marcada indisponível, o resto roda.

Boa vizinhança de rede: UA identificável, `robots.txt` respeitado, um request por segundo por domínio, concorrência global 6, timeout 20 s, duas tentativas com backoff.

## 9. Custo

Página limpa de financiador dá algo em torno de 8–12 mil tokens. Com quarenta fontes e Haiku, o pior caso, todas mudando todo dia, fica perto de US$ 0,40/dia na extração. O hash gate deve cortar a maior parte disso, porque página de oportunidade de instituto muda pouco. Juiz roda em dezenas de itens por semana, uns 2 mil tokens cada. Estimativa de regime: abaixo de US$ 5/mês. `custos` mede o real em vez de confiar na estimativa.

## 10. Testes

O `pncp/` não tem suíte, e aqui vale ter, porque o ponto frágil é o par limpeza/extração.

- `tests/fixtures/` guarda HTML real por fonte, capturado no `bootstrap`.
- Limpeza: fixture → texto esperado, sem `nav`/`footer`, âncoras preservadas.
- Hash gate: mesma página duas vezes faz zero chamada de LLM.
- Dedup: mesma oportunidade em duas trilhas gera um registro.
- Escopo: caso do WRI Ouvidoria pontua acima do mínimo; vaga de emprego e chamada de projeto são descartadas.
- Extração: fixture com LLM mockado, valida contrato do structured output.
- Relatório: snapshot do `.md` a partir de banco semeado.

## 11. Fases

| Fase | Entrega |
|---|---|
| 1 | `bootstrap` + catálogo tier 1 validado + coleta HTML + hash gate + extração LLM + banco + relatório mínimo. Ponta a ponta em quatorze fontes. |
| 2 | `escopo.py` + juiz + relatório completo com blocos de prazo e saúde. |
| 3 | Tier 2 no catálogo + trilha `gnews` + agregadores. |
| 4 | `descoberta.py` mensal + trilha newsletter Gmail. |
| 5 | `cron_diario.sh` + unit systemd + `custos` + `saude`. |

Fase 1 já é útil sozinha: catorze INGO ambientais varridas todo dia é mais cobertura do que existe hoje.

## 12. Riscos

- **Financiador sem página de oportunidade.** Vários publicam edital em post de blog ou só na newsletter. Mitigação: `gnews` e newsletter cobrem; `bootstrap` marca a fonte como `tipo: gnews` quando não acha seção própria.
- **Parser cego.** Fonte que para de retornar item parece "nada novo". Mitigação: bloco Saúde acusa fonte sem item há mais de sessenta dias.
- **Bloqueio por Cloudflare.** Já aconteceu no `googlerss` com o Intercept. Mitigação: cair para Google News naquela fonte.
- **Ruído do padrão textual.** Aceito por desenho; o funil de dois passos absorve.
- **PDF.** Muito TdR vive em PDF linkado. Primeira versão extrai da página de listagem e guarda `url_anexo` sem abrir. Baixar e ler o PDF fica para depois; `pncp/monitor_pncp/arquivos.py` já resolve esse problema e serve de referência quando chegar a hora.
