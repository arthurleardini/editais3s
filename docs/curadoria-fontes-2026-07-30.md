# Curadoria de fontes — 2026-07-30

Cinco levantamentos com verificação por fetch. Regra usada: só entra URL que foi aberta, que
lista **vários** itens e cujos títulos foram citados como prova. Chute não entra.

## O discriminador que mais importa

`contrata` (a organização contrata fornecedor) versus `so_fomento` (ela repassa dinheiro para
projeto de terceiro). Sete das dezesseis fundações brasileiras publicam **apenas** fomento. Sem
essa distinção o catálogo encheria de edital que nunca vira contrato para a NOTABC.

## O erro sistemático do catálogo original

As catorze fontes foram escritas de memória, com o padrão `/oportunidades` e `/editais` chutado
para todo mundo. Onze das catorze estavam erradas. O padrão real do setor é **`/trabalhe-conosco`
com uma seção de consultoria dentro da página de vagas**.

## Entram — verificadas, `contrata`, HTML puro

| id | URL | nota |
|---|---|---|
| `wri-brasil` | `https://www.wribrasil.org.br/trabalhe-conosco` | corrige 404. Seção "Oportunidades de consultoria", 15+ TdRs. A fonte que originou o projeto |
| `tnc-brasil` | `https://www.tnc.org.br/conecte-se/trabalhe-conosco/` | corrige 404. Consultoria separada das vagas. Tem "Análises Geoespaciais e Design da Informação" aberto |
| `isa` | `https://www.socioambiental.org/vagas-e-editais` | corrige 404. Quatro consultorias abertas, rotatividade semanal |
| `ci-brasil` | `https://brasil.conservation.org/oportunidades` | canônico do redirect. Seis TdRs, um deles de desenvolvimento de plataforma |
| `abong` | `https://abong.org.br/editais/` | **nova**. Único achado `contrata` do tier 2. Seleções de consultoria desde 2019 |
| `undp-procurement` | `https://procurement-notices.undp.org/search.cfm?order_by=cty_sht_t` | **nova**. Agregador global filtrável por país, atualização diária |
| `unesco-brasilia` | `https://compras.brasilia.unesco.org/` | **nova**. Republica editais de dezenas de projetos |
| `c40-cities` | `https://www.c40.org/work-with-c40/` | **nova**. RFP de mapeamento de risco e dados climáticos; item de Salvador confirmado |
| `jica-brasil` | `https://www.jica.go.jp/portuguese/overseas/brazil/information/topics/index.html` | **nova**. Histórico de licitação de SAR e IA para desmatamento |

## Entram via navegador — bloqueio ou JavaScript

| id | URL | motivo |
|---|---|---|
| `wwf-brasil` | `https://www.wwf.org.br/sobrenos/aquisicoesecontratacoes/` | 403 de WAF no domínio inteiro, inclusive no `robots.txt` e no feed. Decisão do dono |
| `ungm` | UNGM, filtro Brasil | tabela só popula via JavaScript. Sem bloqueio — caso legítimo de render |
| `banco-mundial` | `https://projects.worldbank.org/en/projects-operations/procurement` | idem, "Loading…" no HTML cru |

## Entram como `gnews` — não têm página de listagem

`ipam`, `imazon`, `escolhas`, `sos-mata-atlantica`, `talanoa`, `observatorio-do-clima`, `gife`,
`fundacao-lemann`.

Os TdRs existem e são reais, mas vivem como PDF avulso em `wp-content`, post no meio do feed de
notícias, sistema de RH terceirizado ou LinkedIn. `gife` e `fundacao-lemann` dão 403 e não foram
verificáveis; o sinal de busca do GIFE é forte ("GIFE contrata consultoria para desenvolver
estudo de caso"), mas não foi certificado.

## Saem — só fomento

`fundo-casa`, `itau-social`, `ics-clima-sociedade`, `instituto-serrapilheira`,
`fundacao-tide-setubal`, `instituto-unibanco`, `fundo-baoba`, `movimento-bem-maior`.

Todas têm página boa e ativa. Nenhuma contrata fornecedor — repassam dinheiro para projeto de
terceiro. Manter qualquer uma delas é ruído garantido.

## Ficam de fora por ora, com motivo

- `funbio` — a URL catalogada é feed de notícias; a listagem real é `chamadas.funbio.org.br`, mas
  é sobretudo fomento. Os TdRs de consultoria ficam soltos em `wp-content`, sem índice.
- `fas` — listagem correta encontrada, mas é fomento (editais REM MT). Consultoria corre por
  `fas-amazonia.factorialhr.com`, que é ATS, outro tipo de fonte.
- `fundacao-bb` — licitação formal sob a Lei 13.303, ativa, mas majoritariamente compras gerais.
- `fao-brasil` — página boa, mas os prazos visíveis são de meados de 2025. Parece parada.
- `climateworks` — RFP real de estudo comissionado, mas é URL de busca, e nada específico do Brasil.
- `plan-international-brasil` — só dois itens ativos.
- `rockefeller` — tem RFP de fornecedor de verdade, inclusive de M&A, mas não existe página índice.

## Becos sem saída confirmados

Prosas e Mapa das OSC (maiores agregadores de edital do terceiro setor no Brasil, mas só fomento
e carregam por JS), Fundo Vale, Fiocruz Farmanguinhos, Avante Social, GIZ, IDB, UNICEF, ONU
Mulheres, PAHO, UNODC, OIT, CAF, AFD, KfW, FCDO, Norad. Filantropia internacional é quase toda
fomento por convite, sem página pública de RFP.

## Lição de ritmo

O IPAM passou a recusar conexão depois de poucas requisições seguidas. O intervalo de 1s por
domínio que já está no código precisa ser respeitado, e vale considerar backoff por fonte.
