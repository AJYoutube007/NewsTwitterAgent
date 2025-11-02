**NewsTwitterAgent Using LangGraph & UiPath SDK**

**Overview**
This application is an automated news aggregation and Twitter posting system built with LangGraph. It fetches recent news articles on a specified topic, prioritizes them based on source credibility and recency, generates engaging tweet summaries using AI, and optionally posts them to Twitter with images.

🏁 START 
   ↓
📰 Fetch News 
   ↓
🏆 Prioritize Articles 
   ↓
✍️ Rewrite News 
   ↓
🐦 Post to Twitter 
   ↓
✅ END

**Inital Configuration**

1. Go to https://newsapi.org/ & Create the API for News Gathering
2. Go to https://developer.x.com/en/docs/x-api for creating the API for Twitter

**Prerequisites**

Required Python Packages

```bash
    pip install langgraph pydantic uipath-langchain tweepy aiohttp requests python-dotenv newsapi-python
```

**Environment Variables**
Create a .env file with the following credentials:

```bash
# NewsAPI Configuration
News_Api_Key=your_newsapi_key_here

# Twitter API v1.1 and v2 Credentials
BEARER_TOKEN=your_bearer_token
API_KEY=your_api_key
API_SECRET=your_api_secret
ACCESS_TOKEN=your_access_token
ACCESS_TOKEN_SECRET=your_access_token_secret

# Workflow Configuration
NEWS_TOPIC=india                    # Topic to search for
AUTO_POST_TWEETS=false             # Set to 'true' to enable posting
NUM_TWEETS_TO_POST=2               # Number of tweets to post (1-5)
```

**WorkFlow**
<img width="2774" height="6563" alt="Untitled diagram-2025-11-02-054859" src="https://github.com/user-attachments/assets/deb3e5c2-ad02-4112-a9e5-72246f578a31" />

🧩 Components

1️⃣ **Graph State Management**

GraphState (TypedDict) keeps track of:

🧵 topic – Current topic for search
📰 articles – Raw news data
🏆 top_articles – Best 5 articles by score
✍️ rewritten_tweets – AI-generated tweet text
🐦 auto_post – Post or preview mode
🔢 num_tweets_to_post – Number of tweets to create
📊 tweet_results – Posting outcome details

2️⃣ **Workflow Nodes**:---------------

📰** Fetch News**

🟢Function: fetch_news(state: GraphState)
🟢Fetches up to 20 articles via NewsAPI
🟢Extracts metadata (title, description, source, URL, image, etc.)
🟢Logs first 5 sources for sanity check

Output: Populates articles

🏆 **Prioritize Articles:**

Function: prioritize_articles(state: GraphState)

Scoring is based on:
⭐ Source Credibility (0–10)
⏱️ Recency (2–10)
🖼️ Image Bonus (+2)
Output: Selects top 5 articles

✍️ **Rewrite News**

🟢Function: rewrite_news(state: GraphState)
🟢Uses GPT via UiPath LangChain
🟢Converts headlines to short, tweetable versions
🟢Removes URLs & markdown
🟢Keeps tone factual yet catchy

**Prompt Goal:**
“Write an engaging, factual tweet under 250 characters, no URLs or markdown.”
Output: rewritten_tweets

🐦 **Post to Twitter**

🟢Function: post_to_twitter(state: GraphState)
🟢Uploads article images via Tweepy v1.1
🟢Posts tweets using Tweepy v2
🟢Handles fallbacks & errors gracefully

✅ **Safety Features:**
Preview mode (AUTO_POST_TWEETS=false)
Strict control on number of tweets
Error logging for every failure

Installation

1️⃣ Clone the Repository
```bash
    pip install langgraph pydantic uipath-langchain tweepy aiohttp requests python-dotenv newsapi-python
```

