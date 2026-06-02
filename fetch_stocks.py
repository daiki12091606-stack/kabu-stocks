"""
株教授 - 株価取得スクリプト（GitHub Actions用）
watchlist.csv を読み、yfinanceで各銘柄の最新株価とテクニカル指標を計算し、
stocks.json として出力する。GitHub Actionsが1日3回これを実行してコミットする。
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


def calc_one(code, name, sector):
    out = {"code": code, "name": name, "sector": sector}
    try:
        df = yf.download(code + ".T", period="9mo", interval="1d",
                         progress=False, auto_adjust=True)
        if df is None or df.empty or len(df) < 80:
            out["status"] = "no_data"
            return out
        c = df["Close"].squeeze()
        v = df["Volume"].squeeze()
        last = float(c.iloc[-1])
        ma5 = float(c.rolling(5).mean().iloc[-1])
        ma25 = float(c.rolling(25).mean().iloc[-1])
        ma75 = float(c.rolling(75).mean().iloc[-1])
        ma25_prev = float(c.rolling(25).mean().iloc[-6])
        rsi14 = float(rsi(c).iloc[-1])
        vol25 = float(v.rolling(25).mean().iloc[-1])
        vol5 = float(v.tail(5).mean())
        hi52 = float(c.tail(252).max())
        m1ago = float(c.iloc[-22])
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
    except Exception as e:
        out["status"] = "error"
        out["error"] = str(e)[:120]
    return out


def main():
    rows = []
    with open("watchlist.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("コード"):
                rows.append((r["コード"].strip(), r["銘柄名"].strip(), r.get("セクター", "").strip()))

    jst = datetime.timezone(datetime.timedelta(hours=9))
    result = {
        "generated_at_jst": datetime.datetime.now(jst).strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(rows),
        "stocks": [calc_one(code, name, sec) for code, name, sec in rows],
    }
    with open("stocks.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    ok = sum(1 for s in result["stocks"] if s.get("status") == "ok")
    print(f"wrote stocks.json: {ok}/{len(rows)} ok at {result['generated_at_jst']}")


if __name__ == "__main__":
    main()
