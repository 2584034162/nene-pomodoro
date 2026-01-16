from app import create_app
from extensions import db
from models import User

app = create_app()

def create_user(username, password):
    with app.app_context():
        if User.query.filter_by(username=username).first():
            print(f"用户 {username} 已存在")
            return

        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        print(f"用户 {username} 创建成功")

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("用法: python create_user.py <username> <password>")
    else:
        create_user(sys.argv[1], sys.argv[2])
