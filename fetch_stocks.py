"""
株教授 - 株価取得スクリプト（GitHub Actions用 / 日経225対応・バッチ取得版）
watchlist.csv の全銘柄を yfinance でバッチ取得し、テクニカル指標を計算して
stocks.json に出力する。
"""
import csv, json, datetime
import yfinance as yf
import pandas as pd
import numpy as np


def rsi(series, n=14):
    delta = series.diff()
    up = delta.clip(lower=0).rolling(n).mean()
    down = (-delta.clip(upper=0)).rolling(n).mean()
    rs = up / down
    return 100 - 100 / (1 + rs)


def calc_from_close(code, name, sector, c, v):
    out = {"code": code, "name": name, "sector": sector}
    c = c.dropna()
    if len(c) < 80:
        out["status"] = "no_data"
        return out
    last = float(c.iloc[-1])
    ma5 = float(c.rolling(5).mean().iloc[-1])
    ma25 = float(c.rolling(25).mean().iloc[-1])
    ma75 = float(c.rolling(75).mean().iloc[-1])
    ma25_prev = float(c.rolling(25).mean().iloc[-6])
    rsi14 = float(rsi(c).iloc[-1])
    hi52 = float(c.tail(252).max())
    m1ago = float(c.iloc[-22])
    vol25 = vol5 = None
    try:
        v = v.dropna()
        vol25 = float(v.rolling(25).mean().iloc[-1])
        vol5 = float(v.tail(5).mean())
    except Exception:
        pass
    out.update({
        "last": round(last, 1),
        "rsi14": round(rsi14, 1),
        "ma5": round(ma5, 1),
        "ma25": round(ma25, 1),
        "ma75": round(ma75, 1),
        "ma25_trend": "up" if ma25 > ma25_prev else "down",
        "dev_ma25_pct": round((last / ma25 - 1) * 100, 1),
        "chg_1m_pct": round((last / m1ago - 1) * 100, 1),
        "vol_ratio_pct": round(vol5 / vol25 * 100, 0) if vol25 else None,
        "dev_52w_high_pct": round((last / hi52 - 1) * 100, 1),
        "status": "ok",
    })
    return out


def main():
    rows = []
    with open("watchlist.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("コード"):
                rows.append((r["コード"].strip(), r["銘柄名"].strip(), r.get("セクター", "").strip()))

    tickers = [code + ".T" for code, _, _ in rows]
    # バッチ取得（チャンクに分けて安定化）
    frames = {}
    CHUNK = 50
    for i in range(0, len(tickers), CHUNK):
        part = tickers[i:i + CHUNK]
        try:
            d = yf.download(part, period="9mo", interval="1d", group_by="ticker",
                            threads=True, progress=False, auto_adjust=True)
            frames[i] = d
        except Exception as e:
            print("chunk error", i, str(e)[:80])
            frames[i] = None

    def get_series(idx_in_chunk, t):
        d = frames.get(idx_in_chunk)
        if d is None:
            return None, None
        try:
            if isinstance(d.columns, pd.MultiIndex):
                sub = d[t]
                return sub["Close"], sub.get("Volume")
            else:  # 単一銘柄になった場合
                return d["Close"], d.get("Volume")
        except Exception:
            return None, None

    stocks = []
    for n, (code, name, sec) in enumerate(rows):
        chunk_start = (n // CHUNK) * CHUNK
        t = code + ".T"
        c, v = get_series(chunk_start, t)
        if c is None:
            stocks.append({"code": code, "name": name, "sector": sec, "status": "no_data"})
            continue
        stocks.append(calc_from_close(code, name, sec, c, v))

    jst = datetime.timezone(datetime.timedelta(hours=9))
    result = {
        "generated_at_jst": datetime.datetime.now(jst).strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(stocks),
        "stocks": stocks,
    }
    with open("stocks.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    ok = sum(1 for s in stocks if s.get("status") == "ok")
    print(f"wrote stocks.json: {ok}/{len(stocks)} ok at {result['generated_at_jst']}")


if __name__ == "__main__":
    main()
