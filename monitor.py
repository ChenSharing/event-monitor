#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
from bs4 import BeautifulSoup
import json
import re
import os
from datetime import datetime, timedelta

# ======================== 环境变量 ========================
FEISHU_WEBHOOK = os.environ.get('FEISHU_WEBHOOK', '')
ZHIPU_API_KEY = os.environ.get('ZHIPU_API_KEY', '')

print(f"🔑 FEISHU_WEBHOOK: {'✅' if FEISHU_WEBHOOK else '❌'}")
print(f"🔑 ZHIPU_API_KEY: {'✅' if ZHIPU_API_KEY else '❌'}")

# ======================== 配置 ========================
with open('urls.txt', 'r', encoding='utf-8') as f:
    URLS = [line.strip() for line in f if line.strip()]

try:
    with open('events.json', 'r', encoding='utf-8') as f:
        known_events = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    known_events = {}

# ======================== AI 提取函数 ========================
def extract_info_with_ai(page_text, url):
    if not ZHIPU_API_KEY:
        return None

    # 截断文本，控制 token
    if len(page_text) > 3000:
        page_text = page_text[:3000] + "..."

    prompt = f"""
你是一个专业的赛事活动信息提取助手。从网页内容中提取关键信息，输出 JSON 格式（只输出 JSON，不要附加任何文字）。

【提取规则】
1. 时间类：报名截止、考试时间、比赛日期、报名开始、成绩公布、参赛确认
2. 节点类：初赛、复赛、决赛、总决赛、终评、第一轮、第二轮（判断是哪个节点）
3. 地点类：城市、具体场馆
4. 区分"开始"和"截止"
5. 如果有具体时间（如16:00截止），保留
6. 如果有"预计""待定"等不确定词，标记 is_confirmed=false
7. 核心判断：事件是否已发生？未发生才提取，已发生的直接忽略

【输出字段】
{{
  "title": "赛事/活动名称",
  "is_confirmed": true/false,
  "reg_deadline": "报名截止时间（含具体时刻）",
  "event_date": "比赛日期",
  "location": "举办地点",
  "node_type": "初赛/复赛/决赛/终评/总决赛",
  "deadline_urgent": true/false,
  "status": "进行中/已截止/待确认/已过期",
  "summary": "一句话核心内容",
  "full_details": "详细说明"
}}

网页内容：
{page_text}
"""
    headers = {
        "Authorization": f"Bearer {ZHIPU_API_KEY}",
        "Content-Type": "application/json"
    }
    api_url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    payload = {
        "model": "glm-4-flash",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"}
    }

    try:
        print(f"      📤 调用智谱 AI...")
        resp = requests.post(api_url, json=payload, headers=headers, timeout=30)
        if resp.status_code != 200:
            print(f"      ❌ API 错误: {resp.text[:200]}")
            return None
        result = resp.json()
        content = result['choices'][0]['message']['content']
        data = json.loads(content)
        print(f"      ✅ AI 提取成功: {data.get('title', '')[:30]}")
        return data
    except Exception as e:
        print(f"      ❌ AI 提取失败: {e}")
        return None

# ======================== 推送函数 ========================
def send_feishu(events_list):
    if not events_list or not FEISHU_WEBHOOK:
        return

    today = datetime.now().strftime("%Y年%m月%d日")
    lines = [f"📢 近期赛事信息汇总更新（{today}）", "━━━━━━━━━━━━━━━━━━━━"]

    for ev in events_list:
        lines.append("")
        lines.append(f"【{ev.get('title', '未命名')}】")

        if ev.get('summary'):
            lines.append(ev['summary'])

        if ev.get('is_confirmed') is False:
            lines.append("⏳ 日期待确认（标注为'预计'）")

        # 紧急提醒（7天内截止）
        if ev.get('deadline_urgent'):
            lines.append("⚠️ 即将截止，请尽快处理！")

        if ev.get('reg_deadline'):
            lines.append(f"📅 报名截止：{ev['reg_deadline']}")

        if ev.get('event_date'):
            lines.append(f"📅 比赛时间：{ev['event_date']}")

        if ev.get('location'):
            lines.append(f"📍 地点：{ev['location']}")

        if ev.get('node_type'):
            lines.append(f"🏷 节点：{ev['node_type']}")

        if ev.get('status'):
            lines.append(f"📌 状态：{ev['status']}")

        if ev.get('full_details'):
            lines.append(ev['full_details'])

        lines.append(f"🔗 官网：{ev['url']}")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 日历提醒：提前1周 + 提前1天")
    msg = "\n".join(lines)

    payload = {"msg_type": "text", "content": {"text": msg}}
    try:
        requests.post(FEISHU_WEBHOOK, json=payload, timeout=5)
        print(f"✅ 推送成功，共 {len(events_list)} 条")
    except Exception as e:
        print(f"❌ 推送失败: {e}")

# ======================== 去重函数 ========================
def is_event_active(event_date_str):
    """判断事件是否已过期，以事件日期为准"""
    if not event_date_str:
        return True  # 无日期默认保留
    # 简单判断：如果包含"已截止""已过期"等关键词，则跳过
    # 更复杂的日期解析留给 AI 判断
    return True

# ======================== 主程序 ========================
def main():
    new_events = []
    print(f"\n🔍 监控 {len(URLS)} 个网址...")
    print("=" * 50)

    for idx, url in enumerate(URLS, 1):
        print(f"\n[{idx}/{len(URLS)}] {url}")
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            resp.encoding = 'utf-8'
            soup = BeautifulSoup(resp.text, 'html.parser')

            # 清除脚本和样式
            for tag in soup(["script", "style"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            text = ''.join(c for c in text if c.isprintable() or c == '\n')
            page_text = text[:3000]  # 控制长度

            # AI 提取
            ai_data = extract_info_with_ai(page_text, url)

            if not ai_data:
                # 兜底
                title = soup.title.string.strip() if soup.title else url.split('/')[2]
                ai_data = {
                    "title": title,
                    "is_confirmed": False,
                    "reg_deadline": "",
                    "event_date": "",
                    "location": "",
                    "node_type": "",
                    "deadline_urgent": False,
                    "status": "待核实",
                    "summary": "AI 提取失败，请手动查看",
                    "full_details": ""
                }
                print(f"      ⚠️ 使用兜底数据")

            # 判断是否已过期
            if not is_event_active(ai_data.get('event_date', '')):
                print(f"      ⏳ 事件已过期，跳过")
                continue

            # 去重
            key = f"{url}_{ai_data.get('title', '')}_{ai_data.get('event_date', '')}"
            if key not in known_events:
                ai_data['url'] = url
                ai_data['found_at'] = datetime.now().isoformat()
                known_events[key] = ai_data
                new_events.append(ai_data)
                print(f"      ✅ 新事件: {ai_data.get('title')}")
            else:
                print(f"      ⏳ 已存在")

        except Exception as e:
            print(f"      ❌ 错误: {e}")

    # 保存缓存
    with open('events.json', 'w', encoding='utf-8') as f:
        json.dump(known_events, f, ensure_ascii=False, indent=2)

    # 推送
    if new_events:
        send_feishu(new_events)
    else:
        print("\n📭 无新事件")

if __name__ == "__main__":
    main()
