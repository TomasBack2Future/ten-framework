# Build separately from the WS image. The base image is pinned by the deployer.
ARG WS_IMAGE
FROM ${WS_IMAGE} AS build
USER root
COPY .bootstrap/tools/ten_manager/ /opt/ten_manager/
COPY ai_agents/agents/examples/jev-demo-rtc/ /workspace/ai_agents/agents/examples/jev-demo-rtc/
ENV TMAN=/opt/ten_manager/bin/tman
WORKDIR /workspace/ai_agents/agents/examples/jev-demo-rtc
# The release build must supply a lockfile produced from the pinned package.json.
RUN test -f web/package-lock.json \
    && cd tenapp && /opt/ten_manager/bin/tman -y install
# Reuse the exact installed Python environment of the immutable WS base image.
RUN ln -s ../jev-turn-control/.venv .venv
FROM node:22.21.1-bookworm-slim AS js
WORKDIR /web
COPY ai_agents/agents/examples/jev-demo-rtc/web/package*.json ./
RUN npm ci --omit=dev --ignore-scripts
FROM build
COPY --from=js --chown=1000:1000 /web/node_modules/ web/node_modules/
RUN chown -R 1000:1000 /workspace/ai_agents/agents/examples/jev-demo-rtc
ARG REVISION=development
ENV JEV_REVISION=$REVISION PORT=3000 JEV_MODE=live
ENV JEV_GRAPH_COMMAND=".venv/bin/python scripts/run_graph.py"
ENV AGORA_APP_ID=518383bde9d44172961da1595e982189
USER 1000:1000
EXPOSE 3000
CMD ["node", "web/server.mjs"]
