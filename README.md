# PicGate - OpenWebUI AI 绘图网关

🖼️ 面向 OpenWebUI 的 AI 绘图网关/中转 + 本地缓存 + R2 归档 + 管理后台

## 功能特性

- **OpenAI 兼容 API** - 对 OpenWebUI 暴露标准的 `/v1/*` 接口
- **URL→Base64 转换** - 自动将图片 URL 转换为 base64 后发送到上游 AI
- **本地缓存** - 生成的图片先存本地，返回 URL 给 OpenWebUI
- **R2 云存储** - 异步上传到 Cloudflare R2 长期归档
- **TTL 清理** - 自动清理过期的本地缓存
- **R2 回源** - 本地缺失时自动从 R2 下载
- **管理后台** - Web 界面配置所有设置

## 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone https://github.com/your-repo/pic-gate.git
cd pic-gate

# 复制环境变量
cp .env.example .env

# 安装依赖
pip install -r requirements.txt
```

### 2. 启动服务

```bash
# 开发模式
python -m uvicorn app.main:app --host 0.0.0.0 --port 5643 --reload

# 生产模式
python -m uvicorn app.main:app --host 0.0.0.0 --port 5643
```

### 3. 初始设置

1. 访问 `http://localhost:5643/admin`
2. 创建管理员账号
3. 配置上游 AI API（API Base URL、API Key、模型名）
4. 配置网关（模型名、API Key）
5. **重要**：配置 `公开基础 URL`（见下文）

## 配置说明

### 公开基础 URL（重要！）

`public_base_url` 控制返回给 OpenWebUI 的图片 URL 域名：

| 场景             | 设置值                    |
| ---------------- | ------------------------- |
| 同机运行，无反代 | `http://服务器IP:5643`    |
| 使用反向代理     | `https://img.example.com` |
| 留空             | 自动从请求头推断          |

**反向代理用户必须设置此项！** 否则图片 URL 可能不正确。

### OpenWebUI 配置

在 OpenWebUI 中添加图片生成模型：

1. 进入 管理 → 设置 → 图片
2. 设置 URL：`http://picgate-ip:5643/v1`
3. 设置 API Key：（管理后台生成的网关 API Key）
4. 设置模型：（管理后台配置的网关模型名，默认 `picgate`）

## Docker 部署

```bash
# 构建镜像
docker build -t picgate .

# 运行容器
docker run -d \
  --name picgate \
  -p 5643:5643 \
  -v picgate-data:/app/data \
  picgate
```

### Docker Compose

```yaml
version: "3.8"
services:
  picgate:
    build: .
    ports:
      - "5643:5643"
    volumes:
      - picgate-data:/app/data
    environment:
      - HOST=0.0.0.0
      - PORT=5643
    restart: unless-stopped

volumes:
  picgate-data:
```

## 反向代理配置

### Nginx

```nginx
server {
    listen 443 ssl;
    server_name img.example.com;

    location / {
        proxy_pass http://127.0.0.1:5643;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
    }
}
```

### Caddy

```caddyfile
img.example.com {
    reverse_proxy localhost:5643
}
```

## API 端点

### Gateway API（需要 Bearer 认证）

| 端点                          | 说明                 |
| ----------------------------- | -------------------- |
| `GET /v1/models`              | 获取可用模型列表     |
| `POST /v1/images/generations` | 文生图               |
| `POST /v1/images/edits`       | 图生图/编辑          |
| `POST /v1/chat/completions`   | 多轮对话（支持图片） |

### 图片服务

| 端点                     | 说明                     |
| ------------------------ | ------------------------ |
| `GET /images/{image_id}` | 获取图片（本地/R2 回源） |

### 管理后台

| 端点                   | 说明         |
| ---------------------- | ------------ |
| `GET /admin`           | 管理后台入口 |
| `GET /admin/dashboard` | 仪表盘       |
| `GET /admin/settings`  | 配置设置     |
| `GET /admin/cache`     | 缓存管理     |

## Cloudflare R2 配置（详细教程）

Cloudflare R2 是一个 S3 兼容的对象存储服务，用于图片的长期归档。以下是详细的申请和配置步骤。

### 步骤 1：注册/登录 Cloudflare

1. 访问 [Cloudflare Dashboard](https://dash.cloudflare.com/)
2. 注册新账号或登录已有账号
3. 完成邮箱验证

### 步骤 2：获取 Account ID

1. 登录后，在左侧菜单点击 **R2 对象存储**
2. 如果首次使用，需要点击 **开始使用** 激活 R2
3. 在 R2 概览页面，右侧会显示 **账户 ID (Account ID)**
4. 复制此 ID（格式类似：`a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6`）

> 💡 **提示**：Account ID 也可以在任意域名的概览页面右下角找到

### 步骤 3：创建 R2 存储桶

1. 在 R2 页面点击 **创建存储桶**
2. 输入存储桶名称（例如：`picgate-images`）
   - 名称只能包含小写字母、数字和连字符
   - 名称需全局唯一
3. 选择位置（建议选择靠近您服务器的区域）
   - **自动** - Cloudflare 自动选择最优位置
   - 或选择特定区域如 `亚太地区`
4. 点击 **创建存储桶**

### 步骤 4：创建 R2 API 令牌

这是获取 Access Key ID 和 Secret Access Key 的关键步骤：

1. 在 R2 页面，点击右侧的 **管理 R2 API 令牌**
2. 点击 **创建 API 令牌**
3. 配置令牌：
   - **令牌名称**：输入一个描述性名称（如 `picgate-token`）
   - **权限**：选择 **对象读和写**（这允许上传和下载）
   - **指定存储桶**：
     - 选择 **仅应用于特定存储桶**
     - 选择刚创建的存储桶（如 `picgate-images`）
   - **TTL**：可选，设置令牌有效期（留空为永久）
4. 点击 **创建 API 令牌**
5. **重要**：立即复制显示的凭证：
   - **Access Key ID** 访问密钥 ID （格式：`xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`）
   - **Secret Access Key** 机密访问密钥（只显示一次！格式：`xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`）

> ⚠️ **警告**：Secret Access Key 只会显示一次，请务必立即保存！如果丢失，需要重新创建令牌。

### 步骤 5：在 PicGate 中配置

1. 访问 PicGate 管理后台 → **设置**
2. 找到 **Cloudflare R2 存储** 部分
3. 填入以下信息：

| 字段              | 说明                      | 示例                               |
| ----------------- | ------------------------- | ---------------------------------- |
| Account ID        | 步骤 2 获取的账户 ID      | `a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6` |
| Access Key ID     | 步骤 4 创建的访问密钥 ID  | `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| Secret Access Key | 步骤 4 创建的秘密访问密钥 | `xxxxxxxx...`                      |
| Bucket Name       | 步骤 3 创建的存储桶名称   | `picgate-images`                   |

4. 点击 **保存设置**

### 验证配置

配置完成后，可以通过以下方式验证：

1. 在管理后台生成一张测试图片
2. 进入 **缓存管理** 页面
3. 点击 **上传到 R2** 按钮
4. 查看是否有上传成功的提示

### R2 存储结构

图片会以以下格式存储在 R2 中：

```
{bucket-name}/
└── openwebui/
    ├── {image-id-1}.png
    ├── {image-id-2}.png
    └── ...
```

### R2 免费额度

Cloudflare R2 提供慷慨的免费额度：

| 项目     | 免费额度             |
| -------- | -------------------- |
| 存储空间 | 10 GB/月             |
| A 类操作 | 100 万次/月（写入）  |
| B 类操作 | 1000 万次/月（读取） |
| 出站流量 | 免费（无出站费用！） |

对于大多数个人使用场景，免费额度完全够用。

## 数据目录

```
data/
├── db/
│   └── picgate.db      # SQLite 数据库
└── images/
    └── *.png           # 本地缓存的图片
```

## 技术栈

- **Python 3.11+**
- **FastAPI** - Web 框架
- **SQLAlchemy** - ORM
- **SQLite** - 数据库
- **boto3** - R2 (S3) 客户端
- **httpx** - HTTP 客户端
- **Jinja2** - 模板引擎

## 许可证

MIT License
