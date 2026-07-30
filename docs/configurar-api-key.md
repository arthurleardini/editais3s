# Configurar a ANTHROPIC_API_KEY

O `editais3s` roda sem chave de API, mas degradado: a extração cai numa heurística de regex
sobre o texto das âncoras e o juiz LLM desliga, então nenhum item recebe score. O relatório
avisa isso no cabeçalho. Para a operação real a chave é necessária.

## Onde pegar

console.anthropic.com → **API keys**.

## Gravar a chave

**Não cole a chave em chat, em prompt de agente, nem em arquivo versionado.** O comando abaixo
lê a chave sem ecoar na tela e grava com permissão restrita ao seu usuário:

```bash
umask 077
mkdir -p ~/.config
read -rsp "cole a key: " K \
  && printf 'export ANTHROPIC_API_KEY=%s\n' "$K" > ~/.config/editais3s.env \
  && unset K \
  && chmod 600 ~/.config/editais3s.env \
  && echo "gravado em ~/.config/editais3s.env"
```

`umask 077` garante que o arquivo nasça sem permissão para grupo e outros; o `chmod 600` é
redundante de propósito.

## Usar

```bash
. ~/.config/editais3s.env
cd /config/workspace/editais3s
.venv/bin/python -m editais3s diario
```

Para valer em toda sessão interativa, acrescente ao `~/.bashrc`:

```bash
[ -f ~/.config/editais3s.env ] && . ~/.config/editais3s.env
```

## Verificar sem imprimir a chave

```bash
.venv/bin/python -c "from editais3s.config import tem_api_key; print(tem_api_key())"
```

Deve imprimir `True`. Para conferir que o pipeline saiu do modo degradado, rode um `diario` e
confirme que a linha de aviso **não** aparece no cabeçalho do `.md`:

```
> Aviso: rodada sem juiz LLM (--sem-llm ou ANTHROPIC_API_KEY ausente).
```

## Cron e systemd (Fase 5)

O cron não lê `~/.bashrc`. A chave precisa entrar no ambiente da unit:

```ini
[Service]
EnvironmentFile=/config/.config/editais3s.env
ExecStart=/config/workspace/editais3s/.venv/bin/python -m editais3s diario
WorkingDirectory=/config/workspace/editais3s
```

O `EnvironmentFile` do systemd espera `CHAVE=valor` sem `export`. Se for usar o mesmo arquivo
para shell e systemd, grave sem o `export` e use `set -a` no shell:

```bash
set -a; . ~/.config/editais3s.env; set +a
```

## Duas ressalvas do nosso código

### `tem_api_key()` só olha a variável de ambiente

O SDK da Anthropic aceita mais de uma forma de credencial, nesta ordem: `ANTHROPIC_API_KEY`,
depois `ANTHROPIC_AUTH_TOKEN`, depois um profile OAuth criado por `ant auth login` (guardado em
`~/.config/anthropic/`), depois Workload Identity Federation.

`editais3s/config.py` implementa só a primeira:

```python
def tem_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
```

Consequência: se você autenticar por profile OAuth, o SDK funcionaria mas o nosso código acharia
que não há chave. `extrai.extrair` iria direto para a heurística, `juiz.julgar` devolveria tudo
sem score, e o relatório sairia com o aviso de rodada degradada — tudo isso sem erro nenhum, que
é o modo de falha silencioso que o projeto tenta evitar.

Se quiser suportar profile, `tem_api_key` precisa também aceitar `ANTHROPIC_AUTH_TOKEN` e a
existência de um profile em `~/.config/anthropic/`. Enquanto isso não acontecer, **use a variável
de ambiente**, não `ant auth login`.

### Escolha de modelo por etapa

`config.py` usa Haiku nas duas etapas:

```python
MODELO_EXTRACAO = "claude-haiku-4-5"
MODELO_JUIZ = "claude-haiku-4-5"
```

Para a extração isso está certo: é a etapa de volume, roda em toda página que mudou, e o trabalho
é mecânico — achar candidatos num texto.

Para o juiz vale reconsiderar. É ele que decide qual edital sobe ao topo do relatório e qual é
descartado, roda em dezenas de itens por semana, e o custo de um erro dele é um edital perdido.
Trocar para um modelo mais capaz é uma linha e, nesse volume, mantém o custo mensal irrelevante:

```python
MODELO_JUIZ = "claude-sonnet-5"   # ou "claude-opus-5"
```

O campo `modelo_llm` da tabela `oportunidades` guarda qual modelo pontuou cada item, então trocar
o modelo não confunde safras antigas de score.

## Higiene

- `~/.config/editais3s.env` fica fora do repo. Não versione a chave.
- `data/` está no `.gitignore` — banco e relatórios não vão para o git.
- Se a chave vazar, revogue no console antes de qualquer outra coisa; rotacionar é barato.
- Nada de chave em `fontes.json`, em prompt de sistema ou em mensagem de usuário: o prompt vai
  para a API e fica no histórico da execução.
