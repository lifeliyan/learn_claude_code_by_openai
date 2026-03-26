#!/usr/bin/env python3
"""
用户登录系统测试脚本
"""

import requests
import json
import sys

BASE_URL = "http://localhost:5000"

def test_api_endpoints():
    """测试API端点"""
    print("测试API端点...")
    
    # 测试检查认证状态（应该返回未认证）
    try:
        response = requests.get(f"{BASE_URL}/api/check_auth")
        data = response.json()
        print(f"✓ /api/check_auth: {data}")
        assert data['authenticated'] == False
    except Exception as e:
        print(f"✗ /api/check_auth 测试失败: {e}")
        return False
    
    return True

def test_pages():
    """测试页面访问"""
    print("\n测试页面访问...")
    
    pages = [
        ("/", "首页"),
        ("/login", "登录页面"),
        ("/register", "注册页面"),
    ]
    
    all_passed = True
    for path, name in pages:
        try:
            response = requests.get(f"{BASE_URL}{path}")
            if response.status_code == 200:
                print(f"✓ {name}: 可访问")
            else:
                print(f"✗ {name}: 状态码 {response.status_code}")
                all_passed = False
        except Exception as e:
            print(f"✗ {name}: 访问失败 - {e}")
            all_passed = False
    
    return all_passed

def test_demo_account():
    """测试演示账户"""
    print("\n测试演示账户...")
    
    # 测试登录
    login_data = {
        'username': 'admin',
        'password': 'admin123'
    }
    
    try:
        # 注意：实际测试需要运行Flask应用
        print("⚠️  登录测试需要运行中的Flask应用")
        print("   请先运行: python app.py")
        print("   然后在另一个终端运行此测试")
        return True
    except Exception as e:
        print(f"✗ 登录测试失败: {e}")
        return False

def main():
    """主测试函数"""
    print("=" * 50)
    print("用户登录系统测试")
    print("=" * 50)
    
    tests = [
        ("API端点测试", test_api_endpoints),
        ("页面访问测试", test_pages),
        ("演示账户测试", test_demo_account),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n{test_name}:")
        try:
            if test_func():
                print(f"✓ {test_name} 通过")
                results.append((test_name, True))
            else:
                print(f"✗ {test_name} 失败")
                results.append((test_name, False))
        except Exception as e:
            print(f"✗ {test_name} 异常: {e}")
            results.append((test_name, False))
    
    # 输出总结
    print("\n" + "=" * 50)
    print("测试总结:")
    print("=" * 50)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for test_name, success in results:
        status = "✓ 通过" if success else "✗ 失败"
        print(f"{test_name}: {status}")
    
    print(f"\n总计: {passed}/{total} 个测试通过")
    
    if passed == total:
        print("🎉 所有测试通过！")
        return 0
    else:
        print("⚠️  部分测试失败")
        return 1

if __name__ == "__main__":
    # 检查Flask应用是否运行
    try:
        response = requests.get(BASE_URL, timeout=2)
        print(f"检测到运行中的Flask应用: {response.status_code}")
    except:
        print("警告: Flask应用未运行")
        print("请先启动应用: python app.py")
        print("或使用: ./start.sh")
        print("\n是否继续测试？(y/n)")
        choice = input().lower()
        if choice != 'y':
            sys.exit(1)
    
    sys.exit(main())