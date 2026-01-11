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
    また、Header Too Largeエラー防止のため、100件を超えるログは自動で切り詰める。
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
    
    # 必須キーの存在とデータ型の保証（KeyError対策）
    if 'wrong_list' not in storage or not isinstance(storage['wrong_list'], list):
        storage['wrong_list'] = []
    if 'logs' not in storage or not isinstance(storage['logs'], list):
        storage['logs'] = []
    
    # 【Header制限対策】蓄積されたログが多すぎる場合は最新100件に制限（物理的なエラー回避）
    if len(storage['logs']) > 100:
        storage['logs'] = storage['logs'][-100:]
        
    return storage

# 全15分野（理論 ＋ 機械配下14分野）をフラットに定義
ALL_CATEGORIES = [
    "理論", "直流機", "誘導機", "同期機", "変圧器", "四機総合問題", "電動機応用", 
    "電気機器", "パワーエレクトロニクス", "自動制御", "照明", "電熱", 
    "電気化学", "メカトロニクス", "情報伝送及び処理"
]

def load_csv_data(mode):
    """
    CSVファイルを読み込む。
    mode: 'fill' (穴埋め) または 'ox' (○×)
    """
    # 穴埋め(fill)はtaku4フォルダ、○×(ox)はnormalフォルダを参照
    folder_mode = 'taku4' if mode == 'fill' else 'normal'
    
    # 全フォルダを再帰的にスキャンしてCSVを取得
    search_path = os.path.join(CSV_BASE_DIR, folder_mode, "**", "*.csv")
    files = glob.glob(search_path, recursive=True)
    
    questions = []
    for f_path in files:
        f_name = os.path.basename(f_path)
        try:
            with open(f_path, encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                for i, row in enumerate(reader):
                    # 最低限 0:カテゴリ, 1:問題, 2:正解 の3列が必要
                    if len(row) >= 3:
                        # 改行や空白をクレンジング（データ品質維持）
                        cleaned_row = [str(cell).strip().replace('\r', '').replace('\n', '') for cell in row]
                        
                        # ID生成ロジック（重複防止）
                        short_f_name = f_name.replace('.csv', '').replace('ox_', '').replace('normal_', '')
                        q_id = f"{mode[:1]}_{short_f_name}_{i}" 

                        dummies = []
                        if mode == 'fill':
                            # 5列目から7列目をダミー選択肢として取得
                            raw_dummies = cleaned_row[4:7] if len(cleaned_row) >= 5 else []
                            # 空文字や正解と同じものは除外
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
            # 読み込みエラーが発生しても全体を止めない
            print(f"CSV Read Error ({f_path}): {e}")
            
    return questions

@app.route('/')
def index():
    """メインメニュー表示と学習状況グラフの生成"""
    storage = get_storage(request)
    wrong_count = len(storage.get('wrong_list', []))
    now_jst = get_jst_now()
    
    # グラフ表示用のカテゴリ選択（URLパラメータから取得）
    selected_cat = request.args.get('chart_cat', 'すべて')
    logs = storage.get('logs', [])
    
    chart_labels, chart_values = [], []
    # 直近7日分のデータを集計（単位：回答数）
    for i in range(6, -1, -1):
        d_obj = now_jst - timedelta(days=i)
        d_str = d_obj.strftime('%m/%d')
        chart_labels.append(d_str)
        
        # 指定カテゴリの回答数をカウント（正解率ではなく「問」として集計）
        day_logs = [l for l in logs if l.get('date') == d_str and (selected_cat == 'すべて' or l.get('cat') == selected_cat)]
        chart_values.append(len(day_logs))
            
    # 試験日までのカウントダウン (2026/03/22)
    exam_date = datetime(2026, 3, 22, tzinfo=JST)
    days_left = max(0, (exam_date - now_jst).days)
    
    # グラフのY軸単位やタイトルを「回答数」として扱う情報をテンプレートに渡す
    chart_title = f"{selected_cat}の学習問題数"
    
    return render_template('index.html', 
                           categories=ALL_CATEGORIES, 
                           days_left=days_left, 
                           wrong_count=wrong_count, 
                           labels=chart_labels, 
                           values=chart_values, 
                           selected_cat=selected_cat,
                           chart_title=chart_title)

@app.route('/start_study', methods=['POST'])
def start_study():
    """学習セッションの初期化。指定された条件に基づいて問題を抽出する。"""
    session.clear() # 前回のセッションをクリーンアップ

    mode = request.form.get('mode', 'fill')
    cat = request.form.get('cat', 'すべて')
    
    # 10問か20問をフォームから取得
    q_count = int(request.form.get('q_count', 10))
    
    is_review = (request.form.get('review') == 'true')
    storage = get_storage(request)
    
    # 問題データの読み込みとフィルタリング
    if is_review:
        wrong_ids = storage.get('wrong_list', [])
        # 復習時は全形式から間違えた問題を抽出
        all_q = load_csv_data('fill') + load_csv_data('ox')
        all_q = [q for q in all_q if q['id'] in wrong_ids]
    else:
        # 通常学習
        all_q = load_csv_data(mode)
        # 15分野のいずれかが選ばれた場合のフィルタリング
        if cat != 'すべて':
            all_q = [q for q in all_q if q['category'] == cat]

    if not all_q:
        # 対象問題がない場合はホームへ戻す
        return redirect(url_for('index'))

    # ランダムにシャッフル
    random.shuffle(all_q)
    
    # 指定された問題数分だけ抽出（スライス処理により問題数が少なくてもエラーにならない）
    selected_qs = all_q[:q_count]
    
    # セッションに保存
    session['quiz_queue'] = selected_qs
    session['total_in_session'] = len(selected_qs)
    session['correct_count'] = 0
    session['combo'] = 0  # コンボ数初期化
    session.modified = True 
    
    return redirect(url_for('study'))

@app.route('/study')
def study():
    """問題表示と解説表示のメインロジック"""
    last_result = session.get('last_result')
    
    # 全問終了チェック
    if not last_result and (not session.get('quiz_queue') or len(session.get('quiz_queue')) == 0):
        if session.get('total_in_session'):
            return redirect(url_for('show_result'))
        return redirect(url_for('index'))

    # --- 解説表示モード (回答直後の状態) ---
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
                               progress=last_result['progress'],
                               combo=session.get('combo', 0))

    # --- 問題表示モード ---
    card = session['quiz_queue'][0]
    current_mode = 'fill' if card['id'].startswith('f_') else 'ox'
    
    display_q = card['front']
    choices = []
    
    if current_mode == 'fill':
        # 穴埋め形式の場合、正解文字列を伏せ字に置換
        if card['back'] in card['front']:
            display_q = card['front'].replace(card['back'], " 【 ？ 】 ")
        
        # 選択肢の生成
        correct_answer = str(card['back']).strip()
        choices = [correct_answer] + [str(d).strip() for d in card.get('dummies', [])]
        
        # iOS Safariでのボタン崩れや空表示を防ぐためのダミー補填
        while len(choices) < 4:
            choices.append(f"選択肢_{len(choices)}")
        
        random.shuffle(choices)

    # 進捗率と現在の問題番号を計算
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
                           is_answered=False,
                           combo=session.get('combo', 0))

@app.route('/answer/<card_id>', methods=['POST'])
def answer(card_id):
    """回答を判定し、学習ログ(Cookie)を更新する"""
    if not session.get('quiz_queue'):
        return redirect(url_for('index'))
        
    card = session['quiz_queue'][0]
    storage = get_storage(request)
    now_jst = get_jst_now()
    
    # 比較用に文字列を正規化
    user_answer = str(request.form.get('user_answer', '')).strip().replace('\r', '').replace('\n', '')
    correct_answer = str(card['back']).strip().replace('\r', '').replace('\n', '')
    
    is_correct = (user_answer == correct_answer)
    
    if is_correct:
        session['correct_count'] += 1
        session['combo'] = session.get('combo', 0) + 1 # コンボ加算
        # 正解したら復習リストから削除
        if card_id in storage['wrong_list']:
            storage['wrong_list'] = [i for i in storage['wrong_list'] if i != card_id]
    else:
        session['combo'] = 0 # コンボリセット
        # 不正解なら復習リストに追加（重複登録防止）
        if card_id not in storage['wrong_list']:
            storage['wrong_list'].append(card_id)
    
    # ログデータの追加
    storage['logs'].append({
        'date': now_jst.strftime('%m/%d'), 
        'cat': card['category'], 
        'correct': is_correct
    })
    
    # 【重要】Header Too Large防止：ログ保存数を厳格に100件に制限
    storage['logs'] = storage['logs'][-100:]
    
    # 進捗の更新
    session['quiz_queue'].pop(0)
    idx = session['total_in_session'] - len(session['quiz_queue'])
    progress = int((idx/session['total_in_session'])*100)
    
    # 解説画面表示用に今回の結果を一時保存
    session['last_result'] = {
        'card': card,
        'is_correct': is_correct,
        'correct_answer': correct_answer, 
        'current': idx,
        'progress': progress
    }
    session.modified = True 
    
    # Cookieの更新（JSON化し、データサイズを抑えるためのセパレータ指定）
    storage_json = json.dumps(storage, separators=(',', ':'))
    resp = make_response(redirect(url_for('study')))
    resp.set_cookie('denken_storage', storage_json, max_age=60*60*24*365, path='/', samesite='Lax')
    return resp

@app.route('/next_question')
def next_question():
    """解説画面から次の問題へ遷移"""
    session.pop('last_result', None)
    session.modified = True
    return redirect(url_for('study'))

@app.route('/result')
def show_result():
    """最終的な正解率を表示"""
    t = session.get('total_in_session', 0)
    c = session.get('correct_count', 0)
    score = int((c/t)*100) if t > 0 else 0
    return render_template('result.html', score=score, total=t, correct=c)

@app.route('/home')
def go_home():
    """中断してホーム画面へ"""
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    # 実行環境のポートに合わせて起動
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)