"""SQLite local: cache de consultas ao YouTube e log de eventos/erros para auditoria."""
import json
import sqlite3
import time
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS cache (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL,
    criado REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quando TEXT NOT NULL DEFAULT (datetime('now')),
    nivel TEXT NOT NULL,      -- info | aviso | erro
    tipo TEXT NOT NULL,       -- rede | cache | transitorio | permanente | bloqueio | ytdlp
    alvo TEXT,
    tentativa INTEGER,
    mensagem TEXT
);
"""


class Cache:
    def __init__(self, caminho, horas=168, relogio=time.time):
        if str(caminho) != ":memory:":
            Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(caminho))
        self.db.executescript(ESQUEMA)
        self.validade = horas * 3600
        self.relogio = relogio

    def get(self, chave):
        """Retorna o valor guardado ou None se ausente/expirado."""
        linha = self.db.execute("SELECT valor, criado FROM cache WHERE chave = ?", (chave,)).fetchone()
        if not linha:
            return None
        valor, criado = linha
        if self.validade and self.relogio() - criado > self.validade:
            return None
        return json.loads(valor)

    def put(self, chave, valor):
        self.db.execute(
            "INSERT OR REPLACE INTO cache (chave, valor, criado) VALUES (?, ?, ?)",
            (chave, json.dumps(valor, ensure_ascii=False), self.relogio()),
        )
        self.db.commit()

    def evento(self, nivel, tipo, alvo=None, mensagem=None, tentativa=None):
        self.db.execute(
            "INSERT INTO eventos (nivel, tipo, alvo, tentativa, mensagem) VALUES (?, ?, ?, ?, ?)",
            (nivel, tipo, alvo, tentativa, mensagem),
        )
        self.db.commit()

    def eventos(self, nivel=None):
        sql = "SELECT quando, nivel, tipo, alvo, tentativa, mensagem FROM eventos"
        args = ()
        if nivel:
            sql += " WHERE nivel = ?"
            args = (nivel,)
        return self.db.execute(sql + " ORDER BY id", args).fetchall()
