import json
import os
import pandas as pd
import streamlit as st
from scanner_core import run_scan, deserialize, format_message, send_telegram

st.set_page_config(page_title="FII/DII Scanner", page_icon="📈", layout="centered")
st.title("📈 FII/DII Stock Scanner")
st.caption("NSE FII/DII flow + institutional bulk/block deals + delivery% + trend. Research tool, advice nahi.")

HIST = "data/fii_dii_history.csv"
LATEST = "data/latest.json"
hist = pd.read_csv(HIST) if os.path.exists(HIST) else pd.DataFrame()

with st.sidebar:
    st.header("Settings")
    capital = st.number_input("Capital (Rs)", 10000, 100000000, 200000, 10000)
    risk = st.slider("Risk per trade %", 0.25, 2.0, 1.0, 0.25)
    min_turn = st.slider("Min turnover (Rs cr)", 5, 200, 20)
    st.caption("NSE fetch fail ho to FII/DII manual daalo (Rs cr):")
    mf = st.text_input("FII net", "")
    md = st.text_input("DII net", "")

def _f(x):
    try:
        return float(x)
    except Exception:
        return None

if st.button("🔍 Abhi scan karo (live)", type="primary", use_container_width=True):
    with st.spinner("NSE data + prices aa rahe hain (30-60 sec)..."):
        st.session_state["res"] = run_scan(capital, risk, min_turn, 10, _f(mf), _f(md), hist)

res = st.session_state.get("res")
if res is None and os.path.exists(LATEST):
    res = deserialize(json.load(open(LATEST)))
    st.info("Last auto-scan dikha raha hu (%s). Fresh ke liye button dabao." % res.get("asof"))

if res is None:
    st.warning("Abhi koi data nahi. Upar 'Abhi scan karo' dabao.")
    st.stop()

m = res.get("market") or {}
c1, c2 = st.columns(2)
c1.metric("FII net (cr)", "%+.0f" % m.get("fii_net", 0) if m else "NA")
c2.metric("DII net (cr)", "%+.0f" % m.get("dii_net", 0) if m else "NA")
icon = {"RISK-ON": "🟢", "RISK-OFF": "🔴", "MIXED": "🟡"}.get(res.get("regime"), "⚪")
st.subheader("%s %s" % (icon, res.get("regime")))
st.write(res.get("regime_note"))
for n in res.get("notes") or []:
    st.caption("⚠️ " + str(n))

tab1, tab2, tab3 = st.tabs(["Suggestions", "FII/DII trend", "Institutional deals"])
with tab1:
    p = res["picks"]
    if p.empty:
        st.info("Aaj koi strong setup nahi. Kabhi kabhi 'wait' bhi best trade hota hai.")
    for _, r in p.iterrows():
        tag = "🔥" if r["signal"] == "STRONG" else "👀"
        with st.expander("%s %s  |  score %.0f  |  Rs %.2f" % (tag, r["symbol"], r["score"], r["close"])):
            st.write("**Buy ~%.2f** | **SL %.2f** | T1 %.2f | T2 %.2f" % (r["close"], r["sl"], r["t1"], r["t2"]))
            st.write("Qty (%.2f%% risk): **%d**" % (risk, r["qty"]))
            st.write(r["why"])
    if not p.empty:
        st.dataframe(p.drop(columns=["why"]), use_container_width=True, hide_index=True)
        tok = st.secrets.get("TELEGRAM_BOT_TOKEN", "") if hasattr(st, "secrets") else ""
        chat = st.secrets.get("TELEGRAM_CHAT_ID", "") if hasattr(st, "secrets") else ""
        if tok and chat and st.button("Telegram par bhejo"):
            st.success("Bhej diya" if send_telegram(format_message(res), tok, chat) else "Fail")
with tab2:
    if len(hist):
        h = hist.tail(30).set_index("date")[["fii_net", "dii_net"]]
        st.bar_chart(h)
        st.dataframe(hist.tail(10), use_container_width=True, hide_index=True)
    else:
        st.write("History GitHub Action chalne ke baad banegi.")
with tab3:
    d = res["deals"]
    if len(d):
        st.caption("Recent bulk/block deals me net institutional buy (name se pehchaan, approx).")
        st.dataframe(d, use_container_width=True, hide_index=True)
    else:
        st.write("Deals data nahi mila.")
