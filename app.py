import streamlit as st
import yfinance as yf
import pandas as pd
from pathlib import Path

st.set_page_config(page_title="Forex AI Panel", layout="wide")
st.title("📊 Forex AI Ticarət Paneli - EUR/USD")

@st.cache_data(ttl=600)
def get_data():
    df = yf.download('EURUSD=X', period='5d', interval='15m', auto_adjust=True)
    df['ATR'] = (df['High'] - df['Low']).rolling(14).mean()
    return df

data = get_data()

col1, col2, col3 = st.columns(3)
col1.metric("Son Qiymət", f"{data['Close'].iloc[-1]:.5f}")
col2.metric("ATR (14)", f"{data['ATR'].iloc[-1]:.5f}")
col3.metric("Günlük Dəyişim", f"{((data['Close'].iloc[-1]/data['Close'].iloc[0])-1)*100:.2f}%")

st.line_chart(data['Close'])

st.subheader("Son Siqnallar")
log_path = Path("signals_log.csv")
if log_path.exists():
    df_log = pd.read_csv(log_path).tail(20).sort_values('timestamp_utc', ascending=False)
    st.dataframe(df_log, use_container_width=True)
else:
    st.info("Hələ siqnal yoxdur.")

if st.button('Yenilə'):
    st.cache_data.clear()
    st.rerun()
