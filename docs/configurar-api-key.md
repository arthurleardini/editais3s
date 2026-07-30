# Configurar a ANTHROPIC_API_KEY

Sem chave: extração cai na heurística, juiz desliga, relatório sai sem score e com aviso.

## Gravar

Chave em console.anthropic.com → API keys.

**Este passo tem que ser feito num terminal de verdade, fora de sessão de agente.** Comando
disparado por agente não tem TTY: editor interativo e `read` falham com
`Standard input is not a terminal`. E chave digitada em chat fica no transcript.

**Nunca ponha a chave numa linha de comando** — fica no histórico do shell.

Cria o arquivo vazio, com permissão restrita:

```bash
umask 077
mkdir -p ~/.config
printf 'ANTHROPIC_API_KEY=\n' > ~/.config/editais3s.env
chmod 600 ~/.config/editais3s.env
```

Preenche o valor no editor:

```bash
nano ~/.config/editais3s.env
```

Cola a chave imediatamente depois do `=`, sem espaço e sem aspas. Salvar: `Ctrl+O`, `Enter`,
`Ctrl+X`.

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
