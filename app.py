"""きょうの時間割ボード todaytimetable

週間時間割を登録しておき、トップページでは Asia/Tokyo の「今日」の曜日の
授業だけを時限順に大きく表示するボード。曜日ごとの一覧ページで、その曜日の
授業の登録・削除ができる。単一ファイル Flask + SQLite。
"""
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, g, jsonify, redirect, render_template_string, request, url_for, abort

app = Flask(__name__)
JST = ZoneInfo("Asia/Tokyo")
DB_PATH = os.environ.get("TODAYTIMETABLE_DB", os.path.join(os.path.dirname(__file__), "todaytimetable.db"))

WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]  # index は datetime.weekday()（月=0〜日=6）
PERIOD_MIN = 1
PERIOD_MAX = 8
PERIODS = list(range(PERIOD_MIN, PERIOD_MAX + 1))


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weekday INTEGER NOT NULL,
            period INTEGER NOT NULL,
            subject TEXT NOT NULL,
            room TEXT NOT NULL DEFAULT '',
            memo TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        """
    )
    db.commit()
    db.close()


def parse_int(value, default=None):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def weekday_label(weekday):
    if 0 <= weekday < len(WEEKDAYS):
        return WEEKDAYS[weekday]
    return ""


def today_weekday(now=None):
    """Asia/Tokyo の今日の曜日（月=0〜日=6）を返す。"""
    now = now or datetime.now(JST)
    return now.weekday()


def classes_for_weekday(classes, weekday):
    """授業リスト（dict の列）から指定曜日のものだけを時限順に返す純粋関数。"""
    selected = [c for c in classes if int(c["weekday"]) == int(weekday)]
    return sorted(selected, key=lambda c: (int(c["period"]), int(c.get("id") or 0)))


def all_classes(db):
    rows = db.execute("SELECT * FROM classes ORDER BY weekday, period, id").fetchall()
    return [dict(r) for r in rows]


def validate_class(weekday, period, subject):
    if weekday is None or not (0 <= weekday < 7):
        return False
    if period is None or not (PERIOD_MIN <= period <= PERIOD_MAX):
        return False
    if not subject:
        return False
    return True


STYLE = """body{font-family:sans-serif;max-width:760px;margin:2em auto;padding:0 1em}
nav a{margin-right:.4em}
.big{font-size:1.35em}
.card{border:1px solid #bbb;border-radius:8px;padding:.8em 1em;margin:.8em 0}
.period{font-weight:bold;font-size:1.2em}
.subject{font-size:1.5em;font-weight:bold}
table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:.3em .5em}
input[type=text]{margin:.2em 0}"""

NAV = """<nav><a href="{{ url_for('index') }}">今日</a>｜{% for d in range(7) %}<a href="{{ url_for('week', weekday=d) }}">{{ weekdays[d] }}曜</a>{% if not loop.last %}・{% endif %}{% endfor %}</nav>"""

INDEX = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>きょうの時間割ボード</title>
<style>""" + STYLE + """</style>
</head><body>
""" + NAV + """
<h1>きょうの時間割ボード</h1>
<p class="big">今日は {{ today_label }}（{{ weekdays[today] }}曜日）です。</p>
<h2>{{ weekdays[today] }}曜日の授業（{{ classes|length }}件）</h2>
{% for c in classes %}
<div class="card">
  <span class="period">{{ c.period }}限</span>
  <span class="subject">{{ c.subject }}</span>
  {% if c.room %}<div>教室：{{ c.room }}</div>{% endif %}
  {% if c.memo %}<div>メモ：{{ c.memo }}</div>{% endif %}
</div>
{% else %}
<p class="big">今日の授業はありません。</p>
{% endfor %}
<p>授業の登録・変更は曜日ごとのページから行えます（上のナビから曜日を選んでください）。</p>
</body></html>"""

WEEK = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ weekdays[weekday] }}曜日の時間割 - きょうの時間割ボード</title>
<style>""" + STYLE + """</style>
</head><body>
""" + NAV + """
<h1>{{ weekdays[weekday] }}曜日の時間割（{{ classes|length }}件）</h1>
<table>
<tr><th>時限</th><th>科目名</th><th>教室</th><th>メモ</th><th>操作</th></tr>
{% for c in classes %}
<tr>
  <td>{{ c.period }}限</td>
  <td>{{ c.subject }}</td>
  <td>{{ c.room }}</td>
  <td>{{ c.memo }}</td>
  <td><form method="post" action="{{ url_for('delete_class', cid=c.id) }}" style="display:inline" onsubmit="return confirm('この授業を削除しますか？')"><input type="hidden" name="weekday" value="{{ weekday }}"><button>削除</button></form></td>
</tr>
{% else %}
<tr><td colspan="5">この曜日の授業はまだ登録されていません</td></tr>
{% endfor %}
</table>

<h2>授業を追加（{{ weekdays[weekday] }}曜日）</h2>
<form method="post" action="{{ url_for('add_class') }}">
  <input type="hidden" name="weekday" value="{{ weekday }}">
  <label>時限
    <select name="period">{% for p in periods %}<option value="{{ p }}">{{ p }}限</option>{% endfor %}</select></label><br>
  <label>科目名 <input type="text" name="subject" required size="40"></label><br>
  <label>教室 <input type="text" name="room" size="30" placeholder="任意"></label><br>
  <label>メモ <input type="text" name="memo" size="40" placeholder="任意"></label><br>
  <button type="submit">追加する</button>
</form>
<p><a href="{{ url_for('index') }}">今日の時間割に戻る</a></p>
</body></html>"""


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/")
def index():
    db = get_db()
    today = today_weekday()
    classes = classes_for_weekday(all_classes(db), today)
    return render_template_string(
        INDEX,
        weekdays=WEEKDAYS,
        today=today,
        today_label=datetime.now(JST).strftime("%Y年%m月%d日"),
        classes=classes,
    )


@app.route("/week/<int:weekday>")
def week(weekday):
    if not (0 <= weekday < 7):
        abort(404)
    db = get_db()
    classes = classes_for_weekday(all_classes(db), weekday)
    return render_template_string(
        WEEK,
        weekdays=WEEKDAYS,
        periods=PERIODS,
        weekday=weekday,
        classes=classes,
    )


@app.route("/classes", methods=["POST"])
def add_class():
    weekday = parse_int(request.form.get("weekday"))
    period = parse_int(request.form.get("period"))
    subject = (request.form.get("subject") or "").strip()
    if validate_class(weekday, period, subject):
        db = get_db()
        db.execute(
            "INSERT INTO classes(weekday, period, subject, room, memo, created_at) VALUES(?, ?, ?, ?, ?, ?)",
            (weekday, period, subject,
             (request.form.get("room") or "").strip(),
             (request.form.get("memo") or "").strip(),
             datetime.now(JST).strftime("%Y-%m-%d %H:%M")),
        )
        db.commit()
    if weekday is not None and 0 <= weekday < 7:
        return redirect(url_for("week", weekday=weekday))
    return redirect(url_for("index"))


@app.route("/classes/<int:cid>/delete", methods=["POST"])
def delete_class(cid):
    db = get_db()
    db.execute("DELETE FROM classes WHERE id = ?", (cid,))
    db.commit()
    weekday = parse_int(request.form.get("weekday"))
    if weekday is not None and 0 <= weekday < 7:
        return redirect(url_for("week", weekday=weekday))
    return redirect(url_for("index"))


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
