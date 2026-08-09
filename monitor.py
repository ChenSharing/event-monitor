#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime, timedelta

# ======================== 环境变量 ========================
FEISHU_WEBHOOK = os.environ.get('FEISHU_WEBHOOK', '')
ZHIPU_API_KEY = os.environ.get('ZHIPU_API_KEY', '')

print(f"🔑 FEISHU: {'✅' if FEISHU_WEBHOOK else '❌'}")
print(f"🔑 ZHIPU: {'✅' if ZHIPU_API_KEY else '❌'}")

# ======================== 配置 ========================
with open('urls.txt', 'r', encoding='utf-8') as f:
    URLS = [line.strip() for line in f if line.strip()]

try:
    with open('events.json', 'r', encoding='utf-8') as f:
        known_events = json.load(f)
except:
    known_events = {}

# ======================== AI 提取 ========================
def extract_info_with_ai(page_text, url):
    if not ZHIPU_API_KEY:
        return None

    if len(page_text) > 3000:
        page_text = page_text[:3000] + "..."

    prompt = f"""
你是赛事活动信息提取助手。从以下网页内容中提取重要的赛事/活动信息，遵循以下原则：

1. **筛选标准**：
   - 优先关注最近两个月内发布的通知；
   - 但如果通知中提到的活动日期在未来（包括明年），即使通知发布时间早，也要提取；
   - 如果活动日期明显已过去，忽略。

2. **提取内容**：
   - 活动名称、关键时间节点（报名开始/截止、比赛日期等）
   - 地点、日程安排、特别提醒（如“逾期视为放弃”）
   - 保留原文关键表述。

3. **输出格式（JSON）**：
   {{
     "title": "活动名称",
     "summary": "一段完整的自然语言描述",
     "reg_deadline": "YYYY-MM-DD",   // 报名截止日，没有则为空
     "event_date": "YYYY-MM-DD",     // 比赛开始日，没有则为空
     "is_confirmed": true/false,
     "raw_dates": ["提取到的日期文本"]
   }}

网页内容：
{page_text}
"""
    headers = {"Authorization": f"Bearer {ZHIPU_API_KEY}", "Content-Type": "application/json"}
    api_url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    payload = {
        "model": "glm-4-flash",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "response_format": {"type": "json_object"}
    }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=30)
        if resp.status_code != 200:
            print(f"      ❌ API 错误: {resp.text[:200]}")
            return None
        result = resp.json()
        content = result['choices'][0]['message']['content']
        data = json.loads(content)
        print(f"      ✅ AI 提取: {data.get('title', '')[:30]}")
        return data
    except Exception as e:
        print(f"      ❌ AI 失败: {e}")
        return None

# ======================== 飞书推送 ========================
def send_feishu(msg):
    if not FEISHU_WEBHOOK:
        return
    try:
        requests.post(FEISHU_WEBHOOK, json={"msg_type": "text", "content": {"text": msg}}, timeout=5)
        print(f"✅ 推送成功")
    except Exception as e:
        print(f"❌ 推送失败: {e}")

# ======================== 提醒检查 ========================
def check_reminders():
    today = datetime.now().date()
    reminders_sent = []

    for key, ev in known_events.items():
        reminders = ev.get('reminders', [])

        # 检查报名截止提醒
        reg_date_str = ev.get('reg_deadline')
        if reg_date_str:
            try:
                reg_date = datetime.strptime(reg_date_str, '%Y-%m-%d').date()
                days = (reg_date - today).days
                if days == 7 and '7d_reg' not in reminders:
                    msg = f"⚠️ 提醒：{ev['title']} 报名截止倒计时7天！\n请尽快完成报名。\n🔗 {ev['url']}"
                    send_feishu(msg)
                    reminders.append('7d_reg')
                elif days == 1 and '1d_reg' not in reminders:
                    msg = f"🚨 紧急提醒：{ev['title']} 报名明天截止！\n逾期将无法参加，请立即登录官网办理。\n🔗 {ev['url']}"
                    send_feishu(msg)
                    reminders.append('1d_reg')
            except:
                pass

        # 检查比赛日期提醒
        event_date_str = ev.get('event_date')
        if event_date_str:
            try:
                event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date()
                days = (event_date - today).days
                if days == 7 and '7d_event' not in reminders:
                    msg = f"📅 提醒：{ev['title']} 将于7天后开始！\n请做好准备。\n🔗 {ev['url']}"
                    send_feishu(msg)
                    reminders.append('7d_event')
                elif days == 1 and '1d_event' not in reminders:
                    msg = f"📅 提醒：{ev['title']} 明天正式开始！\n详细信息请查看官网。\n🔗 {ev['url']}"
                    send_feishu(msg)
                    reminders.append('1d_event')
            except:
                pass

        # 更新提醒记录
        if reminders != ev.get('reminders', []):
            ev['reminders'] = reminders
            reminders_sent.append(key)

    # 如果有更新，保存到文件
    if reminders_sent:
        with open('events.json', 'w', encoding='utf-8') as f:
            json.dump(known_events, f, ensure_ascii=False, indent=2)

# ======================== 主程序 ========================
def main():
    new_events = []
    print(f"\n🔍 监控 {len(URLS)} 个网址...")
    print("=" * 50)

    # 1. 抓取并发现新事件
    for idx, url in enumerate(URLS, 1):
        print(f"\n[{idx}/{len(URLS)}] {url}")
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            resp.encoding = 'utf-8'
            soup = BeautifulSoup(resp.text, 'html.parser')

            for tag in soup(["script", "style"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            text = ''.join(c for c in text if c.isprintable() or c == '\n')
            page_text = text[:3000]

            ai_data = extract_info_with_ai(page_text, url)
            if not ai_data:
                title = soup.title.string.strip() if soup.title else url.split('/')[2]
                ai_data = {
                    "title": title,
                    "summary": "（AI 提取失败，请手动查看）",
                    "reg_deadline": "",
                    "event_date": "",
                    "is_confirmed": False,
                    "raw_dates": []
                }
                print(f"      ⚠️ 兜底")

            key = f"{url}_{ai_data.get('title', '')}"
            if key not in known_events:
                ai_data['url'] = url
                ai_data['found_at'] = datetime.now().isoformat()
                ai_data['reminders'] = []  # 新增提醒状态
                known_events[key] = ai_data
                new_events.append(ai_data)
                print(f"      ✅ 新事件")
            else:
                # 若已有事件，检查日期是否有变化（可选），暂不处理
                print(f"      ⏳ 已存在")

        except Exception as e:
            print(f"      ❌ 错误: {e}")

    # 2. 保存新事件
    if new_events:
        with open('events.json', 'w', encoding='utf-8') as f:
            json.dump(known_events, f, ensure_ascii=False, indent=2)

        # 推送新事件汇总
        today = datetime.now().strftime("%Y年%m月%d日")
        lines = [f"📢 近期赛事信息汇总更新（{today}）", "━━━━━━━━━━━━━━━━━━━━"]
        for ev in new_events:
            lines.append("")
            lines.append(f"【{ev.get('title', '未命名')}】")
            if ev.get('summary'):
                lines.append(ev['summary'])
            if ev.get('is_confirmed') is False:
                lines.append("⏳ 日期待确认")
            lines.append(f"🔗 {ev['url']}")
            lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("💡 日历提醒：提前1周 + 提前1天")
        send_feishu("\n".join(lines))
    else:
        print("\n📭 无新事件")

    # 3. 无论有无新事件，都检查并发送提醒
    check_reminders()

if __name__ == "__main__":
    main()
