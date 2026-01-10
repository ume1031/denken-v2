import os, csv, random, json, time, glob
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, session, make_response
from datetime import datetime, timedelta, timezone

app = Flask(__name__)
app.config['SECRET_KEY'] = 'denken-v2-1-stable-final'

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
    Header Too Largeエラー防止のため、データ構造をチェックする。
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
    
    # 必須キーの初期化
    if 'wrong_list' not in storage: storage['wrong_list'] = []
    if 'logs' not in storage: storage['logs'] = []
        
    return storage

# 全15分野をフラットに定義
ALL_CATEGORIES = [
    "理論", "直流機", "誘導機", "同期機", "変圧器", "四機総合問題", 
    "電動機応用", "電気機器", "パワーエレクトロニクス", "自動制御", 
    "照明", "電熱", "電気化学", "メカトロニクス", "情報伝送及び処理"
]

def load_csv_data(mode):
    """
    CSVファイルを一括またはフォルダ別に読み込む。
    mode: 'fill' (穴埋め) または 'ox' (○×)
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
                        
                        # ユニークIDの生成 (f_ファイル名_行番号 / o_ファイル名_行番号)
                        short_f_name = f_name.replace('.csv', '').replace('ox_', '').replace('normal_', '')
                        q_id = f"{mode[:1]}_{short_f_name}_{i}" 

                        dummies = []
                        if mode == 'fill':
                            # CSVの5列目以降をダミーとして取得
                            raw_dummies = cleaned_row[4:7] if len(cleaned_row) >= 5 else []
                            dummies = [d for d in raw_dummies if d and d != cleaned_row[2]]

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
    
    # 学習状況グラフのフィルタリング用
    selected_cat = request.args.get('chart_cat', 'すべて')
    logs = storage.get('logs', [])
    
    chart_labels, chart_values = [], []
    for i in range(6, -1, -1):
        d_str = (now_jst - timedelta(days=i)).strftime('%m/%d')
        chart_labels.append(d_str)
        
        # 指定されたカテゴリのログを集計
        day_logs = [l for l in logs if l.get('date') == d_str and (selected_cat == 'すべて' or l.get('cat') == selected_cat)]
        chart_values.append(len(day_logs))
            
    # カウントダウン設定
    exam_date = datetime(2026, 3, 22, tzinfo=JST)
    days_left = max(0, (exam_date - now_jst).days)
    
    return render_template('index.html', 
                           categories=ALL_CATEGORIES, 
                           days_left=days_left, 
                           wrong_count=wrong_count, 
                           labels=chart_labels, 
                           values=chart_values, 
                           selected_cat=selected_cat)

@app.route('/start_study', methods=['POST'])
def start_study():
    """学習セッションの開始（20/30問選択を排除し、安全に問題を抽出）"""
    session.clear() 

    mode = request.form.get('mode', 'fill')
    cat = request.form.get('cat', 'すべて')
    
    # 20問/30問の廃止。常に全問または標準的な数をセット。
    # ここでは既存の q_count を安全に10問デフォルトとして扱う
    q_count = 10 
    
    is_review = (request.form.get('review') == 'true')
    storage = get_storage(request)
    
    # 問題のロード
    if is_review:
        wrong_ids = storage.get('wrong_list', [])
        all_q = load_csv_data('fill') + load_csv_data('ox')
        all_q = [q for q in all_q if q['id'] in wrong_ids]
    else:
        all_q = load_csv_data(mode)
    
    # カテゴリフィルタリング (15分野フラット)
    if cat != 'すべて':
        all_q = [q for q in all_q if q['category'] == cat]

    if not all_q:
        return redirect(url_for('index'))

    # シャッフルして抽出
    random.shuffle(all_q)
    # スライスを使うことで、問題数が足りなくてもエラーにならない
    selected_qs = all_q[:q_count]
    
    session['quiz_queue'] = selected_qs
    session['total_in_session'] = len(selected_qs)
    session['correct_count'] = 0
    session.modified = True 
    return redirect(url_for('study'))

@app.route('/study')
def study():
    """問題表示画面と解説画面のコントロール"""
    last_result = session.get('last_result')
    
    # 全問終了時の処理
    if not last_result and (not session.get('quiz_queue') or len(session.get('quiz_queue')) == 0):
        if session.get('total_in_session'):
            return redirect(url_for('show_result'))
        return redirect(url_for('index'))

    # 解説画面（回答後）
    if last_result:
        card = last_result['card']
        current_mode = 'fill' if card['id'].startswith('f_') else 'ox'
        return render_template('study.html', 
                               card=card, display_q=card['front'], is_answered=True, 
                               is_correct=last_result['is_correct'], 
                               correct_answer=last_result.get('correct_answer'),
                               mode=current_mode, current=last_result['current'], 
                               total=session['total_in_session'], progress=last_result['progress'])

    # 問題画面
    card = session['quiz_queue'][0]
    current_mode = 'fill' if card['id'].startswith('f_') else 'ox'
    display_q = card['front']
    choices = []
    
    if current_mode == 'fill':
        # 穴埋め形式の置換
        if card['back'] in card['front']:
            display_q = card['front'].replace(card['back'], " 【 ？ 】 ")
        
        # 選択肢の生成
        correct_answer = str(card['back']).strip()
        choices = [correct_answer] + [str(d).strip() for d in card.get('dummies', [])]
        
        # iOS表示安定化のためのダミー補填
        while len(choices) < 4:
            choices.append(f"選択肢_{len(choices)}")
        random.shuffle(choices)

    idx = session['total_in_session'] - len(session['quiz_queue']) + 1
    progress = int(((idx-1)/session['total_in_session'])*100)
    
    return render_template('study.html', 
                           card=card, display_q=display_q, choices=choices, 
                           mode=current_mode, progress=progress, current=idx, 
                           total=session['total_in_session'], is_answered=False)

@app.route('/answer/<card_id>', methods=['POST'])
def answer(card_id):
    """回答判定とCookieの更新。Cookie肥大化を防止。"""
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
    
    # --- Cookie肥大化(Header Too Large)対策 ---
    # ログを直近100件に絞り、Headerサイズを抑制する
    storage['logs'].append({
        'date': now_jst.strftime('%m/%d'), 
        'cat': card['category'], 
        'correct': is_correct
    })
    storage['logs'] = storage['logs'][-100:] 
    
    # セッション更新
    session['quiz_queue'].pop(0)
    idx = session['total_in_session'] - len(session['quiz_queue'])
    progress = int((idx/session['total_in_session'])*100)
    
    # 結果保持
    session['last_result'] = {
        'card': card, 'is_correct': is_correct, 'correct_answer': correct_answer, 
        'current': idx, 'progress': progress
    }
    session.modified = True 
    
    # Cookieへの保存 (データ圧縮を意識)
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
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)