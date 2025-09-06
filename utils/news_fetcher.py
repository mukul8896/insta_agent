# utils/news_fetcher.py
import requests
import time
import os
import json
from config import NEWS_API_URL,TRADIENT_NEWS_URL
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

def fetch_all_stock_news():
    """
    Fetches latest stock-specific NSE/BSE news from Tradient API.
    Only includes items where sm_symbol is non-empty and not 'global'.
    Returns a compact list suitable for LLM input.
    """
    try:
        response = requests.get(TRADIENT_NEWS_URL, timeout=10)
        response.raise_for_status()
        data = response.json().get("data", {}).get("latest_news", [])
    except Exception as e:
        print(f"Error fetching news: {e}")
        return []

    summarized_news = []
    for item in data:
        sm_symbol = item.get("sm_symbol", "").strip()
        nse_scrip_code = str(item.get("nse_scrip_code", "")).strip()
        bse_scrip_code = str(item.get("bse_scrip_code", "")).strip()
        if (not sm_symbol or ((not nse_scrip_code or str(nse_scrip_code).strip() == "0") and (not bse_scrip_code or str(bse_scrip_code).strip() == "0"))):
            continue

        news = item.get("news_object", {})
        title = news.get("title", "")[:200]   # limit title length
        summary = news.get("text", "")[:1000]  # limit summary length
        sentiment = news.get("overall_sentiment", "")
        publish_ts = item.get("publish_date", 0)
        publish_dt = datetime.fromtimestamp(publish_ts / 1000).strftime("%Y-%m-%d %H:%M:%S") if publish_ts else ""

        summarized_news.append({
            "tradingsymbol": sm_symbol,
            "new_headline": title,
            "sentiment": sentiment,
            # "summary": summary,
            "publish_dt":publish_dt,
            "publish_ts":publish_ts,
        }) 
    return summarized_news

def fetch_positive_stock_news(news_data=None):
    """
    Fetches latest stock-specific NSE/BSE news from Tradient API.
    Only includes items where sm_symbol is non-empty and not 'global'.
    Returns a compact list suitable for LLM input.
    """
    if news_data == None:
        try:
            response = requests.get(TRADIENT_NEWS_URL, timeout=10)
            response.raise_for_status()
            news_data = response.json().get("data", {}).get("latest_news", [])
            summarized_news = []
            for item in news_data:
                sm_symbol = item.get("sm_symbol", "").strip()
                nse_scrip_code = str(item.get("nse_scrip_code", "")).strip()
                bse_scrip_code = str(item.get("bse_scrip_code", "")).strip()
                if (not sm_symbol or ((not nse_scrip_code or str(nse_scrip_code).strip() == "0") and (not bse_scrip_code or str(bse_scrip_code).strip() == "0"))):
                    continue # skip non-stock news         
                news = item.get("news_object", {})
                title = news.get("title", "")[:200]   # limit title length
                summary = news.get("text", "")[:1000]  # limit summary length
                sentiment = news.get("overall_sentiment", "neutral")
                if sentiment.lower() == "negative" or sentiment.lower() == "neutral":
                    continue 
                publish_ts = item.get("publish_date", 0)
                publish_dt = datetime.fromtimestamp(publish_ts / 1000).strftime("%Y-%m-%d %H:%M:%S") if publish_ts else ""

                summarized_news.append({
                    "tradingsymbol": sm_symbol,
                    "new_headline": title,
                    "sentiment": sentiment,
                    # "summary": summary,
                    #"publish_dt":publish_dt,
                    #"publish_ts":publish_ts,
                })
            return summarized_news
        except Exception as e:
            print(f"Error fetching news: {e}")
            return []

    summarized_news = []
    for item in news_data:
        tradingsymbol = item.get("tradingsymbol", "").strip()
        sentiment = item.get("sentiment", "").strip()
        new_headline = item.get("new_headline", "")[:200]   # limit title length

        if sentiment.lower() == "negative" or sentiment.lower() == "neutral":
            continue  # skip non-stock news

        summarized_news.append({
            "tradingsymbol": tradingsymbol,
            "new_headline": new_headline
            # "summary": summary
        })   
    return summarized_news

import requests
from bs4 import BeautifulSoup

def fetch_article_text(url):
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()  # raise error for bad status codes (4xx, 5xx)
        
        soup = BeautifulSoup(resp.text, "html.parser")
        paragraphs = [p.get_text() for p in soup.find_all("p")]
        article_text = "\n".join(paragraphs).strip()
        
        if not article_text:
            return "⚠️ No readable article content found."
        
        return article_text

    except requests.exceptions.RequestException as e:
        # handles connection errors, timeouts, invalid URL, etc.
        return f"⚠️ Failed to fetch article: RequestException"
    except Exception as e:
        # any other unexpected errors
        return f"⚠️ Unexpected error while parsing article: Got an Exception"



def fetch_newapi_articles(query=None):
    """
    Fetch news.
    Returns a list of news articles as dictionaries.
    """
    all_articles = []

    params = {
        "q": query,
        "language": "en",
        "from": (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d"),
        "sortBy": "popularity",
        "apiKey": os.getenv("NEWS_API_KEY")
    }
    response = requests.get(NEWS_API_URL, params=params)
    data = response.json()
    if data.get("status") != "ok":
        print(f"Error fetching general market news: {data}")
    else:
        for article in data.get("articles", []):
            all_articles.append({
                "title": article.get("title"),
                # "description": article.get("description"),
                "url": article.get("url"),
                "article_text": fetch_article_text(article.get("url")),
                "urlToImage": article.get("urlToImage"),
                "source": article.get("source", {}).get("name")
            })
    return all_articles

def filter_news(news_list,filter_keywords=None):
    """
    Filter news for earnings/financial related keywords.
    Accepts a list of news dicts and returns a filtered list.
    """
    filter_keywords = [
        "earnings", "quarterly results", "profit", "loss", "revenue",
        "net income", "Q1 results", "Q2 results", "Q3 results", "Q4 results"
    ]
    filtered_news = []
    for news in news_list:
        content = (news.get("new_headline") or "") + " " + (news.get("summery") or "")
        if any(keyword.lower() in content.lower() for keyword in filter_keywords):
            filtered_news.append(news)
    return filtered_news
