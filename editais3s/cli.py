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
