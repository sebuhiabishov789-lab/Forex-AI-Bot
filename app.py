import streamlit as st
import pandas as pd
from pathlib import Path
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import market_utils
import economic_calendar
from dotenv import load_dotenv

load_dotenv()
st.set_page_config(page_title="Forex AI Panel", layout="wide", page_icon="📊")

st.title("📊 Forex AI Panel - EUR/USD")

@st.cache_data(ttl=300)
def get_full_status():
    return market_utils.get_current_status()

@st.cache_data(ttl=3600)
def get_calendar_text():
    return economic_calendar.format_upcoming_high_impact(24)

with st.spinner("Data yüklənir..."):
    status = get_full_status()

if not status:
    st.error("Data yüklənmədi - yfinance işləmir, bir az sonra yenilə")
    st.stop()

data = status['data'].tail(500)
price = status['current_price']
prob = status['prob']

# Üst metrikalar
col1, col2, col3, col4 = st.columns(4)
col1.metric("Son Qiymət", f"{price:.5f}", f"ATR: {status['current_atr']:.5f}")
col2.metric("Model Prob", f"{prob*100:.1f}%", f"RF:{status['rf_prob']*100:.0f}% GB:{status['gb_prob']*100:.0f}%")
col3.metric("Test Acc", f"{status['test_acc']*100:.1f}%", "Model dəqiqliyi")
col4.metric("Trend", "Yuxarı 🟢" if status['trend_up'] else "Aşağı 🔴", f"Pattern: {status['pattern']}")

# Qrafik
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.8, 0.2], vertical_spacing=0.05)
fig.add_trace(go.Candlestick(x=data.index, open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'], name="EUR/USD"), row=1, col=1)
fig.add_trace(go.Scatter(x=data.index, y=data['EMA_fast'], name="EMA 20", line=dict(color="orange", width=1)), row=1, col=1)
fig.add_trace(go.Scatter(x=data.index, y=data['EMA_slow'], name="EMA 50", line=dict(color="blue", width=1)), row=1, col=1)
if status['support']: fig.add_hline(y=status['support'], line_dash="dash", line_color="green", annotation_text="Support", row=1, col=1)
if status['resistance']: fig.add_hline(y=status['resistance'], line_dash="dash", line_color="red", annotation_text="Resistance", row=1, col=1)
fig.add_trace(go.Scatter(x=data.index, y=data['RSI'], name="RSI", line=dict(color="purple")), row=2, col=1)
fig.add_hline(y=70, line_dash="dot", row=2, col=1); fig.add_hline(y=30, line_dash="dot", row=2, col=1)
fig.update_layout(height=600, xaxis_rangeslider_visible=False, showlegend=False)
st.plotly_chart(fig, use_container_width=True)

colA, colB = st.columns(2)
with colA:
    st.subheader("📊 MTF Trend")
    st.json(status['mtf_trends'])
    st.subheader("📅 Təqvim")
    st.code(get_calendar_text())

with colB:
    st.subheader("📝 Son Siqnallar")
    log_path = Path("signals_log.csv")
    if log_path.exists():
        try:
            df_log = pd.read_csv(log_path)
            if not df_log.empty:
                df_log = df_log.tail(20).sort_values('timestamp_utc', ascending=False)
                st.dataframe(df_log, use_container_width=True)
                # WinRate
                closed = df_log[df_log['outcome'] != 'OPEN']
                if not closed.empty:
                    wins = len(closed[closed['outcome']=='WIN'])
                    st.metric("WinRate", f"{wins/len(closed)*100:.1f}% ({wins}/{len(closed)})")
            else:
                st.info("Hələ siqnal yoxdur")
        except Exception as e:
            st.warning(f"Log oxunmadı: {e}")
    else:
        st.info("Hələ signals_log.csv yaranmayıb - bot ilk siqnalı göndərəndə yaranacaq")

if st.button('🔄 Yenilə (Cache təmizlə)'):
    st.cache_data.clear()
    st.rerun()
