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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all for dev, restrict in prod
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
import random
import string

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
        
    user = crud.get_user_by_username_or_email(db, identifier=identifier)
    if not user or not user.email:
        raise HTTPException(status_code=404, detail="User not found or no email registered")
        
    email = user.email
    # Generate 6-digit code
    code = "".join([str(random.randint(0, 9)) for _ in range(6)])
    expiry = datetime.now() + timedelta(minutes=10)
    
    reset_codes[email] = {"code": code, "expires": expiry}
    
    # Send actual email
    email_sent = send_reset_email(email, code)
    
    print("\n" + "="*50)
    print(f"RESET CODE FOR {email}: {code} (Email sent: {email_sent})")
    print("="*50 + "\n")
    
    if not email_sent:
        return {"message": "Development Mode: Security code logged to console (Email configuration required for real sending)"}
        
    return {"message": f"Security code sent to your registered email: {email[:3]}***@{email.split('@')[1]}"}

@app.post("/auth/verify-code")
async def verify_code(data: dict):
    email = data.get("email")
    code = data.get("code")
    
    if not email or not code:
        raise HTTPException(status_code=400, detail="Email and code are required")
        
    if email not in reset_codes:
        raise HTTPException(status_code=400, detail="No reset requested for this email")
        
    stored_data = reset_codes[email]
    if datetime.now() > stored_data["expires"]:
        del reset_codes[email]
        raise HTTPException(status_code=400, detail="Code has expired")
        
    if stored_data["code"] != code:
        raise HTTPException(status_code=400, detail="Invalid security code")
        
    return {"message": "Code verified"}

@app.post("/auth/reset-password")
async def reset_password(data: dict, db: Session = Depends(database.get_db)):
    email = data.get("email")
    code = data.get("code")
    new_password = data.get("new_password")
    
    if not email or not code or not new_password:
        raise HTTPException(status_code=400, detail="Missing required fields")
        
    if email not in reset_codes or reset_codes[email]["code"] != code:
        raise HTTPException(status_code=400, detail="Unauthorized reset attempt")
        
    user = crud.get_user_by_email(db, email=email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    crud.update_user_password(db, user=user, new_password=new_password)
    
    # Clean up code after use
    del reset_codes[email]
    
    return {"message": "Password updated successfully"}

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

@app.get("/market/popular")
def get_popular_stocks():
    """
    Returns a curated catalog of stocks by sector.
    """
    return {
        "Indices": [
            {"symbol": "^NSEI", "company_name": "NIFTY 50", "price": "21500.00", "change": "+0.5%"},
            {"symbol": "^BSESN", "company_name": "SENSEX", "price": "71000.00", "change": "+0.4%"},
        ],
        "Banking & Finance": [
            {"symbol": "HDFCBANK", "company_name": "HDFC Bank", "price": "1650.00", "change": "+0.2%"},
            {"symbol": "ICICIBANK", "company_name": "ICICI Bank", "price": "980.00", "change": "-0.1%"},
            {"symbol": "SBIN", "company_name": "State Bank of India", "price": "620.00", "change": "+1.1%"},
            {"symbol": "KOTAKBANK", "company_name": "Kotak Mahoney Bank", "price": "1800.00", "change": "-0.5%"},
            {"symbol": "AXISBANK", "company_name": "Axis Bank", "price": "1100.00", "change": "+0.8%"},
            {"symbol": "BAJFINANCE", "company_name": "Bajaj Finance", "price": "7500.00", "change": "+1.5%"},
            {"symbol": "KTKBANK", "company_name": "Karnataka Bank", "price": "240.00", "change": "+0.5%"},
             {"symbol": "LICI", "company_name": "LIC India", "price": "900.00", "change": "+0.6%"},
        ],
        "Technology (IT)": [
            {"symbol": "TCS", "company_name": "Tata Consultancy Services", "price": "3800.00", "change": "+0.5%"},
            {"symbol": "INFY", "company_name": "Infosys", "price": "1500.00", "change": "-0.2%"},
            {"symbol": "HCLTECH", "company_name": "HCL Technologies", "price": "1400.00", "change": "+1.2%"},
            {"symbol": "WIPRO", "company_name": "Wipro", "price": "450.00", "change": "-0.8%"},
            {"symbol": "TECHM", "company_name": "Tech Mahindra", "price": "1200.00", "change": "+0.1%"},
        ],
        "Automotive": [
            {"symbol": "TATAMOTORS", "company_name": "Tata Motors", "price": "800.00", "change": "+2.1%"},
            {"symbol": "MARUTI", "company_name": "Maruti Suzuki", "price": "10500.00", "change": "-0.5%"},
            {"symbol": "M&M", "company_name": "Mahindra & Mahindra", "price": "1600.00", "change": "+1.8%"},
            {"symbol": "EICHERMOT", "company_name": "Eicher Motors", "price": "3800.00", "change": "+0.3%"},
        ],
        "Energy & Conglomerates": [
            {"symbol": "RELIANCE", "company_name": "Reliance Industries", "price": "2600.00", "change": "+0.9%"},
            {"symbol": "ONGC", "company_name": "ONGC", "price": "200.00", "change": "-1.2%"},
            {"symbol": "NTPC", "company_name": "NTPC", "price": "300.00", "change": "+0.5%"},
            {"symbol": "POWERGRID", "company_name": "Power Grid Corp", "price": "230.00", "change": "+0.4%"},
             {"symbol": "ADANIENT", "company_name": "Adani Enterprises", "price": "3000.00", "change": "-1.5%"},
        ],
        "FMCG & Consumer": [
            {"symbol": "ITC", "company_name": "ITC Limited", "price": "460.00", "change": "+0.2%"},
            {"symbol": "HINDUNILVR", "company_name": "Hindustan Unilever", "price": "2500.00", "change": "-0.3%"},
            {"symbol": "NESTLEIND", "company_name": "Nestle India", "price": "25000.00", "change": "+0.1%"},
            {"symbol": "TITAN", "company_name": "Titan Company", "price": "3600.00", "change": "+1.2%"},
            {"symbol": "ASIANPAINT", "company_name": "Asian Paints", "price": "3000.00", "change": "-0.8%"},
        ]
    }

@app.get("/market/history/{symbol}")
def get_market_history(symbol: str):
    """
    Returns historical price data for a symbol (default 1mo) for charting.
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
        hist = ticker.history(period="1mo")
        
        data = []
        for index, row in hist.iterrows():
            data.append({
                "date": index.strftime("%Y-%m-%d"),
                "price": round(row['Close'], 2)
            })
            
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

