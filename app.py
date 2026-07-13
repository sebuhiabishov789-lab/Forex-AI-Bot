import streamlit as st
import yfinance as yf
import pandas as pd

st.set_page_config(page_title="Forex AI Panel", layout="wide")

st.title("📊 Forex AI Ticarət Paneli")
st.write("EUR/USD valyuta cütlüyü üçün canlı bazar təhlili.")

# Məlumatların yüklənməsi
@st.cache_data(ttl=600) # 10 dəqiqədən bir yeniləyir
def get_data():
    data = yf.download('EURUSD=X', period='5d', interval='15m', auto_adjust=True)
    return data

data = get_data()

# Qrafik göstərilməsi
st.subheader("Son qiymət dəyişimi")
st.line_chart(data['Close'])

# Məlumat cədvəli
st.subheader("Son 10 dövrün qiymətləri")
st.write(data.tail(10))

if st.button('Bazar məlumatlarını yenilə'):
    st.rerun()
