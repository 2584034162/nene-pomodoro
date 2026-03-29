import json
import re
from datetime import datetime, timedelta
from urllib import request as urlrequest
from urllib.error import URLError, HTTPError

from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity

from extensions import db
from models import User, Task, CheckIn, AiAssistantConfig, AccountingRecord

auth_bp = Blueprint('auth', __name__)
api_bp = Blueprint('api', __name__)

CHECKIN_TYPE_TASK = 'task_checkin'
CHECKIN_TYPE_POMODORO = 'pomodoro'
TARGET_TYPE_COUNT = 'count'
TARGET_TYPE_TIME = 'time'

ENTRY_TYPE_EXPENSE = 'expense'
ENTRY_TYPE_INCOME = 'income'


def calculate_task_progress(task_id, target_type, on_date):
    if target_type == TARGET_TYPE_COUNT:
        return CheckIn.query.filter(
            CheckIn.task_id == task_id,
            db.func.date(CheckIn.timestamp) == on_date,
            CheckIn.type == CHECKIN_TYPE_TASK
        ).count()

    return db.session.query(db.func.sum(CheckIn.duration)).filter(
        CheckIn.task_id == task_id,
        db.func.date(CheckIn.timestamp) == on_date,
        CheckIn.type == CHECKIN_TYPE_POMODORO
    ).scalar() or 0


def serialize_task(task, today):
    progress_value = calculate_task_progress(task.id, task.target_type, today)
    return {
        'id': task.id,
        'title': task.title,
        'description': task.description,
        'target': {
            'type': task.target_type,
            'value': task.target_value,
            'unit': '分钟' if task.target_type == TARGET_TYPE_TIME else '次'
        },
        'progress': {
            'value': progress_value,
            'completed': progress_value >= task.target_value
        },
        'created_at': task.created_at.isoformat()
    }


def serialize_accounting_record(record):
    return {
        'id': record.id,
        'amount': record.amount,
        'entry_type': record.entry_type,
        'category': record.category,
        'note': record.note,
        'source_text': record.source_text,
        'occurred_at': record.occurred_at.isoformat() if record.occurred_at else None,
        'created_at': record.created_at.isoformat()
    }


def get_or_create_ai_config(user_id):
    config = AiAssistantConfig.query.filter_by(user_id=user_id).first()
    if not config:
        config = AiAssistantConfig(user_id=user_id)
        db.session.add(config)
        db.session.commit()
    return config


def build_system_prompt(assistant_name, personality):
    safe_name = (assistant_name or '记账助理').strip() or '记账助理'
    safe_personality = (personality or '温柔、耐心、像朋友一样自然聊天').strip()
    return (
        f'你是{safe_name}，你的性格设定是：{safe_personality}。'
        '你要像真人朋友一样和用户聊天，语气自然、简短、真诚，不要生硬。'
        '你同时是记账助手：需要从用户输入中识别账单信息。'
        '请始终返回 JSON 格式：'
        '{"reply":"给用户的话（口语化）","should_save":true/false,'
        '"record":{"amount":数字,"entry_type":"expense|income","category":"分类","note":"备注","occurred_at":"YYYY-MM-DD"}}。'
        '如果信息不足无法记账，should_save=false，并在reply里继续追问用户补充。'
    )


def extract_personality(system_prompt):
    if not system_prompt:
        return '温柔、耐心、像朋友一样自然聊天'
    marker = '你的性格设定是：'
    idx = system_prompt.find(marker)
    if idx == -1:
        return system_prompt[:120]
    text = system_prompt[idx + len(marker):]
    end = text.find('。')
    if end != -1:
        return text[:end].strip()
    return text[:120].strip()


def serialize_ai_config(config):
    return {
        'assistant_name': config.assistant_name or '记账助理',
        'personality': extract_personality(config.system_prompt or ''),
        'api_url': config.api_url or '',
        'api_key': config.api_key or '',
        'api_model': config.api_model or 'gpt-4o-mini'
    }


def build_models_endpoint(api_url):
    if not api_url:
        return ''
    text = str(api_url).strip()
    if text.endswith('/chat/completions'):
        return text[: -len('/chat/completions')] + '/models'
    if text.endswith('/v1/chat/completions'):
        return text[: -len('/v1/chat/completions')] + '/v1/models'
    if text.endswith('/'):
        return text + 'models'
    return text + '/models'


def deep_get(obj, path):
    if not path:
        return obj
    current = obj
    for key in path.split('.'):
        if isinstance(current, list):
            if not key.isdigit():
                return None
            idx = int(key)
            if idx < 0 or idx >= len(current):
                return None
            current = current[idx]
            continue
        if isinstance(current, dict):
            if key not in current:
                return None
            current = current.get(key)
            continue
        return None
    return current


def fill_template(template_str, mapping):
    rendered = template_str
    for k, v in mapping.items():
        rendered = rendered.replace('{{' + k + '}}', str(v))
    return rendered


def parse_ai_json_output(text):
    if not text:
        return None
    text = text.strip()

    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?', '', text).strip()
        text = re.sub(r'```$', '', text).strip()

    try:
        return json.loads(text)
    except Exception:
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                return None
    return None


def fallback_parse_accounting(user_text):
    amount_match = re.search(r'(-?\d+(?:\.\d+)?)', user_text)
    if not amount_match:
        return {
            'reply': '我这边还没听到金额呢～你可以像聊天一样告诉我：比如“今天午饭花了28元”。',
            'should_save': False,
            'record': {}
        }

    amount = abs(float(amount_match.group(1)))
    text = user_text.lower()

    entry_type = ENTRY_TYPE_EXPENSE
    if any(k in text for k in ['收入', '工资', '收款', '入账', '报销', '奖金']):
        entry_type = ENTRY_TYPE_INCOME

    category = '其他'
    category_rules = {
        '餐饮': ['饭', '餐', '奶茶', '咖啡', '早餐', '午餐', '晚餐'],
        '交通': ['地铁', '公交', '打车', '出租', '加油', '停车'],
        '购物': ['买', '淘宝', '京东', '购物', '超市'],
        '娱乐': ['电影', '游戏', 'KTV', '旅游'],
        '住房': ['房租', '物业', '水电', '煤气']
    }
    for c, keys in category_rules.items():
        if any(k in user_text for k in keys):
            category = c
            break

    type_text = '支出' if entry_type == ENTRY_TYPE_EXPENSE else '收入'
    return {
        'reply': f'收到啦，我帮你记了一笔：{type_text} {amount:.2f} 元，分类先放在「{category}」。如果你想改分类，直接跟我说～',
        'should_save': True,
        'record': {
            'amount': amount,
            'entry_type': entry_type,
            'category': category,
            'note': user_text[:255],
            'occurred_at': datetime.now().date().isoformat()
        }
    }


def call_custom_ai_api(config, user_message, history_messages=None):
    if not config.api_url:
        return fallback_parse_accounting(user_message)

    headers = {
        'Content-Type': 'application/json'
    }
    if config.api_key:
        headers['Authorization'] = f'Bearer {config.api_key}'

    messages = [{
        'role': 'system',
        'content': config.system_prompt or build_system_prompt(config.assistant_name, '温柔、耐心、像朋友一样自然聊天')
    }]

    history_messages = history_messages or []
    for msg in history_messages[-10:]:
        role = str(msg.get('role', '')).strip()
        content = str(msg.get('content', '')).strip()
        if role in ['user', 'assistant'] and content:
            messages.append({'role': role, 'content': content})

    messages.append({'role': 'user', 'content': user_message})

    body = {
        'model': (config.api_model or 'gpt-4o-mini'),
        'messages': messages,
        'temperature': 0.7
    }

    req = urlrequest.Request(
        url=config.api_url,
        data=json.dumps(body).encode('utf-8'),
        headers=headers,
        method='POST'
    )

    try:
        with urlrequest.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode('utf-8')
            data = json.loads(raw)
    except HTTPError as e:
        return {
            'reply': f'我刚刚没连上 AI 服务（HTTP {e.code}）。你检查一下 API URL 或密钥，我们再试一次～',
            'should_save': False,
            'record': {}
        }
    except URLError:
        return {
            'reply': '我这边网络有点小问题，暂时没连上你配置的 AI 服务。稍后再试试～',
            'should_save': False,
            'record': {}
        }
    except Exception:
        return {
            'reply': 'AI 服务返回的数据我暂时没读懂，你可以检查一下这个 API 是否兼容 chat completions 格式。',
            'should_save': False,
            'record': {}
        }

    content = (
        deep_get(data, 'choices.0.message.content')
        or deep_get(data, 'output_text')
        or deep_get(data, 'data.0.output.0.content.0.text')
    )

    if content is None:
        return {
            'reply': 'AI 服务有响应，但我没找到可读的回复内容。',
            'should_save': False,
            'record': {}
        }

    parsed = parse_ai_json_output(str(content))
    if not isinstance(parsed, dict):
        return {
            'reply': str(content),
            'should_save': False,
            'record': {}
        }

    parsed.setdefault('reply', '好呀，我在。')
    parsed.setdefault('should_save', False)
    parsed.setdefault('record', {})
    return parsed


def normalize_record_from_ai(record_data, user_text):
    if not isinstance(record_data, dict):
        return None, 'AI 返回 record 格式错误'

    try:
        amount = float(record_data.get('amount', 0))
    except (TypeError, ValueError):
        return None, '金额格式错误'

    if amount <= 0:
        return None, '金额必须大于 0'

    entry_type = str(record_data.get('entry_type', ENTRY_TYPE_EXPENSE)).lower()
    if entry_type not in [ENTRY_TYPE_EXPENSE, ENTRY_TYPE_INCOME]:
        entry_type = ENTRY_TYPE_EXPENSE

    category = str(record_data.get('category', '其他'))[:80]
    note = str(record_data.get('note', user_text))[:255]

    occurred_raw = record_data.get('occurred_at')
    occurred_at = datetime.now().date()
    if occurred_raw:
        try:
            occurred_at = datetime.strptime(str(occurred_raw), '%Y-%m-%d').date()
        except ValueError:
            return None, '日期格式应为 YYYY-MM-DD'

    return {
        'amount': abs(amount),
        'entry_type': entry_type,
        'category': category or '其他',
        'note': note,
        'source_text': user_text,
        'occurred_at': occurred_at
    }, None


# --- Auth Routes ---

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"msg": "Username and password required"}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"msg": "Username already exists"}), 400

    new_user = User(username=username)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()

    return jsonify({"msg": "User created successfully"}), 201


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
        access_token = create_access_token(identity=str(user.id))
        return jsonify(access_token=access_token), 200

    return jsonify({"msg": "Bad username or password"}), 401


# --- API Routes ---

@api_bp.route('/tasks', methods=['GET', 'POST'])
@jwt_required()
def handle_tasks():
    current_user_id = int(get_jwt_identity())

    if request.method == 'GET':
        tasks = Task.query.filter_by(user_id=current_user_id).order_by(Task.created_at.desc()).all()
        today = datetime.now().date()
        task_list = [serialize_task(task, today) for task in tasks]
        return jsonify(task_list), 200

    if request.method == 'POST':
        data = request.get_json() or {}
        target_data = data.get('target', {})
        target_type = target_data.get('type', data.get('target_type', TARGET_TYPE_COUNT))
        target_value = target_data.get('value', data.get('target_value', 1))

        new_task = Task(
            user_id=current_user_id,
            title=data.get('title'),
            description=data.get('description', ''),
            target_type=target_type,
            target_value=target_value
        )
        db.session.add(new_task)
        db.session.commit()
        return jsonify({"msg": "Task created", "id": new_task.id}), 201


@api_bp.route('/tasks/<int:task_id>', methods=['DELETE'])
@jwt_required()
def delete_task(task_id):
    current_user_id = int(get_jwt_identity())
    task = Task.query.filter_by(id=task_id, user_id=current_user_id).first()

    if not task:
        return jsonify({"msg": "Task not found"}), 404

    db.session.delete(task)
    db.session.commit()
    return jsonify({"msg": "Task deleted"}), 200


@api_bp.route('/checkin', methods=['POST'])
@jwt_required()
def checkin():
    current_user_id = int(get_jwt_identity())
    data = request.get_json() or {}

    checkin_type = data.get('type')
    task_id = data.get('task_id')
    duration = data.get('duration', 0)

    if checkin_type == CHECKIN_TYPE_TASK and not task_id:
        return jsonify({"msg": "Task ID required for task checkin"}), 400

    new_checkin = CheckIn(
        user_id=current_user_id,
        task_id=task_id,
        type=checkin_type,
        duration=duration
    )
    db.session.add(new_checkin)
    db.session.commit()

    return jsonify({"msg": "Check-in successful"}), 201


@api_bp.route('/stats', methods=['GET'])
@jwt_required()
def get_stats():
    current_user_id = int(get_jwt_identity())
    today = datetime.now().date()

    today_checkins = CheckIn.query.filter(
        CheckIn.user_id == current_user_id,
        db.func.date(CheckIn.timestamp) == today
    ).count()

    total_pomodoro_time = db.session.query(db.func.sum(CheckIn.duration)).filter(
        CheckIn.user_id == current_user_id,
        CheckIn.type == CHECKIN_TYPE_POMODORO
    ).scalar() or 0

    score = min((today_checkins * 10) + (total_pomodoro_time / 5), 100)

    tasks = Task.query.filter_by(user_id=current_user_id).all()
    total_tasks = len(tasks)
    completed_count = 0

    for task in tasks:
        progress = calculate_task_progress(task.id, task.target_type, today)
        if progress >= task.target_value:
            completed_count += 1

    completion_rate = int((completed_count / total_tasks) * 100) if total_tasks > 0 else 0

    checkin_dates = db.session.query(db.func.date(CheckIn.timestamp)).filter(
        CheckIn.user_id == current_user_id
    ).distinct().order_by(db.func.date(CheckIn.timestamp).desc()).all()

    dates = []
    for d in checkin_dates:
        value = d[0]
        if isinstance(value, datetime):
            value = value.date()
        elif isinstance(value, str):
            try:
                value = datetime.strptime(value, '%Y-%m-%d').date()
            except ValueError:
                continue
        dates.append(value)

    current_streak = 0
    if dates:
        if dates[0] == today:
            current_streak = 1
            check_date = today - timedelta(days=1)
            idx = 1
        elif dates[0] == today - timedelta(days=1):
            current_streak = 1
            check_date = today - timedelta(days=2)
            idx = 1
        else:
            idx = 0

        while idx < len(dates):
            if dates[idx] == check_date:
                current_streak += 1
                check_date -= timedelta(days=1)
                idx += 1
            else:
                break

    return jsonify({
        "checkins": {
            "today": today_checkins,
            "streak_days": current_streak
        },
        "pomodoro": {
            "total_minutes": total_pomodoro_time
        },
        "tasks": {
            "completed_today": completed_count,
            "completion_rate": completion_rate
        },
        "score": {
            "discipline": int(score)
        }
    }), 200


@api_bp.route('/ai-accounting/config', methods=['GET', 'PUT'])
@jwt_required()
def ai_accounting_config():
    current_user_id = int(get_jwt_identity())
    config = get_or_create_ai_config(current_user_id)

    if request.method == 'GET':
        return jsonify(serialize_ai_config(config)), 200

    data = request.get_json() or {}
    assistant_name = data.get('assistant_name', config.assistant_name or '记账助理')
    personality = data.get('personality', extract_personality(config.system_prompt or '温柔、耐心、像朋友一样自然聊天'))
    config.assistant_name = assistant_name
    config.system_prompt = build_system_prompt(assistant_name, personality)
    config.api_url = data.get('api_url', config.api_url)
    config.api_key = data.get('api_key', config.api_key)
    config.api_model = data.get('api_model', config.api_model or 'gpt-4o-mini')

    # 保持简单固定，避免前端复杂配置
    config.api_method = 'POST'
    config.api_headers = '{}'
    config.request_template = ''
    config.response_path = 'choices.0.message.content'

    db.session.commit()
    return jsonify({"msg": "配置已保存", "config": serialize_ai_config(config)}), 200


@api_bp.route('/ai-accounting/models', methods=['GET'])
@jwt_required()
def ai_accounting_models():
    current_user_id = int(get_jwt_identity())
    config = get_or_create_ai_config(current_user_id)

    api_url = (request.args.get('api_url') or config.api_url or '').strip()
    api_key = (request.args.get('api_key') or config.api_key or '').strip()

    if not api_url:
        return jsonify({'models': [], 'msg': '请先填写 API URL'}), 200

    models_url = build_models_endpoint(api_url)
    headers = {}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    req = urlrequest.Request(
        url=models_url,
        headers=headers,
        method='GET'
    )

    try:
        with urlrequest.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode('utf-8')
            data = json.loads(raw)
    except HTTPError as e:
        return jsonify({'models': [], 'msg': f'拉取模型失败（HTTP {e.code}）'}), 200
    except URLError:
        return jsonify({'models': [], 'msg': '拉取模型失败（网络错误）'}), 200
    except Exception:
        return jsonify({'models': [], 'msg': '拉取模型失败（响应格式异常）'}), 200

    model_list = []
    items = data.get('data', []) if isinstance(data, dict) else []
    for item in items:
        if isinstance(item, dict):
            mid = str(item.get('id', '')).strip()
            if mid:
                model_list.append(mid)

    model_list = sorted(list(set(model_list)))
    return jsonify({
        'models': model_list,
        'models_endpoint': models_url
    }), 200


@api_bp.route('/ai-accounting/chat', methods=['POST'])
@jwt_required()
def ai_accounting_chat():
    current_user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    user_message = (data.get('message') or '').strip()
    history = data.get('history') or []

    if not user_message:
        return jsonify({"msg": "message 不能为空"}), 400

    config = get_or_create_ai_config(current_user_id)
    ai_result = call_custom_ai_api(config, user_message, history)

    assistant_reply = str(ai_result.get('reply', '已收到')).strip()
    should_save = bool(ai_result.get('should_save', False))
    saved_record = None

    if should_save:
        normalized, err = normalize_record_from_ai(ai_result.get('record', {}), user_message)
        if err:
            assistant_reply = f'{assistant_reply}\n（未记账：{err}）'
        else:
            record = AccountingRecord(
                user_id=current_user_id,
                amount=normalized['amount'],
                entry_type=normalized['entry_type'],
                category=normalized['category'],
                note=normalized['note'],
                source_text=normalized['source_text'],
                occurred_at=normalized['occurred_at']
            )
            db.session.add(record)
            db.session.commit()
            saved_record = serialize_accounting_record(record)

    latest_records = AccountingRecord.query.filter_by(user_id=current_user_id).order_by(
        AccountingRecord.occurred_at.desc(), AccountingRecord.created_at.desc()
    ).limit(20).all()

    return jsonify({
        'assistant_reply': assistant_reply,
        'saved_record': saved_record,
        'records': [serialize_accounting_record(r) for r in latest_records]
    }), 200


@api_bp.route('/accounting/records', methods=['GET'])
@jwt_required()
def list_accounting_records():
    current_user_id = int(get_jwt_identity())
    records = AccountingRecord.query.filter_by(user_id=current_user_id).order_by(
        AccountingRecord.occurred_at.desc(),
        AccountingRecord.created_at.desc()
    ).limit(100).all()

    income = sum(r.amount for r in records if r.entry_type == ENTRY_TYPE_INCOME)
    expense = sum(r.amount for r in records if r.entry_type == ENTRY_TYPE_EXPENSE)

    return jsonify({
        'records': [serialize_accounting_record(r) for r in records],
        'summary': {
            'income': round(income, 2),
            'expense': round(expense, 2),
            'balance': round(income - expense, 2)
        }
    }), 200
