import os
import re
import asyncio
import aiohttp
import tweepy
import requests
import tempfile
from datetime import datetime, timezone
from dotenv import load_dotenv
from typing import List, Optional, TypedDict

from langgraph.graph import START, END, StateGraph
from pydantic import BaseModel
from uipath_langchain.chat import UiPathChat
from langchain_core.messages import SystemMessage, HumanMessage

# ---------------------------------------------------------------------------
# 1️⃣ SETUP ENVIRONMENT & CLIENTS
# ---------------------------------------------------------------------------
load_dotenv()

llm = UiPathChat(model="gpt-4o-mini-2024-07-18")

try:
    twitter_client = tweepy.Client(
        bearer_token=os.getenv("BEARER_TOKEN"),
        consumer_key=os.getenv("API_KEY"),
        consumer_secret=os.getenv("API_SECRET"),
        access_token=os.getenv("ACCESS_TOKEN"),
        access_token_secret=os.getenv("ACCESS_TOKEN_SECRET")
    )
    print("✅ Twitter client initialized successfully")
except Exception as e:
    print(f"⚠️ Twitter client initialization failed: {e}")
    twitter_client = None

# Initialize Tweepy v1.1 API for media upload
try:
    twitter_api_v1 = tweepy.API(
        tweepy.OAuth1UserHandler(
            os.getenv("API_KEY"),
            os.getenv("API_SECRET"),
            os.getenv("ACCESS_TOKEN"),
            os.getenv("ACCESS_TOKEN_SECRET")
        )
    )
    print("✅ Tweepy v1.1 API initialized for media uploads")
except Exception as e:
    print(f"⚠️ Tweepy v1.1 API failed: {e}")
    twitter_api_v1 = None


# ---------------------------------------------------------------------------
# 2️⃣ STATE & MODELS
# ---------------------------------------------------------------------------
class Article(BaseModel):
    title: str
    description: str
    source: str
    author: Optional[str] = None
    url: str
    published_at: str
    image_url: Optional[str] = None
    priority_score: float = 0.0
    priority_reason: str = ""


class TweetResult(BaseModel):
    tweet_text: str
    tweet_id: Optional[str] = None
    tweet_url: Optional[str] = None
    success: bool = False
    error: Optional[str] = None


class GraphState(TypedDict, total=False):
    topic: str
    articles: List[Article]
    top_articles: List[Article]
    rewritten_tweets: List[str]
    auto_post: bool
    num_tweets_to_post: int
    tweet_results: List[TweetResult]


# ---------------------------------------------------------------------------
# 3️⃣ SCORING HELPERS
# ---------------------------------------------------------------------------
TRUSTED_SOURCES = {
    "BBC News": 10, "Reuters": 10, "Associated Press": 10, "The Guardian": 9,
    "CNN": 8, "The New York Times": 9, "Al Jazeera": 8, "The Washington Post": 9,
    "Bloomberg": 8, "CNBC": 7, "Financial Times": 9, "NPR": 8, "The Wall Street Journal": 9,
}

def calculate_recency_score(published_at: str) -> float:
    try:
        pub_date = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
        hours_old = (datetime.now(timezone.utc) - pub_date).total_seconds() / 3600
        if hours_old <= 6: return 10
        elif hours_old <= 24: return 8
        elif hours_old <= 48: return 6
        elif hours_old <= 168: return 4
        else: return 2
    except:
        return 3

def has_image_bonus(url: Optional[str]) -> float:
    return 2.0 if url else 0.0


# ---------------------------------------------------------------------------
# 4️⃣ NODES
# ---------------------------------------------------------------------------

# 🟩 Node 1: Fetch News (with topic + source logging)
async def fetch_news(state: GraphState) -> dict:
    topic = state.get("topic", "india")
    api_key = os.getenv("News_Api_Key")
    if not api_key:
        raise ValueError("Missing News_Api_Key in .env")

    url = f"https://newsapi.org/v2/everything?q={topic}&language=en&pageSize=20&sortBy=publishedAt&apiKey={api_key}"

    print(f"📰 Fetching top news for topic: {topic}")

    articles = []
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            for article in data.get("articles", []):
                if article.get("title"):
                    articles.append(Article(
                        title=article.get("title", ""),
                        description=article.get("description", ""),
                        source=article.get("source", {}).get("name", "Unknown"),
                        author=article.get("author"),
                        url=article.get("url", ""),
                        published_at=article.get("publishedAt", ""),
                        image_url=article.get("urlToImage")
                    ))

    print(f"✅ Total articles fetched: {len(articles)}")
    print(f"📍 Showing first 5 sources for topic '{topic}':")
    for i, art in enumerate(articles[:5], start=1):
        print(f"   {i}. {art.source} — {art.title[:80]}")

    return {"articles": articles}


# 🟨 Node 2: Prioritize
async def prioritize_articles(state: GraphState) -> dict:
    articles = state.get("articles", [])
    for article in articles:
        src_score = TRUSTED_SOURCES.get(article.source, 5)
        recency = calculate_recency_score(article.published_at)
        total = src_score + recency + has_image_bonus(article.image_url)
        article.priority_score = total
        article.priority_reason = f"source={src_score}, recency={recency}"
    sorted_articles = sorted(articles, key=lambda x: x.priority_score, reverse=True)
    top_articles = sorted_articles[:5]
    print(f"🏆 Selected top {len(top_articles)} articles")
    return {"top_articles": top_articles}


# 🟦 Node 3: Rewrite
async def rewrite_news(state: GraphState) -> dict:
    top_articles = state.get("top_articles", [])
    rewritten = []
    for article in top_articles:
        prompt = (
            "Write a factual, engaging tweet (max 250 characters, no URLs/markdown). "
            "Summarize the key point and make it eye-catching.\n\n"
            f"Title: {article.title}\nDescription: {article.description}\nSource: {article.source}"
        )
        output = await llm.ainvoke([
            SystemMessage("You are an expert journalist summarizing news for social media."),
            HumanMessage(prompt)
        ])
        tweet_text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', output.content.strip())
        rewritten.append(tweet_text[:250])
    print(f"✍️ Rewrote {len(rewritten)} tweets")
    return {"rewritten_tweets": rewritten}


# 🟥 Node 4: Post to Twitter (with image fallback and strict count)
async def post_to_twitter(state: GraphState) -> dict:
    tweets = state.get("rewritten_tweets", [])
    articles = state.get("top_articles", [])

    # ✅ Handle both string and bool for auto_post
    raw_auto_post = state.get("auto_post", False)
    if isinstance(raw_auto_post, str):
        auto_post = raw_auto_post.lower() == "true"
    else:
        auto_post = bool(raw_auto_post)

    num_to_post = int(state.get("num_tweets_to_post", 1))
    tweet_results = []

    if not auto_post:
        print("⚠️ Auto-post disabled — showing preview only")
        for t in tweets[:num_to_post]:
            tweet_results.append(TweetResult(tweet_text=t, success=False, error="Auto-post disabled"))
        return {"tweet_results": tweet_results}

    if not twitter_client or not twitter_api_v1:
        raise Exception("Twitter clients not initialized properly")

    print(f"🐦 Posting up to {num_to_post} tweets with image fallback...")

    # ✅ Strictly limit tweets and articles
    tweets_to_post = tweets[:num_to_post]
    articles_to_post = articles[:num_to_post]

    for i, (tweet, article) in enumerate(zip(tweets_to_post, articles_to_post), 1):
        full_tweet = f"{tweet}\n\n{article.url}"
        media_id = None

        # 🖼️ Try uploading image (fallback if fails)
        if article.image_url:
            try:
                resp = requests.get(article.image_url, timeout=10)
                if resp.status_code == 200:
                    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                        tmp.write(resp.content)
                        tmp.flush()
                        media = twitter_api_v1.media_upload(tmp.name)
                        media_id = media.media_id
                        print(f"🖼️ Uploaded image for tweet {i}")
                else:
                    print(f"⚠️ Image fetch failed ({resp.status_code}) for tweet {i}, using text-only fallback")
            except Exception as e:
                print(f"⚠️ Image upload failed for tweet {i}: {e}")

        # 🐦 Try posting the tweet (fallback to text-only if media fails)
        try:
            if media_id:
                resp = twitter_client.create_tweet(text=full_tweet, media_ids=[media_id])
                print(f"✅ Posted tweet {i} with image")
            else:
                resp = twitter_client.create_tweet(text=full_tweet)
                print(f"✅ Posted tweet {i} (text-only fallback)")

            tweet_id = resp.data["id"]
            tweet_url = f"https://x.com/user/status/{tweet_id}"
            tweet_results.append(TweetResult(
                tweet_text=full_tweet,
                tweet_id=tweet_id,
                tweet_url=tweet_url,
                success=True
            ))
        except Exception as e:
            tweet_results.append(TweetResult(
                tweet_text=full_tweet,
                success=False,
                error=str(e)
            ))
            print(f"❌ Error posting tweet {i}: {e}")

    return {"tweet_results": tweet_results}

# ---------------------------------------------------------------------------
# 5️⃣ BUILD THE GRAPH
# ---------------------------------------------------------------------------
builder = StateGraph(GraphState)
builder.add_node("fetch_news", fetch_news)
builder.add_node("prioritize_articles", prioritize_articles)
builder.add_node("rewrite_news", rewrite_news)
builder.add_node("post_to_twitter", post_to_twitter)

builder.add_edge(START, "fetch_news")
builder.add_edge("fetch_news", "prioritize_articles")
builder.add_edge("prioritize_articles", "rewrite_news")
builder.add_edge("rewrite_news", "post_to_twitter")
builder.add_edge("post_to_twitter", END)

graph = builder.compile()


# ---------------------------------------------------------------------------
# 6️⃣ ENTRYPOINT
# ---------------------------------------------------------------------------
async def main():
    topic = os.getenv("NEWS_TOPIC", "india")
    auto_post = os.getenv("AUTO_POST_TWEETS", "false").lower() == "true"
    num_tweets = int(os.getenv("NUM_TWEETS_TO_POST", "2"))
    print(f"🔍 Loaded NEWS_TOPIC from environment: {os.getenv('NEWS_TOPIC')}")
    print(f"🚀 Running news workflow for topic: {topic}")

    input_state = {
        "topic": topic,
        "articles": [],
        "top_articles": [],
        "rewritten_tweets": [],
        "auto_post": auto_post,
        "num_tweets_to_post": num_tweets,
        "tweet_results": []
    }

    print(f"🚀 Running news workflow for topic: {topic}")
    result = await graph.ainvoke(input_state)
    print("\n✅ Flow finished.")
    print(f"Tweets generated: {len(result['rewritten_tweets'])}")
    print(f"Tweets posted: {sum(1 for r in result['tweet_results'] if r.success)}")

if __name__ == "__main__":
    asyncio.run(main())
