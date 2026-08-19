from datetime import datetime, timedelta
import os
from urllib.parse import quote
from xml.etree import ElementTree
from linebot import LineBotApi
from linebot.exceptions import LineBotApiError
from linebot.models import TextSendMessage
import requests
import time

# 從環境變數讀取憑證（避免金鑰直接暴露在 GitHub 上）
LINE_TOKEN = os.environ.get(
    'LINE_TOKEN',
    'ZoCExUoUpUQ+3A9LhOGq5doeaylobJFgSO/2Tkwyz72qGs+gHiJsWZuMQmTXHidWC2I/WROppq36PysQxBT2Z8suEL+ZyVVEod8tzPYkN4wAokHiqXMoy9z4ZVu0OMDYgjsdjNYq3ZP+w2GCcXf/GwdB04t89/1O/w1cDnyilFU=',
)

TARGET_IDS = [
      'U6ac6a7a58e085194ac436f346d803aad',  # 課長個人 ID
]

DEFAULT_KEYWORDS = '基隆 台電, 汐止 台電, 瑞芳 台電, 萬里 台電, 金山 台電, 貢寮 台電, 雙溪 台電, 平溪 台電, 基隆區處, 停電 基隆, 停電 汐止, 跳電 基隆, 跳電 汐止'
SEARCH_HOURS = 24
MAX_DISPLAY_ITEMS = 15 # 縮短網址後，維持顯示 15 則

line_bot_api = LineBotApi(LINE_TOKEN)

def shorten_url(url):
    """使用 TinyURL 縮短網址，失敗則回傳原網址"""
    try:
        api_url = f"http://tinyurl.com/api-create.php?url={quote(url)}"
        response = requests.get(api_url, timeout=5)
        if response.status_code == 200:
            return response.text
    except Exception as e:
        print(f"縮網址失敗: {e}")
    return url

def fetch_google_news(keywords_str, hours):
    keyword_groups = [
        g.strip()
        for g in keywords_str.replace('，', ',').split(',')
        if g.strip()
    ]
    all_news = []
    # 修正：搜尋範圍比較也使用 UTC 轉 TW 時間，確保一致性
    now_tw = datetime.utcnow() + timedelta(hours=8)
    time_limit_tw = now_tw - timedelta(hours=int(hours))

    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36 (KHTML,'
            ' like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
        )
    }

    for group in keyword_groups:
        search_query = group.replace(' ', ' AND ')
        encoded_query = quote(search_query)
        url = f'https://news.google.com/rss/search?q={encoded_query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant'

        try:
            response = requests.get(url, timeout=15, headers=headers)
            if response.status_code == 200:
                tree = ElementTree.fromstring(response.content)
                for item in tree.findall('.//item'):
                    title = (
                        item.find('title').text if item.find('title') is not None else ''
                    )
                    pub_date_str = item.find('pubDate').text
                    pub_date_gmt = datetime.strptime(
                        pub_date_str, '%a, %d %b %Y %H:%M:%S %Z'
                    )
                    pub_date_tw = pub_date_gmt + timedelta(hours=8)

                    if pub_date_tw > time_limit_tw:
                        link = (
                            item.find('link').text
                            if item.find('link') is not None
                            else ''
                        )
                        source_el = item.find('source')
                        source = source_el.text if source_el is not None else '網路'
                        # 時間格式優化：只顯示時分，節省空間
                        display_time = pub_date_tw.strftime('%m/%d %H:%M')

                        all_news.append({
                            'title': title,
                            'time': display_time,
                            'source': source,
                            'link': link,
                            'timestamp': pub_date_tw # 用於排序
                        })
        except Exception as e:
            print(f'抓取關鍵字組 [{group}] 異常: {e}')

    # 去除重複新聞標題
    unique_news = []
    seen_titles = set()
    for item in all_news:
        if item['title'] not in seen_titles:
            seen_titles.add(item['title'])
            unique_news.append(item)
            
    # 依時間由新到舊排序
    unique_news.sort(key=lambda x: x['timestamp'], reverse=True)

    return unique_news

def format_line_message(news_list, keywords_str, hours):
    # 修正時區問題：取得 UTC 時間並加上 8 小時轉為台灣時間
    now_tw = datetime.utcnow() + timedelta(hours=8)
    now_str = now_tw.strftime("%Y-%m-%d %H:%M")

    if not news_list:
        return (
            f"【基隆區處轄區-重點新聞輿情日報】\n 自動生成時間：{now_str}\n"
            f" 搜尋條件：{keywords_str}（過去 {hours} 小時）\n\n尚無符合條件的新聞(註:即時新聞剛發布可能尚未進入RSS索引中)"
        )

    total_count = len(news_list)
    msg_lines = [
        f"【基隆區處轄區-重點新聞輿情日報】",
        f" 自動生成時間：{now_str}",
        f" 搜尋範圍：基隆區處轄區"
        f" 共發現 {total_count} 則相關新聞",
        '================================',
    ]

    display_news = news_list[:MAX_DISPLAY_ITEMS]
    
    print(f"開始縮短 {len(display_news)} 則新聞網址...")
    for idx, item in enumerate(display_news, 1):
        # **重點修改：縮短網址**
        short_url = shorten_url(item['link'])
        
        # 格式優化：標題與來源同列，下一列顯示時間與縮網址
        news_block = f"{idx}. [{item['source']}] {item['title']}\n⏰ {item['time']} 🔗 {short_url}"
        msg_lines.append(news_block)
        
        # 稍微停頓，避免連續請求縮網址服務被拒絕
        if idx < len(display_news):
            time.sleep(0.5)

    if total_count > MAX_DISPLAY_ITEMS:
        msg_lines.append(
            '================================\n'
            f'⚠️ 訊息過長，已展示前 {MAX_DISPLAY_ITEMS} 則最新新聞。'
        )

    return '\n\n'.join(msg_lines)

def main():
    print(f'[{datetime.now()}] 啟動 GitHub Actions 輿情推播工作...')
    try:
        # 1. 抓取新聞
        news_data = fetch_google_news(DEFAULT_KEYWORDS, SEARCH_HOURS)
        
        # 2. 格式化訊息（含縮網址）
        line_message = format_line_message(
            news_data, DEFAULT_KEYWORDS, SEARCH_HOURS
        )

        # 3. 發送 LINE
        for target_id in TARGET_IDS:
            try:
                line_bot_api.push_message(
                    target_id, TextSendMessage(text=line_message)
                )
                print(f'成功推播至：{target_id}')
            except LineBotApiError as e:
                print(f'推播失敗 [{target_id}]: {e.error.message}')
                # 如果訊息還是太長（這通常不太可能，因為有縮網址和筆數限制），嘗試分批發送
                if "Too long" in e.error.message and target_id == TARGET_IDS[0]:
                     print("嘗試分批發送給群組...")
                     # 簡單的粗略分批：前 8 則和後 7 則
                     part1 = format_line_message(news_data[:8], DEFAULT_KEYWORDS, SEARCH_HOURS)
                     part2 = format_line_message(news_data[8:15], DEFAULT_KEYWORDS, SEARCH_HOURS)
                     try:
                         line_bot_api.push_message(target_id, TextSendMessage(text=part1))
                         line_bot_api.push_message(target_id, TextSendMessage(text=part2))
                     except:
                         print("分批發送也失敗。")

    except Exception as e:
        error_text = f'⚠️ 輿情自動推播系統異常: {e}'
        print(error_text)
        line_bot_api.push_message(
            'U6ac6a7a58e085194ac436f346d803aad',
            TextSendMessage(text=error_text),
        )

if __name__ == '__main__':
    main()
