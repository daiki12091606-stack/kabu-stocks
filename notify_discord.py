"""
株教授 - Discord通知スクリプト（日経225スクリーニング / 買値・利確・損切・理由・保有売り時つき）
- stocks.json 全銘柄を7点ルールで型A/型B判定
- 通知するのは「候補」と「保有の売り時」と「監視12銘柄の状況」。見送りは件数のみ要約
- 保有は環境変数 HOLDINGS（GitHub Secret, 非公開）から取得
- Discordの2000字制限のため複数メッセージに分割送信
"""
import json, os, datetime, urllib.request

WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "").strip()
HOLDINGS_RAW = os.environ.get("HOLDINGS", "").strip()

# あなたの得意12銘柄（常に状況を表示）
CORE12 = {"6330", "1662", "1605", "7011", "7013", "6141",
          "6157", "3436", "6981", "5401", "3402", "3036"}


def yen(x):
    return f"¥{int(round(x)):,}"


def classify(s):
    rsi = s["rsi14"]; dev = s["dev_ma25_pct"]; m1 = s["chg_1m_pct"]
    vol = s.get("vol_ratio_pct") or 0; trend = s["ma25_trend"]
    if trend == "down":
        return "ng"
    if rsi > 70 or dev > 25:
        return "hot"
    if vol >= 200 and rsi >= 50 and dev > 0:
        return "b"
    if 40 <= rsi <= 65 and abs(dev) <= 5 and m1 <= 20:
        return "a"
    return "watch"


def price_lines(s, typ):
    last = s["last"]
    buy = last
    target = last * (1.10 if typ == "b" else 1.06)
    stop = last * 0.97
    hard = last * 0.95
    return (f"買値メド {yen(buy)}（現値近辺）／利確メド {yen(target)}"
            f"／損切 {yen(stop)}（-3%）／強制損切 {yen(hard)}（-5%）")


def reason(s, cat):
    rsi = s["rsi14"]; dev = s["dev_ma25_pct"]; m1 = s["chg_1m_pct"]; vol = s.get("vol_ratio_pct") or 0
    if cat == "a":
        return (f"25日線が上向きで株価は25日線{dev:+.1f}%と近接、RSI{rsi}で過熱なく、"
                f"1ヶ月騰落{m1:+.0f}%も過熱圏外。上昇トレンド中の押し目として型Aの条件を満たす。"
                f"反発(下ヒゲ/陽線)を確認してから入る。")
    if cat == "b":
        return (f"25日線が上向き、出来高が25日平均比{vol:.0f}%と急増し株価は25日線+{dev:.1f}%でブレイク基調。"
                f"本日のホットテーマに該当すれば型Bの順張り候補。RSI{rsi}と過熱気味なのでトレーリングで利を伸ばす。")
    if cat == "hot":
        return (f"RSI{rsi}・25日線+{dev:.0f}%乖離と過熱の極み。飛びつきは高値掴み(日立型)リスク大。"
                f"押し目か、出来高を伴う再加速まで待つ。")
    if cat == "ng":
        return (f"25日線が下向き(RSI{rsi}, 1ヶ月{m1:+.0f}%)。中長期トレンドが崩れており、"
                f"型A・型Bとも前提を満たさず見送り。落ちるナイフは掴まない。")
    return (f"25日線は上向きだが、RSI{rsi}/25日線{dev:+.1f}%/1ヶ月{m1:+.0f}%が型A・型Bの条件に未達。"
            f"様子見。")


def holdings_section():
    if not HOLDINGS_RAW:
        return None
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date()
    items = []
    for raw in HOLDINGS_RAW.replace(";", "\n").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) < 4:
            continue
        code = parts[0]; buy = float(parts[1]); shares = int(float(parts[2]))
        bdate = datetime.datetime.strptime(parts[3], "%Y-%m-%d").date()
        typ = (parts[4].upper() if len(parts) > 4 else "A")
        items.append((code, buy, shares, bdate, typ))
    return items, today


def action_for(pl, days, typ):
    if pl <= -5:
        return "🛑 即損切り（-5%到達・無条件）"
    if days >= 21:
        return "⏰ 強制決済（21日経過）"
    if days >= 14:
        return "🔍 強制レビュー（14日経過・損益問わず見直し）"
    if days <= 3 and pl <= -3:
        return "🛑 損切り（3日以内-3%）"
    if days >= 7 and pl <= 0:
        return "🛑 撤退（7日経過で建値割れ）"
    if days >= 10 and pl < 3:
        return "💧 手仕舞い検討（10日経過で+3%未満・資金回転優先）"
    if typ == "A" and pl >= 5:
        return "🎯 +5%超→トレーリング利確（高値-2%で利確）"
    if typ == "B" and pl >= 10:
        return "🎯 +10%超→トレーリング（高値-2%）"
    return "✅ 保有継続"


def send(msg):
    req = urllib.request.Request(
        WEBHOOK, data=json.dumps({"content": msg}).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "User-Agent": "kabu-stocks-bot/1.0 (+https://github.com/)"},
        method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        print("discord status:", r.status)


def send_blocks(header, blocks, footer):
    """blocks(文字列リスト)を2000字制限内に詰めて複数送信"""
    chunks = []
    cur = header
    for b in blocks:
        if len(cur) + len(b) + 2 > 1850:
            chunks.append(cur)
            cur = ""
        cur += ("\n" + b)
    cur += "\n" + footer
    chunks.append(cur)
    for i, c in enumerate(chunks):
        send(c if i == 0 else "（続き）\n" + c)


def main():
    if not WEBHOOK:
        print("DISCORD_WEBHOOK 未設定。終了。"); return
    with open("stocks.json", encoding="utf-8") as f:
        data = json.load(f)
    by_code = {s["code"]: s for s in data["stocks"]}

    cats = {"a": [], "b": [], "hot": [], "watch": [], "ng": [], "data": []}
    for s in data["stocks"]:
        if s.get("status") != "ok":
            cats["data"].append(s); continue
        cats[classify(s)].append(s)

    jst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    h = jst.hour
    sess = "🌅朝" if h < 9 else ("🕛昼" if h < 14 else "🌆夕")
    header = f"**{sess} 株教授スクリーニング {jst:%Y-%m-%d %H:%M}**（対象{data['count']}銘柄/日経225+得意12）"

    blocks = []

    # 1) 保有の売り時
    hs = holdings_section()
    if hs:
        items, today = hs
        blocks.append("\n__🔵 保有銘柄の売り時__")
        if not items:
            blocks.append("・（保有データなし）")
        for code, buy, shares, bdate, typ in items:
            s = by_code.get(code)
            cur = s["last"] if s and s.get("status") == "ok" else None
            days = (today - bdate).days
            if cur is not None:
                pl = (cur / buy - 1) * 100
                act = action_for(pl, days, typ)
                nm = s["name"]
                pnl_yen = (cur - buy) * shares
                blocks.append(f"・{nm}({code}) 型{typ} 買{yen(buy)}→現{yen(cur)} "
                              f"損益{pl:+.1f}%({pnl_yen:+,.0f}円) 保有{days}日 → {act}")
            else:
                blocks.append(f"・{code} 現値取得不可（保有{days}日）")

    # 2) 型A候補
    if cats["a"]:
        blocks.append("\n__🟢 型A候補（押し目順張り）__")
        for s in sorted(cats["a"], key=lambda x: x["rsi14"]):
            blocks.append(f"・**{s['name']}({s['code']})**　{price_lines(s,'a')}\n　{reason(s,'a')}")

    # 3) 型B候補
    if cats["b"]:
        blocks.append("\n__🟢 型B候補（ブレイク・要テーマ確認）__")
        for s in sorted(cats["b"], key=lambda x: -(x.get("vol_ratio_pct") or 0)):
            blocks.append(f"・**{s['name']}({s['code']})**　{price_lines(s,'b')}\n　{reason(s,'b')}")

    # 4) 過熱（上位のみ・飛びつき注意）
    if cats["hot"]:
        top = sorted(cats["hot"], key=lambda x: -(x["dev_ma25_pct"]))[:5]
        blocks.append("\n__⚠️ 過熱・飛びつき注意（上位5）__")
        for s in top:
            blocks.append(f"・{s['name']}({s['code']}) RSI{s['rsi14']}/25線+{s['dev_ma25_pct']:.0f}%"
                          f"/月{s['chg_1m_pct']:+.0f}%/出来高{(s.get('vol_ratio_pct') or 0):.0f}% — {reason(s,'hot')}")

    # 5) 監視12銘柄の状況（常に詳細）
    blocks.append("\n__📋 得意12銘柄の状況__")
    label = {"a": "🟢型A候補", "b": "🟢型B候補", "hot": "⚠️過熱", "watch": "🟡様子見", "ng": "🔴見送り", "data": "❓データ不可"}
    for code in CORE12:
        s = by_code.get(code)
        if not s:
            continue
        if s.get("status") != "ok":
            blocks.append(f"・{s['name']}({code}) ❓データ取得不可"); continue
        cat = classify(s)
        blocks.append(f"・{s['name']}({code}) {label[cat]}：{reason(s, cat)}")

    # 6) 見送り件数の要約
    blocks.append(f"\n__🔴 見送り（全体）__ {len(cats['ng'])}銘柄が25日線下向き等で見送り。"
                  f"様子見{len(cats['watch'])}・過熱{len(cats['hot'])}・データ不可{len(cats['data'])}。")

    footer = (f"\nデータ:{data['generated_at_jst']} ／ マクロ・ニュース・テーマはPC側の深い分析参照。"
              f"これは判断材料であり、最終判断はご自身で（投資助言ではありません）。")

    send_blocks(header, blocks, footer)


if __name__ == "__main__":
    main()
