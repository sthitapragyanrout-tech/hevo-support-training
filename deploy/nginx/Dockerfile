# Builds the React app, then serves it with nginx. Build context: the repo root.
FROM node:22-alpine AS frontend
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=frontend /app/dist /usr/share/nginx/html
# The site config is mounted by docker-compose.prod.yml (http.conf or https.conf).
