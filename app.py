from datetime import datetime, timedelta
import os
from urllib.parse import quote
from xml.etree import ElementTree
from linebot import LineBotApi
from linebot.exceptions import LineBotApiError
from linebot.models import TextSendMessage
import requests

# 從環境變數讀取憑證（避免金鑰直接暴露在 GitHub 上）
LINE_TOKEN = os.environ.get(
    'LINE_TOKEN',
    'ZoCExUoUpUQ+3A9LhOGq5doeaylobJFgSO/2Tkwyz72qGs+gHiJsWZuMQmTXHidWC2I/WROppq36PysQxBT2Z8suEL+ZyVVEod8tzPYkN4wAokHiqXMoy9z4ZVu0OMDYgjsdjNYq3ZP+w2GCcXf/GwdB04t89/1O/w1cDnyilFU=',
)

TARGET_IDS = [
        'U6ac6a7a58e085194ac436f346d803aad',  # 課長個人 ID
]

DEFAULT_KEYWORDS = '基隆 台電'
SEARCH_HOURS = 24
MAX_DISPLAY_ITEMS = 15

line_bot_api = LineBotApi(LINE_TOKEN)


def fetch_google_news(keywords_str, hours):
  keyword_groups = [
      g.strip()
      for g in keywords_str.replace('，', ',').split(',')
      if g.strip()
  ]
  all_news = []
  now_tw = datetime.now()
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
            display_time = pub_date_tw.strftime('%m/%d %H:%M')

            all_news.append({
                'title': title,
                'time': display_time,
                'source': source,
                'link': link,
            })
    except Exception as e:
      print(f'抓取關鍵字組 [{group}] 異常: {e}')

  unique_news = []
  seen_titles = set()
  for item in all_news:
    if item['title'] not in seen_titles:
      seen_titles.add(item['title'])
      unique_news.append(item)

  return unique_news


def format_line_message(news_list, keywords_str, hours):
  now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

  if not news_list:
    return f'⚡️【台電新聞輿情日報】\n📅 統計時間：{now_str}\n🔍 搜尋條件：{keywords_str}（過去 {hours} 小時）\n\n目前未發現符合條件的新聞。'

  total_count = len(news_list)
  msg_lines = [
      f'⚡️【台電新聞輿情日報】',
      f'📅 統計時間：{now_str}',
      f'🔍 關鍵字：{keywords_str}（過去 {hours} 小時）',
      f'📊 共發現 {total_count} 則關聯訊息',
      '--------------------------------',
  ]

  display_news = news_list[:MAX_DISPLAY_ITEMS]
  for idx, item in enumerate(display_news, 1):
    news_block = f"{idx}. [{item['source']}] {item['title']}\n⏰ {item['time']}\n🔗 {item['link']}"
    msg_lines.append(news_block)

  if total_count > MAX_DISPLAY_ITEMS:
    msg_lines.append(
        '--------------------------------\n'
        f'⚠️ 訊息過長，已展示前 {MAX_DISPLAY_ITEMS} 則最新新聞。'
    )

  return '\n\n'.join(msg_lines)


def main():
  print(f'[{datetime.now()}] 啟動 GitHub Actions 輿情推播工作...')
  try:
    news_data = fetch_google_news(DEFAULT_KEYWORDS, SEARCH_HOURS)
    line_message = format_line_message(
        news_data, DEFAULT_KEYWORDS, SEARCH_HOURS
    )

    for target_id in TARGET_IDS:
      try:
        line_bot_api.push_message(
            target_id, TextSendMessage(text=line_message)
        )
        print(f'成功推播至：{target_id}')
      except LineBotApiError as e:
        print(f'推播失敗 [{target_id}]: {e.error.message}')

  except Exception as e:
    error_text = f'⚠️ 輿情自動推播系統異常: {e}'
    print(error_text)
    line_bot_api.push_message(
        'U6ac6a7a58e085194ac436f346d803aad',
        TextSendMessage(text=error_text),
    )


if __name__ == '__main__':
  main()
