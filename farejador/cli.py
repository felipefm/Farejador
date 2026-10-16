"""CLI: python farejador.py <canal>"""
import argparse
import json
import sys
from dataclasses import fields

from .cache import Cache
from .canais import ler_exclusoes
from .coleta import BloqueioYouTube, Coletor
from .config import Config
from .descoberta import ErroCanal, descobrir


def _args(argv):
    p = argparse.ArgumentParser(
        prog="farejador",
        description="Descobre canais do YouTube parecidos com um canal de referência (via yt-dlp).",
        epilog="Toda opção também pode vir de variável de ambiente FAREJADOR_<NOME>, ex.: FAREJADOR_PAUSA=4.",
    )
    p.add_argument("canal", help="@handle, ID (UC...) ou URL do canal de referência")
    padrao = Config()
    for f in fields(Config):
        p.add_argument(f"--{f.name.replace('_', '-')}", type=type(getattr(padrao, f.name)), default=None,
                       help=f"padrão: {getattr(padrao, f.name)}")
    return p.parse_args(argv)


def _corta(t, n):
    t = t or ""
    return t if len(t) <= n else t[: n - 1] + "…"


def tabela(candidatos, top):
    linhas = [f"{'#':>3}  {'score':>5}  {'nome':<32}  {'@handle / ID':<26}  url"]
    linhas.append("-" * 110)
    for i, c in enumerate(candidatos[:top], 1):
        ident = c.get("handle") or c["channel_id"]
        linhas.append(f"{i:>3}  {c['score']:>5}  {_corta(c.get('nome'), 32):<32}  {_corta(ident, 26):<26}  {c['url']}")
        linhas.append(f"{'':>12}por quê: {c['motivo']}")
    return "\n".join(linhas)


def main(argv=None):
    a = _args(argv)
    cfg = Config.from_env()
    for f in fields(Config):
        v = getattr(a, f.name)
        if v is not None:
            setattr(cfg, f.name, v)

    cache = Cache(cfg.caminho("dados") / "farejador.db", cfg.cache_horas)
    coletor = Coletor(cfg, cache)
    exclusoes = ler_exclusoes(cfg.caminho("exclude"))
    log = lambda m: print(f"· {m}", file=sys.stderr, flush=True)  # noqa: E731

    try:
        r = descobrir(a.canal, cfg, coletor, exclusoes, log=log)
    except BloqueioYouTube as e:
        print(f"\nO YouTube bloqueou as requisições (anti-bot/limite). Parei para não piorar.\n"
              f"Mensagem: {e}\nTente mais tarde ou aumente FAREJADOR_PAUSA. "
              f"Detalhes na tabela 'eventos' de {cfg.caminho('dados') / 'farejador.db'}.", file=sys.stderr)
        return 2
    except (ErroCanal, ValueError) as e:
        print(f"\nErro: {e}", file=sys.stderr)
        return 1

    ref = r["referencia"]
    print(f"\nReferência: {ref['nome']} ({ref['handle'] or ref['channel_id']}) — "
          f"{ref['videos_lidos']} vídeos lidos, {ref['videos_com_tags']} com tags")
    print(f"Palavras-chave: {', '.join(r['palavras_chave']) or '(nenhuma)'}")
    print(f"Frases: {', '.join(r['frases']) or '(nenhuma)'}")
    print(f"Buscas: {' | '.join(r['consultas'])}")
    d = r["destaques"]
    print(f"Canais em destaque: {len(d['canais'])} (fonte: {d['fonte'] or 'nenhuma'})")
    rm = r["removidos"]
    print(f"Removidos: {rm['proprio']} próprio, {rm['exclusao']} da exclusão, {rm['ruido']} automáticos (Topic/VEVO)")
    print(f"Requisições: {r['requisicoes']['rede']} na rede, {r['requisicoes']['cache']} do cache")
    for aviso in r["avisos"]:
        print(f"AVISO: {aviso}")
    print()
    print(tabela(r["candidatos"], cfg.top) if r["candidatos"] else "Nenhum candidato encontrado.")

    saida = cfg.caminho("saida")
    saida.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(r['candidatos'])} candidatos gravados em {saida}")
    return 0
