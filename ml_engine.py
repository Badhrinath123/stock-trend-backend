import yfinance as yf
from datetime import date
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
import models

def train_model():
    """
    Mock function to simulate model training.
    In a real app, this would be more complex.
    """
    print("Training model... (No-op for yfinance heuristic model)")
    return True

    print("Training model... (No-op for yfinance heuristic model)")
    return True

def validate_ticker(symbol: str):
    """
    Validates if a stock symbol exists on Yahoo Finance.
    Returns the resolved symbol (e.g., 'RELIANCE' -> 'RELIANCE.NS') or None.
    """
    candidates = [symbol.upper()]
    if not symbol.upper().endswith(".NS") and not symbol.upper().endswith(".BO"):
        candidates.append(symbol.upper() + ".NS")
        candidates.append(symbol.upper() + ".BO")
    
    for cand in candidates:
        try:
            # We use history(period='1d') as a cheap check
            ticker = yf.Ticker(cand)
            hist = ticker.history(period="1d")
            if not hist.empty:
                return cand
        except Exception:
            continue
            
    return None

def predict_stock_trend(stock_symbol: str, db: Session):
    """
    Predict stock trend using Real-Time data from Yahoo Finance.
    Saves fetched data to PostgreSQL database.
    Strategy: Simple Moving Average (SMA) Crossover.
    """
    try:
        ticker_symbol = stock_symbol.upper()
        
        # Try fetching with .NS first (assuming Indian user key context)
        # If that fails, try raw symbol (e.g. for US stocks like AAPL)
        
        chosen_symbol = ticker_symbol
        if not ticker_symbol.endswith(".NS") and not ticker_symbol.endswith(".BO") and "." not in ticker_symbol:
             chosen_symbol = ticker_symbol + ".NS"
        
        ticker = yf.Ticker(chosen_symbol)
        hist = ticker.history(period="3mo")
        
        # Fallback 1: if .NS failed, try .BO (BSE)
        if hist.empty and chosen_symbol.endswith(".NS"):
            print(f"No data for {chosen_symbol}, trying .BO suffix...")
            chosen_symbol = chosen_symbol.replace(".NS", ".BO")
            ticker = yf.Ticker(chosen_symbol)
            hist = ticker.history(period="3mo")

        # Fallback 2: if .BO failed (or wasn't tried), try raw
        if hist.empty and chosen_symbol != ticker_symbol:
            print(f"No data for {chosen_symbol}, trying {ticker_symbol}...")
            chosen_symbol = ticker_symbol
            ticker = yf.Ticker(chosen_symbol)
            hist = ticker.history(period="3mo")

        if hist.empty:
            return {
                "prediction": "UNKNOWN",
                "confidence": 0.0,
                "date": date.today(),
                "error": "No data found"
            }

        # 2. Save to Database (Data Persistence)
        # Find the stock ID first
        stock = db.query(models.Stock).filter(models.Stock.symbol == stock_symbol.upper()).first()
        
        if stock:
            # Iterate and save prices
            # Optimization: Check last saved date to avoid duplicates, or use merge
            # For simplicity in this demo, we'll simple-check existence of the last date
            # or just upsert if we had unique constraint.
            # Let's just save the last record to ensure we have the latest.
            # Or better, loop through all fetched and add missing.
            
            for index, row in hist.iterrows():
                row_date = index.date()
                
                # Check if price exists for this date
                existing_price = db.query(models.StockPrice).filter(
                    models.StockPrice.stock_id == stock.id,
                    models.StockPrice.date == row_date
                ).first()

                if not existing_price:
                    new_price = models.StockPrice(
                        stock_id=stock.id,
                        date=row_date,
                        open=float(row['Open']),
                        high=float(row['High']),
                        low=float(row['Low']),
                        close=float(row['Close']),
                        volume=float(row['Volume'])
                    )
                    db.add(new_price)
            
            try:
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"Error saving prices: {e}")

        # 3. Calculate Prediction
        hist['SMA_50'] = hist['Close'].rolling(window=50).mean()
        
        if len(hist) < 50:
             return {
                "prediction": "NEUTRAL",
                "confidence": 0.5,
                "date": date.today(),
                "message": "Insufficient historical data"
            }

        last_price = hist['Close'].iloc[-1]
        sma_50 = hist['SMA_50'].iloc[-1]
        
        if last_price > sma_50:
            prediction = "UP"
            diff_pct = (last_price - sma_50) / sma_50
            confidence = min(0.5 + (abs(diff_pct) * 5), 0.95) 
        else:
            prediction = "DOWN"
            diff_pct = (sma_50 - last_price) / sma_50
            confidence = min(0.5 + (abs(diff_pct) * 5), 0.95)
        
        # Critical Fix: Cast numpy float to python float for SQLAlchemy
        confidence = float(confidence)
            
        return {
            "prediction": prediction,
            "confidence": round(confidence, 2),
            "date": date.today(),
            "details": {
                "current_price": round(float(last_price), 2),
                "sma_50": round(float(sma_50), 2)
            }
        }
        
    except Exception as e:
        print(f"Error predicting for {stock_symbol}: {e}")
        return {
            "prediction": "ERROR",
            "confidence": 0.0,
            "date": date.today()
        }
