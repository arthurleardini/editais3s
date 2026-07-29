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
