"""Pipeline de descoberta: canal de referência -> palavras-chave/menções -> buscas -> candidatos ranqueados."""
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from . import busca, llm as llm_mod, mencoes, palavras, ranking
from .canais import chaves_do_canal, url_base

VIDEOS_CANDIDATO = 10  # vídeos lidos da aba Vídeos de um candidato (atividade + títulos para o LLM)


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

    def __init__(self, coletor, llm=None, relogio=time.monotonic):
        self.coletor, self.llm, self.relogio, self.lista = coletor, llm, relogio, []

    @contextmanager
    def medir(self, nome):
        r0, c0, t0 = self.coletor.requisicoes, self.coletor.acertos_cache, self.relogio()
        l0, lc0 = (self.llm.chamadas, self.llm.acertos_cache) if self.llm else (0, 0)
        try:
            yield
        finally:
            e = {"etapa": nome, "rede": self.coletor.requisicoes - r0, "cache": self.coletor.acertos_cache - c0,
                 "segundos": round(self.relogio() - t0, 1)}
            if self.llm:
                e["llm"] = self.llm.chamadas - l0
                e["llm_cache"] = self.llm.acertos_cache - lc0
            self.lista.append(e)


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
    vistos, diagnostico, playlists = set(), [], []
    while tentativas:
        fonte, url = tentativas.pop(0)
        if url in vistos:
            continue
        vistos.add(url)
        log(f"lendo canais em destaque ({fonte})…")
        r = coletor.destaques(url)
        if r is not None:
            r = dict(r, canais=[c for c in r["canais"] if c["channel_id"] != dono])
            playlists += [pl for pl in r.get("playlists", []) if pl["url"] not in {x["url"] for x in playlists}]
        estado, texto = _diagnostico_aba(fonte, url, r, coletor.ultimo_erro)
        diagnostico.append({"fonte": fonte, "url": url, "estado": estado, "detalhe": texto})
        if estado == "ok":
            return fonte, r["canais"], diagnostico, playlists
        avisos.append(texto)
        if r and r["links"]:  # prateleira que só aponta para outra página de canais
            tentativas.insert(0, (f"{fonte} → link da prateleira", r["links"][0]))
    avisos.append("Sem canais em destaque: o bônus de destaque não foi aplicado a ninguém.")
    return None, [], diagnostico, playlists


def _playlists(coletor, cfg, listadas, ja_lidos, log):
    """Lê as playlists da aba Início: o núcleo do canal costuma estar ali, não nos vídeos recentes.

    Retorna (vídeos novos para as palavras-chave, relatório por playlist).
    """
    videos, relatorio = [], []
    for pl in listadas[: cfg.max_playlists]:
        log(f"lendo playlist {pl['titulo'] or pl['url']!r}…")
        info = coletor.playlist(pl["url"], cfg.videos_playlist)
        if not info:
            relatorio.append({"titulo": pl["titulo"], "url": pl["url"], "videos": 0, "erro": True})
            continue
        novos = [v for v in info["videos"] if v["id"] not in ja_lidos]
        ja_lidos.update(v["id"] for v in novos)
        videos += [{"id": v["id"], "titulo": v["titulo"], "tags": []} for v in novos]
        relatorio.append({"titulo": info["titulo"] or pl["titulo"], "url": pl["url"], "videos": len(novos)})
    return videos, relatorio


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
        info = coletor.canal(m["url"], VIDEOS_CANDIDATO)
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
        _dados_do_canal(c, info, cfg, agora)
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


def _dados_do_canal(c, info, cfg, agora):
    """Aproveita a leitura da aba Vídeos do candidato: atividade, inscritos e títulos recentes."""
    c["handle"] = c.get("handle") or info.get("handle")
    c["nome"] = c.get("nome") or info.get("nome")
    c["seguidores"] = info.get("seguidores")
    c["verificado"] = True
    c["titulos_recentes"] = [v["titulo"] for v in info["videos"] if v.get("titulo")]
    c["atividade"] = ranking.atividade([v["timestamp"] for v in info["videos"]], cfg.dias_ativo, agora)


def _consultas_llm(llm, ref, videos, playlists, ignorar, consultas, cfg, avisos, log):
    """Consultas sobre o tema pedidas ao LLM, sem termos do canal e sem repetir as determinísticas."""
    log("pedindo consultas ao LLM…")
    tags = list(dict.fromkeys(t for v in videos for t in v.get("tags") or []))[:40]
    descricoes = [v["descricao"] for v in videos if v.get("descricao")][:5]
    proibidos = [t for t in ignorar.lista() if not t.startswith("(")] + [ref.get("handle") or ""]
    prompt = llm_mod.prompt_consultas(ref.get("nome"), [v["titulo"] for v in videos], tags, descricoes,
                                      [p for p in proibidos if p], playlists)
    ja = {q.lower() for q, _ in consultas}

    def proibido(q):
        return q.lower() in ja or any(c in ignorar for c, _ in palavras.tokens(q))

    r = llm.perguntar("consultas", prompt, llm_mod.SCHEMA_CONSULTAS,
                      llm_mod.validar_consultas(proibido, cfg.llm_max_buscas))
    if r is None and llm.ligado:
        avisos.append("LLM não devolveu consultas válidas (ver eventos/llm_invalido); usei só as determinísticas.")
    return [(q, "llm") for q in r or []]


def _perfil(ref, unigramas, frases, videos, playlists=()):
    return "\n".join([
        f"Canal: {ref.get('nome')}",
        "Temas: " + ", ".join([f["termo"] for f in frases] + [u["termo"] for u in unigramas[:10]]),
        *([("Playlists: " + "; ".join(playlists))] if playlists else []),
        "Títulos recentes:",
        *[f"- {v['titulo']}" for v in videos[:10]],
    ])


def _avaliar_llm(llm, coletor, lista, perfil, cfg, agora, avisos, log):
    """Nota de afinidade temática para os primeiros candidatos. Lê a aba Vídeos de quem ainda não foi lido."""
    avaliados = 0
    for c in lista[: cfg.llm_avaliar]:
        if not llm.ligado:
            break
        if not c.get("titulos_recentes"):
            log(f"lendo títulos recentes de {c.get('nome') or c['channel_id']} para o LLM…")
            info = coletor.canal(f"https://www.youtube.com/channel/{c['channel_id']}", VIDEOS_CANDIDATO)
            if info:
                _dados_do_canal(c, info, cfg, agora)
        if c.get("atividade") == "inativo":
            continue  # descoberto agora; sai na filtragem
        titulos = c.get("titulos_recentes") or c.get("videos") or []
        if not titulos:
            continue
        log(f"LLM avaliando {c.get('nome') or c['channel_id']}…")
        r = llm.perguntar("nota", llm_mod.prompt_nota(perfil, c.get("nome") or c["channel_id"], titulos[:10]),
                          llm_mod.SCHEMA_NOTA, llm_mod.validar_nota)
        if r:
            c["nota_llm"], c["justificativa_llm"] = r["nota"], r["justificativa"]
            avaliados += 1
    tentados = min(len(lista), cfg.llm_avaliar)
    if tentados and avaliados < tentados:
        avisos.append(f"LLM avaliou {avaliados}/{tentados} candidatos; os demais ficaram só com o score "
                      "determinístico.")
    return avaliados


def descobrir(entrada, cfg, coletor, exclusoes=frozenset(), agora=None, log=lambda m, detalhe=False: None,
              relogio=time.monotonic, llm=None):
    agora = agora or time.time()
    avisos = []
    llm = llm if llm is not None and llm.ligado else None
    etapas = Etapas(coletor, llm, relogio)
    base = url_base(entrada)
    limitadas0, rede0 = coletor.limitadas, coletor.requisicoes  # o Coletor é compartilhado entre sementes

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
    com_detalhes = com_tags = corrigidos = 0
    with etapas.medir(f"detalhes de {len(alvo)} vídeos"):
        for i, v in enumerate(alvo, 1):
            log(f"detalhes do vídeo {i}/{len(alvo)} ({v['id']})…")
            d = coletor.video(v["id"])
            if d:
                com_detalhes += 1
                v["tags"] = d["tags"]
                # o título do modo flat vem traduzido para o idioma da interface; o da extração completa é o original
                if d.get("titulo") and d["titulo"] != v["titulo"]:
                    v["titulo_flat"], v["titulo"] = v["titulo"], d["titulo"]
                    corrigidos += 1
                v["descricao"] = d["descricao"] or v.get("descricao", "")
                com_tags += bool(d["tags"])
    if alvo and com_detalhes < len(alvo):
        avisos.append(f"Detalhes lidos de {com_detalhes}/{len(alvo)} vídeos (falhas na tabela eventos).")
    if com_detalhes and not com_tags:
        avisos.append("Nenhum vídeo tinha tags: palavras-chave vieram só dos títulos.")

    with etapas.medir("abas de destaque"):
        fonte_destaque, destaques, diag_abas, listadas = _destaques(coletor, base, ref["channel_id"], avisos, log)
    if len(listadas) > cfg.max_playlists:
        avisos.append(f"{len(listadas)} playlists na aba Início; só as {cfg.max_playlists} primeiras foram lidas "
                      "(FAREJADOR_MAX_PLAYLISTS).")
    with etapas.medir(f"playlists ({min(len(listadas), cfg.max_playlists)})"):
        videos_pl, rel_playlists = _playlists(coletor, cfg, listadas, {v["id"] for v in videos}, log)
    titulos_pl = [r["titulo"] for r in rel_playlists if r["titulo"]]

    ignorar = palavras.Ignorados(ref.get("nome") or "", ref.get("handle") or "", cfg.termos_ignorados())
    # vídeos das playlists contam como evidência; títulos das playlists só reforçam (como tags do canal)
    unigramas, frases = palavras.extrair(videos + videos_pl, ref["tags"] + titulos_pl, ref["descricao"], ignorar,
                                         cfg.min_videos_termo)
    titulos = palavras.titulos_representativos(videos, unigramas, frases, ignorar, cfg.buscas_titulos)
    consultas = busca.montar_consultas(unigramas, frases, cfg.max_buscas, titulos)
    if not unigramas and not frases:
        avisos.append(f"Nenhum termo aparece em {cfg.min_videos_termo}+ vídeos distintos "
                      "(FAREJADOR_MIN_VIDEOS_TERMO); só títulos foram usados nas buscas.")
    if llm:
        with etapas.medir("LLM: consultas"):
            consultas += _consultas_llm(llm, ref, videos, titulos_pl, ignorar, consultas, cfg, avisos, log)
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
        for k in ("mencoes", "seguidores", "verificado", "atividade", "titulos_recentes"):
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
            info = coletor.canal(f"https://www.youtube.com/channel/{c['channel_id']}", VIDEOS_CANDIDATO)
            if info:
                _dados_do_canal(c, info, cfg, agora)

    def filtrar_inativos(cs):
        fora = [c for c in cs if c["atividade"] == "inativo"]
        inativos.extend(c.get("nome") or c["channel_id"] for c in fora)
        return [c for c in cs if c["atividade"] != "inativo"]

    inativos = []
    lista = filtrar_inativos(lista)
    for c in lista:
        ranking.pontuar(c, total, cfg.dias_ativo)
        c["url"] = _url_canal(c)
    lista = ranking.ordenar(lista)
    fortes = [c for c in lista if c["sinais"] >= cfg.min_sinais]
    fracos = [c for c in lista if c["sinais"] < cfg.min_sinais]

    avaliados = 0
    if llm and fortes:
        with etapas.medir("LLM: reavaliação"):
            avaliados = _avaliar_llm(llm, coletor, fortes, _perfil(ref, unigramas, frases, videos, titulos_pl), cfg, agora,
                                     avisos, log)
        fortes = filtrar_inativos(fortes)
    reprovados_llm = []
    if llm and cfg.llm_nota_min > 0:
        reprovados_llm = [c for c in fortes if c.get("nota_llm") is not None and c["nota_llm"] < cfg.llm_nota_min]
        fortes = [c for c in fortes if c not in reprovados_llm]
        if reprovados_llm and not fortes:
            avisos.append(f"Todos os candidatos avaliados tiveram nota < {cfg.llm_nota_min:g} no LLM: "
                          "nenhum canal parecido encontrado nesta execução.")
    ranking.combinar(fortes, cfg.llm_peso if llm else 0)
    ranking.combinar(reprovados_llm, 0)
    ranking.combinar(fracos, 0)
    removidos["inativo"] = len(inativos)
    if llm:
        avisos.extend(llm.avisos)
    limitadas = coletor.limitadas - limitadas0
    if limitadas:
        dica = ("" if coletor.cookies_origem else
                " Sem cookies: considere enviar um cookies.txt ou aumentar FAREJADOR_PAUSA.")
        avisos.append(f"YouTube respondeu 429 (limite de requisições) em {limitadas} de "
                      f"{coletor.requisicoes - rede0} requisições; o yt-dlp contornou quando pôde, mas os "
                      f"dados dessas podem ter vindo incompletos.{dica}")

    def so(c):
        return "menção" if c["mencoes"] else "destaque" if c["destaque"] else "1 busca"

    def exportar(cs):
        campos = ("nome", "handle", "channel_id", "url", "score_final", "score", "nota_llm", "justificativa_llm",
                  "sinais", "motivo", "atividade", "destaque", "mencoes", "consultas", "videos",
                  "titulos_recentes", "seguidores")
        return [{k: c.get(k) for k in campos} for c in cs]

    return {
        "gerado_em": datetime.fromtimestamp(agora, timezone.utc).isoformat(timespec="seconds"),
        "referencia": {
            "entrada": entrada, "channel_id": ref["channel_id"], "nome": ref.get("nome"),
            "handle": ref.get("handle"), "seguidores": ref.get("seguidores"), "videos_lidos": len(videos),
            "videos_com_detalhes": com_detalhes, "videos_com_tags": com_tags, "tags_do_canal": ref["tags"],
            "titulos_corrigidos": corrigidos, "videos_de_playlists": len(videos_pl),
        },
        "termos_ignorados": ignorar.lista(),
        "palavras_chave": [{"termo": u["termo"], "videos": u["videos"]} for u in unigramas],
        "frases": [{"termo": f["termo"], "videos": f["videos"]} for f in frases],
        "consultas": [{"consulta": q, "origem": o} for q, o in consultas],
        "destaques": {"fonte": fonte_destaque, "canais": [d.get("nome") for d in destaques], "abas": diag_abas},
        "playlists": rel_playlists,
        "mencoes": rel_mencoes,
        "removidos": removidos,
        "inativos": inativos,
        "fracos": {"total": len(fracos), "por_sinal": {s: sum(so(c) == s for c in fracos)
                                                       for s in ("1 busca", "menção", "destaque")}},
        "llm": {"ligado": llm is not None, "modelo": llm.modelo if llm else None,
                "nota_min": cfg.llm_nota_min if llm else 0, "reprovados": len(reprovados_llm),
                "consultas": sum(o == "llm" for _, o in consultas), "avaliados": avaliados,
                "peso": cfg.llm_peso if llm else 0},
        "avisos": avisos,
        "etapas": etapas.lista,
        "requisicoes": {"rede": coletor.requisicoes, "cache": coletor.acertos_cache,
                        "avisos_ytdlp": coletor.avisos_ytdlp, "limitadas": coletor.limitadas - limitadas0},
        "cookies": coletor.cookies_origem,
        "candidatos": exportar(fortes),
        "reprovados_llm": exportar(reprovados_llm),
        "candidatos_fracos": exportar(fracos) if cfg.mostrar_fracos else [],
    }
