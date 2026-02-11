from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import models, database, schemas, crud, auth
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import yfinance as yf

import random
import string
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv

load_dotenv()

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="Stock Trend Prediction API")

# CORS for frontend
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    os.getenv("FRONTEND_URL"), # Production URL from Vercel
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin for origin in origins if origin], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Auth Routes ---
@app.post("/token", response_model=schemas.Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(database.get_db)):
    user = crud.get_user_by_username(db, username=form_data.username)
    if not user or not auth.verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = auth.create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/register", response_model=schemas.User)
def register_user(user: schemas.UserCreate, db: Session = Depends(database.get_db)):
    db_user = crud.get_user_by_username(db, username=user.username)
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    return crud.create_user(db=db, user=user)

@app.get("/users/me", response_model=schemas.User)
async def read_users_me(current_user: schemas.User = Depends(auth.get_current_user)):
    return current_user

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests


GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "1009501543323-240mm0oj17urabqn3htf4lc1g79edt37.apps.googleusercontent.com")

@app.post("/auth/google", response_model=schemas.Token)
async def google_login(token_data: dict, db: Session = Depends(database.get_db)):
    token = token_data.get("token")
    if not token:
        raise HTTPException(status_code=400, detail="Token is missing")
        
    try:
        # Verify the ID token
        idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), GOOGLE_CLIENT_ID)
        
        # ID token is valid. Get user info.
        email = idinfo['email']
        name = idinfo.get('name', email.split('@')[0])
        
        # Check if user exists
        user = crud.get_user_by_email(db, email=email)
        if not user:
            # Create user if not exists
            # Generate a random username if name is taken
            username = name
            existing_user = crud.get_user_by_username(db, username=username)
            if existing_user:
                username = f"{name}_{''.join(random.choices(string.ascii_lowercase + string.digits, k=4))}"
            
            user_in = schemas.UserCreate(
                username=username,
                email=email,
                password=''.join(random.choices(string.ascii_letters + string.digits, k=12)) # Random password
            )
            user = crud.create_user(db, user=user_in)
            
        # Create access token
        access_token = auth.create_access_token(data={"sub": user.username})
        return {"access_token": access_token, "token_type": "bearer"}
        
    except ValueError as e:
        # Invalid token
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {str(e)}")

# Temporary storage for reset codes: {email: {"code": "123456", "expires": timestamp}}
from datetime import datetime, timedelta
reset_codes = {}

def send_reset_email(email: str, code: str):
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_user = os.getenv("SMTP_USERNAME")
    smtp_pass = os.getenv("SMTP_PASSWORD")

    if not all([smtp_server, smtp_user, smtp_pass]) or "your-email" in smtp_user:
        print("SMTP credentials missing or default. Code logged to console instead.")
        return False

    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = email
    msg['Subject'] = "Security Code for Password Reset"

    body = f"""
    Hello,

    You requested a password reset for your account. 
    Your security code is: {code}

    This code will expire in 10 minutes.

    If you did not request this, please ignore this email.
    """
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

@app.post("/auth/forgot-password")
async def forgot_password(data: dict, db: Session = Depends(database.get_db)):
    identifier = data.get("email") or data.get("identifier")
    if not identifier:
        raise HTTPException(status_code=400, detail="Username or Email is required")
    
    # Normalize identifier for keying
    identifier = identifier.strip().lower()
        
    user = crud.get_user_by_username_or_email(db, identifier=identifier)
    if not user or not user.email:
        raise HTTPException(status_code=404, detail="User not found or no email registered")
        
    email = user.email
    # Generate 6-digit code
    code = "".join([str(random.randint(0, 9)) for _ in range(6)])
    expiry = datetime.now() + timedelta(minutes=10)
    
    # Store by identifier provided by user to ensure Step 2/3 work with same input
    reset_codes[identifier] = {"code": code, "expires": expiry, "email": email}
    
    # Send actual email
    email_sent = send_reset_email(email, code)
    
    print("\n" + "="*50)
    print(f"RESET CODE FOR {identifier} (Email: {email}): {code} (Email sent: {email_sent})")
    print("="*50 + "\n")
    
    if not email_sent:
        return {"message": "Development Mode: Security code logged to console"}
        
    return {"message": f"Security code sent to your registered email: {email[:3]}***@{email.split('@')[1]}"}

@app.post("/auth/verify-code")
async def verify_code(data: dict):
    identifier = data.get("email") or data.get("identifier")
    code = data.get("code")
    
    if not identifier or not code:
        raise HTTPException(status_code=400, detail="Identifier and code are required")
    
    identifier = identifier.strip().lower()
        
    if identifier not in reset_codes:
        raise HTTPException(status_code=400, detail="No reset requested for this account")
        
    stored_data = reset_codes[identifier]
    if datetime.now() > stored_data["expires"]:
        del reset_codes[identifier]
        raise HTTPException(status_code=400, detail="Code has expired")
        
    if stored_data["code"] != code:
        raise HTTPException(status_code=400, detail="Invalid security code")
        
    return {"message": "Code verified"}

@app.post("/auth/reset-password")
async def reset_password(data: dict, db: Session = Depends(database.get_db)):
    identifier = data.get("email") or data.get("identifier")
    code = data.get("code")
    new_password = data.get("new_password")
    
    if not identifier or not code or not new_password:
        raise HTTPException(status_code=400, detail="Missing required fields")

    identifier = identifier.strip().lower()
        
    if identifier not in reset_codes:
        raise HTTPException(status_code=400, detail="Unauthorized reset attempt")
        
    stored_data = reset_codes[identifier]
    if stored_data["code"] != code:
         raise HTTPException(status_code=400, detail="Invalid security code")

    user = crud.get_user_by_username_or_email(db, identifier=identifier)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    try:
        crud.update_user_password(db, user=user, new_password=new_password)
        # Clean up code after use
        del reset_codes[identifier]
        return {"message": "Password updated successfully"}
    except Exception as e:
        print(f"Error resetting password: {e}")
        raise HTTPException(status_code=500, detail="Internal server error while updating password")

# --- Stock Routes ---
@app.get("/stocks", response_model=List[schemas.Stock])
def read_stocks(skip: int = 0, limit: int = 100, db: Session = Depends(database.get_db)):
    stocks = crud.get_stocks(db, skip=skip, limit=limit)
    return stocks

@app.post("/stocks", response_model=schemas.Stock)
def create_stock(stock: schemas.StockCreate, db: Session = Depends(database.get_db)):
    # Validate symbol first
    valid_symbol = ml_engine.validate_ticker(stock.symbol)
    if not valid_symbol:
         raise HTTPException(status_code=400, detail=f"Invalid Stock Symbol: '{stock.symbol}'. Please check if it is listed on NSE/BSE.")
    
    # Use the resolved symbol (e.g. user typed RELIANCE, we save RELIANCE.NS)
    stock.symbol = valid_symbol
    return crud.create_stock(db=db, stock=stock)

# --- Watchlist Routes ---
@app.get("/watchlist", response_model=List[schemas.Watchlist])
def read_watchlist(db: Session = Depends(database.get_db), current_user: schemas.User = Depends(auth.get_current_user)):
    return crud.get_watchlist(db, user_id=current_user.id)

@app.post("/watchlist", response_model=schemas.Watchlist)
def add_to_watchlist(watchlist: schemas.WatchlistCreate, db: Session = Depends(database.get_db), current_user: schemas.User = Depends(auth.get_current_user)):
    return crud.add_to_watchlist(db=db, watchlist=watchlist, user_id=current_user.id)

import ml_engine

@app.get("/predict/{symbol}", response_model=schemas.Prediction)
def predict_stock(symbol: str, db: Session = Depends(database.get_db), current_user: schemas.User = Depends(auth.get_current_user)):
    # 1. Ensure stock exists in DB (or create it if user is requesting it)
    # The frontend adds to watchlist first, so it likely exists. 
    # But let's look it up to get ID.
    stock = db.query(models.Stock).filter(models.Stock.symbol == symbol.upper()).first()
    if not stock:
        # Optionally create it automatically
        stock = models.Stock(symbol=symbol.upper(), company_name=symbol.upper())
        db.add(stock)
        db.commit()
        db.refresh(stock)
    
    # 2. Run prediction (which now syncs data)
    result = ml_engine.predict_stock_trend(symbol, db)
    
    # 3. Use generic ID for response if not strictly saving prediction *record* to DB table 'predictions' 
    # (The requirement was saving *prices*. Storing *prediction* is also good.)
    
    # Let's save the prediction record too
    new_prediction = models.Prediction(
        stock_id=stock.id,
        date=result["date"],
        prediction=result["prediction"],
        confidence=result["confidence"]
    )
    db.add(new_prediction)
    db.commit()
    db.refresh(new_prediction)
    
    # Return schema-compatible dict
    return new_prediction

@app.delete("/watchlist/{symbol}")
def remove_from_watchlist(symbol: str, db: Session = Depends(database.get_db), current_user: schemas.User = Depends(auth.get_current_user)):
    success = crud.delete_from_watchlist(db=db, user_id=current_user.id, stock_symbol=symbol)
    if not success:
        raise HTTPException(status_code=404, detail="Stock not found in watchlist")
    return {"message": "Stock removed from watchlist"}

import time

# Simple cache for popular stocks
# Format: {"timestamp": 0, "data": {}}
POPULAR_STOCKS_CACHE = {"timestamp": 0, "data": {}}
CACHE_DURATION = 300 # 5 minutes

@app.get("/market/popular")
def get_popular_stocks():
    """
    Returns a curated catalog of stocks by sector with real-time data.
    """
    current_time = time.time()
    if current_time - POPULAR_STOCKS_CACHE["timestamp"] < CACHE_DURATION:
        return POPULAR_STOCKS_CACHE["data"]

    catalog_config = {
        "Indices": ["^NSEI", "^BSESN"],
        "Banking & Finance": ["HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS", "BAJFINANCE.NS", "LICI.NS"],
        "Technology (IT)": ["TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS"],
        "Automotive": ["TATAMOTORS.NS", "MARUTI.NS", "M&M.NS", "EICHERMOT.NS"],
        "Energy & Conglomerates": ["RELIANCE.NS", "ONGC.NS", "NTPC.NS", "POWERGRID.NS", "ADANIENT.NS"],
        "FMCG & Consumer": ["ITC.NS", "HINDUNILVR.NS", "NESTLEIND.NS", "TITAN.NS", "ASIANPAINT.NS"]
    }

    # Map for clean company names (could be in DB, but keeping here for simplicity as config)
    company_names = {
        "^NSEI": "NIFTY 50", "^BSESN": "SENSEX",
        "HDFCBANK.NS": "HDFC Bank", "ICICIBANK.NS": "ICICI Bank", "SBIN.NS": "State Bank of India",
        "KOTAKBANK.NS": "Kotak Mahindra Bank", "AXISBANK.NS": "Axis Bank", "BAJFINANCE.NS": "Bajaj Finance", "LICI.NS": "LIC India",
        "TCS.NS": "Tata Consultancy Services", "INFY.NS": "Infosys", "HCLTECH.NS": "HCL Technologies", "WIPRO.NS": "Wipro", "TECHM.NS": "Tech Mahindra",
        "TATAMOTORS.NS": "Tata Motors", "MARUTI.NS": "Maruti Suzuki", "M&M.NS": "Mahindra & Mahindra", "EICHERMOT.NS": "Eicher Motors",
        "RELIANCE.NS": "Reliance Industries", "ONGC.NS": "ONGC", "NTPC.NS": "NTPC", "POWERGRID.NS": "Power Grid Corp", "ADANIENT.NS": "Adani Enterprises",
        "ITC.NS": "ITC Limited", "HINDUNILVR.NS": "Hindustan Unilever", "NESTLEIND.NS": "Nestle India", "TITAN.NS": "Titan Company", "ASIANPAINT.NS": "Asian Paints"
    }

    all_symbols = [s for sublist in catalog_config.values() for s in sublist]
    market_data = ml_engine.get_latest_market_data(all_symbols)
    
    # Re-organize into sectors
    data_by_symbol = {item["symbol"]: item for item in market_data}
    
    response_data = {}
    for sector, symbols in catalog_config.items():
        response_data[sector] = []
        for sym in symbols:
            info = data_by_symbol.get(sym, {"price": "N/A", "change": "0.0%"})
            response_data[sector].append({
                "symbol": sym.replace(".NS", "").replace(".BO", ""),
                "company_name": company_names.get(sym, sym),
                "price": info["price"],
                "change": info["change"]
            })

    POPULAR_STOCKS_CACHE["timestamp"] = current_time
    POPULAR_STOCKS_CACHE["data"] = response_data
    return response_data

@app.get("/market/sentiment")
def get_market_sentiment_api(db: Session = Depends(database.get_db)):
    """
    Returns real-time market sentiment (NIFTY 50 prediction) and VIX.
    """
    return ml_engine.get_market_sentiment(db)

@app.get("/market/history/{symbol}")
def get_market_history(symbol: str, period: str = "1mo"):
    """
    Returns historical price data for a symbol for charting.
    Supported periods: 1d, 5d, 1mo, 6mo, 1y
    """
    try:
        # Validate/Suffix logic similar to ml_engine
        if not symbol.upper().endswith(".NS") and not symbol.upper().endswith(".BO") and not symbol.startswith("^"):
             # Simple heuristic for indices vs stocks
             if symbol.upper() == "NIFTY_50":
                 symbol = "^NSEI"
             elif symbol.upper() == "SENSEX":
                 symbol = "^BSESN"
             else:
                 symbol = symbol.upper() + ".NS"
        
        ticker = yf.Ticker(symbol)
        
        # Determine interval based on period
        interval = "1d"
        if period == "1d":
            interval = "5m"
        elif period == "5d":
            interval = "15m"
            
        hist = ticker.history(period=period, interval=interval)
        
        data = []
        for index, row in hist.iterrows():
            # For 1d, show time. For others, show date.
            date_format = "%H:%M" if period == "1d" else "%d %b"
            if period == "1y" or period == "6mo":
                date_format = "%b %y"
                
            data.append({
                "date": index.strftime(date_format),
                "price": round(row['Close'], 2)
            })
            
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

