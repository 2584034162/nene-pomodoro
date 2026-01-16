from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from extensions import db
from models import User, Task, CheckIn
from datetime import datetime, timedelta

auth_bp = Blueprint('auth', __name__)
api_bp = Blueprint('api', __name__)

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
    current_user_id = get_jwt_identity()
    
    if request.method == 'GET':
        tasks = Task.query.filter_by(user_id=current_user_id).order_by(Task.created_at.desc()).all()
        task_list = []
        today = datetime.now().date()
        
        for task in tasks:
            # 计算今日进度
            if task.target_type == 'count':
                progress = CheckIn.query.filter(
                    CheckIn.task_id == task.id,
                    db.func.date(CheckIn.timestamp) == today,
                    CheckIn.type == 'task_checkin'
                ).count()
            else: # time
                progress = db.session.query(db.func.sum(CheckIn.duration)).filter(
                    CheckIn.task_id == task.id,
                    db.func.date(CheckIn.timestamp) == today,
                    CheckIn.type == 'pomodoro'
                ).scalar() or 0
            
            is_completed = progress >= task.target_value
            
            task_list.append({
                'id': task.id,
                'title': task.title,
                'description': task.description,
                'target_type': task.target_type,
                'target_value': task.target_value,
                'created_at': task.created_at.isoformat(),
                'progress': progress,
                'is_completed': is_completed
            })
            
        return jsonify(task_list), 200

    if request.method == 'POST':
        data = request.get_json()
        new_task = Task(
            user_id=current_user_id,
            title=data.get('title'),
            description=data.get('description', ''),
            target_type=data.get('target_type', 'count'),
            target_value=data.get('target_value', 1)
        )
        db.session.add(new_task)
        db.session.commit()
        return jsonify({"msg": "Task created", "id": new_task.id}), 201

@api_bp.route('/tasks/<int:task_id>', methods=['DELETE'])
@jwt_required()
def delete_task(task_id):
    current_user_id = get_jwt_identity()
    task = Task.query.filter_by(id=task_id, user_id=current_user_id).first()
    
    if not task:
        return jsonify({"msg": "Task not found"}), 404
        
    db.session.delete(task)
    db.session.commit()
    return jsonify({"msg": "Task deleted"}), 200

@api_bp.route('/checkin', methods=['POST'])
@jwt_required()
def checkin():
    current_user_id = get_jwt_identity()
    data = request.get_json()
    
    # type: 'task_checkin' or 'pomodoro'
    checkin_type = data.get('type')
    task_id = data.get('task_id') # Optional for pomodoro
    duration = data.get('duration', 0)
    
    if checkin_type == 'task_checkin' and not task_id:
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
    current_user_id = get_jwt_identity()
    today = datetime.now().date()
    
    # 1. 今日打卡次数
    today_checkins = CheckIn.query.filter(
        CheckIn.user_id == current_user_id,
        db.func.date(CheckIn.timestamp) == today
    ).count()
    
    # 2. 总专注时长 (番茄钟)
    total_pomodoro_time = db.session.query(db.func.sum(CheckIn.duration)).filter(
        CheckIn.user_id == current_user_id,
        CheckIn.type == 'pomodoro'
    ).scalar() or 0
    
    # 3. 自律评分 (简单算法: (今日打卡 * 10) + (专注时长 / 5))
    score = (today_checkins * 10) + (total_pomodoro_time / 5)
    score = min(score, 100) # 上限 100

    # 4. 完成率 (Completion Rate)
    tasks = Task.query.filter_by(user_id=current_user_id).all()
    completed_count = 0
    total_tasks = len(tasks)
    
    if total_tasks > 0:
        for task in tasks:
            if task.target_type == 'count':
                progress = CheckIn.query.filter(
                    CheckIn.task_id == task.id,
                    db.func.date(CheckIn.timestamp) == today,
                    CheckIn.type == 'task_checkin'
                ).count()
            else: # time
                progress = db.session.query(db.func.sum(CheckIn.duration)).filter(
                    CheckIn.task_id == task.id,
                    db.func.date(CheckIn.timestamp) == today,
                    CheckIn.type == 'pomodoro'
                ).scalar() or 0
            
            if progress >= task.target_value:
                completed_count += 1
        
        completion_rate = int((completed_count / total_tasks) * 100)
    else:
        completion_rate = 0

    # 5. 连续打卡天数 (Streak)
    # 获取所有打卡日期 (去重)
    checkin_dates = db.session.query(db.func.date(CheckIn.timestamp)).filter(
        CheckIn.user_id == current_user_id
    ).distinct().order_by(db.func.date(CheckIn.timestamp).desc()).all()
    
    # checkin_dates 是一个元组列表 [('2023-01-01',), ('2022-12-31',), ...]
    dates = [datetime.strptime(d[0], '%Y-%m-%d').date() for d in checkin_dates if d[0]]
    
    current_streak = 0
    if dates:
        # 检查最近一次打卡是否是今天或昨天
        if dates[0] == today:
            current_streak = 1
            check_date = today - timedelta(days=1)
            idx = 1
        elif dates[0] == today - timedelta(days=1):
            current_streak = 1
            check_date = today - timedelta(days=2)
            idx = 1
        else:
            current_streak = 0
            idx = 0 # 不进入循环
            
        # 继续检查前一天
        while idx < len(dates):
            if dates[idx] == check_date:
                current_streak += 1
                check_date -= timedelta(days=1)
                idx += 1
            else:
                break
    
    return jsonify({
        "today_checkins": today_checkins,
        "total_pomodoro_minutes": total_pomodoro_time,
        "discipline_score": int(score),
        "completion_rate": completion_rate,
        "current_streak": current_streak,
        "completed_tasks_count": completed_count
    }), 200
