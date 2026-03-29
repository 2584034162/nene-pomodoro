from flask import Flask
from flask_cors import CORS
from config import Config
from extensions import db, jwt, admin, babel
from routes import auth_bp, api_bp
from models import User, Task, CheckIn, AiAssistantConfig, AccountingRecord
from flask_admin.contrib.sqla import ModelView
from wtforms import PasswordField
from sqlalchemy import inspect, text

class UserModelView(ModelView):
    column_exclude_list = ['password_hash']
    form_excluded_columns = ['password_hash']

    form_extra_fields = {
        'password': PasswordField('密码')
    }


def ensure_ai_config_columns():
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    if 'ai_assistant_config' not in tables:
        return

    cols = {c['name'] for c in inspector.get_columns('ai_assistant_config')}
    sqls = []

    if 'personality' not in cols:
        sqls.append(
            "ALTER TABLE ai_assistant_config ADD COLUMN personality VARCHAR(255) DEFAULT '温柔、耐心、像朋友一样自然聊天'"
        )
    if 'api_provider' not in cols:
        sqls.append(
            "ALTER TABLE ai_assistant_config ADD COLUMN api_provider VARCHAR(50) DEFAULT 'custom'"
        )

    if not sqls:
        return

    for sql in sqls:
        db.session.execute(text(sql))

    db.session.execute(text(
        "UPDATE ai_assistant_config SET personality = '温柔、耐心、像朋友一样自然聊天' "
        "WHERE personality IS NULL OR personality = ''"
    ))
    db.session.execute(text(
        "UPDATE ai_assistant_config SET api_provider = 'custom' "
        "WHERE api_provider IS NULL OR api_provider = ''"
    ))
    db.session.commit()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    db.init_app(app)
    jwt.init_app(app)
    
    # Initialize Babel
    babel.init_app(app)
    
    admin.init_app(app)
    CORS(app)

    # JWT Error Handlers
    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        print(f"Invalid token error: {error}")
        return {"msg": "Invalid token", "error": str(error)}, 422

    @jwt.unauthorized_loader
    def missing_token_callback(error):
        print(f"Missing token error: {error}")
        return {"msg": "Missing token", "error": str(error)}, 401

    # Add admin views
    admin.add_view(UserModelView(User, db.session, name='用户'))
    admin.add_view(ModelView(Task, db.session, name='任务'))
    admin.add_view(ModelView(CheckIn, db.session, name='打卡记录'))
    admin.add_view(ModelView(AiAssistantConfig, db.session, name='AI配置'))
    admin.add_view(ModelView(AccountingRecord, db.session, name='记账记录'))

    # Register blueprints
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(api_bp, url_prefix='/api')

    with app.app_context():
        db.create_all()
        ensure_ai_config_columns()

    return app

app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
