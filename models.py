from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Float, DateTime, Date
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    watchlists = relationship("Watchlist", back_populates="user")

class Stock(Base):
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, unique=True, index=True)
    company_name = Column(String)
    exchange = Column(String, default="NSE")
    is_index = Column(Boolean, default=False)

    prices = relationship("StockPrice", back_populates="stock")
    predictions = relationship("Prediction", back_populates="stock")
    watchlists = relationship("Watchlist", back_populates="stock")

class Watchlist(Base):
    __tablename__ = "watchlists"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    stock_id = Column(Integer, ForeignKey("stocks.id"))

    user = relationship("User", back_populates="watchlists")
    stock = relationship("Stock", back_populates="watchlists")

class StockPrice(Base):
    __tablename__ = "stock_prices"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"))
    date = Column(Date, index=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)

    stock = relationship("Stock", back_populates="prices")

class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"))
    date = Column(Date)
    prediction = Column(String) # UP / DOWN
    confidence = Column(Float)

    stock = relationship("Stock", back_populates="predictions")
