// 用户登录系统 - JavaScript功能

document.addEventListener('DOMContentLoaded', function() {
    // 密码强度检查
    const passwordInput = document.getElementById('password');
    if (passwordInput) {
        passwordInput.addEventListener('input', checkPasswordStrength);
    }
    
    // 表单验证
    const registerForm = document.getElementById('registerForm');
    if (registerForm) {
        registerForm.addEventListener('submit', validateRegisterForm);
    }
    
    // 自动隐藏消息提示
    autoHideMessages();
    
    // 检查认证状态
    checkAuthStatus();
});

// 检查密码强度
function checkPasswordStrength() {
    const password = this.value;
    const strengthBar = document.querySelector('.strength-bar');
    const strengthText = document.querySelector('.strength-text');
    
    if (!strengthBar || !strengthText) return;
    
    let strength = 0;
    let width = 0;
    let text = '密码强度：';
    let color = '#e74c3c'; // 红色
    
    // 检查长度
    if (password.length >= 8) strength++;
    if (password.length >= 12) strength++;
    
    // 检查字符类型
    if (/[a-z]/.test(password)) strength++; // 小写字母
    if (/[A-Z]/.test(password)) strength++; // 大写字母
    if (/[0-9]/.test(password)) strength++; // 数字
    if (/[^a-zA-Z0-9]/.test(password)) strength++; // 特殊字符
    
    // 根据强度设置宽度和颜色
    switch(strength) {
        case 0:
        case 1:
            width = 25;
            text += '弱';
            color = '#e74c3c'; // 红色
            break;
        case 2:
        case 3:
            width = 50;
            text += '中';
            color = '#f39c12'; // 橙色
            break;
        case 4:
            width = 75;
            text += '强';
            color = '#2ecc71'; // 绿色
            break;
        case 5:
        case 6:
            width = 100;
            text += '很强';
            color = '#27ae60'; // 深绿色
            break;
    }
    
    // 更新UI
    strengthBar.style.width = width + '%';
    strengthBar.style.backgroundColor = color;
    strengthText.textContent = text;
    strengthText.style.color = color;
}

// 注册表单验证
function validateRegisterForm(event) {
    const password = document.getElementById('password').value;
    const confirmPassword = document.getElementById('confirm_password').value;
    const username = document.getElementById('username').value;
    const email = document.getElementById('email').value;
    
    let errors = [];
    
    // 验证用户名
    if (username.length < 3) {
        errors.push('用户名至少需要3个字符');
    }
    
    // 验证邮箱
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
        errors.push('请输入有效的邮箱地址');
    }
    
    // 验证密码
    if (password.length < 6) {
        errors.push('密码至少需要6个字符');
    }
    
    // 验证密码匹配
    if (password !== confirmPassword) {
        errors.push('两次输入的密码不一致');
    }
    
    // 如果有错误，阻止提交并显示错误
    if (errors.length > 0) {
        event.preventDefault();
        showFormErrors(errors);
        return false;
    }
    
    return true;
}

// 显示表单错误
function showFormErrors(errors) {
    // 移除现有的错误提示
    const existingErrors = document.querySelectorAll('.form-error');
    existingErrors.forEach(error => error.remove());
    
    // 添加新的错误提示
    errors.forEach(error => {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'alert alert-error form-error';
        errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${error}`;
        
        // 插入到表单顶部
        const form = document.querySelector('.auth-form');
        if (form) {
            form.insertBefore(errorDiv, form.firstChild);
        }
    });
}

// 自动隐藏消息提示
function autoHideMessages() {
    const messages = document.querySelectorAll('.alert');
    messages.forEach(message => {
        setTimeout(() => {
            message.style.opacity = '0';
            message.style.transform = 'translateY(-10px)';
            setTimeout(() => {
                if (message.parentNode) {
                    message.parentNode.removeChild(message);
                }
            }, 300);
        }, 5000); // 5秒后自动隐藏
    });
}

// 检查认证状态
function checkAuthStatus() {
    // 如果用户已登录，可以执行一些特定操作
    fetch('/api/check_auth')
        .then(response => response.json())
        .then(data => {
            if (data.authenticated) {
                // 用户已登录，可以更新UI
                updateUIForLoggedInUser(data.user);
            } else {
                // 用户未登录
                updateUIForGuest();
            }
        })
        .catch(error => {
            console.error('检查认证状态失败:', error);
        });
}

// 更新已登录用户的UI
function updateUIForLoggedInUser(user) {
    // 可以在这里添加一些特定于已登录用户的功能
    console.log('用户已登录:', user.username);
    
    // 示例：更新页面标题
    const pageTitle = document.querySelector('title');
    if (pageTitle && !pageTitle.textContent.includes(user.username)) {
        pageTitle.textContent = `${user.username} - ${pageTitle.textContent}`;
    }
}

// 更新访客用户的UI
function updateUIForGuest() {
    console.log('用户未登录');
}

// 显示加载状态
function showLoading(button) {
    if (!button) return;
    
    const originalText = button.innerHTML;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 处理中...';
    button.disabled = true;
    
    return originalText;
}

// 恢复按钮状态
function restoreButton(button, originalText) {
    if (!button || !originalText) return;
    
    button.innerHTML = originalText;
    button.disabled = false;
}

// 复制到剪贴板
function copyToClipboard(text) {
    navigator.clipboard.writeText(text)
        .then(() => {
            showToast('已复制到剪贴板');
        })
        .catch(err => {
            console.error('复制失败:', err);
            showToast('复制失败，请手动复制', 'error');
        });
}

// 显示Toast通知
function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <i class="fas fa-${type === 'success' ? 'check-circle' : 'exclamation-circle'}"></i>
        <span>${message}</span>
    `;
    
    document.body.appendChild(toast);
    
    // 显示动画
    setTimeout(() => {
        toast.classList.add('show');
    }, 10);
    
    // 自动隐藏
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, 300);
    }, 3000);
}

// 添加Toast样式
const toastStyles = document.createElement('style');
toastStyles.textContent = `
    .toast {
        position: fixed;
        bottom: 20px;
        right: 20px;
        background: white;
        padding: 15px 20px;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        display: flex;
        align-items: center;
        gap: 10px;
        transform: translateY(100px);
        opacity: 0;
        transition: all 0.3s ease;
        z-index: 9999;
    }
    
    .toast.show {
        transform: translateY(0);
        opacity: 1;
    }
    
    .toast-success {
        border-left: 4px solid #2ecc71;
    }
    
    .toast-error {
        border-left: 4px solid #e74c3c;
    }
    
    .toast i {
        font-size: 1.2rem;
    }
    
    .toast-success i {
        color: #2ecc71;
    }
    
    .toast-error i {
        color: #e74c3c;
    }
`;

document.head.appendChild(toastStyles);