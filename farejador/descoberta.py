"""Pipeline de descoberta: canal de referência -> palavras-chave -> buscas -> candidatos ranqueados."""
import time
from datetime import datetime, timezone

from . import busca, palavras, ranking
from .canais import chaves_do_canal, url_base


class ErroCanal(RuntimeError):
    pass


def _url_canal(c):
    if c.get("handle"):
        return f"https://www.youtube.com/{c['handle']}"
    return f"https://www.youtube.com/channel/{c['channel_id']}"


def _destaques(coletor, base, dono, avisos, log):
    """Tenta a aba "Canais"; se não houver, a aba inicial (prateleira de canais em destaque)."""
    tentativas = [("aba Canais", f"{base}/channels"), ("aba Início", f"{base}/featured")]
    vistos = set()
    while tentativas:
        fonte, url = tentativas.pop(0)
        if url in vistos:
            continue
        vistos.add(url)
        log(f"lendo canais em destaque ({fonte})…")
        r = coletor.destaques(url)
        if r is None:
            avisos.append(f"{fonte} ({url}) indisponível pelo yt-dlp.")
            continue
        canais = [c for c in r["canais"] if c["channel_id"] != dono]
        if canais:
            return fonte, canais
        if r["links"]:  # prateleira que só aponta para outra página de canais
            tentativas.insert(0, (f"{fonte} → link da prateleira", r["links"][0]))
        else:
            avisos.append(f"{fonte} não trouxe nenhum canal.")
    avisos.append("Sem canais em destaque: o bônus de destaque não foi aplicado a ninguém.")
    return None, []


def descobrir(entrada, cfg, coletor, exclusoes=frozenset(), agora=None, log=lambda m: None):
    agora = agora or time.time()
    avisos = []
    base = url_base(entrada)

    log(f"lendo os últimos {cfg.videos_referencia} vídeos de {base}…")
    ref = coletor.canal(base, cfg.videos_referencia)
    if not ref or not ref.get("channel_id"):
        raise ErroCanal(f"não consegui ler o canal {entrada!r} (veja a tabela eventos no SQLite)")
    videos = [dict(v, tags=[]) for v in ref["videos"]]
    if not videos:
        avisos.append("O canal de referência não retornou vídeos na aba Vídeos.")

    # tags só vêm na extração completa do vídeo; limitado para não martelar o YouTube
    com_tags = 0
    for v in videos[: cfg.detalhes_videos]:
        log(f"detalhes do vídeo {v['id']}…")
        d = coletor.video(v["id"])
        if d:
            v["tags"] = d["tags"]
            com_tags += bool(d["tags"])
    if cfg.detalhes_videos and not com_tags:
        avisos.append("Nenhuma tag obtida dos vídeos: palavras-chave vieram só de títulos e tags do canal.")

    fonte_destaque, destaques = _destaques(coletor, base, ref["channel_id"], avisos, log)

    unigramas, frases = palavras.extrair(
        videos, ref["tags"], ref["descricao"], ignorar=[ref.get("nome") or "", ref.get("handle") or ""])
    consultas = busca.montar_consultas(unigramas, frases, cfg.max_buscas)
    if not consultas:
        avisos.append("Não sobrou palavra-chave útil para buscar (títulos muito curtos ou genéricos?).")

    resultados = []
    for i, q in enumerate(consultas, 1):
        log(f"busca {i}/{len(consultas)}: {q!r}")
        resultados.append((q, coletor.buscar(q, cfg.resultados_por_busca) or []))
    candidatos = busca.agregar(resultados)

    for d in destaques:
        c = candidatos.setdefault(d["channel_id"], {
            "channel_id": d["channel_id"], "nome": d.get("nome"), "handle": d.get("handle"),
            "consultas": [], "videos": [], "timestamps": [],
        })
        c["destaque"] = True
        c["handle"] = c["handle"] or d.get("handle")

    # filtros: o próprio canal, a lista de exclusão e canais automáticos
    proprio = chaves_do_canal(ref["channel_id"], ref.get("handle"))
    removidos = {"proprio": 0, "exclusao": 0, "ruido": 0}
    lista = []
    for c in candidatos.values():
        c.setdefault("destaque", False)
        k = chaves_do_canal(c["channel_id"], c.get("handle"))
        if k & proprio:
            removidos["proprio"] += 1
        elif k & set(exclusoes):
            removidos["exclusao"] += 1
        elif ranking.eh_ruido(c.get("nome")):
            removidos["ruido"] += 1
        else:
            lista.append(c)

    # atividade: datas aproximadas dos resultados; se não bastar, olha a aba Vídeos do candidato
    total = len(consultas)
    for c in lista:
        c["atividade"] = ranking.atividade(c["timestamps"], cfg.dias_ativo, agora)
        ranking.pontuar(c, total, cfg.dias_ativo)
    pendentes = [c for c in ranking.ordenar(lista) if c["atividade"] != "ativo"][: cfg.verificar_atividade]
    for c in pendentes:
        log(f"checando atividade de {c.get('nome') or c['channel_id']}…")
        info = coletor.canal(f"https://www.youtube.com/channel/{c['channel_id']}", 5)
        if info:
            c["handle"] = c.get("handle") or info.get("handle")
            c["nome"] = c.get("nome") or info.get("nome")
            c["seguidores"] = info.get("seguidores")
            c["atividade"] = ranking.atividade([v["timestamp"] for v in info["videos"]], cfg.dias_ativo, agora)

    for c in lista:
        ranking.pontuar(c, total, cfg.dias_ativo)
        c["url"] = _url_canal(c)
    lista = ranking.ordenar(lista)

    return {
        "gerado_em": datetime.fromtimestamp(agora, timezone.utc).isoformat(timespec="seconds"),
        "referencia": {
            "entrada": entrada, "channel_id": ref["channel_id"], "nome": ref.get("nome"),
            "handle": ref.get("handle"), "videos_lidos": len(videos), "videos_com_tags": com_tags,
            "tags_do_canal": ref["tags"],
        },
        "palavras_chave": [u["termo"] for u in unigramas],
        "frases": [f["termo"] for f in frases],
        "consultas": consultas,
        "destaques": {"fonte": fonte_destaque, "canais": [d.get("nome") for d in destaques]},
        "removidos": removidos,
        "avisos": avisos,
        "requisicoes": {"rede": coletor.requisicoes, "cache": coletor.acertos_cache},
        "candidatos": [
            {k: c.get(k) for k in ("nome", "handle", "channel_id", "url", "score", "motivo",
                                   "atividade", "destaque", "consultas", "videos", "seguidores")}
            for c in lista
        ],
    }
