"""Pipeline de descoberta: canal de referência -> palavras-chave/menções -> buscas -> candidatos ranqueados."""
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from . import busca, mencoes, palavras, ranking
from .canais import chaves_do_canal, url_base


class ErroCanal(RuntimeError):
    pass


def _url_canal(c):
    if c.get("handle"):
        return f"https://www.youtube.com/{c['handle']}"
    return f"https://www.youtube.com/channel/{c['channel_id']}"


def _novo(cid, nome=None, handle=None):
    return {"channel_id": cid, "nome": nome, "handle": handle, "consultas": [], "videos": [],
            "timestamps": [], "mencoes": 0, "destaque": False, "verificado": False}


class Etapas:
    """Custo de cada etapa: requisições na rede, acertos de cache e tempo."""

    def __init__(self, coletor, relogio=time.monotonic):
        self.coletor, self.relogio, self.lista = coletor, relogio, []

    @contextmanager
    def medir(self, nome):
        r0, c0, t0 = self.coletor.requisicoes, self.coletor.acertos_cache, self.relogio()
        try:
            yield
        finally:
            self.lista.append({"etapa": nome, "rede": self.coletor.requisicoes - r0,
                               "cache": self.coletor.acertos_cache - c0,
                               "segundos": round(self.relogio() - t0, 1)})


def _diagnostico_aba(fonte, url, r, erro):
    """Diferencia aba que falhou, aba vazia e aba que veio sem canais. Retorna (estado, texto)."""
    if r is None:
        return "falhou", f"{fonte}: FALHOU no yt-dlp ({(erro or 'sem mensagem').strip()[:160]})."
    tipos = ", ".join(f"{n} {t}" for t, n in sorted(r.get("tipos", {}).items())) or "nada"
    nao_lidos = [a for a in r.get("avisos_ytdlp", []) if "unsupported" in a.lower()]
    extra = (f" O yt-dlp avisou que ignorou itens que não sabe ler ({len(nao_lidos)} aviso(s)): "
             "o YouTube pode ter canais ali que o yt-dlp não expõe." if nao_lidos else "")
    if not r.get("total"):
        return "vazia", f"{fonte}: respondeu, mas VAZIA (0 itens).{extra}"
    if not r["canais"]:
        return "sem_canais", f"{fonte}: respondeu com {r['total']} itens ({tipos}), NENHUM canal.{extra}"
    return "ok", f"{fonte}: {len(r['canais'])} canais ({tipos}).{extra}"


def _destaques(coletor, base, dono, avisos, log):
    """Tenta a aba "Canais"; se não houver, a aba inicial (prateleira de canais em destaque)."""
    tentativas = [("aba Canais", f"{base}/channels"), ("aba Início", f"{base}/featured")]
    vistos, diagnostico = set(), []
    while tentativas:
        fonte, url = tentativas.pop(0)
        if url in vistos:
            continue
        vistos.add(url)
        log(f"lendo canais em destaque ({fonte})…")
        r = coletor.destaques(url)
        if r is not None:
            r = dict(r, canais=[c for c in r["canais"] if c["channel_id"] != dono])
        estado, texto = _diagnostico_aba(fonte, url, r, coletor.ultimo_erro)
        diagnostico.append({"fonte": fonte, "url": url, "estado": estado, "detalhe": texto})
        if estado == "ok":
            return fonte, r["canais"], diagnostico
        avisos.append(texto)
        if r and r["links"]:  # prateleira que só aponta para outra página de canais
            tentativas.insert(0, (f"{fonte} → link da prateleira", r["links"][0]))
    avisos.append("Sem canais em destaque: o bônus de destaque não foi aplicado a ninguém.")
    return None, [], diagnostico


def _mencoes(coletor, cfg, videos, ref, agora, avisos, log):
    """Valida via yt-dlp os canais citados por link nas descrições. Retorna (candidatos, relatório)."""
    lidos = [v for v in videos if v.get("descricao")]
    achados = mencoes.extrair(lidos)
    chaves_ref = chaves_do_canal(ref["channel_id"], ref.get("handle"))
    validos, ignorados = mencoes.filtrar(achados, len(lidos), chaves_ref, ref.get("nome"), ref.get("handle"))
    ordem = sorted(validos.items(), key=lambda kv: (-len(kv[1]["videos"]), kv[0]))
    if len(ordem) > cfg.max_mencoes:
        avisos.append(f"{len(ordem)} canais citados nas descrições; só os {cfg.max_mencoes} mais citados "
                      "foram validados (FAREJADOR_MAX_MENCOES).")
    por_id, invalidos = {}, []
    for chave, m in ordem[: cfg.max_mencoes]:
        log(f"validando canal citado {chave} ({len(m['videos'])} vídeos)…")
        info = coletor.canal(m["url"], 5)
        if not info or not info.get("channel_id"):
            invalidos.append(chave)
            continue
        cid = info["channel_id"]
        if cid == ref["channel_id"] or mencoes.parece_do_criador(info.get("handle") or info.get("nome") or "",
                                                                  ref.get("nome"), ref.get("handle")):
            ignorados.append((chave, "resolveu para o próprio canal/criador"))
            continue
        c = por_id.setdefault(cid, dict(_novo(cid, info.get("nome"), info.get("handle")), ids=set()))
        c["ids"] |= m["videos"]
        c["mencoes"] = len(c["ids"])
        c["seguidores"] = info.get("seguidores")
        c["verificado"] = True
        c["atividade"] = ranking.atividade([v["timestamp"] for v in info["videos"]], cfg.dias_ativo, agora)
    for c in por_id.values():
        c.pop("ids")
    relatorio = {
        "descricoes_lidas": len(lidos),
        "links_encontrados": len(achados),
        "validados": len(por_id),
        "invalidos": invalidos,
        "ignorados": [{"canal": k, "motivo": mot} for k, mot in ignorados],
    }
    if lidos and not achados:
        avisos.append(f"Nenhum link de canal do YouTube nas {len(lidos)} descrições lidas.")
    return por_id, relatorio


def descobrir(entrada, cfg, coletor, exclusoes=frozenset(), agora=None, log=lambda m, detalhe=False: None,
              relogio=time.monotonic):
    agora = agora or time.time()
    avisos = []
    etapas = Etapas(coletor, relogio)
    base = url_base(entrada)

    with etapas.medir("canal de referência"):
        log(f"lendo os últimos {cfg.videos_referencia} vídeos de {base}…")
        ref = coletor.canal(base, cfg.videos_referencia)
    if not ref or not ref.get("channel_id"):
        raise ErroCanal(f"não consegui ler o canal {entrada!r} (veja a tabela eventos no SQLite)")
    videos = [dict(v, tags=[]) for v in ref["videos"]]
    if not videos:
        avisos.append("O canal de referência não retornou vídeos na aba Vídeos.")

    # descrição completa e tags só vêm abrindo cada vídeo: 1 requisição por vídeo (com cache)
    alvo = videos[: cfg.detalhes_videos]
    log(f"detalhes de {len(alvo)} vídeos: até {len(alvo)} requisições, ~{len(alvo) * cfg.pausa:.0f} s de "
        "pausa se nada estiver em cache", detalhe=True)
    com_detalhes = com_tags = 0
    with etapas.medir(f"detalhes de {len(alvo)} vídeos"):
        for i, v in enumerate(alvo, 1):
            log(f"detalhes do vídeo {i}/{len(alvo)} ({v['id']})…")
            d = coletor.video(v["id"])
            if d:
                com_detalhes += 1
                v["tags"] = d["tags"]
                v["descricao"] = d["descricao"] or v.get("descricao", "")
                com_tags += bool(d["tags"])
    if alvo and com_detalhes < len(alvo):
        avisos.append(f"Detalhes lidos de {com_detalhes}/{len(alvo)} vídeos (falhas na tabela eventos).")
    if com_detalhes and not com_tags:
        avisos.append("Nenhum vídeo tinha tags: palavras-chave vieram só dos títulos.")

    with etapas.medir("abas de destaque"):
        fonte_destaque, destaques, diag_abas = _destaques(coletor, base, ref["channel_id"], avisos, log)

    ignorar = palavras.Ignorados(ref.get("nome") or "", ref.get("handle") or "", cfg.termos_ignorados())
    unigramas, frases = palavras.extrair(videos, ref["tags"], ref["descricao"], ignorar, cfg.min_videos_termo)
    titulos = palavras.titulos_representativos(videos, unigramas, frases, ignorar, cfg.buscas_titulos)
    consultas = busca.montar_consultas(unigramas, frases, cfg.max_buscas, titulos)
    if not unigramas and not frases:
        avisos.append(f"Nenhum termo aparece em {cfg.min_videos_termo}+ vídeos distintos "
                      "(FAREJADOR_MIN_VIDEOS_TERMO); só títulos foram usados nas buscas.")
    if not consultas:
        avisos.append("Nenhuma consulta montada: nada foi buscado.")

    with etapas.medir("menções nas descrições"):
        citados, rel_mencoes = _mencoes(coletor, cfg, videos, ref, agora, avisos, log)

    resultados = []
    with etapas.medir(f"{len(consultas)} buscas"):
        for i, (q, origem) in enumerate(consultas, 1):
            log(f"busca {i}/{len(consultas)} ({origem}): {q!r}")
            resultados.append((q, coletor.buscar(q, cfg.resultados_por_busca) or []))
    candidatos = {cid: dict(_novo(cid), **c) for cid, c in busca.agregar(resultados).items()}

    for d in destaques:
        c = candidatos.setdefault(d["channel_id"], _novo(d["channel_id"], d.get("nome"), d.get("handle")))
        c["destaque"] = True
        c["handle"] = c["handle"] or d.get("handle")
    for cid, m in citados.items():
        c = candidatos.setdefault(cid, _novo(cid))
        for k in ("mencoes", "seguidores", "verificado", "atividade"):
            c[k] = m.get(k)
        c["nome"] = c["nome"] or m["nome"]
        c["handle"] = c["handle"] or m["handle"]

    # filtros: o próprio canal, a lista de exclusão e canais automáticos
    proprio = chaves_do_canal(ref["channel_id"], ref.get("handle"))
    removidos = {"proprio": 0, "exclusao": 0, "ruido": 0, "inativo": 0}
    lista = []
    for c in candidatos.values():
        k = chaves_do_canal(c["channel_id"], c.get("handle"))
        if k & proprio:
            removidos["proprio"] += 1
        elif k & set(exclusoes):
            removidos["exclusao"] += 1
        elif ranking.eh_ruido(c.get("nome")):
            removidos["ruido"] += 1
        else:
            lista.append(c)

    # atividade: data recente num resultado de busca basta para "ativo"; o contrário não prova
    # inatividade (a busca pode ter trazido um vídeo antigo), então confirma na aba Vídeos.
    total = len(consultas)
    for c in lista:
        if ranking.atividade(c["timestamps"], cfg.dias_ativo, agora) == "ativo":
            c["atividade"] = "ativo"
        elif not c["verificado"]:
            c["atividade"] = "desconhecido"
        ranking.pontuar(c, total, cfg.dias_ativo)
    fortes = [c for c in ranking.ordenar(lista) if c["sinais"] >= cfg.min_sinais]
    fracos = [c for c in ranking.ordenar(lista) if c["sinais"] < cfg.min_sinais]
    a_checar = [c for c in fortes + (fracos if cfg.mostrar_fracos else [])
                if c["atividade"] != "ativo" and not c["verificado"]]
    if len(a_checar) > cfg.verificar_atividade:
        avisos.append(f"{len(a_checar) - cfg.verificar_atividade} candidatos ficaram sem checagem de atividade "
                      "(FAREJADOR_VERIFICAR_ATIVIDADE).")
    with etapas.medir("checagem de atividade"):
        for c in a_checar[: cfg.verificar_atividade]:
            log(f"checando atividade de {c.get('nome') or c['channel_id']}…")
            info = coletor.canal(f"https://www.youtube.com/channel/{c['channel_id']}", 5)
            if info:
                c["handle"] = c.get("handle") or info.get("handle")
                c["nome"] = c.get("nome") or info.get("nome")
                c["seguidores"] = info.get("seguidores")
                c["verificado"] = True
                c["atividade"] = ranking.atividade([v["timestamp"] for v in info["videos"]], cfg.dias_ativo, agora)

    inativos = [c.get("nome") or c["channel_id"] for c in lista if c["atividade"] == "inativo"]
    removidos["inativo"] = len(inativos)
    lista = [c for c in lista if c["atividade"] != "inativo"]
    for c in lista:
        ranking.pontuar(c, total, cfg.dias_ativo)
        c["url"] = _url_canal(c)
    lista = ranking.ordenar(lista)
    fortes = [c for c in lista if c["sinais"] >= cfg.min_sinais]
    fracos = [c for c in lista if c["sinais"] < cfg.min_sinais]

    def so(c):
        return "menção" if c["mencoes"] else "destaque" if c["destaque"] else "1 busca"

    def exportar(cs):
        campos = ("nome", "handle", "channel_id", "url", "score", "sinais", "motivo", "atividade",
                  "destaque", "mencoes", "consultas", "videos", "seguidores")
        return [{k: c.get(k) for k in campos} for c in cs]

    return {
        "gerado_em": datetime.fromtimestamp(agora, timezone.utc).isoformat(timespec="seconds"),
        "referencia": {
            "entrada": entrada, "channel_id": ref["channel_id"], "nome": ref.get("nome"),
            "handle": ref.get("handle"), "seguidores": ref.get("seguidores"), "videos_lidos": len(videos),
            "videos_com_detalhes": com_detalhes, "videos_com_tags": com_tags, "tags_do_canal": ref["tags"],
        },
        "termos_ignorados": ignorar.lista(),
        "palavras_chave": [{"termo": u["termo"], "videos": u["videos"]} for u in unigramas],
        "frases": [{"termo": f["termo"], "videos": f["videos"]} for f in frases],
        "consultas": [{"consulta": q, "origem": o} for q, o in consultas],
        "destaques": {"fonte": fonte_destaque, "canais": [d.get("nome") for d in destaques], "abas": diag_abas},
        "mencoes": rel_mencoes,
        "removidos": removidos,
        "inativos": inativos,
        "fracos": {"total": len(fracos), "por_sinal": {s: sum(so(c) == s for c in fracos)
                                                       for s in ("1 busca", "menção", "destaque")}},
        "avisos": avisos,
        "etapas": etapas.lista,
        "requisicoes": {"rede": coletor.requisicoes, "cache": coletor.acertos_cache,
                        "avisos_ytdlp": coletor.avisos_ytdlp},
        "candidatos": exportar(fortes),
        "candidatos_fracos": exportar(fracos) if cfg.mostrar_fracos else [],
    }
