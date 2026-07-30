# Configurar a ANTHROPIC_API_KEY

O `editais3s` roda sem chave de API, mas degradado: a extração cai numa heurística de regex
sobre o texto das âncoras e o juiz LLM desliga, então nenhum item recebe score. O relatório
avisa isso no cabeçalho. Para a operação real a chave é necessária.

## Onde pegar

console.anthropic.com → **API keys**.

## Gravar a chave

**Não cole a chave em chat, em prompt de agente, nem em arquivo versionado.**

Exportar a variável na sua sessão de terminal **não basta**: ela morre quando o terminal fecha, e
não alcança processo nenhum disparado por um agente ou pelo cron. A chave tem que estar num
arquivo. O comando abaixo lê sem ecoar na tela e grava com permissão restrita ao seu usuário.

Dentro do Claude Code, cole com o prefixo `!`, que executa na sua própria sessão:

```
! umask 077; mkdir -p ~/.config; read -rsp "cole a key: " K && printf 'ANTHROPIC_API_KEY=%s\n' "$K" > ~/.config/editais3s.env && unset K && chmod 600 ~/.config/editais3s.env && echo ok
```

Num terminal comum é o mesmo, quebrado em linhas:

```bash
umask 077
mkdir -p ~/.config
read -rsp "cole a key: " K \
  && printf 'ANTHROPIC_API_KEY=%s\n' "$K" > ~/.config/editais3s.env \
  && unset K \
  && chmod 600 ~/.config/editais3s.env \
  && echo ok
```

Três detalhes que não são acidentais:

- **`umask 077`** faz o arquivo nascer sem permissão para grupo e outros. O `chmod 600` depois é
  redundante de propósito, para o caso de o arquivo já existir com permissão frouxa.
- **`read -rsp`** não ecoa o que você digita, então a chave não fica no scrollback do terminal.
  O `-r` evita que barra invertida seja interpretada.
- **`ANTHROPIC_API_KEY=...` sem `export`.** É o formato que o `EnvironmentFile` do systemd exige,
  e o shell também consegue usar (ver abaixo). Um arquivo só serve os dois casos.

## Usar

O arquivo não tem `export`, então carregue com `set -a`, que exporta automaticamente tudo que for
atribuído entre o `-a` e o `+a`:

```bash
set -a; . ~/.config/editais3s.env; set +a
cd /config/workspace/editais3s
.venv/bin/python -m editais3s diario
```

Para valer em toda sessão interativa, acrescente ao `~/.bashrc`:

```bash
[ -f ~/.config/editais3s.env ] && { set -a; . ~/.config/editais3s.env; set +a; }
```

Atenção: shell **não-interativo** não lê `~/.bashrc`. Se um agente ou script disparar o job e
reclamar que falta a chave, é isso — carregue o arquivo explicitamente no comando, como no bloco
acima, em vez de confiar no `.bashrc`.

## Verificar sem imprimir a chave

```bash
.venv/bin/python -c "from editais3s.config import tem_api_key; print(tem_api_key())"
```

Deve imprimir `True`. Para conferir que o pipeline saiu do modo degradado, rode um `diario` e
confirme que a linha de aviso **não** aparece no cabeçalho do `.md`:

```
> Aviso: rodada sem juiz LLM (--sem-llm ou ANTHROPIC_API_KEY ausente).
```

Se quiser inspecionar o arquivo sem revelar o valor:

```bash
stat -c '%a %n' ~/.config/editais3s.env   # deve ser 600
cut -d= -f1 ~/.config/editais3s.env        # imprime so o nome da variavel
```

## Cron e systemd (Fase 5)

O cron não lê `~/.bashrc`. A chave entra pelo ambiente da unit:

```ini
[Service]
EnvironmentFile=/config/.config/editais3s.env
ExecStart=/config/workspace/editais3s/.venv/bin/python -m editais3s diario
WorkingDirectory=/config/workspace/editais3s
```

É por isso que o arquivo foi gravado sem `export`: o `EnvironmentFile` espera `CHAVE=valor` puro
e falha se encontrar `export`.

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

## Primeira rodada depois de configurar

O gate de hash guarda o hash da última coleta de cada fonte. Se as páginas já foram coletadas numa
rodada anterior sem chave, um `diario` normal vê hash igual, pula a extração e faz **zero** chamada
de LLM — o relatório sai vazio e parece que a chave não funcionou. Para forçar o caminho completo
na primeira rodada com chave:

```bash
set -a; . ~/.config/editais3s.env; set +a
.venv/bin/python -m editais3s diario --forcar
```

Isso gasta crédito de API e faz requisição a todos os financiadores do catálogo.

## Higiene

- `~/.config/editais3s.env` fica fora do repo. Não versione a chave.
- `data/` está no `.gitignore` — banco e relatórios não vão para o git.
- Se a chave vazar, revogue no console antes de qualquer outra coisa; rotacionar é barato.
- Nada de chave em `fontes.json`, em prompt de sistema ou em mensagem de usuário: o prompt vai
  para a API e fica no histórico da execução.
