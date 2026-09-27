FROM node:22.21.1-alpine3.22
WORKDIR /app/web
COPY web/package*.json ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force
COPY web/ ./
COPY fixtures/ /app/fixtures/
ARG REVISION=development
ENV NODE_ENV=production JEV_REVISION=$REVISION PORT=3000
USER node
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=3s CMD node -e "fetch('http://127.0.0.1:3000/healthz').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"
CMD ["node", "server.mjs"]
