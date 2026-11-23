# API + Streamlit app. Models and the corpus embeddings are baked in at build time, so the
# container answers search and calculate requests with no network and no account.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" HF_HOME=/opt/hf HF_HUB_DISABLE_PROGRESS_BARS=1
WORKDIR /srv
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --group app --no-install-project
COPY src ./src
COPY prompts ./prompts
COPY config ./config
COPY corpus/processed ./corpus/processed
COPY app ./app
RUN uv sync --frozen --no-dev --group app \
 && python -c "from rtc.retrieve import Retriever; from rtc.retrieve.pipeline import reranker; Retriever.load('dispositivo'); reranker()"
RUN useradd --create-home app && mkdir -p /srv/.cache/llm && chown -R app /srv/.cache /opt/hf
USER app
EXPOSE 8000 8501
CMD ["uvicorn", "rtc.api:app", "--host", "0.0.0.0", "--port", "8000"]
