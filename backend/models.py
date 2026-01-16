from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, info={'label': '用户名'})
    password_hash = db.Column(db.String(128), info={'label': '密码哈希'})
    created_at = db.Column(db.DateTime, default=datetime.now, info={'label': '创建时间'})
    tasks = db.relationship('Task', backref='user', lazy=True)
    checkins = db.relationship('CheckIn', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, info={'label': '用户ID'})
    title = db.Column(db.String(120), nullable=False, info={'label': '标题'})
    description = db.Column(db.String(200), info={'label': '描述'})
    # 目标类型: 'count' (次数) 或 'time' (时长)
    target_type = db.Column(db.String(20), default='count', info={'label': '目标类型'}) 
    # 目标值: 例如 1次 或 30分钟
    target_value = db.Column(db.Integer, default=1, info={'label': '目标值'})
    created_at = db.Column(db.DateTime, default=datetime.now, info={'label': '创建时间'})
    checkins = db.relationship('CheckIn', backref='task', lazy=True)

class CheckIn(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, info={'label': '用户ID'})
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=True, info={'label': '任务ID'}) # 可以是纯番茄钟，不关联特定任务
    timestamp = db.Column(db.DateTime, default=datetime.now, info={'label': '时间戳'})
    # 类型: 'task_checkin' (任务打卡) 或 'pomodoro' (番茄钟)
    type = db.Column(db.String(20), nullable=False, info={'label': '类型'})
    # 持续时间 (分钟), 番茄钟通常是25
    duration = db.Column(db.Integer, default=0, info={'label': '持续时间(分钟)'})
