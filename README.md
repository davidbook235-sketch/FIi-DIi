# FII/DII Stock Scanner (GitHub + Streamlit, mobile-friendly)

## Ye kya karta hai
- NSE ka daily FII/DII flow dekhta hai -> market RISK-ON / MIXED / RISK-OFF
- Bulk/block deals me institutional net buying dhoondta hai
- Delivery % + price trend + volume se stocks ko score deta hai (0-100)
- Har pick ke saath Buy, SL, T1, T2 aur quantity (1% risk) deta hai
- Telegram par alert + Streamlit app me dashboard

NOTE: NSE stock-wise daily FII/DII buying publish nahi karta. Isliye institutional buying ka
proxy bulk/block deals hain (client ke naam se pehchaan, approx). Ye research tool hai, advice nahi.

## Setup (sirf mobile se)
1. GitHub app/browser me naya repo banao: `fii-dii-scanner` (Public rakho, Streamlit free ke liye easy).
2. Zip extract karo. Repo me **Add file > Upload files** se ye files upload karo:
   `app.py, scanner_core.py, run_scan.py, requirements.txt, README.md`
   aur `.streamlit/config.toml`, `data/fii_dii_history.csv`, `data/.gitkeep` (folder wale files ke liye
   **Create new file** me path type karo jaise `data/fii_dii_history.csv`, aur content paste karo).
3. **Workflow file**: Add file > Create new file > naam me likho `.github/workflows/scan.yml`
   aur `SCAN_YML_COPY_PASTE.txt` ka poora content paste karke Commit karo.
4. Repo > Settings > Secrets and variables > Actions > New secret:
   `TELEGRAM_BOT_TOKEN` aur `TELEGRAM_CHAT_ID` (optional, bina iske bhi chalega).
5. Repo > Settings > Actions > General > Workflow permissions > **Read and write permissions** ON.
6. Actions tab > "FII-DII Scan" > Run workflow (pehla test).
7. share.streamlit.io par GitHub se login > New app > repo select > main file `app.py` > Deploy.
   (Telegram button chahiye to App settings > Secrets me wahi 2 values daalo:
   `TELEGRAM_BOT_TOKEN = "..."` aur `TELEGRAM_CHAT_ID = "..."`)

## Timing
- 7:00 PM IST (Mon-Fri): FII/DII + deals + delivery data aane ke baad scan + Telegram
- 8:45 AM IST: subah ka plan (kal ke data par)
- Data NSE par kabhi late aata hai; us din 7:30 PM ke baad "Run workflow" dabao.

## Agar kuch fail ho
- **403 Forbidden (FII/DII)**: NSE Streamlit ke server ko block karta hai. App ab last saved data
  (GitHub Action se bana `data/fii_dii_history.csv`) use karta hai. Isliye Actions > Run workflow
  ek baar chalao taaki history ban jaye. Phir bhi na mile to sidebar me manual daalo.
- NSE kabhi cloud/foreign IP ko block karta hai. App me notes me "fail" dikhega. Tab sidebar me
  FII/DII manual daalo, ya Actions ka dobara run karo (kabhi 2-3 try me chal jata hai).
- yfinance fail ho to trend score skip hota hai aur picks kam milenge.
- Score >= 65 STRONG, 50-65 WATCH. RISK-OFF market me score 25% kam hota hai.
