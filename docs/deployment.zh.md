# 部署指南

AgentHub 提供两种部署方式，根据你的场景选择。

---

## 📦 方式一：单服务器/本地部署（SQLite + sqlite-vec）

> ✅ 零外部依赖，最简单，默认推荐模式

### ⚠️ 重要提醒（必读！）

`docker-compose.yml` 使用 **绝对路径** 映射宿主机目录和 `.env` 文件，启动前必须手动创建以下目录，否则 Docker 会启动失败。

```
/app/agenthub/
├── backend/
│   ├── .env      ← 必须存在
│   └── data/     ← 必须存在
└── frontend/
    └── .env      ← 必须存在
```

### 部署步骤

```bash
# 1. 克隆项目
git clone https://github.com/realyinchen/AgentHub.git
cd AgentHub

# 2. 创建宿主机目录（⭐ 最重要的一步）
mkdir -p /app/agenthub/backend/data
mkdir -p /app/agenthub/frontend

# 3. 拷贝环境变量文件到指定位置
cp backend/.env.example /app/agenthub/backend/.env
cp frontend/.env.example /app/agenthub/frontend/.env

# 4. 编辑后端配置（填入你的 API Keys）
vim /app/agenthub/backend/.env
# TAVILY_API_KEY=your-key
# AMAP_API_KEY=your-key
# ...

# 5. 构建镜像
docker compose build

# 6. 启动服务
docker compose up -d

# 7. 查看运行状态
docker compose ps
docker compose logs -f
```

**访问地址**：
- 本地：http://localhost
- 服务器：http://你的服务器IP

---

## 🏭 方式二：生产环境部署（PostgreSQL + Qdrant）

> ✅ 高并发支持，前后端分离部署

### 前置准备

确保你已经有独立运行的 **PostgreSQL** 和 **Qdrant** 服务。

---

### 后端服务器配置

```bash
# 1. 准备宿主机目录
mkdir -p /app/agenthub/backend/data

# 2. 拷贝并编辑 .env
cp backend/.env.example /app/agenthub/backend/.env
vim /app/agenthub/backend/.env
```

**关键配置项**：
```bash
# 切换到 PostgreSQL + Qdrant
DATABASE_TYPE=postgres
VECTORSTORE_TYPE=qdrant

# PostgreSQL 连接信息
POSTGRES_HOST=你的PostgreSQL服务器IP
POSTGRES_PORT=5432
POSTGRES_USER=langchain
POSTGRES_PASSWORD=你的密码
POSTGRES_DB=agentdb

# Qdrant 连接信息
QDRANT_HOST=你的Qdrant服务器IP
QDRANT_PORT=6333

# API Keys（必需）
TAVILY_API_KEY=your-key
AMAP_API_KEY=your-key
```

**启动后端**：
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

### 前端服务器配置

```bash
# 1. 准备目录
mkdir -p /app/agenthub/frontend

# 2. 拷贝并编辑 .env
cp frontend/.env.example /app/agenthub/frontend/.env
vim /app/agenthub/frontend/.env
```

**关键配置项**：
```bash
# 指向你的后端服务器地址
VITE_API_BASE_URL=http://你的后端服务器IP:8080
```

**启动前端**：
```bash
cd AgentHub/frontend
docker build -t agenthub-frontend .

docker run -d \
  -p 80:80 \
  -e NGINX_BACKEND_HOST=你的后端服务器IP \
  -e NGINX_BACKEND_PORT=8080 \
  -v /app/agenthub/frontend/.env:/app/.env \
  --name agenthub-frontend \
  --restart unless-stopped \
  agenthub-frontend
```

---

## 🔧 常用命令

### Docker Compose 部署

```bash
# 查看所有服务日志
docker compose logs -f

# 查看特定服务日志
docker compose logs -f backend
docker compose logs -f frontend

# 重启服务
docker compose restart

# 停止服务
docker compose down

# 更新部署
git pull
docker compose build
docker compose up -d

# 查看服务状态
docker compose ps
```

### 独立容器部署

```bash
# 查看日志
docker logs -f agenthub-backend
docker logs -f agenthub-frontend

# 重启容器
docker restart agenthub-backend
docker restart agenthub-frontend

# 停止容器
docker stop agenthub-backend agenthub-frontend

# 删除容器
docker rm agenthub-backend agenthub-frontend
```

---

## ❓ 常见问题

### Q: docker compose up 报错 "no such file or directory"？

**A**: 这是因为宿主机上的 `.env` 文件不存在。请确保你已经执行了：
```bash
mkdir -p /app/agenthub/backend/data
mkdir -p /app/agenthub/frontend
cp backend/.env.example /app/agenthub/backend/.env
cp frontend/.env.example /app/agenthub/frontend/.env
```

### Q: 前端连接不上后端？

**A**: 检查：
1. 后端容器是否正常运行：`docker ps`
2. 后端健康检查：`curl http://localhost:8080/health`
3. 前端的 `NGINX_BACKEND_HOST` 配置是否正确

### Q: 如何切换存储模式？

**A**: 编辑 `/app/agenthub/backend/.env`，修改：
```bash
# SQLite + sqlite-vec
DATABASE_TYPE=sqlite
VECTORSTORE_TYPE=sqlite_vec

# 或 PostgreSQL + Qdrant
DATABASE_TYPE=postgres
VECTORSTORE_TYPE=qdrant
```
然后重启后端：`docker compose restart backend`