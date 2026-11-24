#!/usr/bin/env python3
"""SJTV ショート動画の自動生成（縦1080x1920・3人掛け合い・イラスト入り）

  python3 sjtv_video.py digest --match 548 --phase review --kickoff "2026-11-22 00:00"
      → 試合ひも付けの記事から「3行要約・レポート・記事解説」だけを抜き出して表示（台本の材料）
  python3 sjtv_video.py render script.json [--rules rules.json] [--out 出力.mp4]
      → 台本JSONから動画を書き出す（表記チェック→音声→コマ→mp4）。初回は音声合成を自動で導入

台本JSON:
{"title": "スパーズ 2-0 イプスウィッチ", "label": "MATCH REVIEW", "cast": ["I", "H", "K"],  # castは出演者（1人なら大きく表示）
 "scenes": [{"art": "score", "args": {...}, "kicker": "結果", "info": ["1行目(強調)", "2行目", "3行目"],
             "lines": [["I", "セリフ"], ["H", "..."], ["K", "字幕の文", "読み上げ用の文（読み間違いの回避。省略可）"]]}, ...],
 "credit": "情報源：..."}
話者: I=石川（進行） H=ひなっち（事実） K=AKARI（ファン・トレーナー目線）
イラスト(art)と args:
  score   {"score": "2 - 0"}                       ピッチとスコアボード
  versus  {"home": "スパーズ", "away": "サンダーランド"}   対戦カード（プレビュー向け）
  star    {"no": "18"}                             選手のシルエット（背番号の位置に数字）
  record  {"big": "No.2", "small": "プレミア史上"}     メダル
  mail    {"to": "Opta", "msg1": "アシスト\\n付けて！", "msg2": "効いた！"}  封筒とスマホ
  coach   {"bubble": "完全に\\nコント\\nロール", "note": "6人入れ替え"}  作戦ボードと吹き出し
  ratings {"rows": [["名前", 9], ...]}  (最大6人)    採点の棒グラフ
  injury  {"note": "同じ負傷"}                      救急箱と氷のう
  next    {"month": "11月", "day": "29", "time": "日曜 23:05", "tag": "AWAY"}  カレンダーとバス
  quote   {"text": "短い発言"}                      大きな吹き出し（会見・発言）
  comment {"theme": "今日のMOMは誰？"}               コメント欄への呼びかけ（毎回の締めの定番）

締めの定番：最後のシーンは art "comment"。3人の回はひなっちが「〇〇をコメント欄に書き込んで！」と先導、
結果速報（1人）は石川が呼びかける。お題はコメントしやすい一言で答えられるものにする
  プレビュー例：スコア予想／先発予想／注目選手　レビュー・結果速報例：MOMは誰？／採点をつけて／今の気持ちを一言
"""
import sys, os, re, json, math, html, wave, argparse, subprocess, urllib.request

W, H, FPS = 1080, 1920, 30
NAVY = (19, 34, 87); NAVY2 = (12, 22, 58); WHITE = (255, 255, 255)
LIGHT = (225, 230, 242); GOLD = (214, 178, 94); GREY = (150, 160, 185)
GREEN, GREEN2, RED = (46, 140, 82), (38, 120, 70), (210, 60, 60)
FR = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FB = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FK = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
HOME = os.path.expanduser("~/.sjtv"); TOHOKU = f"{HOME}/htsvoice-tohoku-f01"
API = "https://spurs.sc/coys/wp-json/wp/v2/posts"
HUB_CATEGORY = 542  # まとめ

CAST = {  # 話者: (表示名, 色, 仮の声ファイル, 速さ, 高さ)  ※本番はクローン音声に差し替え
    "I": ("石川", (110, 165, 255), "mei", 1.05, -5.0),
    "H": ("ひなっち", (110, 210, 150), "tohoku-neutral", 1.08, -4.0),
    "K": ("AKARI", (255, 150, 190), "tohoku-happy", 1.08, 0.0),
}
SPEECH_FIX = [("＝", ""), ("一言", "ひとこと"), ("MOM", "マン・オブ・ザ・マッチ"), ("勝った", "かった"), ("勝って", "かって"), ("勝つ", "かつ"), ("勝ちたい", "かちたい"), ("2-0", "2対0"), ("0-1", "0対1"), ("1-0", "1対0"), ("1-1", "1対1"), ("2-1", "2対1"),
              ("1ゴール1アシスト", "ワンゴール、ワンアシスト"), ("football.london", "フットボールロンドン"),
              ("Opta", "オプタ"), ("COYS", "カモン・ユー・スパーズ"), ("GK", "ゴールキーパー"), ("CB", "センターバック"),
              ("SB", "サイドバック"), ("xG", "ゴール期待値"), ("スパーズジャパンTV", "スパーズジャパン・ティーヴィー"),
              ("Instagram", "インスタグラム"), ("Sky Sports", "スカイスポーツ"), ("BBC", "ビービーシー"),
              ("！", "。"), ("？", "。")]

# ================= digest =================
def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "sjtv-video"}), timeout=40) as r:
        return json.load(r)

def text_of(h):
    h = re.sub(r"<(script|style|blockquote|figure)[^>]*>.*?</\1>", "", h, flags=re.S)
    h = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", h)
    t = html.unescape(re.sub(r"<[^>]+>", "", h))
    return re.sub(r"[ \t]*\n\s*", "\n", t).strip()

def sections(content):
    pts = re.findall(r"✔\s*([^<\n]+)", content)
    m = re.split(r"<h2[^>]*>\s*(レポート|記事解説)\s*</h2>", content)
    rep = ana = ""
    for i in range(1, len(m) - 1, 2):
        if m[i] == "レポート": rep = text_of(m[i + 1])
        else: ana = text_of(m[i + 1].split("投稿元")[0])
    if not rep: rep = text_of(content)
    return [p.strip() for p in pts], rep, ana

def digest(a):
    posts, page = [], 1
    while True:
        batch = get(f"{API}?sj_match={a.match}&per_page=50&page={page}&_fields=id,date,title,content,categories")
        posts += batch
        if len(batch) < 50: break
        page += 1
    ko = a.kickoff.replace(" ", "T")
    sel = [p for p in posts if HUB_CATEGORY not in p.get("categories", [])
           and ((p["date"] >= ko) if a.phase == "review" else (p["date"] < ko))]
    sel.sort(key=lambda p: p["date"])
    print(f"# 試合ID {a.match} {a.phase}：{len(sel)}本（古い順）\n")
    for p in sel:
        pts, rep, ana = sections(p["content"]["rendered"])
        print(f"## [{p['id']}] {p['date'][5:16]} {html.unescape(p['title']['rendered'])}")
        if pts: print("要点：" + "／".join(pts))
        print("レポート：" + rep[:a.report_chars].replace("\n", " "))
        if ana: print("解説：" + ana[:a.analysis_chars].replace("\n", " "))
        print()

# ================= 表記チェック =================
def check_terms(spec, rules_path):
    rules = json.load(open(rules_path))
    texts = [spec.get("title", "")]
    for sc in spec["scenes"]:
        texts += [sc.get("kicker", "")] + sc.get("info", []) + [l[1] for l in sc["lines"]]
        texts += [str(v) for v in sc.get("args", {}).values() if isinstance(v, str)]
        texts += [r[0] for r in sc.get("args", {}).get("rows", [])]
    body = "\n".join(texts); bad = []
    for r in rules.get("banned_terms", []):
        w = r["wrong"]
        if "(" in w: continue
        for m in re.finditer(re.escape(w), body):
            nxt = body[m.end():m.end() + 1]
            if r.get("exclude_if_followed_by") and nxt == r["exclude_if_followed_by"]: continue
            if r["correct"].startswith(w) or w in r["correct"]:  # 正しい表記の一部に含まれる場合
                if body[m.start():m.start() + len(r["correct"])] == r["correct"]: continue
            bad.append(f"「{w}」→「{r['correct']}」")
    return sorted(set(bad))

# ================= 音声 =================
def setup_voice():
    try:
        import pyopenjtalk  # noqa
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--break-system-packages", "pyopenjtalk"], check=True)
    if not os.path.exists(TOHOKU):
        os.makedirs(HOME, exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--depth", "1", "https://github.com/icn-lab/htsvoice-tohoku-f01.git", TOHOKU], check=True)

_eng = {}
def tts(spk, text, out):
    import numpy as np, pyopenjtalk
    from pyopenjtalk.htsengine import HTSEngine
    _, _, v, spd, ht = CAST[spk]
    path = (os.path.join(os.path.dirname(pyopenjtalk.__file__), "htsvoice", "mei_normal.htsvoice") if v == "mei"
            else f"{TOHOKU}/tohoku-f01-{v.split('-')[1]}.htsvoice")
    if path not in _eng: _eng[path] = HTSEngine(path.encode())
    e = _eng[path]; e.set_speed(spd); e.add_half_tone(ht)
    s = text
    for x, y in SPEECH_FIX: s = s.replace(x, y)
    x = e.synthesize(pyopenjtalk.extract_fullcontext(s)); sr = e.get_sampling_frequency()
    x = x / max(1e-6, np.abs(x).max()) * 0.85 * 32767
    x = np.concatenate([np.zeros(int(sr * .1)), x, np.zeros(int(sr * .35))]).astype(np.int16)
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(x.tobytes())
    return len(x) / sr

def reading(text):
    import pyopenjtalk
    s = text
    for x, y in SPEECH_FIX: s = s.replace(x, y)
    return pyopenjtalk.g2p(s, kana=True)

# ================= 描画 =================
from PIL import Image, ImageDraw, ImageFont
_fc = {}
def font(p, s):
    if (p, s) not in _fc: _fc[(p, s)] = ImageFont.truetype(p, s, index=0)
    return _fc[(p, s)]

def wrap(d, text, f, maxw):
    lines, cur = [], ""
    for ch in text:
        if ch == "\n": lines.append(cur); cur = ""; continue
        if d.textlength(cur + ch, font=f) > maxw and cur:
            if ch in "、。」）！？ゃゅょっぁぃぅぇぉャュョッァィゥェォー": cur += ch; continue
            m = re.search(r"[A-Za-z0-9.]+$", cur)  # 英数字の語の途中で切らない
            if m and ch.isascii() and ch.isalnum() and m.start() > 0:
                lines.append(cur[:m.start()]); cur = cur[m.start():] + ch
            else:
                lines.append(cur); cur = ch
        else: cur += ch
    if cur: lines.append(cur)
    return lines

SS = 2
def art(kind, a, cw=960, ch=640):
    im = Image.new("RGB", (cw * SS, ch * SS), (232, 237, 248)); d = ImageDraw.Draw(im)
    s = lambda *v: [x * SS for x in v]
    cx, cy = cw // 2, ch // 2
    T = lambda x, y, t, f, sz, col, **k: d.multiline_text((x * SS, y * SS), t, font=font(f, sz * SS), fill=col, anchor="mm", align="center", **k)
    def ball(x, y, r):
        d.ellipse(s(x - r, y - r, x + r, y + r), fill=WHITE, outline=NAVY2, width=4 * SS)
        pts = [(x + r * .45 * math.cos(t), y + r * .45 * math.sin(t)) for t in [math.radians(-90 + 72 * i) for i in range(5)]]
        d.polygon([(px * SS, py * SS) for px, py in pts], fill=NAVY2)
        for px, py in pts: d.line(s(px, py, x + (px - x) * 2.1, y + (py - y) * 2.1), fill=NAVY2, width=3 * SS)
    def star(x, y, r):
        d.polygon([((x + (r if i % 2 == 0 else r * .45) * math.cos(math.radians(-90 + 36 * i))) * SS,
                    (y + (r if i % 2 == 0 else r * .45) * math.sin(math.radians(-90 + 36 * i))) * SS) for i in range(10)], fill=GOLD)
    def shield(x, y, col, label):
        d.polygon(s(x - 110, y - 130, x + 110, y - 130, x + 110, y + 20, x, y + 130, x - 110, y + 20), fill=col)
        T(x, y - 10, label, FK, 40 if len(label) <= 5 else 30, WHITE)
    if kind in ("score", "versus"):
        d.rounded_rectangle(s(60, 60, cw - 60, ch - 60), 30 * SS, fill=GREEN)
        for i in range(1, 6, 2): d.rectangle(s(60 + i * 140, 60, 60 + (i + 1) * 140, ch - 60), fill=GREEN2)
        d.rounded_rectangle(s(60, 60, cw - 60, ch - 60), 30 * SS, outline=WHITE, width=6 * SS)
        d.line(s(cx, 60, cx, ch - 60), fill=WHITE, width=6 * SS)
        d.ellipse(s(cx - 90, cy - 90, cx + 90, cy + 90), outline=WHITE, width=6 * SS)
        if kind == "score":
            d.rounded_rectangle(s(cx - 250, cy - 120, cx + 250, cy + 60), 24 * SS, fill=NAVY2)
            T(cx, cy - 30, a.get("score", ""), FK, 120, GOLD); ball(cx + 280, cy + 170, 50)
        else:
            shield(cx - 230, cy, NAVY, a.get("home", "")); shield(cx + 230, cy, (90, 90, 100), a.get("away", ""))
            d.ellipse(s(cx - 60, cy - 60, cx + 60, cy + 60), fill=NAVY2); T(cx, cy, "VS", FK, 50, GOLD)
    elif kind == "star":
        for r, c in ((300, (214, 224, 245)), (230, (200, 213, 240))): d.ellipse(s(cx - r, cy - r + 20, cx + r, cy + r + 20), fill=c)
        star(cx - 300, 150, 50); star(cx + 310, 190, 36); star(cx + 250, 470, 28)
        x, y, k = cx - 40, cy + 70, 1.6
        d.ellipse(s(x - 34 * k, y - 150 * k, x + 34 * k, y - 82 * k), fill=(240, 200, 170))
        d.rounded_rectangle(s(x - 48 * k, y - 80 * k, x + 48 * k, y + 20 * k), 22 * SS, fill=NAVY)
        T(x, y - 30 * k, str(a.get("no", "")), FK, int(40 * k), GOLD)
        for x1, y1, x2, y2, c in ((-20, 20, -30, 110, NAVY2), (20, 20, 90, 80, NAVY2), (-46, -70, -100, -20, NAVY), (46, -70, 100, -130, NAVY)):
            d.line(s(x + x1 * k, y + y1 * k, x + x2 * k, y + y2 * k), fill=c, width=int(21 * k * SS))
        ball(cx + 190, cy + 220, 42)
    elif kind == "record":
        d.polygon(s(cx - 120, 90, cx - 40, 300, cx + 40, 300, cx + 120, 90), fill=(30, 60, 150))
        d.polygon(s(cx - 40, 90, cx, 200, cx + 40, 90), fill=(220, 60, 60))
        d.ellipse(s(cx - 160, 250, cx + 160, 570), fill=GOLD); d.ellipse(s(cx - 125, 285, cx + 125, 535), fill=(236, 205, 130))
        T(cx, 395, a.get("big", ""), FK, 92 if len(a.get("big", "")) <= 4 else 60, NAVY2); T(cx, 480, a.get("small", ""), FB, 34, NAVY2)
        star(cx - 300, 300, 46); star(cx + 300, 300, 46)
    elif kind == "mail":
        d.rounded_rectangle(s(110, 170, 560, 470), 20 * SS, fill=WHITE, outline=NAVY2, width=6 * SS)
        d.line(s(110, 175, 335, 340, 560, 175), fill=NAVY2, width=6 * SS); T(335, 420, a.get("to", ""), FK, 44, NAVY)
        for i in range(3): d.line(s(20, 260 + i * 40, 90, 260 + i * 40), fill=GREY, width=6 * SS)
        d.rounded_rectangle(s(640, 80, 860, 560), 34 * SS, fill=NAVY2); d.rounded_rectangle(s(656, 120, 844, 520), 18 * SS, fill=WHITE)
        d.rounded_rectangle(s(670, 150, 830, 260), 16 * SS, fill=(220, 230, 250)); T(750, 205, a.get("msg1", ""), FB, 26, NAVY2)
        d.rounded_rectangle(s(670, 290, 830, 400), 16 * SS, fill=GOLD); T(750, 345, a.get("msg2", ""), FK, 32, NAVY2)
    elif kind == "coach":
        d.rounded_rectangle(s(120, 90, 600, 560), 24 * SS, fill=(60, 120, 80)); d.rounded_rectangle(s(120, 90, 600, 560), 24 * SS, outline=(150, 110, 60), width=16 * SS)
        for x, y in [(220, 200), (220, 440), (360, 320), (500, 200), (500, 440)]: d.ellipse(s(x - 24, y - 24, x + 24, y + 24), fill=WHITE)
        d.line(s(250, 220, 330, 300), fill=GOLD, width=8 * SS); d.line(s(390, 300, 470, 220), fill=GOLD, width=8 * SS)
        d.ellipse(s(640, 120, 900, 380), fill=WHITE, outline=NAVY2, width=6 * SS); d.polygon(s(690, 350, 660, 440, 740, 370), fill=WHITE)
        T(770, 250, a.get("bubble", ""), FK, 40, NAVY2); T(760, 500, a.get("note", ""), FK, 44, NAVY2)
    elif kind == "ratings":
        rows = a.get("rows", [])[:6]; n = max(1, len(rows)); bw = 120; gap = 28; x0 = (cw - (bw * n + gap * (n - 1))) // 2
        top_v = max(float(v) for _, v in rows) if rows else 0
        for i, (name, v) in enumerate(rows):
            v = float(v); x = x0 + i * (bw + gap); top = 480 - v * 40
            col = GOLD if v == top_v else ((70, 100, 180) if v >= 7.5 else (150, 165, 200))
            d.rounded_rectangle(s(x, top, x + bw, 480), 14 * SS, fill=col)
            T(x + bw / 2, top - 34, f"{v:g}", FK, 46, NAVY2)
            nm = name if len(name) <= 6 else name.replace("＝", "\n＝", 1)
            T(x + bw / 2, 535, nm, FB, 22, NAVY2)
    elif kind == "injury":
        d.rounded_rectangle(s(cx - 330, 110, cx + 30, 470), 40 * SS, fill=WHITE, outline=(220, 70, 70), width=8 * SS)
        d.rectangle(s(cx - 190, 170, cx - 110, 410), fill=(220, 70, 70)); d.rectangle(s(cx - 270, 250, cx - 30, 330), fill=(220, 70, 70))
        d.rounded_rectangle(s(cx + 90, 180, cx + 360, 420), 50 * SS, fill=(150, 200, 240))
        for i in range(3): d.ellipse(s(cx + 130 + i * 70, 260, cx + 170 + i * 70, 300), fill=(205, 230, 250))
        T(cx + 225, 480, "ICE", FK, 44, NAVY); T(cx - 150, 540, a.get("note", ""), FK, 50, (200, 60, 60))
    elif kind == "next":
        d.rounded_rectangle(s(110, 100, 470, 540), 26 * SS, fill=WHITE, outline=NAVY2, width=6 * SS)
        d.rounded_rectangle(s(110, 100, 470, 210), 26 * SS, fill=RED); d.rectangle(s(110, 170, 470, 210), fill=RED)
        T(290, 155, a.get("month", ""), FK, 50, WHITE); T(290, 360, a.get("day", ""), FK, 180, NAVY2); T(290, 490, a.get("time", ""), FB, 40, NAVY2)
        d.rounded_rectangle(s(540, 300, 900, 480), 30 * SS, fill=NAVY)
        for i in range(4): d.rounded_rectangle(s(565 + i * 82, 325, 630 + i * 82, 385), 8 * SS, fill=(190, 210, 245))
        d.ellipse(s(590, 450, 660, 520), fill=NAVY2); d.ellipse(s(780, 450, 850, 520), fill=NAVY2)
        T(720, 430, a.get("tag", ""), FK, 34, GOLD); ball(720, 190, 60)
    elif kind == "comment":  # コメント欄への呼びかけ（毎回の締め）
        d.rounded_rectangle(s(70, 70, cw - 70, ch - 70), 40 * SS, fill=WHITE, outline=NAVY2, width=6 * SS)
        d.rectangle(s(70, 70, cw - 70, 160), fill=NAVY); d.rounded_rectangle(s(70, 70, cw - 70, 160), 40 * SS, fill=NAVY)
        d.rectangle(s(70, 120, cw - 70, 160), fill=NAVY)
        T(cx, 115, "💬 コメント欄へ" if False else "コメント欄に書き込んで！", FK, 44, GOLD)
        lines = wrap(d, a.get("theme", ""), font(FK, 64 * SS), (cw - 240) * SS)
        T(cx, 300, "\n".join(lines[:3]), FK, 64, NAVY2, spacing=14 * SS)
        for i, w in enumerate([420, 300, 360]):
            y = 440 + i * 36; d.rounded_rectangle(s(150, y, 150 + w, y + 18), 9 * SS, fill=(215, 222, 238))
            d.ellipse(s(100, y - 6, 130, y + 24), fill=(190, 200, 225))
        d.rounded_rectangle(s(cw - 330, 470, cw - 130, 540), 35 * SS, fill=RED); T(cw - 230, 505, "送信", FK, 34, WHITE)
    elif kind == "quote":
        d.rounded_rectangle(s(90, 80, cw - 90, 470), 60 * SS, fill=WHITE, outline=NAVY2, width=6 * SS)
        d.polygon(s(220, 465, 180, 580, 320, 468), fill=WHITE); d.line(s(220, 470, 180, 580, 320, 470), fill=NAVY2, width=6 * SS)
        T(150, 140, "“", FK, 120, GOLD)
        lines = wrap(d, a.get("text", ""), font(FK, 60 * SS), (cw - 300) * SS)
        T(cx, 280, "\n".join(lines[:3]), FK, 60, NAVY2, spacing=16 * SS)
    return im.resize((cw, ch), Image.LANCZOS)

def avatar(spk, size, active):
    im = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    col = CAST[spk][1]; r = size * SS; m = r * .18
    d.ellipse([0, 0, r, r], fill=col if active else tuple(int(c * .45) for c in col))
    skin = (245, 210, 180) if active else (120, 105, 95); hair = (40, 35, 40) if active else (25, 25, 30)
    if spk == "K": d.ellipse([m * .8, m * .9, r - m * .8, r * 1.05], fill=hair)
    d.ellipse([m, m * 1.2, r - m, r - m * .6], fill=skin)
    if spk == "H": d.pieslice([m * .9, m * .7, r - m * .9, r * .7], 170, 370, fill=hair)
    else: d.chord([m, m * .9, r - m, r * .62], 180, 360, fill=hair)
    ey, ew = r * .55, r * .05
    for ex in (r * .38, r * .62): d.ellipse([ex - ew, ey - ew, ex + ew, ey + ew], fill=(30, 30, 40))
    if active: d.arc([r * .38, r * .58, r * .62, r * .74], 20, 160, fill=(150, 60, 60), width=int(r * .025))
    else: d.line([r * .42, r * .68, r * .58, r * .68], fill=(60, 40, 40), width=int(r * .02))
    return im.resize((size, size), Image.LANCZOS)

def frame(spec, sc, card, spk, text):
    im = Image.new("RGB", (W, H), NAVY2); d = ImageDraw.Draw(im)
    for i in range(0, H, 6):
        t = i / H; d.rectangle([0, i, W, i + 6], fill=tuple(int(NAVY[k] * (1 - t) + NAVY2[k] * t) for k in range(3)))
    d.rectangle([0, 0, W, 140], fill=(8, 14, 40))
    d.text((50, 40), "SJTV", font=font(FK, 52), fill=GOLD); d.text((215, 52), spec.get("label", ""), font=font(FB, 34), fill=LIGHT)
    d.text((W - 50, 52), spec.get("title", ""), font=font(FB, 32), fill=LIGHT, anchor="ra")
    d.text((60, 175), sc.get("kicker", ""), font=font(FK, 60), fill=WHITE)
    mask = Image.new("L", card.size, 0); ImageDraw.Draw(mask).rounded_rectangle([0, 0, *card.size], 36, fill=255)
    im.paste(card, (60, 280), mask)
    y = 950
    for j, ln in enumerate(sc.get("info", [])[:3]):
        d.text((W // 2, y), ln, font=font(FK if j == 0 else FB, 50 if j == 0 else 42), fill=GOLD if j == 0 else LIGHT, anchor="ma")
        y += 72 if j == 0 else 62
    cast = spec.get("cast", list(CAST))
    if len(cast) == 1:  # 1人出演：大きく中央に
        sz = 190; x = W // 2 - sz // 2; yy = 1175
        d.ellipse([x - 8, yy - 8, x + sz + 8, yy + sz + 8], outline=GOLD, width=6)
        av = avatar(cast[0], sz, True); im.paste(av, (x, yy), av)
        d.text((W // 2, 1385), CAST[cast[0]][0], font=font(FK, 34), fill=WHITE, anchor="ma")
    else:
        x = 90
        for c in cast:
            act = c == spk; sz = 170 if act else 120; yy = 1190 + (0 if act else 30)
            if act: d.ellipse([x - 8, yy - 8, x + sz + 8, yy + sz + 8], outline=GOLD, width=6)
            av = avatar(c, sz, act); im.paste(av, (x, yy), av)
            d.text((x + sz // 2, 1380), CAST[c][0], font=font(FK if act else FB, 34 if act else 28), fill=WHITE if act else GREY, anchor="ma")
            x += sz + 90
    f = font(FB, 46); lines = wrap(d, text, f, 800); y0 = 1440; hh = 40 + 62 * len(lines)
    d.rounded_rectangle([50, y0, 960, y0 + hh], 22, fill=(0, 0, 0)); d.rectangle([50, y0 + 14, 60, y0 + hh - 14], fill=CAST[spk][1])
    for i, ln in enumerate(lines): d.text((90, y0 + 20 + 62 * i), ln, font=f, fill=WHITE)
    return im

def render(a):
    spec = json.load(open(a.script))
    if a.rules and os.path.exists(a.rules):
        bad = check_terms(spec, a.rules)
        if bad: sys.exit("表記の誤り：" + "、".join(bad) + "（台本を直して再実行）")
    setup_voice()
    work = a.work or os.path.splitext(a.out)[0] + "_work"; os.makedirs(work, exist_ok=True)
    lst = []; i = 0; yomi = []
    for sc in spec["scenes"]:
        card = art(sc["art"], sc.get("args", {}))
        for li, ln in enumerate(sc["lines"]):
            spk, text = ln[0], ln[1]; say = ln[2] if len(ln) > 2 else text  # 3つ目があれば読み上げ用の文
            p = f"{work}/f{i:03d}"; i += 1
            frame(spec, sc, card, spk, text).save(p + ".png")
            dur = tts(spk, say, p + ".wav"); yomi.append(f"{i:02d} {spk} {reading(say)}")
            if a.frames_only: continue
            vf = f"format=yuv420p,loop=-1:1,trim=duration={dur:.3f}" + (",fade=t=in:st=0:d=0.2" if li == 0 else "")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", p + ".png", "-i", p + ".wav", "-vf", vf,
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
                            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", "-shortest", p + ".tmp.mp4"], check=True)
            os.rename(p + ".tmp.mp4", p + ".mp4"); lst.append(f"file '{os.path.abspath(p)}.mp4'")
    open(f"{work}/yomi.txt", "w").write("\n".join(yomi))  # 読みの確認用（カタカナ）
    if a.frames_only: print(work); return
    open(f"{work}/list.txt", "w").write("\n".join(lst))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", f"{work}/list.txt",
                    "-c", "copy", "-movflags", "+faststart", a.out], check=True)
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.out], capture_output=True, text=True).stdout.strip()
    print(f"{a.out}  {float(dur):.1f}秒  セリフ{i}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("digest"); g.add_argument("--match", required=True); g.add_argument("--phase", choices=["preview", "review"], required=True)
    g.add_argument("--kickoff", required=True, help="日本時間 'YYYY-MM-DD HH:MM'")
    g.add_argument("--report-chars", type=int, default=220); g.add_argument("--analysis-chars", type=int, default=150)
    r = sub.add_parser("render"); r.add_argument("script"); r.add_argument("--rules"); r.add_argument("--out", default="sjtv_short.mp4")
    r.add_argument("--work"); r.add_argument("--frames-only", action="store_true")
    a = ap.parse_args()
    digest(a) if a.cmd == "digest" else render(a)
