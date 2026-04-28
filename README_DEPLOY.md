# 部署指南 - Railway 全栈平台

## 📋 前置要求
- GitHub 账号
- Railway 账号（https://railway.app）
- 项目代码已推送到 GitHub

## 🚀 快速部署步骤

### 第一步：准备代码仓库
```bash
# 在项目根目录初始化 git
git init
git add .
git commit -m "Initial commit"
git remote add origin <你的GitHub仓库地址>
git push -u origin main
```

### 第二步：在 Railway 中部署

1. **访问 Railway** https://railway.app
2. **登录** 使用 GitHub 账号登录
3. **新建项目**
   - 点击 "New Project"
   - 选择 "Deploy from GitHub repo"
   - 选择你的项目仓库
4. **添加数据库**
   - 点击 "New" → "Database" → "MySQL"
   - Railway 会自动配置环境变量

### 第三步：配置环境变量

在 Railway 项目设置中添加以下变量：

```env
# JWT 密钥（必须设置！）
SECRET_KEY=your-very-strong-secret-key-change-this-in-production
```

**数据库变量会由 Railway 自动提供，格式如下：**
```env
MYSQLUSER=...
MYSQLPASSWORD=...
MYSQLHOST=...
MYSQLPORT=...
MYSQLDATABASE=...
```

### 第四步：修改后端配置

更新 `backend/database.py` 以支持 Railway 的环境变量命名：

```python
# 数据库配置（支持 Railway 环境变量）
DB_USER = os.getenv("MYSQLUSER", os.getenv("DB_USER", "root"))
DB_PASSWORD = os.getenv("MYSQLPASSWORD", os.getenv("DB_PASSWORD", ""))
DB_HOST = os.getenv("MYSQLHOST", os.getenv("DB_HOST", "localhost"))
DB_PORT = os.getenv("MYSQLPORT", os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("MYSQLDATABASE", os.getenv("DB_NAME", "wenyilu"))
```

### 第五步：部署前端

**选择 A：使用 Vercel 部署前端（推荐）**
1. 访问 https://vercel.com
2. 使用 GitHub 登录
3. 导入你的项目
4. 配置构建命令：`npm run build`
5. 配置输出目录：`dist`
6. 配置环境变量（如果有）
7. 部署！

**选择 B：将前端和后端一起部署**

在项目根目录创建 `package.json` 脚本：

```json
{
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "railway-build": "npm install && npm run build",
    "railway-start": "cd backend && python -m uvicorn main:app --host 0.0.0.0 --port $PORT"
  }
}
```

修改 `main.py` 以提供前端静态文件：

```python
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os

# ... 其他代码 ...

# 挂载静态文件
app.mount("/", StaticFiles(directory="dist", html=True), name="static")
```

## 🔧 本地测试生产环境

```bash
# 1. 构建前端
npm run build

# 2. 启动后端
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8001

# 3. 访问 http://localhost:8001
```

## 📊 监控和调试

- **Railway 日志**：在 Railway 仪表板查看部署日志
- **数据库**：使用 Railway 提供的数据库管理工具
- **性能监控**：Railway 内置监控功能

## 💡 常见问题

### 问题 1：数据库连接失败
- 检查环境变量是否正确
- 确认数据库已创建

### 问题 2：前端无法访问后端 API
- 确保 CORS 配置正确
- 检查 API 地址是否为相对路径

### 问题 3：部署构建失败
- 检查 package.json 脚本
- 确认 requirements.txt 完整

## 💰 费用说明

- **免费额度**：每月 $5 免费额度
- **基础配置**：约 $5-10/月
- **生产环境**：根据使用量计费

## 📞 获取帮助

- Railway 文档：https://docs.railway.app
- FastAPI 文档：https://fastapi.tiangolo.com
- Vue.js 文档：https://vuejs.org
