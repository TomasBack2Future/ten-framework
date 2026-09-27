# Build context: repository root; tman is fetched by gh and SHA256 checked in CI.
FROM ghcr.io/ten-framework/ten_agent_build:0.7.14 AS build
USER root
WORKDIR /workspace
COPY .bootstrap/tools/ten_manager/ /opt/ten_manager/
COPY ai_agents/agents/examples/jev-turn-control/ ai_agents/agents/examples/jev-turn-control/
COPY ai_agents/agents/ten_packages/extension/jev_turn_control_python/ ai_agents/agents/ten_packages/extension/jev_turn_control_python/
COPY ai_agents/agents/ten_packages/extension/websocket_server/ ai_agents/agents/ten_packages/extension/websocket_server/
COPY ai_agents/agents/ten_packages/extension/soniox_asr_python/ ai_agents/agents/ten_packages/extension/soniox_asr_python/
COPY ai_agents/agents/ten_packages/extension/openai_llm2_python/ ai_agents/agents/ten_packages/extension/openai_llm2_python/
COPY ai_agents/agents/ten_packages/extension/cartesia_tts/ ai_agents/agents/ten_packages/extension/cartesia_tts/
ENV TMAN=/opt/ten_manager/bin/tman
WORKDIR /workspace/ai_agents/agents/examples/jev-turn-control
RUN bash scripts/cache-runtime.sh && uv venv --python python3 .venv && task install \
    && uv pip install --python .venv/bin/python 'aiohttp==3.12.15' 'websockets==15.0.1' \
    && cd web && npm ci --omit=dev --ignore-scripts
FROM node:22.21.1-bookworm-slim AS node
FROM python:3.10.18-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/* && ln -s /usr/local/bin/python3 /usr/bin/python3
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=build --chown=1000:1000 /workspace/ /workspace/
WORKDIR /workspace/ai_agents/agents/examples/jev-turn-control
ARG REVISION=development
ENV JEV_REVISION=$REVISION NODE_ENV=production PORT=3000 JEV_MODE=mock
ENV JEV_GRAPH_COMMAND=".venv/bin/python scripts/run_graph.py"
ENV JEV_EVENT_LOG_DIR=/tmp/jev-observations
ENV TEN_PYTHON_LIB_PATH=/usr/local/lib/libpython3.10.so
USER 1000:1000
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=3s CMD node -e "fetch('http://127.0.0.1:3000/healthz').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"
CMD ["node", "web/server.mjs"]
