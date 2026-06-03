"""
株教授 - Discord通知スクリプト（GitHub Actions用）
stocks.json を読み、7点ルールで型A/型Bを機械判定し、結果をDiscordの非公開チャンネルへプッシュする。
Webhook URLは環境変数 DISCORD_WEBHOOK（GitHub Secrets）から取得。
"""
import json, os, datetime, urllib.request

WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "").strip()


def verdict(s):
    name = f"{s['name']}({s['code']})"
    if s.get("status") != "ok":
        return ("data", f"{name} データ取得不可")
    rsi = s["rsi14"]; dev = s["dev_ma25_pct"]; m1 = s["chg_1m_pct"]
    vol = s.get("vol_ratio_pct") or 0; trend = s["ma25_trend"]; last = s["last"]
    note = ""
    if last > 10000:
        note = " ※予算外(単元未満要)"
    elif last >= 5000:
        note = " ※高価格株特別枠(かぶミニ/手動損切り)"
    elif last < 1000:
        note = " ※低位:流動性要確認"
    if trend == "up" and (rsi > 70 or dev > 25):
        return ("hot", f"{name} RSI{rsi}/25線+{dev}%/月{m1:+.0f}%/出来高{vol:.0f}%{note}")
    if trend == "down":
        return ("ng", f"{name} 25線下向き(RSI{rsi}, 月{m1:+.0f}%)")
    if vol >= 200 and rsi >= 50 and dev > 0:
        return ("b", f"{name} RSI{rsi}/出来高{vol:.0f}%/月{m1:+.0f}% →型B候補(テーマ要確認){note}")
    if 40 <= rsi <= 65 and abs(dev) <= 5 and m1 <= 20:
        return ("a", f"{name} RSI{rsi}/25線{dev:+.1f}%/月{m1:+.0f}% →型A候補{note}")
    return ("watch", f"{name} RSI{rsi}/25線{dev:+.1f}%/月{m1:+.0f}%{note}")


def main():
    if not WEBHOOK:
        print("DISCORD_WEBHOOK 未設定。スキップ。")
        return
    with open("stocks.json", encoding="utf-8") as f:
        data = json.load(f)
    cats = {"a": [], "b": [], "hot": [], "watch": [], "ng": [], "data": []}
    for s in data["stocks"]:
        c, line = verdict(s)
        cats[c].append(line)
    jst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    h = jst.hour
    sess = "🌅朝" if h < 9 else ("🕛昼" if h < 14 else "🌆夕")
    parts = [f"**{sess} 株教授スクリーニング {jst:%Y-%m-%d %H:%M}**"]

    def sec(title, key):
        if cats[key]:
            parts.append(f"\n__{title}__")
            parts.extend("・" + x for x in cats[key])

    sec("🟢 型A候補(押し目)", "a")
    sec("🟢 型B候補(ブレイク/要テーマ確認)", "b")
    sec("⚠️ 過熱・飛びつき注意", "hot")
    sec("🟡 様子見", "watch")
    sec("🔴 見送り(25日線下向き等)", "ng")
    sec("❓ データ取得不可", "data")
    parts.append(f"\nデータ:{data['generated_at_jst']} ／ マクロ・テーマ・売り時は別途。これは判断材料であり、最終判断はご自身で。")
    msg = "\n".join(parts)
    if len(msg) > 1900:
        msg = msg[:1900] + "\n…(省略)"
    req = urllib.request.Request(
        WEBHOOK, data=json.dumps({"content": msg}).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "kabu-stocks-bot/1.0 (+https://github.com/)"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        print("discord status:", r.status)


if __name__ == "__main__":
    main()
