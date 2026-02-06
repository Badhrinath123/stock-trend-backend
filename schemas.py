from pydantic import BaseModel
from typing import List, Optional
from datetime import date

class UserBase(BaseModel):
    username: str
    email: Optional[str] = None

class UserCreate(UserBase):
    password: str
    email: str

class User(UserBase):
    id: int
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class StockBase(BaseModel):
    symbol: str
    company_name: str
    exchange: Optional[str] = "NSE"
    is_index: Optional[bool] = False

class StockCreate(StockBase):
    pass

class Stock(StockBase):
    id: int
    class Config:
        from_attributes = True

class WatchlistBase(BaseModel):
    stock_id: int

class WatchlistCreate(WatchlistBase):
    pass

class Watchlist(WatchlistBase):
    id: int
    user_id: int
    stock: Stock
    class Config:
        from_attributes = True

class PredictionBase(BaseModel):
    stock_id: int
    date: date
    prediction: str
    confidence: float

class Prediction(PredictionBase):
    id: int
    stock_name: Optional[str] = None # Helper for UI
    class Config:
        from_attributes = True
