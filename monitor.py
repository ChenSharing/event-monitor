import requests
from bs4 import BeautifulSoup
import json
import re
import os
from datetime import datetime

# 从环境变量安全读取飞书 Webhook（不硬编码）
FEISHU_WEBHOOK = os.environ.get('FEISHU_WEBHOOK', '')
if not FEISHU_WEBHOOK:
    print("警告：未设置 FEISHU_WEBHOOK 环境变量，将跳过推送。")

# 读取网址列表
with open('urls.txt', 'r') as f:
    URLS = [line.strip() for line in f if line.strip()]

# 读取已存事件（本地缓存，防止重复推送）
try:
    with open('events.json', 'r') as f:
        known_events = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    known_events = {}

def send_feishu(msg):
    """安全推送，不会在日志中泄露 webhook"""
    if not FEISHU_WEBHOOK:
        print("飞书 Webhook 未配置，跳过推送")
        return
    payload = {"msg_type": "text", "content": {"text": msg}}
    try:
        requests.post(FEISHU_WEBHOOK, json=payload, timeout=5)
        print("推送成功")
    except Exception as e:
        print(f"推送失败: {e}")

def extract_dates(text):
    """提取日期（支持 2026-08-15 或 8月15日）"""
    pattern1 = r'(\d{4}[-\/]\d{1,2}[-\/]\d{1,2})'
    pattern2 = r'(\d{1,2}月\d{1,2}日)'
    dates = re.findall(pattern1, text) + re.findall(pattern2, text)
    return list(set(dates))

def main():
    new_events = []
    for url in URLS:
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            text = soup.get_text()
            dates = extract_dates(text)
            for date_str in dates:
                key = f"{url}_{date_str}"
                if key not in known_events:
                    known_events[key] = {
                        'url': url,
                        'date': date_str,
                        'found_at': datetime.now().isoformat()
                    }
                    new_events.append(known_events[key])
                    print(f"发现新事件: {url} -> {date_str}")
        except Exception as e:
            print(f"检查 {url} 出错: {e}")

    # 保存更新（仅本地，不会提交到仓库）
    with open('events.json', 'w') as f:
        json.dump(known_events, f, ensure_ascii=False, indent=2)

    # 推送新事件
    for ev in new_events:
        platform = ev['url'].split('/')[2]
        msg = f"""📢 新赛事/活动发现！
🏷 平台：{platform}
🔗 链接：{ev['url']}
📅 关键日期：{ev['date']}
⚠️ 请及时设置日历提醒（提前1周+提前1天）"""
        send_feishu(msg)

    if not new_events:
        print("未发现新事件，静默退出")

if __name__ == "__main__":
    main()
