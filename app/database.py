from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

DB_PATH = os.getenv("XTREAM_DB_PATH", "sqlite:///./xtream.db")

engine = create_engine(
    DB_PATH,
    connect_args={"check_same_thread": False} if DB_PATH.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
