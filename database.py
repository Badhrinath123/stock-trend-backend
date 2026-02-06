from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Use SQLite for simplicity in this demo, easily swappable to Postgres
# SQLALCHEMY_DATABASE_URL = "sqlite:///./stock_app.db"
SQLALCHEMY_DATABASE_URL = "postgresql+psycopg2://postgres:2210@localhost:5432/stock_trend_db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
