import yfinance as yf
from datetime import date
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session
import models



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

def get_latest_market_data(symbols: list):
    """
    Fetches the latest price and daily change percentage for a list of symbols.
    Returns a list of dicts: {"symbol": "...", "price": "...", "change": "..."}
    """
    results = []
    # yfinance can fetch multiple tickers at once
    tickers_str = " ".join(symbols)
    try:
        data = yf.download(tickers_str, period="2d", group_by='ticker', progress=False)
        for symbol in symbols:
            try:
                if len(symbols) > 1:
                    ticker_data = data[symbol]
                else:
                    ticker_data = data
                
                if ticker_data.empty or len(ticker_data) < 2:
                    results.append({"symbol": symbol, "price": "N/A", "change": "0.0%"})
                    continue
                
                # Get last two close prices for change calculation
                last_close = ticker_data['Close'].iloc[-1]
                prev_close = ticker_data['Close'].iloc[-2]
                
                change_pct = ((last_close - prev_close) / prev_close) * 100
                change_str = f"{'+' if change_pct >= 0 else ''}{round(change_pct, 2)}%"
                
                results.append({
                    "symbol": symbol,
                    "price": str(round(last_close, 2)),
                    "change": change_str
                })
            except Exception as e:
                print(f"Error processing data for {symbol}: {e}")
                results.append({"symbol": symbol, "price": "N/A", "change": "0.0%"})
    except Exception as e:
        print(f"Error downloading market data: {e}")
        return [{"symbol": s, "price": "N/A", "change": "0.0%"} for s in symbols]
        
    return results

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

def get_market_sentiment(db: Session):
    """
    Analyzes NIFTY 50 for sentiment and fetches India VIX.
    """
    try:
        # 1. Fetch India VIX
        vix_ticker = yf.Ticker("^INDIAVIX")
        vix_hist = vix_ticker.history(period="1d")
        vix_val = 0.0
        if not vix_hist.empty:
            vix_val = float(vix_hist['Close'].iloc[-1])
            
        # 2. Predict NIFTY 50 Trend
        # We can reuse the predict_stock_trend logic but specific for NIFTY
        # NIFTY symbol is ^NSEI
        nifty_prediction = predict_stock_trend("^NSEI", db)
        
        sentiment = "Neutral"
        if nifty_prediction.get("prediction") == "UP":
            sentiment = "Bullish"
        elif nifty_prediction.get("prediction") == "DOWN":
            sentiment = "Bearish"
            
        return {
            "sentiment": sentiment,
            "confidence": int(nifty_prediction.get("confidence", 0) * 100),
            "vix": round(vix_val, 2),
            "nifty_price": nifty_prediction.get("details", {}).get("current_price", 0)
        }
    except Exception as e:
        print(f"Error fetching market sentiment: {e}")
        return {
            "sentiment": "Neutral",
            "confidence": 0,
            "vix": 0.0,
            "error": str(e)
        }
