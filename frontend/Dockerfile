# Frontend Dockerfile for AgentHub
# Stage 1: Build the React application
FROM node:25-alpine AS builder

# Set working directory
WORKDIR /app

# Copy package files first (leverage Docker layer cache)
COPY package.json package-lock.json* pnpm-lock.yaml* ./

# Install dependencies - use ci for cleaner, reproducible installs (prefer npm ci)
RUN npm ci --ignore-scripts || npm install --ignore-scripts

# Copy source code
COPY . .

# Build argument for API URL
ARG VITE_API_BASE_URL=http://localhost:8080/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# Build the application
RUN npm run build

# Stage 2: Serve with Nginx
FROM nginx:stable-alpine3.23-perl

# Build arguments for backend configuration (used as defaults)
ARG NGINX_BACKEND_HOST=host.docker.internal
ARG NGINX_BACKEND_PORT=8080

# Set environment variables with defaults (can be overridden at runtime via -e)
ENV NGINX_BACKEND_HOST=${NGINX_BACKEND_HOST}
ENV NGINX_BACKEND_PORT=${NGINX_BACKEND_PORT}

# Copy custom nginx configuration template
COPY nginx.conf /etc/nginx/nginx.conf.template

# Copy built static files from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Create startup script that substitutes env vars and starts nginx
RUN echo '#!/bin/sh' > /docker-entrypoint.sh && \
    echo 'set -e' >> /docker-entrypoint.sh && \
    echo '' >> /docker-entrypoint.sh && \
    echo '# Substitute environment variables in nginx config' >> /docker-entrypoint.sh && \
    echo 'envsubst '"'"'$NGINX_BACKEND_HOST $NGINX_BACKEND_PORT'"'"' < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf' >> /docker-entrypoint.sh && \
    echo '' >> /docker-entrypoint.sh && \
    echo '# Create nginx pid directory and set permissions' >> /docker-entrypoint.sh && \
    echo 'mkdir -p /run' >> /docker-entrypoint.sh && \
    echo 'chown -R nginx:nginx /run' >> /docker-entrypoint.sh && \
    echo '' >> /docker-entrypoint.sh && \
    echo '# Start nginx (nginx.conf has user nginx directive)' >> /docker-entrypoint.sh && \
    echo 'exec nginx -g "daemon off;"' >> /docker-entrypoint.sh && \
    chmod +x /docker-entrypoint.sh

# Set permissions for nginx user
RUN chown -R nginx:nginx /usr/share/nginx/html && \
    chmod -R 755 /usr/share/nginx/html && \
    chown -R nginx:nginx /var/cache/nginx /var/log/nginx /etc/nginx/conf.d /etc/nginx/nginx.conf.template

# Expose port
EXPOSE 80

# Run as root to allow entrypoint to write config
# nginx.conf has 'user nginx' directive so worker processes run as nginx user
USER root

# Start Nginx with env substitution
CMD ["/docker-entrypoint.sh"]
