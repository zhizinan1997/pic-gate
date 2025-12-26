# 🖼️ PicGate - AI 绘图网关图床

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.100+-green.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License">
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED.svg" alt="Docker">
</p>

PicGate 是一个专为 OpenWebUI 设计的 AI 绘图网关，解决 AI 生成图片无法正确显示的问题。它将 AI 返回的 Base64 图片数据转换为可访问的 URL，并支持本地缓存和 Cloudflare R2 云存储。

## ✨ 核心特性

- 🔄 **Base64 转 URL** - 自动将 AI 返回的 Base64 图片转换为可访问的 HTTP URL
- 💾 **本地缓存** - 图片保存在本地，支持 TTL 自动过期清理
- ☁️ **R2 云存储** - 可选的 Cloudflare R2 存储，永久保存图片
- 🔌 **OpenAI 兼容** - 完全兼容 OpenAI API 格式，无缝对接 OpenWebUI 及其他兼容客户端
- 🛡️ **安全访问** - 支持 API 密钥认证
- 📊 **管理后台** - 完整的中文管理界面
- 🔄 **多轮对话支持** - 支持在多轮对话中修改已生成的图片
- 🎬 **流式交互体验** - 图片生成时实时显示进度，提供优雅的用户反馈

## 🎬 流式响应特性

PicGate 提供了优雅的流式响应体验，让用户在等待 AI 绘图时获得实时反馈：

### 交互式进度展示

```markdown
## 🎨 PicGate 图像处理中心

---

**📥 已接收您的创作请求**

![📷 原图1](https://gate.example.com/images/xxx) ← 显示用户上传的图片

---

⏳ 正在连接 AI 绘图引擎，请稍候...

🔄 **处理中** •• 已用时 3s
🔄 **处理中** ••• 已用时 6s
...

✨ **图像生成成功！** 正在优化输出格式...

---

## 🖼️ 创作完成

![生成的图片](https://gate.example.com/images/result)

💡 _图片已保存，点击可查看大图_
```

### 智能图片请求检测

PicGate 会自动检测以下场景并启用交互式流模式：

| 检测条件       | 示例                                                    |
| -------------- | ------------------------------------------------------- |
| **关键词检测** | "画"、"绘"、"生成图"、"换成"、"变为"、"修改"、"背景" 等 |
| **URL 检测**   | 消息中包含任意 HTTP/HTTPS 链接                          |
| **结构化图片** | OpenAI 格式的 `image_url` 类型内容                      |
| **对话历史**   | 历史消息中包含 PicGate 图片 URL（支持多轮编辑）         |

### 友好的错误提示

当配额用尽或服务异常时，会显示友好的错误提示：

```markdown
## ⚠️ 服务暂时不可用

**nano banana 🍌 绘图配额已用尽**

服务器每 5 小时的绘图配额已全部使用完毕，请稍后再试。

💡 _建议等待一段时间后重新发起请求_
```

## 📸 效果截图

<table>
  <tr>
    <td align="center"><img src="https://raw.githubusercontent.com/zhizinan1997/pic-gate/main/docs/screenshots/dashboard.png" width="400" alt="仪表盘"><br><b>仪表盘</b></td>
    <td align="center"><img src="https://raw.githubusercontent.com/zhizinan1997/pic-gate/main/docs/screenshots/settings.png" width="400" alt="设置"><br><b>设置页面</b></td>
  </tr>
  <tr>
    <td align="center"><img src="https://raw.githubusercontent.com/zhizinan1997/pic-gate/main/docs/screenshots/cache.png" width="400" alt="缓存管理"><br><b>缓存管理</b></td>
    <td align="center"><img src="https://raw.githubusercontent.com/zhizinan1997/pic-gate/main/docs/screenshots/images.png" width="400" alt="图片预览"><br><b>图片预览</b></td>
  </tr>
  <tr>
    <td align="center" colspan="2"><img src="https://raw.githubusercontent.com/zhizinan1997/pic-gate/main/docs/screenshots/logs.png" width="600" alt="系统日志"><br><b>系统日志</b></td>
  </tr>
</table>

## �🚀 快速开始

### Docker 部署（推荐）

```bash
# 使用 GitHub Container Registry
docker pull ghcr.io/zhizinan1997/pic-gate:latest

# 运行容器
docker run -d \
  --name picgate \
  -p 5643:5643 \
  -v picgate-data:/app/data \
  ghcr.io/zhizinan1997/pic-gate:latest
```

### Docker Compose 部署

```yaml
version: "3.8"
services:
  picgate:
    image: ghcr.io/zhizinan1997/pic-gate:latest
    container_name: picgate
    ports:
      - "5643:5643"
    volumes:
      - picgate-data:/app/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5643/health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  picgate-data:
```

### 本地开发

```bash
# 克隆项目
git clone https://github.com/zhizinan1997/pic-gate.git
cd pic-gate

# 安装依赖
pip install -r requirements.txt

# 启动服务
uvicorn app.main:app --host 0.0.0.0 --port 5643 --reload
```

## ⚙️ 初始配置

1. 访问管理后台：`http://localhost:5643/admin`
2. 首次访问会要求创建管理员账户
3. 登录后配置上游 AI API 和网关设置

## 📖 管理后台功能详解

### 🏠 仪表盘

仪表盘页面提供系统状态的整体概览：

<p align="center">
  <img src="docs/screenshots/dashboard.png" width="700" alt="仪表盘">
</p>

| 统计项      | 说明                                  |
| ----------- | ------------------------------------- |
| 📊 总图片数 | 系统中所有图片的数量（包括本地和 R2） |
| 💾 本地缓存 | 本地存储的图片数量                    |
| ☁️ R2 存储  | 已上传到 R2 的图片数量                |
| 📁 磁盘使用 | 本地图片占用的磁盘空间                |
| ⏳ 待上传   | 等待上传到 R2 的图片数量              |
| ❌ 上传失败 | R2 上传失败的图片数量                 |

---

### ⚙️ 设置

设置页面用于配置所有系统参数，支持**自动保存**（修改后 2 秒自动保存）。

<p align="center">
  <img src="docs/screenshots/settings.png" width="700" alt="设置页面">
</p>

#### 🤖 上游 AI API

| 设置项       | 说明                      | 示例                        |
| ------------ | ------------------------- | --------------------------- |
| API 基础 URL | 上游 AI 服务的 API 地址   | `https://api.openai.com/v1` |
| API 密钥     | 上游服务的认证密钥        | `sk-xxx...`                 |
| 模型名称     | 用于图片生成的模型        | `dall-e-3`                  |
| 🔗 测试连接  | 点击验证 API 配置是否正确 | -                           |

#### 🌐 网关配置

| 设置项        | 说明                        | 示例                      |
| ------------- | --------------------------- | ------------------------- |
| 网关模型名称  | 对外暴露的模型名称          | `picgate`                 |
| 网关 API 密钥 | OpenWebUI 连接时使用的密钥  | `pg-xxx...`               |
| 生成密钥      | 自动生成随机密钥            | -                         |
| 公共基础 URL  | 返回给客户端的图片 URL 前缀 | `https://img.example.com` |

#### ☁️ Cloudflare R2 存储

| 设置项            | 说明                              |
| ----------------- | --------------------------------- |
| 账户 ID           | Cloudflare 账户 ID                |
| Access Key ID     | R2 API Token 的 Access Key ID     |
| Secret Access Key | R2 API Token 的 Secret Access Key |
| 存储桶名称        | R2 存储桶名称                     |
| ☁️ 测试连接       | 点击验证 R2 配置是否正确          |

#### ⏰ 缓存配置

| 设置项       | 说明                     | 默认值  |
| ------------ | ------------------------ | ------- |
| 本地缓存 TTL | 本地文件保留时间（小时） | 72 小时 |
| 元数据保留期 | 数据库记录保留时间（天） | 365 天  |

#### 🔐 安全设置

| 设置项                   | 说明                             | 默认值 |
| ------------------------ | -------------------------------- | ------ |
| 允许外部图片获取         | 是否允许下载外部图片 URL         | 关闭   |
| 元数据过期时删除 R2 对象 | 元数据过期时是否同步删除 R2 对象 | 关闭   |

---

### 🗑️ 缓存管理

缓存管理页面用于管理本地图片缓存。

<p align="center">
  <img src="docs/screenshots/cache.png" width="700" alt="缓存管理">
</p>

#### 缓存统计

- **本地图片数**：当前本地存储的图片数量
- **磁盘使用**：本地缓存占用的磁盘空间
- **待上传数**：等待上传到 R2 的图片
- **上传失败数**：R2 上传失败的图片

#### 缓存操作

| 操作                | 说明                                         |
| ------------------- | -------------------------------------------- |
| 🧹 清理过期缓存     | 删除超过 TTL 的本地文件                      |
| 🗑️ 清除所有本地缓存 | 删除所有本地图片（保留 R2 和元数据，可恢复） |
| ☁️ 上传到 R2        | 将待处理的图片上传到 R2                      |
| 🔄 重试失败上传     | 重新尝试上传失败的图片                       |

#### 📦 缓存大小限制

可设置本地缓存的最大大小（MB）。当达到限制时，系统会**自动清理最早的图片**直到低于限制值。

- 设为 `0` 表示不限制
- 进度条显示当前使用量
- 超过 80% 显示黄色警告
- 超过 95% 显示红色警告

---

### 🖼️ 图片预览

图片预览页面提供图片网格浏览和管理功能。

<p align="center">
  <img src="docs/screenshots/images.png" width="700" alt="图片预览">
</p>

#### 功能说明

| 功能     | 说明                             |
| -------- | -------------------------------- |
| 🔄 刷新  | 重新加载图片列表                 |
| 排序选择 | 按创建时间/访问时间/文件大小排序 |
| ☐ 全选   | 选择当前页面所有图片             |
| 🔲 单选  | 勾选单张图片                     |

#### 批量删除

| 操作        | 说明                               |
| ----------- | ---------------------------------- |
| 🗑️ 删除本地 | 仅删除选中图片的本地缓存           |
| ☁️ 删除 R2  | 仅删除选中图片的 R2 存储           |
| ❌ 全部删除 | 删除本地 + R2 + 元数据（不可恢复） |

#### 图片卡片

每张图片显示：

- 缩略图预览
- 图片 ID（前 8 位）
- 文件大小和创建时间
- 存储状态标签：
  - 🟢 **本地**：有本地缓存
  - 🔵 **R2**：已上传到 R2

#### 大图预览

点击图片可查看大图，并可在预览界面直接删除。

---

### 📋 日志

日志页面显示系统运行日志，便于调试和监控。

<p align="center">
  <img src="docs/screenshots/logs.png" width="700" alt="系统日志">
</p>

#### 日志内容

日志按时间倒序显示，包含：

- ⏰ **时间戳**：日志产生时间
- 📊 **级别**：INFO（绿色）、WARNING（黄色）、ERROR（红色）
- 📝 **消息**：详细日志内容

#### 日志类型示例

```
📤 发起文生图请求: prompt=画一只可爱的猫...
📥 上游返回成功: 收到 1 张图片
✅ 文生图完成: a1b2c3d4...
📤 发起对话请求: 3 条消息
📥 上游对话返回成功
✅ 对话图片已保存: e5f6g7h8...
❌ 上游返回错误: HTTP 401
🧹 自动清理: 删除 5 张最早的图片，保持在 500MB 限制内
```

#### 操作按钮

| 按钮        | 说明                  |
| ----------- | --------------------- |
| 🔄 刷新日志 | 手动刷新日志内容      |
| 🗑️ 清除日志 | 清空所有日志记录      |
| ☐ 自动刷新  | 开启后每 5 秒自动刷新 |

---

## 🔌 API 端点

### OpenAI 兼容端点

| 端点                     | 方法 | 说明                          |
| ------------------------ | ---- | ----------------------------- |
| `/v1/models`             | GET  | 获取可用模型列表              |
| `/v1/images/generations` | POST | 文生图接口                    |
| `/v1/images/edits`       | POST | 图片编辑接口                  |
| `/v1/chat/completions`   | POST | 聊天补全（支持图片输入/输出） |

### 图片访问

| 端点                           | 方法 | 说明                    |
| ------------------------------ | ---- | ----------------------- |
| `/images/{image_id}`           | GET  | 访问原图（自动回源 R2） |
| `/images/{image_id}/thumbnail` | GET  | 访问缩略图（仅本地）    |

### 系统端点

| 端点      | 方法 | 说明     |
| --------- | ---- | -------- |
| `/health` | GET  | 健康检查 |

---

## ⚠️ 重要注意事项

### 下游客户端（OpenWebUI 等）

| 注意事项               | 说明                                                    |
| ---------------------- | ------------------------------------------------------- |
| **必须使用非流式请求** | PicGate 目前只支持 `stream: false`，不支持 SSE 流式输出 |
| **API 格式**           | 使用标准 OpenAI 格式请求 PicGate                        |

### 上游 AI API

| 注意事项                       | 说明                                                                                 |
| ------------------------------ | ------------------------------------------------------------------------------------ |
| **推荐使用 OpenAI 格式**       | 通过 one-api/new-api 等中转服务请求 Gemini，避免原生 API 的 `thought_signature` 问题 |
| **避免 Thinking 模型原生 API** | 如 gemini-2.0-flash-thinking 的原生 API 需要 `thought_signature`，PicGate 暂不支持   |
| **支持的响应格式**             | 支持 `message.content` 或 `message.images` 中的 base64 图片                          |

---

## 📡 API 请求示例

### 文生图请求（下游 → PicGate）

```bash
curl -X POST "http://localhost:5643/v1/images/generations" \
  -H "Authorization: Bearer YOUR_GATEWAY_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "picgate",
    "prompt": "一只橘猫在阳光下睡觉",
    "n": 1,
    "size": "1024x1024"
  }'
```

**响应示例：**

```json
{
  "created": 1702468800,
  "data": [
    {
      "url": "https://your-domain.com/images/550e8400-e29b-41d4-a716-446655440000",
      "revised_prompt": "..."
    }
  ]
}
```

### 对话绘图请求（下游 → PicGate）

```bash
curl -X POST "http://localhost:5643/v1/chat/completions" \
  -H "Authorization: Bearer YOUR_GATEWAY_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "picgate",
    "stream": false,
    "messages": [
      {
        "role": "user",
        "content": "画一只猫"
      }
    ]
  }'
```

**响应示例：**

```json
{
  "id": "chatcmpl-xxx",
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": [
          {
            "type": "image_url",
            "image_url": {
              "url": "https://your-domain.com/images/550e8400-e29b-41d4-a716-446655440000"
            }
          }
        ]
      }
    }
  ]
}
```

### 多轮对话（修改图片）

```bash
curl -X POST "http://localhost:5643/v1/chat/completions" \
  -H "Authorization: Bearer YOUR_GATEWAY_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "picgate",
    "stream": false,
    "messages": [
      {
        "role": "user",
        "content": "画一只猫"
      },
      {
        "role": "assistant",
        "content": "![image](https://your-domain.com/images/550e8400-e29b-41d4-a716-446655440000)"
      },
      {
        "role": "user",
        "content": "把猫换成布偶猫，场景保持不变"
      }
    ]
  }'
```

> **多轮对话原理**：PicGate 会自动将历史消息中的图片 URL 转换为 base64 发送给上游 AI，使 AI 能够"看到"之前生成的图片。

---

## 🔄 数据流示意图

```
┌─────────────────┐         ┌─────────────┐         ┌─────────────────┐
│   OpenWebUI     │         │   PicGate   │         │  上游 AI API    │
│   (下游客户端)   │         │   (网关)     │         │  (Gemini 等)    │
└────────┬────────┘         └──────┬──────┘         └────────┬────────┘
         │                         │                         │
         │  1. POST /v1/chat/...   │                         │
         │  stream: false          │                         │
         │ ───────────────────────>│                         │
         │                         │                         │
         │                         │  2. 将 URL 转为 base64   │
         │                         │  POST 上游 API          │
         │                         │ ───────────────────────>│
         │                         │                         │
         │                         │  3. 返回 base64 图片     │
         │                         │ <───────────────────────│
         │                         │                         │
         │                         │  4. 保存图片到本地/R2   │
         │                         │     生成访问 URL        │
         │                         │                         │
         │  5. 返回图片 URL        │                         │
         │ <───────────────────────│                         │
         │                         │                         │
```

---

## 🔧 OpenWebUI 配置

在 OpenWebUI 中添加 PicGate 作为图片生成服务：

1. 打开 OpenWebUI 设置 → 图片
2. 选择 "OpenAI DALL-E"
3. 配置：
   - **API Base URL**: `http://your-picgate-host:5643/v1`
   - **API Key**: 你在 PicGate 设置的网关 API 密钥
   - **Model**: 你在 PicGate 设置的网关模型名称（如 `picgate`）

> ⚠️ **注意**：OpenWebUI 的图片功能默认使用非流式请求，与 PicGate 兼容。

---

## ☁️ Cloudflare R2 配置指南

### 1. 获取账户 ID

1. 登录 [Cloudflare Dashboard](https://dash.cloudflare.com)
2. 左侧菜单选择 **R2 对象存储**
3. 右侧面板可以看到 **账户 ID**

### 2. 创建 R2 存储桶

1. 点击 **创建存储桶**
2. 输入存储桶名称（如 `picgate-images`）
3. 选择位置（建议选择亚太地区）

### 3. 创建 API Token

1. 在 R2 页面，点击 **管理 R2 API Token**
2. 点击 **创建 API Token**
3. 权限选择 **对象读写** 或 **管理员读写**
4. 指定存储桶（可选择所有或特定存储桶）
5. 创建后记录：
   - **Access Key ID**
   - **Secret Access Key**

---

## 🛠️ 技术栈

| 组件        | 技术                    |
| ----------- | ----------------------- |
| 后端框架    | FastAPI                 |
| 数据库      | SQLite + SQLAlchemy     |
| 模板引擎    | Jinja2                  |
| HTTP 客户端 | HTTPX                   |
| 云存储      | Cloudflare R2 (S3 兼容) |
| 容器化      | Docker                  |

---

## 📝 环境变量

| 变量           | 说明             | 默认值                                     |
| -------------- | ---------------- | ------------------------------------------ |
| `HOST`         | 监听地址         | `0.0.0.0`                                  |
| `PORT`         | 监听端口         | `5643`                                     |
| `DATABASE_URL` | 数据库连接字符串 | `sqlite+aiosqlite:///./data/db/picgate.db` |
| `IMAGES_DIR`   | 图片存储目录     | `./data/images`                            |

---

## 🔄 工作流程

```
OpenWebUI
    │
    ▼ (1) 请求绘图 (Base64)
┌─────────────────┐
│    PicGate      │
│                 │
│  ┌───────────┐  │
│  │ 上游 API  │◄─┼── (2) 转发请求
│  └───────────┘  │
│        │        │
│        ▼        │
│  ┌───────────┐  │
│  │ 本地存储  │  │◄── (3) 保存 Base64 为文件
│  └───────────┘  │
│        │        │
│        ▼        │
│  ┌───────────┐  │
│  │  R2 存储  │  │◄── (4) 异步上传到云端
│  └───────────┘  │
│        │        │
└────────┼────────┘
         │
         ▼ (5) 返回图片 URL
    OpenWebUI
         │
         ▼ (6) 请求图片
    ┌─────────────────┐
    │    PicGate      │
    │  /images/{id}   │
    └─────────────────┘
         │
         ▼ (7) 返回图片
    OpenWebUI 显示
```

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

## 📄 许可证

MIT License
