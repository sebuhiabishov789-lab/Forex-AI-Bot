import yfinance as yf
import pandas as pd
import requests
import os
from sklearn.ensemble import RandomForestClassifier

# GitHub Secrets-dən məlumatları alır
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

def send_telegram(message):
    if TOKEN and CHAT_ID:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage?chat_id={CHAT_ID}&text={message}"
        requests.get(url)

def run_bot():
    # Məlumatların yüklənməsi
    data = yf.download('EURUSD=X', period='60d', interval='15m', auto_adjust=True)
    if data.index.tz is not None:
        data.index = data.index.tz_localize(None)
    
    # ATR Hesablaması
    high_low = data['High'] - data['Low']
    high_cp = abs(data['High'] - data['Close'].shift())
    low_cp = abs(data['Low'] - data['Close'].shift())
    atr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1).rolling(14).mean().iloc[-1]
    
    # Modelin hazırlanması
    data['Return'] = data['Close'].pct_change()
    data['Range'] = (data['High'] - data['Low']) / data['Close']
    data.dropna(inplace=True)
    data['Target'] = (data['Close'].shift(-1) > data['Close']).astype(int)
    
    model = RandomForestClassifier(n_estimators=100, random_state=42).fit(data[['Return', 'Range']].iloc[:-1], data['Target'].iloc[:-1])
    prob = model.predict_proba(data[['Return', 'Range']].iloc[[-1]])[0][1]
    current_price = data['Close'].iloc[-1].item()
    
    # Siqnalın göndərilməsi
    if prob > 0.60:
        msg = f"🚀 SİQNAL: ALIŞ (BUY)\nQiymət: {round(current_price, 5)}\nSL: {round(current_price - 1.5*atr, 5)}\nTP: {round(current_price + 3.0*atr, 5)}"
        send_telegram(msg)
    elif prob < 0.40:
        msg = f"📉 SİQNAL: SATIŞ (SELL)\nQiymət: {round(current_price, 5)}\nSL: {round(current_price + 1.5*atr, 5)}\nTP: {round(current_price - 3.0*atr, 5)}"
        send_telegram(msg)

if __name__ == "__main__":
    run_bot()
