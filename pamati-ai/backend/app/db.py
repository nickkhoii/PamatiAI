from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    get_settings().database_url,
    pool_pre_ping=True,
    pool_recycle=1800,
    connect_args={"connect_timeout": 3, "read_timeout": 3, "write_timeout": 3},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session():
    with SessionLocal() as session:
        yield session
