# Frontend

React + Vite 前端（默认代理后端到 `http://127.0.0.1:8080`）。

## 启动

```bash
cd frontend
pnpm install
pnpm dev
```

启动后访问：`http://localhost:5173`

## 说明

- 请先启动后端（默认 `8080` 端口）。
- 如需改后端地址，可设置环境变量：`VITE_API_BASE_URL`（例如 `http://127.0.0.1:8080/api/v1`）。
