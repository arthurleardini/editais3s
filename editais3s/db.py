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
