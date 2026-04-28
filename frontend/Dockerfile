# Frontend Dockerfile for AgentHub
# Stage 1: Build the React application
FROM node:24 AS builder

WORKDIR /app

COPY package.json package-lock.json* pnpm-lock.yaml* ./
RUN npm install --ignore-scripts

COPY . .

ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

# Stage 2: Serve with Nginx
FROM nginx:stable-alpine3.23-perl

ARG NGINX_BACKEND_HOST=host.docker.internal
ARG NGINX_BACKEND_PORT=8080

ENV NGINX_BACKEND_HOST=${NGINX_BACKEND_HOST}
ENV NGINX_BACKEND_PORT=${NGINX_BACKEND_PORT}

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=builder /app/dist /usr/share/nginx/html

RUN chown -R nginx:nginx /usr/share/nginx/html \
    && chmod -R 755 /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]