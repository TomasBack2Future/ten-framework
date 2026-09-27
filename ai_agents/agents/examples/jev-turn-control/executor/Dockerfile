FROM python:3.12-slim
RUN useradd --create-home --uid 10001 executor
WORKDIR /opt/jev
COPY requirements-sdk.txt /tmp/requirements-sdk.txt
RUN pip install --no-cache-dir -r /tmp/requirements-sdk.txt
COPY . /opt/jev/executor
RUN mkdir -p /work/artifacts /work/codex && chown -R executor:executor /work
USER 10001:10001
ENV CODEX_HOME=/work/codex
ENV HOME=/work
ENV PYTHONPATH=/opt/jev
WORKDIR /work
CMD ["python", "-m", "executor.probe", "--output", "/work/probe.json"]
