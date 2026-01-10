import os, csv, random, json, time, glob
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, session, make_response
from datetime import datetime, timedelta, timezone

app = Flask(__name__)
app.config['SECRET_KEY'] = 'denken-v2-1-strict-logic-full-final'

# 日本時間設定 (JST)
JST = timezone(timedelta(hours=9))

def get_jst_now():
    """現在の日本時間を取得する"""
    return datetime.now(JST)

# CSVファイルを保存しているルートディレクトリの定義
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_BASE_DIR = os.path.join(BASE_DIR, "logic", "csv_data")

def get_storage(request):
    """
    Cookieからユーザーデータを取得。
    KeyErrorを防止し、データが壊れている場合は空のリストで初期化する。
    """
    storage_str = request.cookies.get('denken_storage')
    storage = {"wrong_list": [], "logs": []}
    
    if storage_str:
        try:
            storage = json.loads(storage_str)
        except Exception as e:
            print(f"Cookie Load Error: {e}")
            storage = {"wrong_list": [], "logs": []}
    
    if not isinstance(storage, dict):
        storage = {"wrong_list": [], "logs": []}
    if 'wrong_list' not in storage or not isinstance(storage['wrong_list'], list):
        storage['wrong_list'] = []
    if 'logs' not in storage or not isinstance(storage['logs'], list):
        storage['logs'] = []
        
    return storage

# 分野の再定義
THEORY_CAT = ["理論"]
MACHINE_CATS = [
    "直流機", "誘導機", "同期機", "変圧器", 
    "四機総合問題", "電動機応用", "電気機器", "パワーエレクトロニクス", 
    "自動制御", "照明", "電熱", "電気化学", "メカトロニクス", "情報伝送及び処理"
]
TARGET_CATEGORIES = THEORY_CAT + MACHINE_CATS

def load_csv_data(mode):
    """
    CSVファイルを読み込む。IDを「カテゴリ_行番号」の形に固定し、
    ファイル名に依存しすぎないようにしてCookieの肥大化を防ぐ。
    """
    folder_mode = 'taku4' if mode == 'fill' else 'normal'
    search_path = os.path.join(CSV_BASE_DIR, folder_mode, "**", "*.csv")
    files = glob.glob(search_path, recursive=True)
    
    questions = []
    for f_path in files:
        f_name = os.path.basename(f_path)
        try:
            with open(f_path, encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                for i, row in enumerate(reader):
                    if len(row) >= 3:
                        cleaned_row = [str(cell).strip().replace('\r', '').replace('\n', '') for cell in row]
                        
                        # ID生成ロジックの固定
                        short_f_name = f_name.replace('.csv', '').replace('ox_', '').replace('normal_', '')
                        q_id = f"{mode[:1]}_{short_f_name}_{i}" 

                        dummies = []
                        if mode == 'fill':
                            # 改良：正解と解説以外の列（5列目以降）からダミーを抽出
                            raw_candidates = cleaned_row[4:] 
                            dummies = [d for d in raw_candidates if d and d != cleaned_row[2]]

                        questions.append({
                            'id': q_id, 
                            'category': cleaned_row[0], 
                            'front': cleaned_row[1], 
                            'back': cleaned_row[2], 
                            'note': cleaned_row[3] if len(cleaned_row) > 3 else "解説はありません。",
                            'dummies': dummies
                        })
        except Exception as e:
            print(f"CSV Read Error ({f_path}): {e}")
            
    return questions

@app.route('/')
def index():
    storage = get_storage(request)
    wrong_count = len(storage.get('wrong_list', []))
    now_jst = get_jst_now()
    
    # グラフ表示用のフィルタリング
    selected_group = request.args.get('chart_cat', 'すべて')
    logs = storage.get('logs', [])
    
    chart_labels, chart_values = [], []
    for i in range(6, -1, -1):
        d_str = (now_jst - timedelta(days=i)).strftime('%m/%d')
        chart_labels.append(d_str)
        
        # 修正：グラフの値を「正答率」ではなく「解答数（問題数）」として集計
        day_logs = []
        for l in logs:
            if l.get('date') == d_str:
                cat = l.get('cat')
                if selected_group == 'すべて':
                    day_logs.append(l)
                elif selected_group == '理論' and cat in THEORY_CAT:
                    day_logs.append(l)
                elif selected_group == '機械' and cat in MACHINE_CATS:
                    day_logs.append(l)
        chart_values.append(len(day_logs))
            
    days_left = max(0, (datetime(2026, 3, 22, tzinfo=JST) - now_jst).days)
    
    return render_template('index.html', 
                           theory_cats=THEORY_CAT,
                           machine_cats=MACHINE_CATS,
                           days_left=days_left, 
                           wrong_count=wrong_count, 
                           labels=chart_labels, 
                           values=chart_values, 
                           selected_cat=selected_group)

@app.route('/start_study', methods=['POST'])
def start_study():
    # 学習開始時にセッションを初期化
    session.pop('quiz_queue', None)
    session.pop('last_result', None)
    session.pop('total_in_session', None)
    session.pop('correct_count', None)

    mode = request.form.get('mode', 'fill')
    cat = request.form.get('cat', 'すべて')
    
    # 修正：q_countが確実に数値として取得されるようにし、挙動不審を解消
    try:
        q_count = int(request.form.get('q_count', 10))
    except (TypeError, ValueError):
        q_count = 10
        
    is_review = (request.form.get('review') == 'true')
    
    storage = get_storage(request)
    
    if is_review:
        wrong_ids = storage.get('wrong_list', [])
        all_q = load_csv_data('fill') + load_csv_data('ox')
        all_q = [q for q in all_q if q['id'] in wrong_ids]
    else:
        all_q = load_csv_data(mode)
    
    # カテゴリフィルタリング（理論/機械の親カテゴリ対応）
    if cat == '理論':
        all_q = [q for q in all_q if q['category'] in THEORY_CAT]
    elif cat == '機械':
        all_q = [q for q in all_q if q['category'] in MACHINE_CATS]
    elif cat != 'すべて':
        all_q = [q for q in all_q if q['category'] == cat]

    if not all_q:
        return redirect(url_for('index'))

    # 指定された問題数でランダムサンプリング
    selected_qs = random.sample(all_q, min(len(all_q), q_count))
    session['quiz_queue'] = selected_qs
    session['total_in_session'] = len(selected_qs)
    session['correct_count'] = 0
    session.modified = True 
    return redirect(url_for('study'))

@app.route('/study')
def study():
    last_result = session.get('last_result')
    
    if not last_result and not session.get('quiz_queue'):
        # 修正：リザルト画面への遷移を確実に
        return redirect(url_for('show_result'))

    # --- 解説画面の表示 ---
    if last_result:
        card = last_result['card']
        current_mode = 'fill' if card['id'].startswith('f_') else 'ox'
        return render_template('study.html', 
                               card=card, 
                               display_q=card['front'], 
                               is_answered=True, 
                               is_correct=last_result['is_correct'], 
                               correct_answer=last_result.get('correct_answer'),
                               mode=current_mode, 
                               current=last_result['current'], 
                               total=session['total_in_session'], 
                               progress=last_result['progress'])

    # --- 問題画面の表示 ---
    if not session.get('quiz_queue'):
        return redirect(url_for('show_result'))
        
    card = session['quiz_queue'][0]
    current_mode = 'fill' if card['id'].startswith('f_') else 'ox'
    
    display_q = card['front']
    choices = []
    
    if current_mode == 'fill':
        if card['back'] in card['front']:
            display_q = card['front'].replace(card['back'], " 【 ？ 】 ")
        
        correct_answer = str(card['back']).strip()
        choices = [correct_answer] + [str(d).strip() for d in card.get('dummies', [])]
        while len(choices) < 4:
            choices.append(f"選択肢{len(choices)+1}")
        random.shuffle(choices)

    idx = session['total_in_session'] - len(session['quiz_queue']) + 1
    progress = int(((idx-1)/session['total_in_session'])*100)
    
    return render_template('study.html', 
                           card=card, 
                           display_q=display_q, 
                           choices=choices, 
                           mode=current_mode, 
                           progress=progress, 
                           current=idx, 
                           total=session['total_in_session'],
                           is_answered=False)

@app.route('/answer/<card_id>', methods=['POST'])
def answer(card_id):
    if not session.get('quiz_queue'):
        return redirect(url_for('index'))
        
    card = session['quiz_queue'][0]
    storage = get_storage(request)
    now_jst = get_jst_now()
    
    user_answer = str(request.form.get('user_answer', '')).strip()
    correct_answer = str(card['back']).strip()
    
    is_correct = (user_answer == correct_answer)
    
    if is_correct:
        session['correct_count'] += 1
        if card_id in storage['wrong_list']:
            storage['wrong_list'] = [i for i in storage['wrong_list'] if i != card_id]
    else:
        if card_id not in storage['wrong_list']:
            storage['wrong_list'].append(card_id)
    
    # ログ記録
    storage['logs'].append({
        'date': now_jst.strftime('%m/%d'), 
        'cat': card['category'], 
        'correct': is_correct
    })
    storage['logs'] = storage['logs'][-200:]
    
    # セッション更新
    session['quiz_queue'].pop(0)
    idx = session['total_in_session'] - len(session['quiz_queue'])
    progress = int((idx/session['total_in_session'])*100)
    
    # 解説画面用に今回の結果を一時保存
    session['last_result'] = {
        'card': card,
        'is_correct': is_correct,
        'correct_answer': correct_answer,
        'current': idx,
        'progress': progress
    }
    session.modified = True 
    
    # Cookie更新とリダイレクト
    storage_json = json.dumps(storage, separators=(',', ':'))
    resp = make_response(redirect(url_for('study')))
    resp.set_cookie('denken_storage', storage_json, max_age=60*60*24*365, path='/', samesite='Lax')
    return resp

@app.route('/next_question')
def next_question():
    session.pop('last_result', None)
    session.modified = True
    return redirect(url_for('study'))

@app.route('/result')
def show_result():
    t = session.get('total_in_session', 0)
    c = session.get('correct_count', 0)
    score = int((c/t)*100) if t > 0 else 0
    return render_template('result.html', score=score, total=t, correct=c)

@app.route('/home')
def go_home():
    session.pop('quiz_queue', None)
    session.pop('last_result', None)
    session.pop('total_in_session', None)
    session.pop('correct_count', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)