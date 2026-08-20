import os
import zipfile
import io
import json
import requests
import time
from datetime import datetime, timedelta
from xml.etree import ElementTree
from linebot import LineBotApi
from linebot.exceptions import LineBotApiError
from linebot.models import TextSendMessage

# --- 設定環境變數 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.environ.get('LINE_USER_ID')
GH_PAT = os.environ.get('GH_PAT') # 跨專案讀取權限

# REPO A 的資訊 (請修改這裡的名稱)
REPO_A_OWNER = "jclin116-oss"
REPO_A_NAME = "Dignitary-s-schedule-linebot" # <<< 請務必填入你的 REPO A 名稱

DEFAULT_KEYWORDS = '基隆 台電, 汐止 台電, 瑞芳 台電, 新北萬里 台電, 金山 台電, 貢寮 台電, 雙溪 台電, 平溪 台電, 基隆區處, 停電 基隆, 停電 汐止, 跳電 基隆, 跳電 汐止, 基隆區營業處'
SEARCH_HOURS = 24
MAX_DISPLAY_ITEMS = 15

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

# --- 新聞相關功能 ---
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
    now_tw = datetime.utcnow() + timedelta(hours=8)
    time_limit_tw = now_tw - timedelta(hours=int(hours))
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
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

def format_line_message(news_list, keywords_str, hours):
    now_str = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    if not news_list: return f"【基隆區處轄區-重點新聞輿情日報】\n{now_str}\n尚無新新聞。"
    msg_lines = [f"【基隆區處轄區-重點新聞輿情日報】", f"時間：{now_str}", f"共發現 {len(news_list)} 則新聞", '------------------------------']
    for idx, item in enumerate(news_list[:MAX_DISPLAY_ITEMS], 1):
        msg_lines.append(f"{idx}. [{item['source']}] {item['title']}\n {item['time']} {shorten_url(item['link'])}")
    return '\n\n'.join(msg_lines)

# --- 政要行程功能 (跨專案) ---
def fetch_itinerary_from_repo_a():
    headers = {"Authorization": f"Bearer {GH_PAT}", "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/repos/{REPO_A_OWNER}/{REPO_A_NAME}/actions/artifacts"
    res = requests.get(url, headers=headers)
    artifacts = res.json().get("artifacts", [])
    target = next((a for a in artifacts if a["name"] == "matched-results-artifact"), None)
    if not target: return None
    dl_res = requests.get(target["archive_download_url"], headers=headers)
    with zipfile.ZipFile(io.BytesIO(dl_res.content)) as z:
        with z.open("matched_results.json") as f: return json.load(f)

# --- 主程式 ---
def main():
    # 1. 執行新聞推送
    try:
        news = fetch_google_news(DEFAULT_KEYWORDS, SEARCH_HOURS)
        line_bot_api.push_message(LINE_USER_ID, TextSendMessage(text=format_line_message(news, DEFAULT_KEYWORDS, SEARCH_HOURS)))
    except Exception as e: print(f"新聞推播失敗: {e}")

    # 2. 執行政要行程推送
    try:
        itinerary = fetch_itinerary_from_repo_a()
        if itinerary and itinerary.get("has_matched"):
            items = itinerary["matched_items"]
            it_msg = f"【政要行程關鍵字通知】\n日期：{itinerary['date']}\n發現 {len(items)} 筆行程：\n"
            for item in items:
                it_msg += f"\n[{item['機關']}] {item['官階']}\n時間：{item['時間']}\n行程：{item['行程']}\n關鍵字：{item['關鍵字']}\n"
            line_bot_api.push_message(LINE_USER_ID, TextSendMessage(text=it_msg))
    except Exception as e: print(f"行程推播失敗: {e}")

if __name__ == '__main__':
    main()
