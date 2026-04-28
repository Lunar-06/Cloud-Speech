from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import Session
from typing import List
import uvicorn
import os
from pathlib import Path

from database import engine, get_db
from models import Base, User, Post, Comment
from schemas import UserCreate, UserLogin, UserResponse, PostCreate, PostResponse
from auth import create_access_token, verify_password, get_password_hash, verify_token
from routers import auth, posts, users

# 创建数据库表
Base.metadata.create_all(bind=engine)

# 初始化FastAPI应用
app = FastAPI(
    title="文旅电商平台后端API",
    description="为文旅电商平台提供用户认证和帖子管理功能",
    version="1.0.0",
    openapi_tags=[
        {
            "name": "认证",
            "description": "用户注册、登录和认证相关接口"
        },
        {
            "name": "帖子",
            "description": "帖子管理和发布相关接口"
        },
        {
            "name": "用户",
            "description": "用户信息和管理相关接口"
        }
    ]
)

# 添加字符编码中间件
@app.middleware("http")
async def add_charset_header(request: Request, call_next):
    response = await call_next(request)
    if "content-type" in response.headers and "application/json" in response.headers["content-type"]:
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response

# 配置限流器
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # 前端开发服务器地址
        "http://localhost:8001",   # 本地部署地址
        # 生产环境域名（部署后添加）
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(posts.router, prefix="/api/posts", tags=["帖子"])
app.include_router(users.router, prefix="/api/user", tags=["用户"])

# 挂载前端静态文件（部署时使用）
# 检查 dist 目录是否存在
frontend_dist = Path(__file__).parent.parent / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")


@app.get("/")
@limiter.limit("5/minute")
async def root(request: Request):
    return {"message": "文旅电商平台后端API服务运行中"}

@app.get("/api/health")
@limiter.limit("10/minute")
async def health_check(request: Request):
    return {"status": "healthy", "service": "文旅电商平台后端"}

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,  # 改为8001端口避免冲突
        reload=True,
        log_level="info"
    )