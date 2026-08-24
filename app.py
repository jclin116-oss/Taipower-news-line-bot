import os
import zipfile
import io
import json
import requests
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree
from linebot import LineBotApi
from linebot.models import TextSendMessage

#  設定環境變數 
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.environ.get('LINE_USER_ID')
GH_PAT = os.environ.get('GH_PAT')

# REPO A設定
REPO_A_OWNER = "jclin116-oss"
REPO_A_NAME = "Dignitary-s-schedule-linebot"

DEFAULT_KEYWORDS = '基隆 台電, 汐止 台電, 汐止 水電, 瑞芳 台電, 新北萬里 台電, 金山 台電, 貢寮 台電, 雙溪 台電, 平溪 台電, 基隆區處, 停電 基隆, 停電 汐止, 跳電 基隆, 跳電 汐止, 基隆區營業處'
SEARCH_HOURS = 24
MAX_DISPLAY_ITEMS = 15

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

# 新聞功能
def shorten_url(url):
    try:
        api_url = f"http://tinyurl.com/api-create.php?url={requests.utils.quote(url)}"
        response = requests.get(api_url, timeout=5)
        if response.status_code == 200: return response.text
    except: pass
    return url

def fetch_google_news(keywords_str, hours):
    keyword_groups = [g.strip() for g in keywords_str.replace('，', ',').split(',') if g.strip()]
    all_news = []
    now_tw = datetime.now(timezone.utc) + timedelta(hours=8)
    time_limit_tw = now_tw - timedelta(hours=int(hours))
    headers = {'User-Agent': 'Mozilla/5.0'}
    for group in keyword_groups:
        url = f'https://news.google.com/rss/search?q={requests.utils.quote(group.replace(" ", " AND "))}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant'
        try:
            response = requests.get(url, timeout=15, headers=headers)
            if response.status_code == 200:
                tree = ElementTree.fromstring(response.content)
                for item in tree.findall('.//item'):
                    title = item.find('title').text if item.find('title') is not None else ''
                    pub_date_str = item.find('pubDate').text
                    pub_date_gmt = datetime.strptime(pub_date_str, '%a, %d %b %Y %H:%M:%S %Z')
                    pub_date_tw = pub_date_gmt + timedelta(hours=8)
                    if pub_date_tw > time_limit_tw:
                        all_news.append({'title': title, 'time': pub_date_tw.strftime('%m/%d %H:%M'), 
                                         'source': item.find('source').text if item.find('source') is not None else '網路',
                                         'link': item.find('link').text, 'timestamp': pub_date_tw})
        except: continue
    unique_news = []
    seen_titles = set()
    for item in all_news:
        if item['title'] not in seen_titles:
            seen_titles.add(item['title']); unique_news.append(item)
    return sorted(unique_news, key=lambda x: x['timestamp'], reverse=True)

def format_news_block(news_list):
    now_str = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    if not news_list:
        return f"【基隆區處轄區-24小時內重點新聞輿情】\n搜尋時間：{now_str}\n❌24小時內尚無本處轄區新聞。"
    
    msg_lines = [
        "【基隆區處轄區-24小時內重點新聞輿情】",
        f"搜尋時間：{now_str}",
        f"✅共 {len(news_list)} 則相關新聞"
    ]
    
    for idx, item in enumerate(news_list[:MAX_DISPLAY_ITEMS], 1):
        msg_lines.append(f"\n{idx}. [{item['source']}] {item['title']}\n{item['time']} {shorten_url(item['link'])}")
        
    return '\n'.join(msg_lines)

# 政要行程功能(REPO A)
def fetch_itinerary_from_repo_a():
    headers = {"Authorization": f"Bearer {GH_PAT}", "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/repos/{REPO_A_OWNER}/{REPO_A_NAME}/actions/artifacts"
    
    try:
        res = requests.get(url, headers=headers)
        if res.status_code != 200:
            return None
            
        artifacts = res.json().get("artifacts", [])
        target = next((a for a in artifacts if a["name"] == "matched-results-artifact"), None)
        if not target: return None
            
        dl_res = requests.get(target["archive_download_url"], headers=headers)
        with zipfile.ZipFile(io.BytesIO(dl_res.content)) as z:
            with z.open("matched_results.json") as f: 
                return json.load(f)
    except Exception as e:
        print(f"DEBUG: 抓取過程發生異常: {e}")
        return None

def format_itinerary_block(itinerary):
    if not itinerary:
        now_str = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")
        return f"【政要公開行程動態】*{now_str} 行程資料抓取失敗*"
    
    date_str = itinerary.get('date', '未知日期')
    has_matched = itinerary.get('has_matched', False)
    items = itinerary.get("all_items", itinerary.get("matched_items", []))
    
    status_str = "✅有本處轄區" if has_matched else "❌無本處轄區"
    header = f"【{date_str}政要公開行程動態】\n{status_str}"
    
    if not items:
        return f"{header}\n今日無公開行程資料。"
    
    msg_lines = [header]
    prev_agency = None
    
    for item in items:
        agency = item.get('機關', '')
        role = item.get('官階', '')
        time_str = item.get('時間', '-')
        content = item.get('行程', '')
        keywords = item.get('關鍵字', '')
        is_jurisdiction = item.get('is_jurisdiction', False)
        
       
        # 標頭與內文排在同一行
        prefix = "🚨 " if is_jurisdiction else ""
        line = f"• {prefix}[{agency}-{role}] {time_str} {content}".strip()
        
        if keywords:
            line += f" (關鍵字：{keywords})"
            
        msg_lines.append(line)
        
    return '\n'.join(msg_lines)

# 主程式：合併為單一訊息
def main():
    try:
        # 1.取得政要行程內容
        itinerary = fetch_itinerary_from_repo_a()
        itinerary_text = format_itinerary_block(itinerary)
        
        # 2.取得新聞內容
        news = fetch_google_news(DEFAULT_KEYWORDS, SEARCH_HOURS)
        news_text = format_news_block(news)
        
        # 3.結合成一則訊息（最上方加上「自動化通知」）
        combined_message = f"系統定時自動化通知\n\n{itinerary_text}\n\n{news_text}"
        
        # 4.LINE合併發送為一則訊息
        line_bot_api.push_message(LINE_USER_ID, TextSendMessage(text=combined_message))
        
    except Exception as e:
        print(f"推播執行失敗: {e}")

if __name__ == '__main__':
    main()
