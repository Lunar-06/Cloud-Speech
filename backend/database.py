from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载环境变量（显式指定路径）
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

# 数据库配置（支持 Railway 环境变量格式）
DB_USER = os.getenv("MYSQLUSER", os.getenv("DB_USER", "root"))
DB_PASSWORD = os.getenv("MYSQLPASSWORD", os.getenv("DB_PASSWORD", ""))
DB_HOST = os.getenv("MYSQLHOST", os.getenv("DB_HOST", "localhost"))
DB_PORT = os.getenv("MYSQLPORT", os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("MYSQLDATABASE", os.getenv("DB_NAME", "wenyilu"))

# MySQL 连接字符串
SQLALCHEMY_DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"

# 创建数据库引擎
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=True  # 开发时开启SQL日志
)

# 创建SessionLocal类
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 创建Base类
Base = declarative_base()

# 依赖注入函数
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()