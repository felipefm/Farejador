"""Estado do servidor (fase 2) no mesmo SQLite do cache: sementes, execuções e candidatos.

Regras dos candidatos:
- novo -> aprovado | descartado; aprovado -> descartado.
- descartado é definitivo: nunca volta à lista nem é sobrescrito por uma descoberta nova.
- aprovados e descartados entram na lista de exclusão das próximas descobertas (não gastam busca
  nem avaliação do LLM de novo).
- arquivar tira os decididos das abas Aprovados/Descartados (e da exportação), mas eles continuam
  na exclusão. Remover do arquivo apaga o registro: o canal volta a poder aparecer como novo.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .canais import chaves_do_canal

ESQUEMA = """
CREATE TABLE IF NOT EXISTS sementes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entrada TEXT NOT NULL UNIQUE,
    criado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS execucoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sementes TEXT NOT NULL,          -- JSON
    estado TEXT NOT NULL,            -- rodando | ok | erro | interrompida
    inicio TEXT NOT NULL,
    fim TEXT,
    progresso TEXT,
    erro TEXT,
    resumo TEXT                      -- JSON por semente
);
CREATE TABLE IF NOT EXISTS candidatos (
    channel_id TEXT PRIMARY KEY,
    nome TEXT,
    handle TEXT,
    url TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'novo',   -- novo | aprovado | descartado
    score_final REAL,
    score INTEGER,
    nota_llm REAL,
    justificativa_llm TEXT,
    motivo TEXT,
    sementes TEXT NOT NULL DEFAULT '[]',   -- JSON: sementes em que apareceu
    seguidores INTEGER,
    visto_em TEXT NOT NULL,
    decidido_em TEXT,
    metube_estado TEXT,                    -- enviado | erro
    metube_msg TEXT,
    arquivado_em TEXT                      -- preenchido = fora das abas, ainda na exclusão
);
"""
MIGRACOES = {"candidatos": {"arquivado_em": "TEXT"}}  # colunas novas em bancos já existentes

ESTADOS = ("novo", "aprovado", "descartado")
LISTAS = (*ESTADOS, "arquivado")  # "arquivado" é uma vista: aprovados e descartados arquivados
TRANSICOES = {("novo", "aprovado"), ("novo", "descartado"), ("aprovado", "descartado")}


def agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TransicaoInvalida(ValueError):
    pass


class Banco:
    def __init__(self, caminho):
        self.caminho = str(caminho)
        Path(self.caminho).parent.mkdir(parents=True, exist_ok=True)
        with self._conexao() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(ESQUEMA)
            for tabela, colunas in MIGRACOES.items():
                existentes = {r["name"] for r in db.execute(f"PRAGMA table_info({tabela})")}
                for nome, tipo in colunas.items():
                    if nome not in existentes:
                        db.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}")

    @contextmanager
    def _conexao(self):
        # uma conexão por operação: a API (threads do FastAPI) e a descoberta (outra thread) não se cruzam
        db = sqlite3.connect(self.caminho, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    # ---------------------------------------------------------------- sementes
    def adicionar_semente(self, entrada):
        with self._conexao() as db:
            cur = db.execute("INSERT OR IGNORE INTO sementes (entrada, criado) VALUES (?, ?)", (entrada, agora()))
            if cur.rowcount:
                return cur.lastrowid
            return db.execute("SELECT id FROM sementes WHERE entrada = ?", (entrada,)).fetchone()["id"]

    def sementes(self):
        with self._conexao() as db:
            return [dict(r) for r in db.execute("SELECT * FROM sementes ORDER BY id")]

    def remover_semente(self, id_):
        with self._conexao() as db:
            return db.execute("DELETE FROM sementes WHERE id = ?", (id_,)).rowcount > 0

    # ---------------------------------------------------------------- execuções
    def criar_execucao(self, sementes):
        with self._conexao() as db:
            return db.execute("INSERT INTO execucoes (sementes, estado, inicio) VALUES (?, 'rodando', ?)",
                              (json.dumps(sementes, ensure_ascii=False), agora())).lastrowid

    def atualizar_execucao(self, id_, **campos):
        if "resumo" in campos:
            campos["resumo"] = json.dumps(campos["resumo"], ensure_ascii=False)
        if campos.get("estado") in ("ok", "erro", "interrompida"):
            campos.setdefault("fim", agora())
        sets = ", ".join(f"{k} = ?" for k in campos)
        with self._conexao() as db:
            db.execute(f"UPDATE execucoes SET {sets} WHERE id = ?", (*campos.values(), id_))

    def interromper_pendentes(self):
        """No arranque: execução que estava 'rodando' morreu com o processo (reinício, --reload)."""
        with self._conexao() as db:
            return db.execute("UPDATE execucoes SET estado = 'interrompida', fim = ?, "
                              "erro = 'processo reiniciado durante a descoberta' WHERE estado = 'rodando'",
                              (agora(),)).rowcount

    def execucao(self, id_):
        with self._conexao() as db:
            r = db.execute("SELECT * FROM execucoes WHERE id = ?", (id_,)).fetchone()
        return _execucao(r) if r else None

    def execucoes(self, limite=20):
        with self._conexao() as db:
            return [_execucao(r) for r in db.execute("SELECT * FROM execucoes ORDER BY id DESC LIMIT ?", (limite,))]

    # ---------------------------------------------------------------- candidatos
    def gravar_candidatos(self, semente, candidatos):
        """Insere novos e atualiza os 'novo'. Aprovado/descartado só ganham a semente na lista."""
        novos = 0
        with self._conexao() as db:
            for c in candidatos:
                atual = db.execute("SELECT estado, sementes FROM candidatos WHERE channel_id = ?",
                                   (c["channel_id"],)).fetchone()
                if atual is None:
                    db.execute(
                        "INSERT INTO candidatos (channel_id, nome, handle, url, score_final, score, nota_llm, "
                        "justificativa_llm, motivo, sementes, seguidores, visto_em) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (c["channel_id"], c.get("nome"), c.get("handle"), c["url"], c.get("score_final"),
                         c.get("score"), c.get("nota_llm"), c.get("justificativa_llm"), c.get("motivo"),
                         json.dumps([semente], ensure_ascii=False), c.get("seguidores"), agora()))
                    novos += 1
                    continue
                sementes = json.loads(atual["sementes"])
                if semente not in sementes:
                    sementes.append(semente)
                if atual["estado"] == "novo":
                    db.execute(
                        "UPDATE candidatos SET nome = ?, handle = ?, url = ?, score_final = ?, score = ?, "
                        "nota_llm = ?, justificativa_llm = ?, motivo = ?, sementes = ?, seguidores = ?, "
                        "visto_em = ? WHERE channel_id = ?",
                        (c.get("nome"), c.get("handle"), c["url"], c.get("score_final"), c.get("score"),
                         c.get("nota_llm"), c.get("justificativa_llm"), c.get("motivo"),
                         json.dumps(sementes, ensure_ascii=False), c.get("seguidores"), agora(), c["channel_id"]))
                else:
                    db.execute("UPDATE candidatos SET sementes = ? WHERE channel_id = ?",
                               (json.dumps(sementes, ensure_ascii=False), c["channel_id"]))
        return novos

    def candidatos(self, estado="novo"):
        if estado not in LISTAS:
            raise ValueError(f"estado inválido: {estado!r}")
        if estado == "arquivado":
            sql, args = "SELECT * FROM candidatos WHERE arquivado_em IS NOT NULL ORDER BY arquivado_em DESC, nome", ()
        else:
            ordem = "score_final DESC, score DESC" if estado == "novo" else "decidido_em DESC"
            sql = f"SELECT * FROM candidatos WHERE estado = ? AND arquivado_em IS NULL ORDER BY {ordem}"
            args = (estado,)
        with self._conexao() as db:
            return [_candidato(r) for r in db.execute(sql, args)]

    def arquivar_decididos(self):
        """Tira aprovados e descartados das abas (continuam na exclusão). Retorna quantos."""
        with self._conexao() as db:
            return db.execute("UPDATE candidatos SET arquivado_em = ? WHERE estado != 'novo' "
                              "AND arquivado_em IS NULL", (agora(),)).rowcount

    def remover_arquivado(self, channel_id):
        """Apaga um arquivado: sai da exclusão e pode reaparecer como novo numa descoberta."""
        with self._conexao() as db:
            r = db.execute("SELECT arquivado_em FROM candidatos WHERE channel_id = ?", (channel_id,)).fetchone()
            if r is None:
                raise KeyError(channel_id)
            if r["arquivado_em"] is None:
                raise TransicaoInvalida("só candidatos arquivados podem ser removidos")
            db.execute("DELETE FROM candidatos WHERE channel_id = ?", (channel_id,))

    def candidato(self, channel_id):
        with self._conexao() as db:
            r = db.execute("SELECT * FROM candidatos WHERE channel_id = ?", (channel_id,)).fetchone()
        return _candidato(r) if r else None

    def decidir(self, channel_id, estado):
        with self._conexao() as db:
            r = db.execute("SELECT estado FROM candidatos WHERE channel_id = ?", (channel_id,)).fetchone()
            if r is None:
                raise KeyError(channel_id)
            if r["estado"] == estado:
                return  # idempotente
            if (r["estado"], estado) not in TRANSICOES:
                raise TransicaoInvalida(f"{r['estado']} -> {estado} não é permitido")
            db.execute("UPDATE candidatos SET estado = ?, decidido_em = ? WHERE channel_id = ?",
                       (estado, agora(), channel_id))

    def marcar_metube(self, channel_id, ok, msg):
        with self._conexao() as db:
            db.execute("UPDATE candidatos SET metube_estado = ?, metube_msg = ? WHERE channel_id = ?",
                       ("enviado" if ok else "erro", (msg or "")[:500], channel_id))

    def chaves_decididas(self):
        """Chaves (ID e @handle) de aprovados e descartados, no formato da lista de exclusão."""
        with self._conexao() as db:
            linhas = db.execute("SELECT channel_id, handle FROM candidatos WHERE estado != 'novo'").fetchall()
        k = set()
        for r in linhas:
            k |= chaves_do_canal(r["channel_id"], r["handle"])
        return k

    def urls_aprovadas(self, arquivados=False):
        filtro = "" if arquivados else " AND arquivado_em IS NULL"
        with self._conexao() as db:
            return [r["url"] for r in db.execute(
                f"SELECT url FROM candidatos WHERE estado = 'aprovado'{filtro} ORDER BY decidido_em, nome")]


def _execucao(r):
    d = dict(r)
    d["sementes"] = json.loads(d["sementes"])
    d["resumo"] = json.loads(d["resumo"]) if d["resumo"] else None
    return d


def _candidato(r):
    d = dict(r)
    d["sementes"] = json.loads(d["sementes"])
    return d
