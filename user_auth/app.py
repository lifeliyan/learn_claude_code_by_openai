#!/usr/bin/env python3
"""
用户登录系统 - Flask应用
包含用户注册、登录、会话管理和安全功能
"""

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime, timedelta
import secrets

# 初始化Flask应用
app = Flask(__name__)

# 配置
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_SECURE'] = False  # 开发环境设为False，生产环境应为True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)

# 初始化数据库
db = SQLAlchemy(app)

# 用户模型
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    
    def set_password(self, password):
        """设置密码哈希"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """验证密码"""
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'is_active': self.is_active
        }

# 登录尝试记录（防止暴力破解）
class LoginAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    ip_address = db.Column(db.String(45), nullable=False)
    attempted_at = db.Column(db.DateTime, default=datetime.utcnow)
    success = db.Column(db.Boolean, default=False)

# 创建数据库表
with app.app_context():
    db.create_all()

# 辅助函数
def is_logged_in():
    """检查用户是否已登录"""
    return 'user_id' in session

def get_current_user():
    """获取当前登录用户"""
    if is_logged_in():
        return User.query.get(session['user_id'])
    return None

def check_login_attempts(username, ip_address, max_attempts=5):
    """检查登录尝试次数"""
    recent_attempts = LoginAttempt.query.filter(
        LoginAttempt.username == username,
        LoginAttempt.ip_address == ip_address,
        LoginAttempt.attempted_at > datetime.utcnow() - timedelta(minutes=15)
    ).count()
    
    return recent_attempts < max_attempts

def record_login_attempt(username, ip_address, success):
    """记录登录尝试"""
    attempt = LoginAttempt(
        username=username,
        ip_address=ip_address,
        success=success
    )
    db.session.add(attempt)
    db.session.commit()

# 路由
@app.route('/')
def index():
    """首页"""
    user = get_current_user()
    return render_template('index.html', user=user)

@app.route('/register', methods=['GET', 'POST'])
def register():
    """用户注册"""
    if is_logged_in():
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        # 验证输入
        errors = []
        
        if not username or len(username) < 3:
            errors.append('用户名至少需要3个字符')
        
        if not email or '@' not in email:
            errors.append('请输入有效的邮箱地址')
        
        if not password or len(password) < 6:
            errors.append('密码至少需要6个字符')
        
        if password != confirm_password:
            errors.append('两次输入的密码不一致')
        
        # 检查用户名和邮箱是否已存在
        if User.query.filter_by(username=username).first():
            errors.append('用户名已存在')
        
        if User.query.filter_by(email=email).first():
            errors.append('邮箱地址已存在')
        
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('register.html')
        
        # 创建新用户
        try:
            user = User(username=username, email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            
            flash('注册成功！请登录。', 'success')
            return redirect(url_for('login'))
        
        except Exception as e:
            db.session.rollback()
            flash(f'注册失败：{str(e)}', 'error')
            return render_template('register.html')
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """用户登录"""
    if is_logged_in():
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)
        
        # 获取客户端IP地址
        ip_address = request.remote_addr
        
        # 检查登录尝试次数
        if not check_login_attempts(username, ip_address):
            flash('登录尝试次数过多，请15分钟后再试。', 'error')
            record_login_attempt(username, ip_address, False)
            return render_template('login.html')
        
        # 查找用户
        user = User.query.filter_by(username=username).first()
        
        if not user:
            flash('用户名或密码错误', 'error')
            record_login_attempt(username, ip_address, False)
            return render_template('login.html')
        
        if not user.is_active:
            flash('账户已被禁用', 'error')
            record_login_attempt(username, ip_address, False)
            return render_template('login.html')
        
        # 验证密码
        if user.check_password(password):
            # 登录成功
            session['user_id'] = user.id
            session['username'] = user.username
            
            if remember:
                session.permanent = True
            
            # 更新最后登录时间
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            record_login_attempt(username, ip_address, True)
            flash('登录成功！', 'success')
            
            # 重定向到原始页面或首页
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            flash('用户名或密码错误', 'error')
            record_login_attempt(username, ip_address, False)
            return render_template('login.html')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """用户登出"""
    session.clear()
    flash('您已成功登出', 'success')
    return redirect(url_for('index'))

@app.route('/profile')
def profile():
    """用户个人资料"""
    if not is_logged_in():
        flash('请先登录', 'error')
        return redirect(url_for('login'))
    
    user = get_current_user()
    return render_template('profile.html', user=user)

@app.route('/api/check_auth')
def check_auth():
    """API：检查认证状态"""
    user = get_current_user()
    if user:
        return jsonify({
            'authenticated': True,
            'user': user.to_dict()
        })
    return jsonify({'authenticated': False})

# 错误处理
@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

if __name__ == '__main__':
    # 创建示例用户（仅开发环境）
    with app.app_context():
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', email='admin@example.com')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("创建了示例用户：admin / admin123")
    
    app.run(debug=True, host='0.0.0.0', port=5000)