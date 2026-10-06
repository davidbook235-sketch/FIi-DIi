"""FII/DII + institutional-footprint scanner for NSE. No API key needed.

Honest note: NSE does NOT publish stock-wise daily FII/DII buying.
So we combine: market-wide FII/DII flow (regime) + stock-wise institutional
bulk/block deals + delivery % (bhavcopy) + price trend (yfinance).
"""
import io
import re
import datetime as dt
import numpy as np
import pandas as pd
import requests

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json,text/csv,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

INST_PAT = re.compile(
    r"\b(?:MUTUAL FUND|FUND|FPI|ASSET MANAGEMENT|INSURANCE|PENSION|GOVERNMENT|"
    r"SINGAPORE|MAURITIUS|NORGES|VANGUARD|BLACKROCK|MORGAN STANLEY|GOLDMAN|"
    r"NOMURA|CITIGROUP|BNP|JPMORGAN|ABU DHABI|SOCIETE|UBS|HSBC|FIDELITY|"
    r"NIPPON|MIRAE|FRANKLIN|LIC)\b", re.I)


# ----------------------------------------------------------------- fetchers
def nse_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    s.headers.update({"Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors",
                      "Sec-Fetch-Site": "same-origin", "X-Requested-With": "XMLHttpRequest"})
    for u in ("https://www.nseindia.com", "https://www.nseindia.com/reports/fii-dii"):
        try:
            s.get(u, timeout=10)
        except Exception:
            pass
    return s


def _num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except Exception:
        return np.nan


def get_fii_dii(s):
    """Latest daily FII/FPI and DII cash-market flow, Rs crore (3 tries)."""
    import time
    last = None
    for attempt in range(3):
        try:
            r = s.get("https://www.nseindia.com/api/fiidiiTradeReact", timeout=15)
            r.raise_for_status()
            return _parse_fii_dii(r.json())
        except Exception as e:
            last = e
            time.sleep(1.5)
            try:
                s.get("https://www.nseindia.com/reports/fii-dii", timeout=10)
            except Exception:
                pass
    raise last


def _parse_fii_dii(rows):
    out = {}
    for x in rows:
        cat = str(x.get("category", "")).upper()
        key = "fii" if "FII" in cat or "FPI" in cat else "dii" if "DII" in cat else None
        if not key:
            continue
        out[key + "_buy"] = _num(x.get("buyValue"))
        out[key + "_sell"] = _num(x.get("sellValue"))
        out[key + "_net"] = _num(x.get("netValue"))
        out["date"] = x.get("date")
    if "fii_net" not in out or "dii_net" not in out:
        raise ValueError("FII/DII fields missing")
    try:
        out["date"] = pd.to_datetime(out["date"], format="%d-%b-%Y").strftime("%Y-%m-%d")
    except Exception:
        out["date"] = dt.date.today().strftime("%Y-%m-%d")
    return out


def _pick(df, *keys):
    for c in df.columns:
        lc = c.lower()
        if all(k in lc for k in keys):
            return c
    return None


def _norm_deals(df, kind):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    m = {
        "date": _pick(df, "date"), "symbol": _pick(df, "symbol"),
        "client": _pick(df, "client"), "side": _pick(df, "buy"),
        "qty": _pick(df, "quantity") or _pick(df, "qty"),
        "price": _pick(df, "price") or _pick(df, "watp"),
    }
    if any(v is None for v in m.values()):
        raise ValueError("deal columns changed: %s" % list(df.columns))
    o = pd.DataFrame({k: df[v] for k, v in m.items()})
    o["qty"] = o["qty"].map(_num)
    o["price"] = o["price"].map(_num)
    o["kind"] = kind
    return o.dropna(subset=["qty", "price"])


def get_deals(s):
    frames, notes = [], []
    for kind, url in (("BULK", "https://nsearchives.nseindia.com/content/equities/bulk.csv"),
                      ("BLOCK", "https://nsearchives.nseindia.com/content/equities/block.csv")):
        try:
            r = s.get(url, timeout=20)
            r.raise_for_status()
            frames.append(_norm_deals(pd.read_csv(io.StringIO(r.text)), kind))
        except Exception as e:
            notes.append("%s csv fail: %s" % (kind, str(e)[:60]))
    if not frames:  # fallback to JSON api
        try:
            r = s.get("https://www.nseindia.com/api/snapshot-capital-market-largedeal", timeout=15)
            r.raise_for_status()
            j = r.json()
            for kind, key in (("BULK", "BULK_DEALS_DATA"), ("BLOCK", "BLOCK_DEALS_DATA")):
                rows = j.get(key) or []
                if rows:
                    d = pd.DataFrame(rows).rename(columns={
                        "clientName": "client", "buySell": "buy_sell", "watp": "price"})
                    d["date"] = d.get("date", "")
                    frames.append(_norm_deals(d.rename(columns={"qty": "quantity"}), kind))
        except Exception as e:
            notes.append("deals api fail: %s" % str(e)[:60])
    if not frames:
        return pd.DataFrame(), notes
    d = pd.concat(frames, ignore_index=True)
    d["symbol"] = d["symbol"].astype(str).str.strip().str.upper()
    d["client"] = d["client"].astype(str).str.strip()
    d["dt"] = pd.to_datetime(d["date"], dayfirst=True, errors="coerce")
    if d["dt"].notna().any():
        d = d[d["dt"] >= d["dt"].max() - pd.Timedelta(days=4)]
    return d, notes


def get_bhavcopy(s, max_back=7):
    today = dt.date.today()
    for i in range(max_back):
        day = today - dt.timedelta(days=i)
        if day.weekday() >= 5:
            continue
        url = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_%s.csv" % day.strftime("%d%m%Y")
        try:
            r = s.get(url, timeout=25)
            if r.status_code == 200 and len(r.text) > 5000:
                df = pd.read_csv(io.StringIO(r.text))
                df.columns = [c.strip() for c in df.columns]
                df["SERIES"] = df["SERIES"].astype(str).str.strip()
                df = df[df["SERIES"] == "EQ"].copy()
                for c in ("PREV_CLOSE", "CLOSE_PRICE", "TURNOVER_LACS", "DELIV_PER", "TTL_TRD_QNTY"):
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                df["SYMBOL"] = df["SYMBOL"].astype(str).str.strip().str.upper()
                return df, day
        except Exception:
            continue
    raise RuntimeError("bhavcopy not available (last %d days)" % max_back)


def get_prices(symbols):
    import yfinance as yf
    out = {}
    tk = [x + ".NS" for x in symbols] + ["^NSEI"]
    try:
        raw = yf.download(tk, period="8mo", interval="1d", group_by="ticker",
                          auto_adjust=True, progress=False, threads=True)
    except Exception:
        return out
    for x in symbols + ["^NSEI"]:
        key = x if x == "^NSEI" else x + ".NS"
        try:
            d = raw[key].dropna(subset=["Close"])
            if len(d) >= 60:
                out[x] = d
        except Exception:
            pass
    return out


# ----------------------------------------------------------------- analytics
def _rsi(c, n=14):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def _atr(df, n=14):
    pc = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def regime(market, hist):
    if not market:
        return "UNKNOWN", 0.9, "FII/DII data nahi mila"
    h = hist.copy() if hist is not None else pd.DataFrame()
    row = pd.DataFrame([{"date": market["date"], "fii_net": market["fii_net"], "dii_net": market["dii_net"]}])
    h = pd.concat([h[["date", "fii_net", "dii_net"]] if len(h) else h, row], ignore_index=True)
    h = h.drop_duplicates("date", keep="last").sort_values("date").tail(5)
    f1, f5 = market["fii_net"], h["fii_net"].sum()
    d1 = market["dii_net"]
    if f1 > 0 and f5 > 0:
        return "RISK-ON", 1.0, "FII lagataar kharid rahe (5d net %+.0f cr)" % f5
    if f1 < 0 and f5 < 0:
        note = "FII bikwal (5d net %+.0f cr)" % f5
        if d1 > abs(f1):
            note += ", DII support kar rahe"
        return "RISK-OFF", 0.75, note
    return "MIXED", 0.9, "FII flow mixed (aaj %+.0f, 5d %+.0f cr)" % (f1, f5)


def agg_deals(d):
    if d is None or d.empty:
        return pd.DataFrame(columns=["SYMBOL", "inst_net_cr", "all_net_cr", "top_buyer"])
    d = d.copy()
    d["inst"] = d["client"].str.contains(INST_PAT)
    d["val_cr"] = d["qty"] * d["price"] / 1e7
    d["sign"] = np.where(d["side"].astype(str).str.upper().str.startswith("B"), 1.0, -1.0)
    d["signed"] = d["sign"] * d["val_cr"]
    inst = d[d["inst"]].groupby("symbol")["signed"].sum().rename("inst_net_cr")
    allv = d.groupby("symbol")["signed"].sum().rename("all_net_cr")
    buys = d[d["sign"] > 0].sort_values("val_cr").groupby("symbol").tail(1).set_index("symbol")["client"].rename("top_buyer")
    g = pd.concat([inst, allv, buys], axis=1).reset_index().rename(columns={"index": "SYMBOL", "symbol": "SYMBOL"})
    g["inst_net_cr"] = g["inst_net_cr"].fillna(0.0)
    g["all_net_cr"] = g["all_net_cr"].fillna(0.0)
    g["top_buyer"] = g["top_buyer"].fillna("")
    return g


def run_scan(capital=200000, risk_pct=1.0, min_turnover_cr=20.0, top_n=10,
             manual_fii=None, manual_dii=None, hist=None):
    notes = []
    s = nse_session()
    market = None
    try:
        market = get_fii_dii(s)
    except Exception as e:
        notes.append("FII/DII live fetch fail (NSE ne block kiya): %s" % str(e)[:60])
        if hist is not None and len(hist):
            last = hist.dropna(subset=["fii_net", "dii_net"]).tail(1)
            if len(last):
                market = {k: (last.iloc[0][k] if k in last.columns else np.nan) for k in
                          ("date", "fii_buy", "fii_sell", "fii_net", "dii_buy", "dii_sell", "dii_net")}
                market["fii_net"], market["dii_net"] = float(market["fii_net"]), float(market["dii_net"])
                notes.append("Last saved FII/DII data use hua (date %s)" % market["date"])
    if manual_fii is not None and manual_dii is not None:
        market = {"date": dt.date.today().strftime("%Y-%m-%d"), "fii_net": float(manual_fii),
                  "dii_net": float(manual_dii), "fii_buy": np.nan, "fii_sell": np.nan,
                  "dii_buy": np.nan, "dii_sell": np.nan}
        notes.append("Manual FII/DII use hua")
    reg, mult, reg_note = regime(market, hist)

    deals, dn = get_deals(s)
    notes += dn
    dagg = agg_deals(deals)
    have_deals = not dagg.empty
    if not have_deals:
        notes.append("Bulk/block deals nahi mile - score sirf delivery + trend par")

    try:
        bhav, bday = get_bhavcopy(s)
    except Exception as e:
        return {"ok": False, "market": market, "regime": reg, "regime_note": reg_note,
                "picks": pd.DataFrame(), "deals": dagg, "notes": notes + [str(e)],
                "asof": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}

    df = bhav.rename(columns={"SYMBOL": "SYMBOL"}).merge(dagg, on="SYMBOL", how="left")
    for c in ("inst_net_cr", "all_net_cr"):
        df[c] = df[c].fillna(0.0)
    df["top_buyer"] = df["top_buyer"].fillna("")
    df["turn_cr"] = df["TURNOVER_LACS"] / 100.0
    df["chg"] = (df["CLOSE_PRICE"] / df["PREV_CLOSE"] - 1) * 100
    df = df[(df["turn_cr"] >= min_turnover_cr) & (df["CLOSE_PRICE"] >= 20)].copy()

    # stage 1: deals + delivery + day action  (max 60)
    deal_pts = np.where(df["inst_net_cr"] > 0, np.clip(df["inst_net_cr"] / 10, 0, 1) * 30,
                        np.where(df["inst_net_cr"] < 0, -20, 0))
    deal_pts = deal_pts + np.where((df["inst_net_cr"] == 0) & (df["all_net_cr"] > 2), 5, 0)
    deliv_pts = np.clip((df["DELIV_PER"].fillna(0) - 40) / 30, 0, 1) * 20
    chg = df["chg"].fillna(0)
    act_pts = np.where((chg > 0) & (chg <= 6), 10, np.where(chg > 8, 0, np.where(chg < -3, -5, 3)))
    df["pre"] = deal_pts + deliv_pts + act_pts
    cand = df.sort_values("pre", ascending=False).head(40).copy()

    # stage 2: technicals (max 40, extension penalty -10)
    px = get_prices(cand["SYMBOL"].tolist())
    if not px:
        notes.append("yfinance prices nahi mile - trend score skip")
    nifty = px.get("^NSEI")
    n63 = (nifty["Close"].iloc[-1] / nifty["Close"].iloc[-64] - 1) if nifty is not None and len(nifty) > 64 else 0
    rows = []
    for _, r in cand.iterrows():
        t, why = 0.0, []
        sym = r["SYMBOL"]
        close = float(r["CLOSE_PRICE"])
        atr = np.nan
        d = px.get(sym)
        if d is not None:
            c = d["Close"]
            sma20, sma50 = c.rolling(20).mean().iloc[-1], c.rolling(50).mean().iloc[-1]
            rsi = _rsi(c).iloc[-1]
            vr = d["Volume"].iloc[-1] / max(d["Volume"].iloc[-21:-1].mean(), 1)
            r63 = c.iloc[-1] / c.iloc[-64] - 1 if len(c) > 64 else 0
            atr = float(_atr(d).iloc[-1])
            if c.iloc[-1] > sma50:
                t += 10; why.append("50DMA ke upar")
            if c.iloc[-1] > sma20:
                t += 5
            if 50 <= rsi <= 68:
                t += 10; why.append("RSI %.0f" % rsi)
            elif rsi > 75:
                t -= 5; why.append("RSI overbought %.0f" % rsi)
            if vr >= 1.3:
                t += 8; why.append("Volume %.1fx" % vr)
            if r63 > n63:
                t += 7; why.append("3M me Nifty se strong")
            if c.iloc[-1] / sma20 - 1 > 0.10:
                t -= 10; why.append("extended (20DMA se >10%)")
        if r["inst_net_cr"] > 0:
            why.insert(0, "Inst net buy Rs %.1f cr (%s)" % (r["inst_net_cr"], str(r["top_buyer"])[:28]))
        elif r["inst_net_cr"] < 0:
            why.insert(0, "Inst net SELL Rs %.1f cr" % abs(r["inst_net_cr"]))
        if r["DELIV_PER"] >= 55:
            why.insert(1 if r["inst_net_cr"] != 0 else 0, "Delivery %.0f%%" % r["DELIV_PER"])
        raw = r["pre"] + t
        score = raw / (100.0 if have_deals else 70.0) * 100.0 * mult
        a = atr if atr == atr else close * 0.03
        sl = max(close - 1.5 * a, close * 0.93)
        risk = close - sl
        qty = int(min(capital * risk_pct / 100.0 / risk, capital * 0.25 / close)) if risk > 0 else 0
        rows.append({
            "symbol": sym, "score": round(float(score), 1), "close": round(close, 2),
            "chg%": round(float(r["chg"]), 2), "deliv%": round(float(r["DELIV_PER"]), 1),
            "inst_net_cr": round(float(r["inst_net_cr"]), 2), "turn_cr": round(float(r["turn_cr"]), 1),
            "sl": round(sl, 2), "t1": round(close + 1.5 * risk, 2), "t2": round(close + 2.5 * risk, 2),
            "qty": qty, "why": " | ".join(why)})
    picks = pd.DataFrame(rows)
    if not picks.empty:
        picks = picks[picks["inst_net_cr"] >= 0]
        picks = picks.sort_values("score", ascending=False)
        picks["signal"] = np.where(picks["score"] >= 65, "STRONG", np.where(picks["score"] >= 50, "WATCH", "-"))
        picks = picks[picks["signal"] != "-"].head(top_n).reset_index(drop=True)
    return {"ok": True, "market": market, "regime": reg, "regime_note": reg_note, "picks": picks,
            "deals": dagg.sort_values("inst_net_cr", ascending=False).head(25) if have_deals else dagg,
            "notes": notes, "data_day": str(bday), "asof": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}


# ----------------------------------------------------------------- io / telegram
def serialize(res):
    o = dict(res)
    for k in ("picks", "deals"):
        o[k] = res[k].to_dict("records") if isinstance(res.get(k), pd.DataFrame) else []
    return o


def deserialize(o):
    o = dict(o)
    for k in ("picks", "deals"):
        o[k] = pd.DataFrame(o.get(k) or [])
    return o


def format_message(res, n=5):
    m = res.get("market") or {}
    lines = ["FII/DII Scanner  %s" % res.get("asof", "")]
    if m:
        lines.append("FII net %+.0f cr | DII net %+.0f cr" % (m.get("fii_net", 0), m.get("dii_net", 0)))
    lines.append("Market: %s - %s" % (res.get("regime"), res.get("regime_note")))
    p = res["picks"]
    if p.empty:
        lines.append("\nAaj koi strong setup nahi mila. Wait karo.")
    for _, r in p.head(n).iterrows():
        lines.append("\n%s [%s %.0f]\nBuy ~%.2f | SL %.2f | T1 %.2f | T2 %.2f | Qty %d\n%s" % (
            r["symbol"], r["signal"], r["score"], r["close"], r["sl"], r["t1"], r["t2"], r["qty"], r["why"]))
    lines.append("\nSirf research tool hai, advice nahi. Apna SL zaroor lagao.")
    return "\n".join(lines)


def send_telegram(text, token, chat_id):
    r = requests.post("https://api.telegram.org/bot%s/sendMessage" % token,
                      data={"chat_id": chat_id, "text": text[:4000]}, timeout=20)
    return r.ok
