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
from .llm import LLM


def _args(argv):
    p = argparse.ArgumentParser(
        prog="farejador",
        description="Descobre canais do YouTube parecidos com um canal de referência (via yt-dlp).",
        epilog="Toda opção também pode vir de variável de ambiente FAREJADOR_<NOME>, ex.: FAREJADOR_PAUSA=4.",
    )
    p.add_argument("canal", help="@handle, ID (UC...) ou URL do canal de referência")
    padrao = Config()
    for f in fields(Config):
        nome = f"--{f.name.replace('_', '-')}"
        valor = getattr(padrao, f.name)
        if isinstance(valor, bool):
            p.add_argument(nome, action="store_true", default=None)
        else:
            p.add_argument(nome, type=type(valor), default=None, help=f"padrão: {valor!r}")
    return p.parse_args(argv)


def _corta(t, n):
    t = t or ""
    return t if len(t) <= n else t[: n - 1] + "…"


def tabela(candidatos, top):
    com_llm = any(c.get("nota_llm") is not None for c in candidatos)
    cab_llm = f"{'final':>5}  {'llm':>4}  " if com_llm else ""
    linhas = [f"{'#':>3}  {cab_llm}{'score':>5}  {'nome':<32}  {'@handle / ID':<26}  url"]
    linhas.append("-" * (110 + len(cab_llm)))
    recuo = " " * (12 + len(cab_llm))
    for i, c in enumerate(candidatos[:top], 1):
        ident = c.get("handle") or c["channel_id"]
        nota = c.get("nota_llm")
        col_llm = (f"{c['score_final']:>5.1f}  {('-' if nota is None else f'{nota:g}'):>4}  " if com_llm else "")
        linhas.append(f"{i:>3}  {col_llm}{c['score']:>5}  {_corta(c.get('nome'), 32):<32}  "
                      f"{_corta(ident, 26):<26}  {c['url']}")
        linhas.append(f"{recuo}por quê: {c['motivo']}")
        if nota is not None:
            linhas.append(f"{recuo}LLM {nota:g}/10: {c['justificativa_llm']}")
    return "\n".join(linhas)


def _resumo(r, cfg):
    ref = r["referencia"]
    print(f"\nReferência: {ref['nome']} ({ref['handle'] or ref['channel_id']}) — {ref['videos_lidos']} vídeos lidos, "
          f"{ref['videos_com_detalhes']} com detalhes, {ref['videos_com_tags']} com tags")
    print(f"Termos ignorados: {', '.join(r['termos_ignorados']) or '(nenhum)'}")
    fmt = lambda xs: ", ".join(f"{x['termo']} ({x['videos']})" for x in xs) or "(nenhuma)"  # noqa: E731
    print(f"Palavras-chave (nº de vídeos): {fmt(r['palavras_chave'])}")
    print(f"Frases (nº de vídeos): {fmt(r['frases'])}")
    print("Buscas: " + " | ".join(f"[{c['origem']}] {c['consulta']}" for c in r["consultas"]))
    d = r["destaques"]
    print(f"Canais em destaque: {len(d['canais'])} (fonte: {d['fonte'] or 'nenhuma'})")
    m = r["mencoes"]
    print(f"Menções: {m['links_encontrados']} canais citados em {m['descricoes_lidas']} descrições, "
          f"{m['validados']} validados, {len(m['invalidos'])} inválidos, {len(m['ignorados'])} ignorados")
    rm = r["removidos"]
    print(f"Removidos: {rm['proprio']} próprio, {rm['exclusao']} da exclusão, {rm['ruido']} automáticos "
          f"(Topic/VEVO), {rm['inativo']} inativos (> {cfg.dias_ativo} dias)")
    f = r["fracos"]
    if f["total"]:
        detalhe = ", ".join(f"{n} só {s}" for s, n in f["por_sinal"].items() if n)
        print(f"Fracos (< {cfg.min_sinais} sinais): {f['total']} ({detalhe})"
              + ("" if cfg.mostrar_fracos else " — ocultos, use --mostrar-fracos"))
    print(f"Requisições: {r['requisicoes']['rede']} na rede, {r['requisicoes']['cache']} do cache")
    lm = r["llm"]
    if lm["ligado"]:
        print(f"LLM: {lm['modelo']} — {lm['consultas']} consultas geradas, {lm['avaliados']} candidatos avaliados, "
              f"peso {lm['peso']:g} na ordem final")
    else:
        print("LLM: desligado (modo determinístico)")
    if cfg.verbose:
        print("\nCusto por etapa:")
        for e in r["etapas"]:
            llm_txt = f"  {e['llm']:>3} LLM  {e['llm_cache']:>3} LLM do cache" if "llm" in e else ""
            print(f"  {e['etapa']:<32} {e['rede']:>4} na rede  {e['cache']:>4} do cache  {e['segundos']:>7.1f} s{llm_txt}")
        for ig in m["ignorados"]:
            print(f"  menção ignorada: {ig['canal']} — {ig['motivo']}")
        for inv in m["invalidos"]:
            print(f"  menção inválida (yt-dlp não resolveu): {inv}")
        for nome in r["inativos"]:
            print(f"  inativo removido: {nome}")
        print(f"  avisos do yt-dlp nesta execução: {r['requisicoes']['avisos_ytdlp']} (texto na tabela eventos)")
    for aviso in r["avisos"]:
        print(f"AVISO: {aviso}")


def main(argv=None):
    a = _args(argv)
    cfg = Config.from_env()
    for f in fields(Config):
        v = getattr(a, f.name)
        if v is not None:
            setattr(cfg, f.name, v)

    cache = Cache(cfg.caminho("dados") / "farejador.db", cfg.cache_horas)
    coletor = Coletor(cfg, cache)
    llm = LLM(cfg, cache)
    exclusoes = ler_exclusoes(cfg.caminho("exclude"))

    def log(m, detalhe=False):
        if cfg.verbose or not detalhe:
            print(f"· {m}", file=sys.stderr, flush=True)

    try:
        r = descobrir(a.canal, cfg, coletor, exclusoes, log=log, llm=llm)
    except BloqueioYouTube as e:
        print(f"\nO YouTube bloqueou as requisições (anti-bot/limite). Parei para não piorar.\n"
              f"Mensagem: {e}\nTente mais tarde ou aumente FAREJADOR_PAUSA. "
              f"Detalhes na tabela 'eventos' de {cfg.caminho('dados') / 'farejador.db'}.", file=sys.stderr)
        return 2
    except (ErroCanal, ValueError) as e:
        print(f"\nErro: {e}", file=sys.stderr)
        return 1

    _resumo(r, cfg)
    print()
    print(tabela(r["candidatos"], cfg.top) if r["candidatos"] else
          f"Nenhum candidato com {cfg.min_sinais}+ sinais independentes.")
    if cfg.mostrar_fracos and r["candidatos_fracos"]:
        print(f"\nFracos (menos de {cfg.min_sinais} sinais):")
        print(tabela(r["candidatos_fracos"], cfg.top))

    saida = cfg.caminho("saida")
    saida.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(r['candidatos'])} candidatos gravados em {saida}")
    if cfg.salvar_bruto:
        print(f"Retorno cru do yt-dlp em {cfg.caminho('dados') / 'bruto'}")
    return 0
