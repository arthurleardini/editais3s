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

Como gravar a chave, verificar, e usar no cron: `docs/configurar-api-key.md`.

## Como funciona

`fontes.json` é o catálogo curado. Para cada fonte HTML: baixa, limpa para texto,
compara o hash com o snapshot anterior e só chama o LLM se a página mudou. As
oportunidades extraídas passam por `escopo.py` (Aho-Corasick) e o que sobra vai ao
juiz LLM, que dá score 0–10 e justificativa. Estado em `data/editais3s.sqlite`.

Design: `docs/specs/2026-07-29-editais3s-design.md`.
Plano do núcleo: `docs/plans/2026-07-29-editais3s-nucleo.md`.
