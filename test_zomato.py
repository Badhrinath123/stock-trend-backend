
import yfinance as yf

def test_download(symbol):
    print(f"Testing download {symbol}...")
    try:
        data = yf.download(symbol, period="1mo", progress=False)
        if data.empty:
            print(f"FAIL: {symbol} returned no data.")
        else:
            print(f"SUCCESS: {symbol} returned {len(data)} rows. Last Close: {data['Close'].iloc[-1]}")
    except Exception as e:
        print(f"ERROR: {symbol} crashed with {e}")

test_download("ZOMATO.NS")
test_download("ZOMATO.BO")
