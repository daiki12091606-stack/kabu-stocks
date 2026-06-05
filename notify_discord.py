"""
株教授 - Discord判断支援デイリー（GitHub Actions用 / (b)方針：規律・判断支援＋セクター強度＋ニュース）
=====================================================================
バックテストの結論「機械的に勝てるエッジは無い／だが負け減らし・選別・規律は効く」を受け、
“買い当て”をやめ、判断支援に作り替えた版。各セクションは best-effort（失敗しても他は出る）。

出力(Discordの非公開チャンネルへプッシュ):
  📊 日経平均(水準・トレンド)＋関連ニュース見出し
  🔥 セクター強度ランク（テーマの勢い）
  👀 注目候補（反発/押し目・テーマ強度順・買いシグナルでなく優先度）＋各ニュース見出し
  ⚠️ 過熱・飛びつき警告（日立型）
  🔵 保有の出口アラート（HOLDINGS secretから）
  末尾: 最終判断はユーザーのニュース・テーマ＋規律。資金の土台は指数買い持ち。

依存: stocks.json(fetch_stocks.pyが生成), DISCORD_WEBHOOK(secret), 任意でHOLDINGS(secret)
      sectors.json(本スクリプトが.infoで生成・キャッシュ), yfinance(指数/セクター取得)
"""
import json, os, datetime, urllib.request, urllib.parse, xml.etree.ElementTree as ET

WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "").strip()
HOLDINGS_RAW = os.environ.get("HOLDINGS", "").strip()
SECTORS_FILE = "sectors.json"

try:
    import yfinance as yf
except Exception:
    yf = None


def yen(x):
    return f"¥{int(round(x)):,}"


# ---------- セクター（yfinance .info をキャッシュ） ----------
def load_sectors(codes):
    cache = {}
    if os.path.exists(SECTORS_FILE):
        try:
            cache = json.load(open(SECTORS_FILE, encoding="utf-8"))
        except Exception:
            cache = {}
    missing = [c for c in codes if c not in cache]
    if missing and yf is not None:
        for c in missing:
            sec = "その他"
            try:
                info = yf.Ticker(c + ".T").info
                sec = info.get("sectorDisp") or info.get("sector") or "その他"
            except Exception:
                sec = "その他"
            cache[c] = sec
        try:
            json.dump(cache, open(SECTORS_FILE, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass
    return cache


# ---------- 日経平均（指数の地合い） ----------
def index_block():
    if yf is None:
        return None
    try:
        df = yf.download("^N225", period="6mo", interval="1d", progress=False, auto_adjust=True)
        if isinstance(df.columns, type(df.columns)) and hasattr(df.columns, "get_level_values"):
            try:
                df.columns = df.columns.get_level_values(0)
            except Exception:
                pass
        c = df["Close"].dropna()
        last = float(c.iloc[-1]); prev = float(c.iloc[-2])
        ma25 = float(c.rolling(25).mean().iloc[-1]); ma75 = float(c.rolling(75).mean().iloc[-1])
        chg = (last / prev - 1) * 100
        trend = "上昇" if (last > ma25 and last > ma75) else ("下落" if (last < ma25 and last < ma75) else "もみ合い")
        return {"last": last, "chg": chg, "ma25": ma25, "ma75": ma75, "trend": trend}
    except Exception:
        return None


# ---------- ニュース（Google News RSS 見出し1件） ----------
def news_one(query):
    try:
        q = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={q}&hl=ja&gl=JP&ceid=JP:ja"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            root = ET.fromstring(r.read())
        item = root.find(".//item")
        if item is None:
            return None
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        return f"{title}" + (f"\n　　<{link}>" if link else "")
    except Exception:
        return None


# ---------- 候補判定（“買い当て”でなく優先度付けの素材） ----------
def candidate_type(s):
    rsi = s["rsi14"]; dev = s["dev_ma25_pct"]; m1 = s["chg_1m_pct"]
    dev52 = s.get("dev_52w_high_pct", 0); vol = s.get("vol_ratio_pct") or 0; trend = s["ma25_trend"]
    if trend == "up" and (rsi > 70 or dev > 25):
        return "hot"
    if dev52 <= -15 and 35 <= rsi <= 52 and vol >= 150:
        return "rebound"     # 安値圏の反発（型B系）
    if trend == "up" and abs(dev) <= 5 and 40 <= rsi <= 65 and m1 <= 20:
        return "pullback"    # 上昇中の押し目（型A系）
    return "none"


def action_for(pl, days, typ):
    # 出口ルール: -5%即損切り / 利確トレーリング / 14日強制決済 / 10日+3%未満手仕舞い / 7日建値割れ撤退
    if pl <= -5: return "🛑即損切り(-5%)"
    if typ == "A" and pl >= 5: return "🎯トレーリング利確(高値-2%)"
    if typ == "B" and pl >= 10: return "🎯トレーリング(高値-2%)"
    if days >= 14: return "⏰強制決済(14日経過)"
    if days >= 10 and pl < 3: return "💧手仕舞い検討(10日+3%未満)"
    if days >= 7 and pl <= 0: return "🛑撤退(7日建値割れ)"
    return "✅継続"


def send(msg):
    req = urllib.request.Request(
        WEBHOOK, data=json.dumps({"content": msg}).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "kabu-stocks-bot/1.0"},
        method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        print("discord:", r.status)


def send_blocks(blocks):
    cur = ""
    for b in blocks:
        if len(cur) + len(b) + 1 > 1850:
            send(cur); cur = ""
        cur += ("\n" + b if cur else b)
    if cur:
        send(cur)


def main():
    if not WEBHOOK:
        print("DISCORD_WEBHOOK 未設定。終了。"); return
    data = json.load(open("stocks.json", encoding="utf-8"))
    stocks = [s for s in data["stocks"] if s.get("status") == "ok"]
    codes = [s["code"] for s in stocks]
    sectors = load_sectors(codes)
    for s in stocks:
        s["sec"] = sectors.get(s["code"], "その他")

    jst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    h = jst.hour
    sess = "🌅朝" if h < 9 else ("🕛昼" if h < 14 else "🌆夕")
    blocks = [f"**🧭 {sess} 株教授デイリー（判断支援） {jst:%Y-%m-%d %H:%M}**\n"
              f"※買いシグナルではなく判断材料。最終判断はあなたのニュース・テーマ＋規律で。資金の土台は指数(買い持ち)。"]

    # 📊 日経平均＋ニュース
    ib = index_block()
    if ib:
        blocks.append(f"\n__📊 日経平均__ {yen(ib['last'])}（前日比{ib['chg']:+.1f}%）／25日線{'上' if ib['last']>ib['ma25'] else '下'}・75日線{'上' if ib['last']>ib['ma75'] else '下'}→**{ib['trend']}**")
    n = news_one("日経平均 株価")
    if n: blocks.append(f"　📰 {n}")

    # 🔥 セクター強度（1ヶ月騰落の平均）
    bysec = {}
    for s in stocks:
        bysec.setdefault(s["sec"], []).append(s["chg_1m_pct"])
    strength = [(sec, sum(v) / len(v), len(v)) for sec, v in bysec.items() if len(v) >= 3]
    strength.sort(key=lambda x: -x[1])
    if strength:
        top = strength[:5]
        blocks.append("\n__🔥 セクター強度（テーマの勢い・1ヶ月平均）__")
        blocks.append("　" + " ／ ".join(f"{i+1}.{sec} {avg:+.1f}%" for i, (sec, avg, _) in enumerate(top)))
    sec_rank = {sec: i for i, (sec, _, _) in enumerate(strength)}

    # 👀 注目候補（テーマ強度順）＋ニュース
    cands = []
    for s in stocks:
        ct = candidate_type(s)
        if ct in ("rebound", "pullback"):
            s["ct"] = ct
            s["secrank"] = sec_rank.get(s["sec"], 999)
            cands.append(s)
    cands.sort(key=lambda s: (s["secrank"], -(s.get("vol_ratio_pct") or 0)))
    if cands:
        blocks.append("\n__👀 注目候補（反発/押し目・テーマ強度順／優先度）__")
        for s in cands[:8]:
            tag = "反発" if s["ct"] == "rebound" else "押し目"
            hot_mark = "★強" if s["secrank"] < 5 else ""
            blocks.append(f"・**{s['name']}({s['code']})** [{s['sec']}{hot_mark}] {tag} "
                          f"RSI{s['rsi14']}/25線{s['dev_ma25_pct']:+.1f}%/出来高{(s.get('vol_ratio_pct') or 0):.0f}%")
        # 上位3候補のニュース
        for s in cands[:3]:
            nn = news_one(s["name"] + " 株")
            if nn: blocks.append(f"　📰 {s['name']}: {nn}")
    else:
        blocks.append("\n__👀 注目候補__ 本日は条件を満たす候補なし（静観）。")

    # ⚠️ 過熱
    hot = [s for s in stocks if candidate_type(s) == "hot"]
    if hot:
        hot.sort(key=lambda x: -x["dev_ma25_pct"])
        blocks.append("\n__⚠️ 過熱・飛びつき注意（日立型）__")
        for s in hot[:5]:
            blocks.append(f"・{s['name']}({s['code']}) RSI{s['rsi14']}/25線+{s['dev_ma25_pct']:.0f}%/月{s['chg_1m_pct']:+.0f}%")

    # 🔵 保有の出口アラート
    if HOLDINGS_RAW:
        by = {s["code"]: s for s in stocks}
        today = jst.date()
        blocks.append("\n__🔵 保有の出口アラート__")
        any_h = False
        for raw in HOLDINGS_RAW.replace(";", "\n").splitlines():
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            p = [x.strip() for x in raw.split(",")]
            if len(p) < 4:
                continue
            any_h = True
            code, buy, shares = p[0], float(p[1]), int(float(p[2]))
            bdate = datetime.datetime.strptime(p[3], "%Y-%m-%d").date()
            typ = p[4].upper() if len(p) > 4 else "A"
            s = by.get(code); days = (today - bdate).days
            if s:
                cur = s["last"]; pl = (cur / buy - 1) * 100
                blocks.append(f"・{s['name']}({code}) 型{typ} 買{yen(buy)}→現{yen(cur)} {pl:+.1f}%({(cur-buy)*shares:+,.0f}円) 保有{days}日 → {action_for(pl,days,typ)}")
            else:
                blocks.append(f"・{code} 現値取得不可（保有{days}日）→ {action_for(0,days,typ)}")
        if not any_h:
            blocks.append("・保有データなし")

    blocks.append(f"\nデータ:{data.get('generated_at_jst','')} ／ これは判断材料であり投資助言ではありません。最終判断はご自身で。")
    send_blocks(blocks)


if __name__ == "__main__":
    main()
