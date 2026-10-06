"""Headless run for GitHub Actions: scan -> save data -> Telegram."""
import json
import os
import pandas as pd
from scanner_core import run_scan, serialize, format_message, send_telegram

HIST = "data/fii_dii_history.csv"
os.makedirs("data", exist_ok=True)
hist = pd.read_csv(HIST) if os.path.exists(HIST) else pd.DataFrame(
    columns=["date", "fii_buy", "fii_sell", "fii_net", "dii_buy", "dii_sell", "dii_net"])

res = run_scan(hist=hist)
m = res.get("market")
if m and res.get("ok"):
    row = {k: m.get(k) for k in hist.columns}
    hist = pd.concat([hist, pd.DataFrame([row])], ignore_index=True)
    hist = hist.drop_duplicates("date", keep="last").sort_values("date").tail(120)
    hist.to_csv(HIST, index=False)

with open("data/latest.json", "w") as f:
    json.dump(serialize(res), f, default=str)

print(format_message(res))
print("NOTES:", res.get("notes"))

tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
if tok and chat and res.get("ok"):
    print("telegram sent:", send_telegram(format_message(res), tok, chat))
