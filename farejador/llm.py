"""LLM local opcional (LM Studio ou qualquer servidor compatível com a API da OpenAI), via HTTP simples.

Nunca derruba a execução: erro, timeout ou resposta inválida devolvem None, ficam registrados
na tabela eventos e viram AVISO. Depois de um timeout/erro de conexão o LLM é desligado até o
fim da execução, para não esperar um timeout por candidato.
"""
import hashlib
import json
import re
import time
import urllib.error
import urllib.request

FALHAS_PARA_DESLIGAR = 3  # respostas HTTP de erro seguidas (fora timeout/conexão, que desligam na hora)


def normalizar_url(url):
    url = (url or "").strip().rstrip("/")
    if url and not url.endswith("/v1"):
        url += "/v1"
    return url


def extrair_json(texto):
    """Primeiro objeto JSON do texto, tolerando <think>…</think> e cercas ```json. None se não houver."""
    if not isinstance(texto, str):
        return None
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.S).strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip())
    try:
        return json.loads(texto)
    except ValueError:
        pass
    inicio = texto.find("{")
    while inicio != -1:
        try:
            obj, _ = json.JSONDecoder().raw_decode(texto[inicio:])
            return obj
        except ValueError:
            inicio = texto.find("{", inicio + 1)
    return None


class LLM:
    def __init__(self, cfg, cache, abrir=urllib.request.urlopen, relogio=time.monotonic):
        self.cfg, self.cache, self.abrir, self.relogio = cfg, cache, abrir, relogio
        self.url = normalizar_url(cfg.llm_url)
        self.modelo = cfg.llm_model.strip()
        self.ligado = bool(self.url) and not cfg.sem_llm
        self.avisos = []
        self.chamadas = 0
        self.acertos_cache = 0
        self._falhas = 0

    # ---------------------------------------------------------------- HTTP
    def _http(self, metodo, caminho, corpo=None):
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(f"{self.url}{caminho}", data=dados, method=metodo,
                                     headers={"Content-Type": "application/json"})
        with self.abrir(req, timeout=self.cfg.llm_timeout) as r:
            return r.read().decode("utf-8", "replace")

    def _desligar(self, motivo):
        if self.ligado:
            self.ligado = False
            self.avisos.append(f"LLM desligado nesta execução ({motivo}); segui no modo determinístico.")

    def _resolver_modelo(self):
        if self.modelo:
            return True
        try:
            ids = [m["id"] for m in json.loads(self._http("GET", "/models")).get("data", [])]
        except Exception as e:  # noqa: BLE001 — qualquer falha aqui só desliga o LLM
            self.cache.evento("erro", "llm_indisponivel", f"{self.url}/models", str(e))
            self._desligar(f"não consegui listar modelos em {self.url}: {e}")
            return False
        if not ids:
            self._desligar(f"nenhum modelo carregado em {self.url}")
            return False
        self.modelo = ids[0]
        self.avisos.append(f"FAREJADOR_LLM_MODEL vazio: usando o primeiro modelo do servidor ({self.modelo}).")
        return True

    def _salvar_bruto(self, tipo, chave, registro):
        if not self.cfg.salvar_bruto:
            return
        p = self.cfg.caminho("dados") / "bruto" / f"llm-{tipo}-{chave[:16]}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(registro, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------------------------------------------------------------- núcleo
    def perguntar(self, tipo, prompt, schema, validar):
        """Envia o prompt, valida o JSON e devolve o resultado validado (ou None). Usa cache."""
        if not self.ligado or not self._resolver_modelo():
            return None
        chave = hashlib.sha256(json.dumps([self.modelo, prompt, schema], ensure_ascii=False).encode()).hexdigest()
        guardado = self.cache.get(f"llm:{chave}")
        if guardado is not None:
            self.acertos_cache += 1
            return guardado["valor"]

        corpo = {
            "model": self.modelo,
            "messages": [{"role": "user", "content": prompt}],  # sem "system": alguns templates (Gemma) recusam
            "temperature": 0.2,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": tipo, "strict": True, "schema": schema}},
        }
        registro = {"tipo": tipo, "url": f"{self.url}/chat/completions", "pedido": corpo}
        alvo = f"llm:{tipo}"
        t0 = self.relogio()
        bruto = None
        try:
            self.chamadas += 1
            try:
                bruto = self._http("POST", "/chat/completions", corpo)
            except urllib.error.HTTPError as e:
                if e.code != 400:
                    raise
                # servidor sem suporte a response_format: tenta uma vez sem ele
                self.cache.evento("aviso", "llm", alvo, f"HTTP 400 com response_format; repetindo sem ({e})")
                corpo = {k: v for k, v in corpo.items() if k != "response_format"}
                registro["pedido_sem_response_format"] = corpo
                bruto = self._http("POST", "/chat/completions", corpo)
        except urllib.error.HTTPError as e:
            ms = round((self.relogio() - t0) * 1000)
            self.cache.evento("erro", "llm_erro", alvo, f"HTTP {e.code} em {ms} ms: {e}")
            registro.update(erro=f"HTTP {e.code}: {e}", latencia_ms=ms)
            self._salvar_bruto(tipo, chave, registro)
            self._falhas += 1
            if self._falhas >= FALHAS_PARA_DESLIGAR:
                self._desligar(f"{self._falhas} erros HTTP seguidos")
            return None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            ms = round((self.relogio() - t0) * 1000)
            motivo = getattr(e, "reason", e)
            self.cache.evento("erro", "llm_indisponivel", alvo, f"{motivo} após {ms} ms")
            registro.update(erro=str(motivo), latencia_ms=ms)
            self._salvar_bruto(tipo, chave, registro)
            self._desligar(f"fora do ar ou lento em {self.url}: {motivo}")
            return None

        ms = round((self.relogio() - t0) * 1000)
        registro.update(resposta_crua=bruto, latencia_ms=ms)
        try:
            conteudo = json.loads(bruto)["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            conteudo = None
        valor = validar(extrair_json(conteudo)) if conteudo is not None else None
        registro["valido"] = valor is not None
        self._salvar_bruto(tipo, chave, registro)
        if valor is None:
            self.cache.evento("erro", "llm_invalido", alvo, f"resposta fora do formato em {ms} ms: {str(conteudo)[:300]}")
            self._falhas += 1
            if self._falhas >= FALHAS_PARA_DESLIGAR:
                self._desligar(f"{self._falhas} respostas inválidas seguidas")
            return None
        self._falhas = 0
        self.cache.evento("info", "llm", alvo, f"ok em {ms} ms")
        self.cache.put(f"llm:{chave}", {"valor": valor})
        return valor


# -------------------------------------------------------------------- tarefas
SCHEMA_CONSULTAS = {
    "type": "object",
    "properties": {"consultas": {"type": "array", "items": {"type": "string"}, "minItems": 8, "maxItems": 10}},
    "required": ["consultas"],
    "additionalProperties": False,
}

SCHEMA_NOTA = {
    "type": "object",
    "properties": {"nota": {"type": "integer", "minimum": 0, "maximum": 10}, "justificativa": {"type": "string"}},
    "required": ["nota", "justificativa"],
    "additionalProperties": False,
}

RE_URL = re.compile(r"https?://\S+|www\.\S+")


def _trecho(texto, n=200):
    t = " ".join(RE_URL.sub("", texto or "").split())
    return t[:n] + ("…" if len(t) > n else "")


def prompt_consultas(nome, titulos, tags, descricoes, proibidos):
    linhas = [
        "Você ajuda a descobrir canais do YouTube parecidos com um canal de referência.",
        "Gere de 8 a 10 consultas de busca para o YouTube sobre os TEMAS deste canal, do jeito que alguém "
        "procurando conteúdo parecido digitaria.",
        "Regras:",
        "- PROIBIDO usar o nome do canal, do apresentador, de programas/quadros ou qualquer um destes termos: "
        + ", ".join(proibidos) + ".",
        "- Cada consulta com 2 a 6 palavras, no idioma predominante dos títulos.",
        "- Consultas variadas entre si, sobre o assunto (não sobre o formato, ex.: evite só \"podcast\").",
        'Responda APENAS com JSON no formato {"consultas": ["...", "..."]}, sem texto antes ou depois.',
        "",
        f"Canal: {nome}",
        "Títulos recentes:",
        *[f"- {t}" for t in titulos],
    ]
    if tags:
        linhas.append("Tags: " + ", ".join(tags))
    if descricoes:
        linhas.append("Trechos de descrições:")
        linhas += [f"- {_trecho(d)}" for d in descricoes]
    return "\n".join(linhas)


def validar_consultas(proibido, maximo):
    """proibido(texto) -> True se a consulta usa termo do canal. Retorna a lista limpa ou None."""
    def validar(obj):
        if not isinstance(obj, dict) or not isinstance(obj.get("consultas"), list):
            return None
        vistas, saida = set(), []
        for q in obj["consultas"]:
            if not isinstance(q, str):
                continue
            q = " ".join(q.strip().strip('"').split())
            if not (2 <= len(q.split()) <= 8) or len(q) > 80 or q.lower() in vistas or proibido(q):
                continue
            vistas.add(q.lower())
            saida.append(q)
        return saida[:maximo] or None
    return validar


def prompt_nota(perfil, candidato, titulos):
    return "\n".join([
        "Compare um canal candidato com um canal de referência do YouTube.",
        "Dê uma nota inteira de 0 a 10 para a AFINIDADE TEMÁTICA: o quanto o candidato fala dos mesmos assuntos. "
        "Ignore tamanho, formato e qualidade de produção. 0 = nada a ver; 10 = mesmo nicho.",
        'Responda APENAS com JSON no formato {"nota": 0-10, "justificativa": "uma frase"}, sem texto antes ou depois.',
        "",
        "REFERÊNCIA",
        perfil,
        "",
        f"CANDIDATO: {candidato}",
        "Títulos recentes:",
        *[f"- {t}" for t in titulos],
    ])


def validar_nota(obj):
    if not isinstance(obj, dict):
        return None
    nota, just = obj.get("nota"), obj.get("justificativa")
    if isinstance(nota, bool) or not isinstance(nota, (int, float)) or not 0 <= nota <= 10:
        return None
    if not isinstance(just, str) or not just.strip():
        return None
    return {"nota": round(float(nota), 1), "justificativa": " ".join(just.split())[:240]}
