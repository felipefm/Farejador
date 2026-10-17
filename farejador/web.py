"""Servidor da fase 2: API + tela mínima. Rodar com:

    uvicorn --factory farejador.web:criar_app --host 0.0.0.0 --port 8000
"""
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse

from . import cookies, metube
from .banco import ESTADOS, Banco, TransicaoInvalida
from .cache import Cache
from .canais import url_base
from .config import Config
from .servico import Executor, JaRodando

PAGINA = Path(__file__).parent / "static" / "index.html"


def criar_app(cfg=None, banco=None, executor=None, enviar_metube=metube.enviar):
    cfg = cfg or Config.from_env()
    banco = banco or Banco(cfg.caminho("dados") / "farejador.db")
    executor = executor or Executor(cfg, banco)
    banco.interromper_pendentes()
    app = FastAPI(title="Farejador", docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    app.state.cfg, app.state.banco, app.state.executor = cfg, banco, executor

    def mandar_metube(cid):
        c = banco.candidato(cid)
        log = Cache(cfg.caminho("dados") / "farejador.db", cfg.cache_horas)  # registra em eventos
        try:
            ok, msg = enviar_metube(cfg, c["url"], cache=log)
        finally:
            log.db.close()
        banco.marcar_metube(cid, ok, msg)
        return {"ok": ok, "msg": msg}

    @app.get("/", include_in_schema=False)
    def pagina():
        return FileResponse(PAGINA, media_type="text/html")

    @app.get("/api/saude")
    def saude():
        return {"ok": True, "rodando": executor.atual, "llm": bool(cfg.llm_url) and not cfg.sem_llm,
                "metube": metube.ligado(cfg), "metube_modo": cfg.metube_modo if metube.ligado(cfg) else None,
                "cookies": cookies.ativo(cfg)[1]}

    # ------------------------------------------------------------ cookies (o conteúdo nunca sai daqui)
    @app.get("/api/cookies")
    def estado_cookies():
        return cookies.estado(cfg)

    @app.put("/api/cookies")
    async def enviar_cookies(request: Request):
        conteudo = await request.body()  # corpo cru: o arquivo cookies.txt (sem multipart, sem dependência extra)
        try:
            n = cookies.salvar(cfg, conteudo)
        except cookies.CookiesInvalidos as e:
            raise HTTPException(400, str(e))
        return dict(cookies.estado(cfg), cookies=n)

    @app.delete("/api/cookies")
    def apagar_cookies():
        if not cookies.apagar(cfg):
            if cookies.configurado(cfg):
                raise HTTPException(409, "não há cookies enviados; os de FAREJADOR_COOKIES só saem pelo compose")
            raise HTTPException(404, "não há cookies enviados")
        return cookies.estado(cfg)

    # ------------------------------------------------------------ sementes
    @app.get("/api/sementes")
    def listar_sementes():
        return banco.sementes()

    @app.post("/api/sementes", status_code=201)
    def adicionar_semente(canal: str = Body(..., embed=True)):
        try:
            url_base(canal)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"id": banco.adicionar_semente(canal.strip())}

    @app.delete("/api/sementes/{id_}", status_code=204)
    def remover_semente(id_: int):
        if not banco.remover_semente(id_):
            raise HTTPException(404, "semente não encontrada")

    # ------------------------------------------------------------ descobertas
    @app.post("/api/descobertas", status_code=202)
    def rodar(sementes: list[str] | None = Body(None, embed=True)):
        alvo = sementes or [s["entrada"] for s in banco.sementes()]
        if not alvo:
            raise HTTPException(400, "nenhuma semente cadastrada")
        for s in alvo:
            try:
                url_base(s)
            except ValueError as e:
                raise HTTPException(400, str(e))
        try:
            return {"id": executor.iniciar(alvo)}
        except JaRodando as e:
            raise HTTPException(409, str(e))

    @app.get("/api/descobertas")
    def listar_descobertas():
        return banco.execucoes()

    @app.get("/api/descobertas/{id_}")
    def descoberta(id_: int):
        e = banco.execucao(id_)
        if not e:
            raise HTTPException(404, "execução não encontrada")
        return e

    # ------------------------------------------------------------ candidatos
    @app.get("/api/candidatos")
    def listar_candidatos(estado: str = "novo"):
        if estado not in ESTADOS:
            raise HTTPException(400, f"estado deve ser um de {', '.join(ESTADOS)}")
        return banco.candidatos(estado)

    def _decidir(cid, estado):
        try:
            banco.decidir(cid, estado)
        except KeyError:
            raise HTTPException(404, "candidato não encontrado")
        except TransicaoInvalida as e:
            raise HTTPException(409, str(e))

    @app.post("/api/candidatos/{cid}/aprovar")
    def aprovar(cid: str):
        _decidir(cid, "aprovado")
        resposta = {"estado": "aprovado", "metube": None}
        if metube.ligado(cfg):
            resposta["metube"] = mandar_metube(cid)
        return resposta

    @app.post("/api/candidatos/{cid}/descartar")
    def descartar(cid: str):
        _decidir(cid, "descartado")
        return {"estado": "descartado"}

    @app.post("/api/candidatos/{cid}/metube")
    def reenviar_metube(cid: str):
        c = banco.candidato(cid)
        if not c:
            raise HTTPException(404, "candidato não encontrado")
        if c["estado"] != "aprovado":
            raise HTTPException(409, "só aprovados vão para o MeTube")
        if not metube.ligado(cfg):
            raise HTTPException(409, "adaptador do MeTube desligado (FAREJADOR_METUBE_URL vazio)")
        return mandar_metube(cid)

    @app.get("/api/exportar", response_class=PlainTextResponse)
    def exportar():
        urls = banco.urls_aprovadas()
        return "\n".join(urls) + ("\n" if urls else "")

    return app
