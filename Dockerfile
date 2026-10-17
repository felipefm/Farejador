# Farejador — imagem enxuta. O código também pode vir montado por volume (ver docker-compose.yml),
# e aí basta salvar o arquivo para o uvicorn recarregar; rebuild só quando mudar um requirements*.txt.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FAREJADOR_DADOS=/data \
    FAREJADOR_EXCLUDE=/data/exclude.txt \
    DENO_DIR=/tmp/deno \
    HOME=/tmp

WORKDIR /app
COPY requirements.txt requirements-web.txt ./
# yt-dlp[default,deno]: traz o yt-dlp-ejs e o binário do deno (runtime JS que o yt-dlp exige para o YouTube)
RUN pip install -r requirements.txt -r requirements-web.txt && deno --version

COPY farejador/ farejador/
COPY farejador.py ./

VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "--factory", "farejador.web:criar_app", "--host", "0.0.0.0", "--port", "8000"]
