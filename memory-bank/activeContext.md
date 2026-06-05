# Active Context

## Current Focus

**URL 参数与认证系统整合** (June 4, 2026)

### 实现目标

1. 打开主页 `localhost:5173` 必须是登录页面（Jack、Rose + 微信二维码）
2. 登录后进入聊天界面，URL 变为 `localhost:5173?userId=xxxx`
3. 进入会话后，URL 变为 `localhost:5173?userId=xxxx&thread_id=xxx`

### URL 结构

| 场景 | URL |
|------|-----|
| 未登录（首页） | `localhost:5173` |
| 登录后（无会话） | `localhost:5173?userId=xxxx` |
| 进入会话 | `localhost:5173?userId=xxxx&thread_id=xxx` |

### 认证系统整合

系统现在支持两种认证方式：
- **Jack/Rose Mock 用户**：通过 `useUser` hook 管理，userId 存储在 localStorage + URL
- **微信登录用户**：通过 `AuthContext` 管理，JWT 存储在 cookie，userId 从后端 `/api/v1/auth/status` 获取

判断逻辑：
```typescript
// Priority: URL userId > mock userId > AuthContext
const effectiveUserId = userId || (authUser?.id) || null
const isLoggedIn = !!effectiveUserId || isAuthenticated
```

### 修改的文件

1. **`frontend/src/features/chat/utils.ts`**
   - 添加 `readUserIdFromUrl()` 函数
   - 添加 `writeToUrl(userId, threadId)` 函数

2. **`frontend/src/hooks/use-user.ts`**
   - 从 URL 读取 userId，同步到 localStorage
   - 登录时写入 URL 参数

3. **`frontend/src/App.tsx`**
   - 导入 `useAuth` 和 URL 工具函数
   - 整合两种认证方式的判断逻辑
   - 使用 `writeUrl` 替代原来的 `writeThreadIdToUrl`
   - 添加 `isAuthLoading` 加载状态
   - 使用 `isLoggedIn` 判断是否显示首页

4. **`backend/app/api/v1/weixin.py`**
   - WebSocket 返回数据添加 `user_id` 字段

5. **`frontend/src/channels/weixin/WeixinQRCode.tsx`**
   - 接收 `user_id` 并写入 URL
   - 移除 `react-router-dom` 的 `useNavigate`，改用 `window.location.reload()`

---

## Previous Focus

**微信扫码登录功能简化重构** (June 4, 2026)

### 简化后的架构

核心原则：**简洁优先，减少抽象**

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend                                  │
├─────────────────────────────────────────────────────────────────┤
│  HomePage.tsx → WeixinQRCode.tsx (内联组件)                      │
│       ↓ WebSocket连接                                           │
│  AuthContext.tsx (用户状态管理)                                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓ WebSocket
┌─────────────────────────────────────────────────────────────────┐
│                        Backend                                   │
├─────────────────────────────────────────────────────────────────┤
│  /ws/weixin/auth         → WebSocket QR码登录 (内联逻辑)          │
│  /api/v1/chat/*          → 会话列表/历史 (过滤微信线程)           │
│  channels/weixin/service → iLink API 封装                        │
│  services/weixin_listener → 消息循环 (无 WebSocket 管理)         │
└─────────────────────────────────────────────────────────────────┘
```

### 关键简化点

1. **移除 WeixinLoginDialog/WeixinLoginButton** — 用单一 `WeixinQRCode` 组件替代
2. **首页直接嵌入二维码** — 无需点击按钮，扫码即登录
3. **WebSocket 逻辑内联** — 所有登录逻辑在 `weixin.py` 端点中，无额外服务类
4. **Listener 只负责消息循环** — 移除 WebSocket 管理代码
5. **微信线程完全过滤** — Web UI 无法访问微信会话，防止数据冲突

### 文件变更

**简化后的文件结构：**
```
frontend/src/channels/weixin/
├── index.ts              # 只导出 WeixinQRCode
├── WeixinQRCode.tsx      # 内联二维码组件 (替代 Dialog + Button)
└── service.ts            # iLink API 客户端 (不变)

backend/app/
├── api/v1/weixin.py      # WebSocket 端点 (内联登录逻辑)
├── services/weixin_listener.py  # 消息循环 (简化)
└── crud/user_channel.py  # 新增: is_weixin_thread() 过滤函数
```

**已删除：**
- `frontend/src/channels/weixin/WeixinLoginDialog.tsx`
- `frontend/src/channels/weixin/WeixinLoginButton.tsx`

### 微信线程统一

**设计决策：** 微信会话与 Web UI 会话一视同仁，用户可以在 Web UI 查看和继续微信对话。

**实现方式：**
- 微信消息通过 `weixin_listener.py` 接收并存储到 LangGraph checkpointer
- Web UI 通过 `/history/{thread_id}` 和 `/conversations` 端点访问所有会话
- 所有会话（包括微信）共享相同的 `thread_id` 机制

---

### 认证流程 (简化版)

```
1. 用户打开首页 → 立即显示二维码 (120秒刷新)
2. WebSocket 连接 → 后端获取 QR 码 → 推送给前端
3. 后端轮询扫码状态 (scaned → confirmed)
4. 确认后:
   - 创建/查找用户 (user_channels 表)
   - 生成 JWT
   - 启动消息循环 (create_listener)
   - 返回 token + user_id 给前端
5. 前端直接登录:
   - 存储 JWT 到 cookie
   - 写入 userId 到 URL
   - 刷新页面进入聊天界面
```

### WebSocket 协议

```json
// Server → Client
{"type": "qrcode", "qrcode": "xxx", "qrcode_img": "https://..."}
{"type": "scaned"}
{"type": "confirmed", "token": "jwt-xxx", "thread_id": "uuid"}
{"type": "expired"}
{"type": "error", "message": "xxx"}
```

### 待完成

- [ ] 测试完整登录流程
- [ ] 测试微信消息收发

---

## Previous Focus

**微信扫码登录功能实现** (June 4, 2026)

### 核心架构 (已简化)
实现了通过个人微信扫码注册/登录 AgentHub 的完整功能，基于腾讯 iLink Bot API。

### 数据库设计 (不变)

```sql
-- 用户表
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name VARCHAR(64) NOT NULL,
    avatar_url VARCHAR(512),
    is_mock_user BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 用户渠道绑定表
CREATE TABLE user_channels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel VARCHAR(32) NOT NULL,           -- 'weixin', 'telegram', etc.
    channel_user_id VARCHAR(128) NOT NULL,  -- 'xxx@im.wechat'
    channel_token TEXT,                      -- Bot token (加密存储)
    channel_base_url VARCHAR(512),           -- API base URL
    channel_token_expires_at TIMESTAMPTZ,
    UNIQUE(channel, channel_user_id)
);
```

---

## Active Decisions

- **微信线程统一** — 微信会话与 Web UI 会话一视同仁，用户可以在 Web UI 查看和继续微信对话
- **首页直接扫码** — 无需点击按钮，用户体验更流畅
- **120秒自动刷新** — 二维码过期后自动重新获取
- **每登录一个 Listener** — 每个微信登录会话独立的消息循环

## Active Branches

- Main development on `main` branch