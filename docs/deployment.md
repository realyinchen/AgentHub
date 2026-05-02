# Deployment Guide

AgentHub provides two deployment methods, choose according to your scenario.

---

## 📦 Option 1: Single Server / Local Deployment (SQLite + sqlite-vec)

> ✅ Zero external dependencies, simplest, default recommended mode

### ⚠️ Important Notice (READ FIRST!)

`docker-compose.yml` uses **absolute paths** to map host directories and `.env` files. You must create these directories manually before starting, otherwise Docker will fail to start.

```
/app/agenthub/
├── backend/
│   ├── .env      ← Must exist
│   └── data/     ← Must exist
└── frontend/
    └── .env      ← Must exist
```

### Deployment Steps

```bash
# 1. Clone the project
git clone https://github.com/realyinchen/AgentHub.git
cd AgentHub

# 2. Create host directories (⭐ Most important step!)
mkdir -p /app/agenthub/backend/data
mkdir -p /app/agenthub/frontend

# 3. Copy environment variable files to the specified location
cp backend/.env.example /app/agenthub/backend/.env
cp frontend/.env.example /app/agenthub/frontend/.env

# 4. Edit backend configuration (fill in your API Keys)
vim /app/agenthub/backend/.env
# TAVILY_API_KEY=your-key
# AMAP_API_KEY=your-key
# ...

# 5. Build images
docker compose build

# 6. Start services
docker compose up -d

# 7. Check running status
docker compose ps
docker compose logs -f
```

**Access URLs**:
- Local: http://localhost
- Server: http://your-server-ip

---

## 🏭 Option 2: Production Environment Deployment (PostgreSQL + Qdrant)

> ✅ High concurrency support, separate frontend and backend deployment

### Prerequisites

Ensure you already have independently running **PostgreSQL** and **Qdrant** services.

---

### Backend Server Configuration

```bash
# 1. Prepare host directories
mkdir -p /app/agenthub/backend/data

# 2. Copy and edit .env
cp backend/.env.example /app/agenthub/backend/.env
vim /app/agenthub/backend/.env
```

**Key Configuration Items**:
```bash
# Switch to PostgreSQL + Qdrant
DATABASE_TYPE=postgres
VECTORSTORE_TYPE=qdrant

# PostgreSQL connection information
POSTGRES_HOST=your-postgresql-server-ip
POSTGRES_PORT=5432
POSTGRES_USER=langchain
POSTGRES_PASSWORD=your-password
POSTGRES_DB=agentdb

# Qdrant connection information
QDRANT_HOST=your-qdrant-server-ip
QDRANT_PORT=6333

# API Keys (Required)
TAVILY_API_KEY=your-key
AMAP_API_KEY=your-key
```

**Start Backend**:
```bash
cd AgentHub/backend
docker build -t agenthub-backend .

docker run -d \
  -p 8080:8080 \
  -v /app/agenthub/backend/.env:/app/.env \
  -v /app/agenthub/backend/data:/app/data \
  --name agenthub-backend \
  --restart unless-stopped \
  agenthub-backend
```

---

### Frontend Server Configuration

```bash
# 1. Prepare directories
mkdir -p /app/agenthub/frontend

# 2. Copy and edit .env
cp frontend/.env.example /app/agenthub/frontend/.env
vim /app/agenthub/frontend/.env
```

**Key Configuration Items**:
```bash
# Point to your backend server address
VITE_API_BASE_URL=http://your-backend-server-ip:8080
```

**Start Frontend**:
```bash
cd AgentHub/frontend
docker build -t agenthub-frontend .

docker run -d \
  -p 80:80 \
  -e NGINX_BACKEND_HOST=your-backend-server-ip \
  -e NGINX_BACKEND_PORT=8080 \
  -v /app/agenthub/frontend/.env:/app/.env \
  --name agenthub-frontend \
  --restart unless-stopped \
  agenthub-frontend
```

---

## 🔧 Common Commands

### Docker Compose Deployment

```bash
# View all service logs
docker compose logs -f

# View specific service logs
docker compose logs -f backend
docker compose logs -f frontend

# Restart services
docker compose restart

# Stop services
docker compose down

# Update deployment
git pull
docker compose build
docker compose up -d

# Check service status
docker compose ps
```

### Independent Container Deployment

```bash
# View logs
docker logs -f agenthub-backend
docker logs -f agenthub-frontend

# Restart containers
docker restart agenthub-backend
docker restart agenthub-frontend

# Stop containers
docker stop agenthub-backend agenthub-frontend

# Delete containers
docker rm agenthub-backend agenthub-frontend
```

---

## ❓ Common Issues

### Q: docker compose up reports "no such file or directory"?

**A**: This is because the `.env` file does not exist on the host. Please ensure you have executed:
```bash
mkdir -p /app/agenthub/backend/data
mkdir -p /app/agenthub/frontend
cp backend/.env.example /app/agenthub/backend/.env
cp frontend/.env.example /app/agenthub/frontend/.env
```

### Q: Frontend cannot connect to backend?

**A**: Check:
1. Is the backend container running normally? `docker ps`
2. Backend health check: `curl http://localhost:8080/health`
3. Is the frontend's `NGINX_BACKEND_HOST` configuration correct?

### Q: How to switch storage mode?

**A**: Edit `/app/agenthub/backend/.env`, modify:
```bash
# SQLite + sqlite-vec
DATABASE_TYPE=sqlite
VECTORSTORE_TYPE=sqlite_vec

# OR PostgreSQL + Qdrant
DATABASE_TYPE=postgres
VECTORSTORE_TYPE=qdrant
```
Then restart backend: `docker compose restart backend`