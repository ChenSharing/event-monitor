#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
from bs4 import BeautifulSoup
import json
import re
import os
from datetime import datetime

# ======================== 读取环境变量 ========================
FEISHU_WEBHOOK = os.environ.get('FEISHU_WEBHOOK', '')
ZHIPU_API_KEY = os.environ.get('ZHIPU_API_KEY', '')

print(f"🔑 FEISHU_WEBHOOK 是否配置: {'✅ 是' if FEISHU_WEBHOOK else '❌ 否'}")
print(f"🔑 ZHIPU_API_KEY 是否配置: {'✅ 是' if ZHIPU_API_KEY else '❌ 否'}")
if ZHIPU_API_KEY:
    print(f"   API Key 前缀: {ZHIPU_API_KEY[:8]}...")

if not FEISHU_WEBHOOK:
    print("⚠️ 警告：未设置 FEISHU_WEBHOOK 环境变量，将跳过飞书推送。")
if not ZHIPU_API_KEY:
    print("⚠️ 警告：未设置 ZHIPU_API_KEY 环境变量，将跳过 AI 解析。")

# ======================== 读取配置 ========================
with open('urls.txt', 'r') as f:
    URLS = [line.strip() for line in f if line.strip()]

try:
    with open('events.json', 'r') as f:
        known_events = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    known_events = {}

# ======================== 辅助函数 ========================
def extract_dates(text):
    patterns = [
        r'(\d{4}[-\/]\d{1,2}[-\/]\d{1,2})',
        r'(\d{1,2}月\d{1,2}日)',
        r'(\d{4}年\d{1,2}月\d{1,2}日)',
        r'(\d{1,2}/\d{1,2})'
    ]
    found = []
    for pat in patterns:
        matches = re.findall(pat, text)
        found.extend(matches)
    unique = []
    for item in found:
        if item not in unique:
            unique.append(item)
    return unique

def extract_info_with_ai(page_text, url):
    """
    调用智谱 GLM-4.7 模型解析页面关键信息
    返回字典，包含 title, reg_deadline, event_date, location, notes, summary
    """
    if not ZHIPU_API_KEY:
        return None

    if len(page_text) > 4000:
        page_text = page_text[:4000] + "..."

    prompt = f"""
你是一个专业的赛事活动信息提取助手。请从以下网页内容中提取关键信息，并以 JSON 格式返回。
提取字段：
- "title": 赛事/活动名称（必须填写，如果找不到则用网页标题或域名）
- "reg_deadline": 报名截止日期（如果有，格式化为 "YYYY-MM-DD" 或 "X月X日截止" 等自然描述，没有则留空）
- "event_date": 比赛/活动举办日期（如果有，格式类似，没有则留空）
- "location": 举办地点（如果有，如 "北京·北人亦创国际会展中心"，没有则留空）
- "notes": 重要备注或特别提醒（如 "逾期视为放弃"、"需登录确认"、"免费参赛" 等，没有则留空）
- "summary": 一句话概括该通知的核心内容（例如 "总决赛报名进行中" 或 "入围名单公示"）

如果某项信息未找到，对应字段设为空字符串。

注意：只输出 JSON 对象，不要添加任何额外文字。

网页内容：
{page_text}
"""
    headers = {
        "Authorization": f"Bearer {ZHIPU_API_KEY}",
        "Content-Type": "application/json"
    }
    api_url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    payload = {
        # ============================================================
        # 用户指定使用 GLM-4.7 模型
        # 注意：智谱公开 API 标准模型一般为 glm-4、glm-4-flash、glm-4-plus
        # 如果 glm-4.7 不可用（返回 1210 错误），请将下面改为上述标准模型
        # ============================================================
        "model": "glm-4.7",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"}
    }
    
    try:
        print(f"      📤 正在调用智谱 API（模型: glm-4.7）...")
        resp = requests.post(api_url, json=payload, headers=headers, timeout=30)
        
        print(f"      📥 HTTP 状态码: {resp.status_code}")
        
        if resp.status_code != 200:
            error_body = resp.text[:500]
            print(f"      ❌ API 返回错误: {error_body}")
            return None
            
        result = resp.json()
        content = result['choices'][0]['message']['content']
        data = json.loads(content)
        
        required = ["title", "reg_deadline", "event_date", "location", "notes", "summary"]
        for field in required:
            if field not in data:
                data[field] = ""
        
        print(f"      ✅ AI 解析成功: {data.get('title', '')[:30]}")
        return data
        
    except requests.exceptions.Timeout:
        print(f"      ❌ AI 解析超时（30秒）")
        return None
    except requests.exceptions.RequestException as e:
        print(f"      ❌ AI 解析网络错误: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"      ❌ AI 返回的 JSON 解析失败: {e}")
        return None
    except Exception as e:
        print(f"      ❌ AI 解析未知错误: {e}")
        return None

def send_feishu_aggregated(events_list):
    if not events_list:
        return
    if not FEISHU_WEBHOOK:
        print("飞书 Webhook 未配置，跳过推送")
        return

    today_str = datetime.now().strftime("%Y年%m月%d日")
    lines = [f"📢 赛事最新动态（{today_str}）", "━━━━━━━━━━━━━━━━━━━━"]

    for idx, ev in enumerate(events_list, 1):
        lines.append("")
        title = ev.get('title', '未命名赛事')
        lines.append(f"【{title}】")
        summary = ev.get('summary', '')
        if summary:
            lines.append(summary)
        reg = ev.get('reg_deadline', '')
        if reg:
            lines.append(f"报名截止：{reg}")
        event_date = ev.get('event_date', '')
        if event_date:
            lines.append(f"比赛时间：{event_date}")
        loc = ev.get('location', '')
        if loc:
            lines.append(f"地点：{loc}")
        notes = ev.get('notes', '')
        if notes:
            lines.append(f"特别提醒：{notes}")
        lines.append(f"官网：{ev['url']}")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 请及时设置日历提醒（提前1周 + 提前1天）")
    msg = "\n".join(lines)

    payload = {"msg_type": "text", "content": {"text": msg}}
    try:
        requests.post(FEISHU_WEBHOOK, json=payload, timeout=5)
        print(f"✅ 汇总推送成功，共 {len(events_list)} 条新事件")
    except Exception as e:
        print(f"❌ 推送失败: {e}")

# ======================== 主逻辑 ========================
def main():
    new_events = []
    print(f"\n🔍 开始监控 {len(URLS)} 个网址...")
    print("=" * 50)

    for idx, url in enumerate(URLS, 1):
        print(f"\n[{idx}/{len(URLS)}] 检查 {url}")
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')

            for script in soup(["script", "style"]):
                script.decompose()
            text = soup.get_text(separator="\n", strip=True)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            page_text = "\n".join(lines)

            raw_dates = extract_dates(page_text)
            print(f"      📅 正则提取到日期: {raw_dates if raw_dates else '无'}")

            ai_data = extract_info_with_ai(page_text, url)
            
            if not ai_data:
                title = soup.title.string.strip() if soup.title and soup.title.string else url.split('/')[2]
                ai_data = {
                    "title": title,
                    "summary": "（AI解析失败，请手动核实）",
                    "reg_deadline": "",
                    "event_date": raw_dates[0] if raw_dates else "",
                    "location": "",
                    "notes": ""
                }
                print(f"      ⚠️ 使用兜底数据")
            else:
                if not ai_data.get('event_date') and raw_dates:
                    ai_data['event_date'] = raw_dates[0]

            event_key = f"{url}_{ai_data.get('title', '')}_{ai_data.get('event_date', '')}"
            if event_key not in known_events:
                event_data = {
                    'url': url,
                    'title': ai_data.get('title', ''),
                    'summary': ai_data.get('summary', ''),
                    'reg_deadline': ai_data.get('reg_deadline', ''),
                    'event_date': ai_data.get('event_date', ''),
                    'location': ai_data.get('location', ''),
                    'notes': ai_data.get('notes', ''),
                    'found_at': datetime.now().isoformat()
                }
                known_events[event_key] = event_data
                new_events.append(event_data)
                print(f"      ✅ 新事件已记录")
            else:
                print(f"      ⏳ 已存在，跳过")

        except requests.exceptions.Timeout:
            print(f"      ❌ 请求超时（15秒）")
        except requests.exceptions.RequestException as e:
            print(f"      ❌ 请求失败: {e}")
        except Exception as e:
            print(f"      ❌ 未知错误: {e}")

    with open('events.json', 'w') as f:
        json.dump(known_events, f, ensure_ascii=False, indent=2)

    if new_events:
        send_feishu_aggregated(new_events)
    else:
        print("\n📭 未发现新事件，静默退出（不推送）")

if __name__ == "__main__":
    main()
