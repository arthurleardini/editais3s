# Configurar a ANTHROPIC_API_KEY

Sem chave: extração cai na heurística, juiz desliga, relatório sai sem score e com aviso.

## Gravar

Chave em console.anthropic.com → API keys. Não colar em chat nem em arquivo versionado.

No Claude Code (prefixo `!` executa na sua sessão):

```
! umask 077; mkdir -p ~/.config; read -rsp "cole a key: " K && printf 'ANTHROPIC_API_KEY=%s\n' "$K" > ~/.config/editais3s.env && unset K && chmod 600 ~/.config/editais3s.env && echo ok
```

## Usar

```bash
set -a; . ~/.config/editais3s.env; set +a
cd /config/workspace/editais3s
.venv/bin/python -m editais3s diario
```

No `~/.bashrc`:

```bash
[ -f ~/.config/editais3s.env ] && { set -a; . ~/.config/editais3s.env; set +a; }
```

## Verificar

```bash
.venv/bin/python -c "from editais3s.config import tem_api_key; print(tem_api_key())"
stat -c '%a %n' ~/.config/editais3s.env
```

`True` e `600`.

## Primeira rodada

Gate de hash pula página não modificada, então sem `--forcar` a primeira rodada com chave não
chama LLM nenhum:

```bash
.venv/bin/python -m editais3s diario --forcar
```

## Cron (Fase 5)

```ini
[Service]
EnvironmentFile=/config/.config/editais3s.env
ExecStart=/config/workspace/editais3s/.venv/bin/python -m editais3s diario
WorkingDirectory=/config/workspace/editais3s
```

## Notas

- Arquivo sem `export`: formato que o `EnvironmentFile` exige e que o shell usa via `set -a`.
- Shell não-interativo não lê `~/.bashrc`. Variável exportada só na sessão do terminal não
  alcança agente nem cron.
- `tem_api_key()` só lê `ANTHROPIC_API_KEY`. Profile OAuth (`ant auth login`) faria o SDK
  funcionar e o nosso código rodar degradado em silêncio — use a variável.
- `MODELO_JUIZ` está em `claude-haiku-4-5`. É o juiz que decide qual edital sobe; trocar para
  `claude-sonnet-5` é uma linha em `config.py` e o custo segue trivial nesse volume.
