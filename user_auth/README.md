# 用户登录系统

一个完整的用户登录系统，包含用户注册、登录、会话管理和安全功能。

## 功能特性

### 核心功能
- ✅ 用户注册（用户名、邮箱、密码）
- ✅ 用户登录/登出
- ✅ 会话管理（支持记住登录状态）
- ✅ 个人资料页面
- ✅ RESTful API接口

### 安全特性
- 🔒 使用bcrypt哈希算法存储密码
- 🛡️ 防止暴力破解（登录尝试限制）
- 🔐 安全的HTTP-only Cookie
- 📝 登录尝试记录
- 🚫 SQL注入防护

### 用户体验
- 📱 响应式设计
- 🎨 现代化的UI界面
- ⚡ 实时表单验证
- 📊 密码强度检查
- 💬 友好的提示消息

## 快速开始

### 1. 安装依赖
```bash
cd user_auth
pip install -r requirements.txt
```

### 2. 运行应用
```bash
python app.py
```

### 3. 访问应用
打开浏览器访问：http://localhost:5000

### 4. 演示账户
- **用户名**: admin
- **密码**: admin123

## 项目结构

```
user_auth/
├── app.py                 # 主应用文件
├── requirements.txt       # Python依赖
├── README.md             # 项目说明
├── templates/            # HTML模板
│   ├── base.html         # 基础模板
│   ├── index.html        # 首页
│   ├── login.html        # 登录页面
│   ├── register.html     # 注册页面
│   ├── profile.html      # 个人资料
│   ├── 404.html          # 404错误页面
│   └── 500.html          # 500错误页面
├── static/               # 静态文件
│   ├── css/
│   │   └── style.css     # 样式表
│   └── js/
│       └── main.js       # JavaScript文件
└── users.db              # SQLite数据库（运行后自动生成）
```

## API接口

### 检查认证状态
```http
GET /api/check_auth
```

**响应示例：**
```json
{
    "authenticated": true,
    "user": {
        "id": 1,
        "username": "admin",
        "email": "admin@example.com",
        "created_at": "2024-01-01T00:00:00",
        "last_login": "2024-01-01T12:00:00",
        "is_active": true
    }
}
```

## 安全特性详解

### 1. 密码安全
- 使用bcrypt算法进行密码哈希
- 自动加盐处理
- 防止彩虹表攻击

### 2. 会话安全
- 使用Flask的session管理
- HTTP-only Cookie防止XSS攻击
- 安全的SameSite策略
- 可配置的会话过期时间

### 3. 暴力破解防护
- 记录所有登录尝试
- 15分钟内最多5次失败尝试
- 失败次数过多会暂时锁定

### 4. 数据库安全
- 使用SQLAlchemy ORM防止SQL注入
- 敏感信息不记录日志
- 安全的数据库连接

## 配置选项

### 环境变量
```bash
# 设置密钥（生产环境必须）
export SECRET_KEY=your-secret-key-here

# 数据库配置（可选）
export DATABASE_URL=sqlite:///users.db
```

### Flask配置
可在`app.py`中修改以下配置：
- `SESSION_COOKIE_SECURE`: 生产环境设为True
- `PERMANENT_SESSION_LIFETIME`: 会话过期时间
- `SQLALCHEMY_DATABASE_URI`: 数据库连接

## 部署指南

### 生产环境部署
1. **设置强密钥**
   ```bash
   export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
   ```

2. **使用生产数据库**
   ```python
   # 修改app.py中的数据库配置
   app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://user:password@localhost/dbname'
   ```

3. **启用安全Cookie**
   ```python
   app.config['SESSION_COOKIE_SECURE'] = True
   ```

4. **使用WSGI服务器**
   ```bash
   pip install gunicorn
   gunicorn -w 4 -b 0.0.0.0:5000 app:app
   ```

### Docker部署
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]
```

## 开发指南

### 添加新功能
1. 在`app.py`中添加新的路由
2. 在`templates/`中创建对应的HTML模板
3. 在`static/css/style.css`中添加样式
4. 在`static/js/main.js`中添加交互逻辑

### 数据库迁移
```python
# 添加新模型后，在Python交互环境中执行：
from app import db
db.create_all()
```

### 测试
```bash
# 运行应用
python app.py

# 访问测试
curl http://localhost:5000/api/check_auth
```

## 故障排除

### 常见问题

1. **数据库连接失败**
   - 检查数据库文件权限
   - 确保有足够的磁盘空间

2. **会话不持久**
   - 检查浏览器Cookie设置
   - 验证SECRET_KEY配置

3. **登录失败**
   - 检查登录尝试限制
   - 验证用户账户状态

### 日志查看
应用运行时会在控制台输出日志，包含：
- 请求信息
- 错误详情
- 数据库操作

## 许可证

MIT License - 详见LICENSE文件

## 贡献指南

1. Fork项目
2. 创建功能分支
3. 提交更改
4. 推送到分支
5. 创建Pull Request

## 更新日志

### v1.0.0 (2024-01-01)
- 初始版本发布
- 完整的用户认证系统
- 安全特性实现
- 响应式UI设计

---

**注意**: 这是一个演示项目，生产环境使用时请确保：
1. 使用强密钥
2. 启用HTTPS
3. 定期备份数据库
4. 监控登录尝试
5. 定期更新依赖