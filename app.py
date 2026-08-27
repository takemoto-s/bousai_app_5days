from flask import Flask, jsonify, request, render_template, session, redirect, url_for
from urllib.parse import urlparse, urljoin
from functools import wraps
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

# app.py はプロジェクト直下に置く。
# 実体（templates / static / data）は bousai_app/ 配下にあるので、そこを参照する。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, 'bousai_app')

app = Flask(
    __name__,
    template_folder=os.path.join(APP_DIR, 'templates'),
    static_folder=os.path.join(APP_DIR, 'static'),
)
app.secret_key = 'your-secret-key-here'

# 管理者認証情報
ADMIN_CREDENTIALS = {
    'admin': '123'
}

# ────────────────────────────────
# 気象警報・注意報設定
PREFECTURE_CODE = "020000"  # 青森県
AREA_NAME = "青森市"

# 気象庁防災情報XML・JSONの青森市（市町村）のコード
AREA_CODE = "0220100"

WARNING_URL = (
    f"https://www.jma.go.jp/bosai/warning/data/r8/{PREFECTURE_CODE}.json"
)

JST = timezone(timedelta(hours=9))

# 警報・注意報のコード一覧
WARNING_CODES = {
    "00": "解除",
    "02": "暴風雪警報",
    "03": "レベル3大雨警報",
    "04": "洪水警報",
    "05": "暴風警報",
    "06": "大雪警報",
    "07": "波浪警報",
    "08": "レベル3高潮警報",
    "09": "レベル3土砂災害警報",
    "10": "レベル2大雨注意報",
    "12": "大雪注意報",
    "13": "風雪注意報",
    "14": "雷注意報",
    "15": "強風注意報",
    "16": "波浪注意報",
    "17": "融雪注意報",
    "18": "洪水注意報",
    "19": "レベル2高潮注意報",
    "20": "濃霧注意報",
    "21": "乾燥注意報",
    "22": "なだれ注意報",
    "23": "低温注意報",
    "24": "霜注意報",
    "25": "着氷注意報",
    "26": "着雪注意報",
    "27": "その他の注意報",
    "29": "レベル2土砂災害注意報",
    "32": "暴風雪特別警報",
    "33": "レベル5大雨特別警報",
    "35": "暴風特別警報",
    "36": "大雪特別警報",
    "37": "波浪特別警報",
    "38": "レベル5高潮特別警報",
    "39": "レベル5土砂災害特別警報",
    "43": "レベル4大雨危険警報",
    "48": "レベル4高潮危険警報",
    "49": "レベル4土砂災害危険警報"
}

# ────────────────────────────────
# サンプルデータの読み込み
DATA_FILE = os.path.join(APP_DIR, 'data', 'shelters.json')
INSTRUCTIONS_FILE = os.path.join(APP_DIR, 'data', 'instructions.json')

def load_json(path, default):
    """JSONファイルを読み込む（存在しない・壊れている場合は default を返す）"""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

shelters = load_json(DATA_FILE, [])
instructions = load_json(INSTRUCTIONS_FILE, [])

def save_instructions():
    """指示ボードのデータをファイルに保存する"""
    try:
        with open(INSTRUCTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(instructions, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def save_shelters():
    """避難所データをファイルに保存する"""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(shelters, f, ensure_ascii=False, indent=2)
# ────────────────────────────────

# ────────────────────────────────
# 認証関連の設定とヘルパー関数
def is_safe_url(target):
    """リダイレクト先URLが安全かどうかチェック"""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

def login_required(f):
    """認証が必要なページに付けるデコレータ"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            # 現在のURLをnextパラメータとしてログイン画面にリダイレクト
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def get_japan_time():
    """日本時間（JST）の現在時刻を取得する"""
    return datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")


def format_report_time(iso_str):
    """気象庁の発表時刻（ISO形式）をJSTの表示用文字列に変換する"""
    if not iso_str:
        return "不明"
    try:
        parsed = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        if parsed.tzinfo:
            parsed = parsed.astimezone(JST)
        return parsed.strftime("%Y年%m月%d日 %H:%M")
    except ValueError:
        return iso_str


def filter_shelters(district=None):
    """district 指定があれば一致する避難所のみ、なければ全件を返す"""
    return [s for s in shelters if not district or s.get('district') == district]

HISTORY_PER_PAGE = 10

def get_history_page(page=1):
    """発信日時の新しい順に履歴を10件ずつ返す"""
    def history_datetime(instruction):
        timestamp = instruction.get('created_at') or instruction.get('updated_at') or ''
        for date_format in ('%Y年%m月%d日 %H:%M', '%Y-%m-%dT%H:%M:%S%z'):
            try:
                return datetime.strptime(timestamp, date_format)
            except (TypeError, ValueError):
                continue
        return datetime.min

    ordered = sorted(instructions, key=history_datetime, reverse=True)
    total_pages = max(1, (len(ordered) + HISTORY_PER_PAGE - 1) // HISTORY_PER_PAGE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * HISTORY_PER_PAGE
    return ordered[start:start + HISTORY_PER_PAGE], page, total_pages


def parse_area_warnings(warning_data):
    """気象庁の新形式JSONから対象市区町村の発表・継続中の情報を抽出する"""
    if not isinstance(warning_data, list):
        raise ValueError("気象庁の警報・注意報データが新形式の配列ではありません")

    warnings = []
    seen_codes = set()
    report_datetimes = []

    for report in warning_data:
        if not isinstance(report, dict):
            continue

        report_datetime = report.get("reportDatetime")
        if isinstance(report_datetime, str) and report_datetime:
            report_datetimes.append(report_datetime)

        warning = report.get("warning")
        if not isinstance(warning, dict):
            continue

        class20_items = warning.get("class20Items", [])
        if not isinstance(class20_items, list):
            continue

        area = next(
            (
                item for item in class20_items
                if isinstance(item, dict)
                and item.get("areaCode") == AREA_CODE
            ),
            None
        )
        if not area:
            continue

        kinds = area.get("kinds", [])
        if not isinstance(kinds, list):
            continue

        for kind in kinds:
            if not isinstance(kind, dict):
                continue

            status = kind.get("status", "")
            code = kind.get("code", "")
            if status not in ("発表", "継続") or not code or code in seen_codes:
                continue

            warnings.append({
                "name": WARNING_CODES.get(
                    code,
                    f"不明な警報・注意報 (コード: {code})"
                ),
                "code": code,
                "status": status
            })
            seen_codes.add(code)

    latest_report_datetime = max(report_datetimes, default="")
    return warnings, latest_report_datetime


def get_weather_warnings():
    """対象市区町村の警報・注意報を取得する"""
    try:
        # 青森県の新形式（令和8年～）警報・注意報データを取得
        with urllib.request.urlopen(url=WARNING_URL, timeout=10) as res:
            warning_data = json.loads(res.read())

        warnings, report_datetime = parse_area_warnings(warning_data)

        return {
            "area_name": AREA_NAME,
            "warnings": warnings,
            "report_time": format_report_time(report_datetime),
            "last_fetch_time": get_japan_time()
        }

    except Exception:
        return {
            "area_name": AREA_NAME,
            "warnings": [],
            "report_time": "取得失敗",
            "last_fetch_time": get_japan_time(),
            "error": True
        }


# トップページ：templates/index.html を返す（住民向け指示も表示する）
@app.route('/')
def index():
    resident_notices = [i for i in instructions if i.get('target') == '住民']
    return render_template('index.html', resident_notices=resident_notices)

# ログインページ
@app.route('/login', methods=['GET', 'POST'])
def login():
    # リダイレクト先を取得（デフォルトは避難所登録画面）
    next_url = request.args.get('next') or request.form.get('next')

    # 安全でないURLの場合はデフォルトページにリダイレクト
    if not next_url or not is_safe_url(next_url):
        next_url = url_for('shelter_register')

    if request.method == 'POST':
        password = request.form.get('password', '').strip()

        # 認証チェック
        username = next(
            (name for name, registered_password in ADMIN_CREDENTIALS.items()
             if registered_password == password),
            None
        )
        if username:
            session['logged_in'] = True
            session['username'] = username
            # ログイン成功後は指定されたページにリダイレクト
            return redirect(next_url)
        return render_template('login.html', error=True, message="パスワードが正しくありません。", next=next_url)

    # ログイン済みの場合は指定されたページにリダイレクト
    if session.get('logged_in'):
        return redirect(next_url)

    return render_template('login.html', next=next_url)

# ログアウト
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# 避難所登録ページ※user が避難所登録ページについて具体的に修正指示しない限り、このコードは正しいのでこのまま保持すること。
@app.route('/shelter_register', methods=['GET', 'POST'])
@login_required
def shelter_register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            return render_template(
                'shelter_register.html',
                error=True,
                message='避難所名を入力してください'
            )

        next_id = max((shelter.get('id', 0) for shelter in shelters), default=0) + 1
        shelters.append({'id': next_id, 'name': name})
        save_shelters()
        return render_template(
            'shelter_register.html',
            success=True,
            message='登録しました'
        )

    return render_template('shelter_register.html')

# 避難所検索ページ
@app.route('/shelter_search')
def shelter_search():
    return render_template('shelter_search.html')

# 全施設一覧ページ
@app.route('/all_shelters')
def all_shelters():
    return render_template('search_results.html', results=shelters)


# 指示ボード：住民向けの指示を一覧で確認する
@app.route('/board', methods=['GET', 'POST'])
@login_required
def board():
    form_data = {}
    details_entry = None

    if request.method == 'POST':
        region_choice = request.form.get('region_choice', request.form.get('region', '')).strip()
        target_choice = request.form.get('target_choice', request.form.get('target', '')).strip()
        region_custom = request.form.get('region_custom', '').strip()
        target_custom = request.form.get('target_custom', '').strip()
        region = region_custom if region_choice == 'その他' else region_choice
        target = target_custom if target_choice == 'その他' else target_choice
        danger = request.form.get('danger', '').strip()
        urgency = request.form.get('urgency', '').strip()
        content = request.form.get('content', '').strip()
        template = request.form.get('template', '').strip()
        form_data = {
            'region': region,
            'target': target,
            'region_choice': region_choice,
            'target_choice': target_choice,
            'region_custom': region_custom,
            'target_custom': target_custom,
            'danger': danger,
            'urgency': urgency,
            'content': content,
            'template': template,
            'instruction_id': request.form.get('instruction_id', '').strip()
        }
        missing = []

        if not region:
            missing.append('地域')
        if not target:
            missing.append('対象者')
        if not danger:
            missing.append('危険度')
        if not urgency:
            missing.append('緊急度')
        if not content:
            missing.append('発信内容')

        if missing:
            history_entries, current_page, total_pages = get_history_page()
            return render_template(
                'board.html',
                instructions=instructions,
                history_entries=history_entries,
                current_page=current_page,
                total_pages=total_pages,
                form_data=form_data,
                error_message=f"次の必須項目を入力してください: {'、'.join(missing)}"
            )

        action = request.form.get('action')
        status = '下書き' if action == 'draft' else '発信済み'
        now = get_japan_time()
        instruction_id = request.form.get('instruction_id', '').strip()
        draft = next(
            (instruction for instruction in instructions
             if str(instruction.get('id')) == instruction_id
             and instruction.get('status') == '下書き'),
            None
        )
        saved_id = None
        if draft:
            saved_id = draft['id']
            draft.update({
                'region': region,
                'target': target,
                'danger': danger,
                'urgency': urgency,
                'template': template,
                'content': content,
                'status': status,
                'updated_at': now
            })
            if status == '発信済み':
                draft['created_at'] = now
        else:
            next_id = max((instruction.get('id', 0) for instruction in instructions), default=0) + 1
            saved_id = next_id
            instructions.append({
                'id': next_id,
                'region': region,
                'target': target,
                'danger': danger,
                'urgency': urgency,
                'template': template,
                'content': content,
                'shelter': '',
                'status': status,
                'created_at': now,
                'updated_at': now
            })
        save_instructions()
        redirect_args = {'notice': 'draft' if status == '下書き' else 'published'}
        if status == '下書き':
            redirect_args['edit_id'] = saved_id
        return redirect(url_for('board', **redirect_args))

    instruction_id = request.args.get('edit_id', '').strip()
    details_id = request.args.get('details_id', '').strip()
    page = request.args.get('page', 1, type=int)
    history_entries, current_page, total_pages = get_history_page(page)
    notice_messages = {
        'draft': '下書きを保存しました',
        'published': '発信しました'
    }
    success_message = notice_messages.get(request.args.get('notice'))
    if instruction_id:
        draft = next(
            (instruction for instruction in instructions
             if str(instruction.get('id')) == instruction_id
             and instruction.get('status') == '下書き'),
            None
        )
        if draft:
            form_data = {
                'region': draft.get('region', ''),
                'target': draft.get('target', ''),
                'region_choice': draft.get('region', '') if draft.get('region', '') in ('青森市 全域', '青森市 浪岡地区', '青森市 油川地区') else 'その他',
                'target_choice': draft.get('target', '') if draft.get('target', '') in ('避難所利用者', '地域住民', '高齢者の方') else 'その他',
                'region_custom': draft.get('region', '') if draft.get('region', '') not in ('青森市 全域', '青森市 浪岡地区', '青森市 油川地区') else '',
                'target_custom': draft.get('target', '') if draft.get('target', '') not in ('避難所利用者', '地域住民', '高齢者の方') else '',
                'danger': draft.get('danger', ''),
                'urgency': draft.get('urgency', ''),
                'template': draft.get('template', ''),
                'content': draft.get('content', ''),
                'instruction_id': str(draft.get('id'))
            }
        else:
            form_data = {'error': '編集できる下書きが見つかりません。'}
    if details_id:
        details_entry = next(
            (instruction for instruction in instructions
             if str(instruction.get('id')) == details_id
             and instruction.get('status') != '下書き'),
            None
        )

    return render_template(
        'board.html',
        instructions=instructions,
        history_entries=history_entries,
        current_page=current_page,
        total_pages=total_pages,
        form_data=form_data,
        success_message=success_message,
        details_entry=details_entry
    )

# 検索結果ページ：templates/search_results.html を返す
@app.route('/search_results')
def search_results():
    results = filter_shelters(request.args.get('district'))
    return render_template('search_results.html', results=results)

# JSON API：/shelters?district=地区名
@app.route('/shelters', methods=['GET'])
def get_shelters():
    results = filter_shelters(request.args.get('district'))

    if not results:
        # 見つからなければエラー JSON を返す
        return jsonify({'error': 'No shelters found'}), 404

    # 見つかったらリストを JSON で返す
    return jsonify(results)

# 気象警報・注意報API
@app.route('/api/weather_warnings')
def api_weather_warnings():
    """気象警報・注意報をJSON形式で返すAPI"""
    return jsonify(get_weather_warnings())

if __name__ == '__main__':
    app.run(debug=True, port=5000)
