from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from flask_admin import Admin
from flask_babel import Babel

db = SQLAlchemy()
jwt = JWTManager()
admin = Admin(name='NeNe番茄钟')
babel = Babel()
