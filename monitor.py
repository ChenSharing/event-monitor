import requests
from bs4 import BeautifulSoup
import json
import re
import os
from datetime import datetime

# ---- 从环境变量读取飞书 Webhook（安全） ----
FEISHU_WEBHOOK = os.environ.get('FEISHU_WEBHOOK', '')
if not FEISHU_WEBHOOK:
    print("警告：未设置 FEISHU_WEBHOOK 环境变量，将跳过推送。")

# ---- 读取网址列表 ----
with open('urls.txt', 'r') as f:
    URLS = [line.strip() for line in f if line.strip()]

# ---- 读取已发现事件（去重缓存） ----
try:
    with open('events.json', 'r') as f:
        known_events = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    known_events = {}

# ---------- 辅助函数 ----------
def fetch_page_metadata(url):
    """
    获取页面的标题和一段摘要描述
    返回 (title, description)
    """
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 标题
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        if not title:
            title = url.split('/')[2]  # 用域名作为后备
        
        # 摘要：优先用 meta description，否则取正文第一段（去掉空行）
        description = ""
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            description = meta_desc['content'].strip()
        else:
            # 尝试找第一个 <p> 且有内容的
            for p in soup.find_all('p'):
                text = p.get_text().strip()
                if len(text) > 20:  # 至少要有20个字符才算有效
                    description = text
                    break
        
        # 如果描述太长，截断到200字符
        if len(description) > 200:
            description = description[:200] + "..."
        
        return title, description
    except Exception as e:
        print(f"  ⚠️ 获取 {url} 元数据失败: {e}")
        return url.split('/')[2], "（详情请访问官网）"

def extract_dates(text):
    """提取各种日期格式"""
    patterns = [
        r'(\d{4}[-\/]\d{1,2}[-\/]\d{1,2})',
        r'(\d{1,2}月\d{1,2}日)',
        r'(\d{4}年\d{1,2}月\d{1,2}日)',
    ]
    dates = []
    for pat in patterns:
        dates.extend(re.findall(pat, text))
    return list(set(dates))

def send_feishu_aggregated(events_list):
    """汇总推送，模仿你之前的手动格式"""
    if not events_list:
        return
    if not FEISHU_WEBHOOK:
        print("飞书 Webhook 未配置，跳过推送")
        return

    today_str = datetime.now().strftime("%m月%d日")
    lines = [
        f"📢 近期赛事信息汇总更新（{today_str}）",
        "━━━━━━━━━━━━━━━━━━━━"
    ]

    for idx, ev in enumerate(events_list, 1):
        # 构建每条赛事信息块
        lines.append("")
        lines.append(f"【{ev['title']}】")
        lines.append(ev['description'])
        lines.append(f"📅 关键日期：{ev['date']}")
        lines.append(f"🔗 官网：{ev['url']}")
        lines.append("")  # 空行分隔

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 请及时设置日历提醒（提前1周 + 提前1天）")

    msg = "\n".join(lines)
    payload = {"msg_type": "text", "content": {"text": msg}}
    try:
        requests.post(FEISHU_WEBHOOK, json=payload, timeout=5)
        print(f"✅ 汇总推送成功，共 {len(events_list)} 条新事件")
    except Exception as e:
        print(f"❌ 推送失败: {e}")

# ---------- 主函数 ----------
def main():
    new_events = []
    print(f"🔍 开始监控 {len(URLS)} 个网址...")

    for url in URLS:
        print(f"\n  → 检查 {url}")
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            text = soup.get_text()

            # 提取日期
            dates = extract_dates(text)
            if not dates:
                print("    ⏳ 未发现日期信息，跳过")
                continue

            # 获取页面标题和描述（只获取一次，避免重复请求）
            title, description = fetch_page_metadata(url)

            # 对每个日期，创建一个事件记录（去重）
            for date_str in dates:
                key = f"{url}_{date_str}"
                if key not in known_events:
                    event_data = {
                        'url': url,
                        'date': date_str,
                        'title': title,
                        'description': description,
                        'found_at': datetime.now().isoformat()
                    }
                    known_events[key] = event_data
                    new_events.append(event_data)
                    print(f"    ✅ 发现新事件：{title} -> {date_str}")
                else:
                    print(f"    ⏳ 已存在：{title} -> {date_str}")
        except Exception as e:
            print(f"    ❌ 检查失败: {e}")

    # 保存缓存
    with open('events.json', 'w') as f:
        json.dump(known_events, f, ensure_ascii=False, indent=2)

    # 汇总推送
    if new_events:
        send_feishu_aggregated(new_events)
    else:
        print("\n📭 未发现新事件，静默退出（不推送）")

if __name__ == "__main__":
    main()
