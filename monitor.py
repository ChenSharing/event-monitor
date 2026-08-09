#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
from bs4 import BeautifulSoup
import json
import os
import chardet
from datetime import datetime
from readability import Document

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

# ======================== 获取纯净正文 ========================
def fetch_clean_text(url):
    """请求网页，自动检测编码，提取纯净正文"""
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()

        # 1. 自动检测编码
        raw_data = resp.content
        detected = chardet.detect(raw_data)
        encoding = detected.get('encoding', 'utf-8')
        # 有时 chardet 会误判为 GB2312/GBK，优先用响应头
        if 'charset' in resp.headers.get('content-type', '').lower():
            encoding = resp.apparent_encoding or encoding

        # 2. 解码
        try:
            html = raw_data.decode(encoding, errors='ignore')
        except:
            html = raw_data.decode('utf-8', errors='ignore')

        # 3. 用 readability 提取正文
        doc = Document(html)
        title = doc.title()
        content = doc.summary()  # 返回 HTML 结构

        # 4. 从正文 HTML 中提取纯文本
        soup = BeautifulSoup(content, 'html.parser')
        clean_text = soup.get_text(separator="\n", strip=True)

        # 如果提取的正文太短（可能是提取失败），回退到全页文本
        if len(clean_text) < 100:
            soup_all = BeautifulSoup(html, 'html.parser')
            for tag in soup_all(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            clean_text = soup_all.get_text(separator="\n", strip=True)

        return title, clean_text
    except Exception as e:
        print(f"      ❌ 抓取失败: {e}")
        return None, None

# ======================== AI 提取 ========================
def extract_info_with_ai(page_text, url):
    if not ZHIPU_API_KEY:
        return None

    if len(page_text) > 3000:
        page_text = page_text[:3000] + "..."

    prompt = f"""
你是一个专业的赛事活动信息提取助手。请从以下纯文本内容中提取关键的赛事/活动信息，遵循以下原则：

1. **只看正文内容**，忽略无关的导航、版权、页脚信息。
2. **提取关键时间节点**：报名开始/截止、比赛日期、公布结果等。
3. **提取地点、日程安排、特别提醒**（如“逾期视为放弃”）。
4. **保留原文关键表述**，不要过度改写。
5. **只提取尚未过期的活动**，已过去的活动忽略。
6. **如果页面是新闻列表**，只提取其中与赛事/活动相关的条目。

输出 JSON 格式：
{{
  "title": "活动名称或页面标题",
  "summary": "一段完整的自然语言描述，包含所有关键时间、地点、提醒",
  "reg_deadline": "YYYY-MM-DD",   // 报名截止日，没有则为空
  "event_date": "YYYY-MM-DD",     // 比赛开始日，没有则为空
  "is_confirmed": true/false,
  "raw_dates": ["提取到的原始日期文本"]
}}

网页正文：
{page_text}
"""
    headers = {"Authorization": f"Bearer {ZHIPU_API_KEY}", "Content-Type": "application/json"}
    api_url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    payload = {
        "model": "glm-4-flash",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
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

    for key, ev in known_events.items():
        reminders = ev.get('reminders', [])
        url = ev.get('url', '')
        title = ev.get('title', '')

        # 检查报名截止提醒
        reg_date_str = ev.get('reg_deadline')
        if reg_date_str:
            try:
                reg_date = datetime.strptime(reg_date_str, '%Y-%m-%d').date()
                days = (reg_date - today).days
                if days == 7 and '7d_reg' not in reminders:
                    msg = f"⚠️ 提醒：{title} 报名截止倒计时7天！\n请尽快完成报名。\n🔗 {url}"
                    send_feishu(msg)
                    reminders.append('7d_reg')
                elif days == 1 and '1d_reg' not in reminders:
                    msg = f"🚨 紧急提醒：{title} 报名明天截止！\n逾期将无法参加，请立即登录官网办理。\n🔗 {url}"
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
                    msg = f"📅 提醒：{title} 将于7天后开始！\n请做好准备。\n🔗 {url}"
                    send_feishu(msg)
                    reminders.append('7d_event')
                elif days == 1 and '1d_event' not in reminders:
                    msg = f"📅 提醒：{title} 明天正式开始！\n详细信息请查看官网。\n🔗 {url}"
                    send_feishu(msg)
                    reminders.append('1d_event')
            except:
                pass

        if reminders != ev.get('reminders', []):
            ev['reminders'] = reminders

# ======================== 主程序 ========================
def main():
    new_events = []
    print(f"\n🔍 监控 {len(URLS)} 个网址...")
    print("=" * 50)

    for idx, url in enumerate(URLS, 1):
        print(f"\n[{idx}/{len(URLS)}] {url}")

        title, clean_text = fetch_clean_text(url)
        if not clean_text:
            print(f"      ❌ 无法获取正文")
            continue

        print(f"      📄 正文长度: {len(clean_text)} 字符")

        ai_data = extract_info_with_ai(clean_text, url)
        if not ai_data:
            ai_data = {
                "title": title or url.split('/')[2],
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
            ai_data['reminders'] = []
            known_events[key] = ai_data
            new_events.append(ai_data)
            print(f"      ✅ 新事件")
        else:
            print(f"      ⏳ 已存在")

    # 保存更新
    with open('events.json', 'w', encoding='utf-8') as f:
        json.dump(known_events, f, ensure_ascii=False, indent=2)

    # 推送新事件汇总
    if new_events:
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

    # 提醒检查
    check_reminders()

if __name__ == "__main__":
    main()
