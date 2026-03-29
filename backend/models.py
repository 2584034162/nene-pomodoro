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
    ai_config = db.relationship('AiAssistantConfig', backref='user', uselist=False, lazy=True, cascade='all, delete-orphan')
    accounting_records = db.relationship('AccountingRecord', backref='user', lazy=True, cascade='all, delete-orphan')

    @property
    def password(self):
        return ""

    @password.setter
    def password(self, password):
        self.password_hash = generate_password_hash(password)

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
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=True, info={'label': '任务ID'})  # 可以是纯番茄钟，不关联特定任务
    timestamp = db.Column(db.DateTime, default=datetime.now, info={'label': '时间戳'})
    # 类型: 'task_checkin' (任务打卡) 或 'pomodoro' (番茄钟)
    type = db.Column(db.String(20), nullable=False, info={'label': '类型'})
    # 持续时间 (分钟), 番茄钟通常是25
    duration = db.Column(db.Integer, default=0, info={'label': '持续时间(分钟)'})


class AiAssistantConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True, info={'label': '用户ID'})
    assistant_name = db.Column(db.String(80), default='NeNe记账助理', info={'label': '助理名称'})
    system_prompt = db.Column(
        db.Text,
        default='你是一个记账助手。请从用户输入中提取账单信息并返回 JSON：{"reply":"给用户的话","should_save":true/false,"record":{"amount":数字,"entry_type":"expense|income","category":"分类","note":"备注","occurred_at":"YYYY-MM-DD"}}。如果信息不足，should_save=false 并引导用户补充。',
        info={'label': '系统提示词'}
    )
    api_url = db.Column(db.String(500), nullable=True, info={'label': 'API地址'})
    api_method = db.Column(db.String(10), default='POST', info={'label': 'API方法'})
    api_headers = db.Column(db.Text, default='{}', info={'label': '请求头JSON'})
    api_model = db.Column(db.String(120), default='', info={'label': '模型名'})
    api_key = db.Column(db.String(255), default='', info={'label': 'API密钥'})
    request_template = db.Column(
        db.Text,
        default='{"model":"{{model}}","messages":[{"role":"system","content":"{{system_prompt}}"},{"role":"user","content":"{{user_message}}"}]}',
        info={'label': '请求体模板'}
    )
    response_path = db.Column(db.String(200), default='choices.0.message.content', info={'label': '回复内容路径'})
    created_at = db.Column(db.DateTime, default=datetime.now, info={'label': '创建时间'})
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, info={'label': '更新时间'})


class AccountingRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True, info={'label': '用户ID'})
    amount = db.Column(db.Float, nullable=False, info={'label': '金额'})
    entry_type = db.Column(db.String(20), nullable=False, default='expense', info={'label': '类型 expense/income'})
    category = db.Column(db.String(80), default='其他', info={'label': '分类'})
    note = db.Column(db.String(255), default='', info={'label': '备注'})
    source_text = db.Column(db.Text, default='', info={'label': '原始输入'})
    occurred_at = db.Column(db.Date, default=lambda: datetime.now().date(), info={'label': '发生日期'})
    created_at = db.Column(db.DateTime, default=datetime.now, info={'label': '创建时间'})
