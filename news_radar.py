import os
import re
import json
import requests
import feedparser
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from google import genai
from google.genai import types


def load_env_file(env_path=".env"):
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key and key not in os.environ:
                os.environ[key] = value

# ==========================================
# 1. CONFIGURATION & KEYS
# ==========================================
load_env_file()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

client = genai.Client(api_key=GEMINI_API_KEY)

# ==========================================
# 2. RSS FEEDS — Google News via Inoreader
#
# Format:
#   https://news.google.com/rss/search?q=QUERY&hl=en-IN&gl=IN&ceid=IN:en
#
# Replace the q= value with your actual search query.
# Use + for spaces, quotes as %22 for exact phrases.
# ==========================================
RSS_FEEDS = {
    # --- CORE GOVERNMENT ACTIVITY ---
    "core_cm_satheeshan": (
        "https://news.google.com/news/rss/search?q=%22Kerala%20government%22%20%22V%20D%20Satheeshan%22&hl=en"
    ),


    "core_udf_government": (
        "https://news.google.com/news/rss/search?q=%22UDF%20government%22%20Kerala&hl=en"
    ),

    # --- KEY PROMISES (Indira Guarantee) ---
    "promise_indira_guarantee": (
        "https://news.google.com/news/rss/search?q=%22Indira%20Guarantee%22%20Kerala&hl=ml-IN&gl=IN&ceid=IN:ml"
    ),
    "promise_welfare_pension": (
        "https://news.google.com/news/rss/search?q=%22Indira%20Guarantee%22%20Kerala&hl=ml-IN&gl=IN&ceid=IN:ml"
    ),
    "promise_health_insurance": (
        "https://news.google.com/news/rss/search?q=%22Oommen%20Chandy%22%20health%20insurance%20Kerala&hl=ml-IN&gl=IN&ceid=IN:ml"
    ),
    "promise_housing": (
        "https://news.google.com/news/rss/search?q=%22housing%22%20five%20lakh%20Kerala%20UDF&hl=en-US&gl=US&ceid=US:en"
    ),
    "mission_samudra":(
        "https://news.google.com/news/rss/search?q=%22Mission%20Samudra%22%20Kerala&hl=ml-IN&gl=IN&ceid=IN:ml"
    ),
    "oomen_chandy_health_insurance": (
        "https://news.google.com/news/rss/search?q=%22Oommen%20Chandy%22%20health%20insurance%20Kerala&hl=ml-IN&gl=IN&ceid=IN:ml"
    ),

    # --- INFRASTRUCTURE & ECONOMY ---
    "promise_ksrtc": (
        "https://news.google.com/news/rss/search?q=%22KSRTC%22%20Kerala%20pension%20salary&hl=ml-IN&gl=IN&ceid=IN:ml"
    ),

    "promise_rubber_msp": (
        "https://news.google.com/news/rss/search?q=%22rubber%22%20support%20price%20Kerala&hl=ml-IN&gl=IN&ceid=IN:ml"
    ),

    # --- WELFARE & COMMUNITY ---

    "promise_disability": (
        "https://news.google.com/news/rss/search?q=%22rubber%22%20support%20price%20Kerala&hl=ml-IN&gl=IN&ceid=IN:ml"
    ),
    "promise_pravasi": (
        "https://news.google.com/news/rss/search?q=%22pravasi%20%22Kerala&hl=ml-IN&gl=IN&ceid=IN:ml"
    ),
    "promise_sabarimala": (
        "https://news.google.com/news/rss/search?q=%22Sabarimala%22%20Kerala%20government&hl=ml-IN&gl=IN&ceid=IN:ml"
    ),

    # --- TECH & STARTUPS ---
    "promise_it_startups": (
        "https://news.google.com/news/rss/search?q=%22technopark%22%20AND%20%22infopark%22&hl=en"
    ),
    "promise_ai_dept": (
        "https://news.google.com/news/rss/search?q=%22%20AI%20department%22%20Kerala&hl=ml-IN&gl=IN&ceid=IN:ml"
    ),


    # --- OFFICIAL SOURCES ---
    "source_pib_kerala": (
        "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3"
    ),
    "source_the_hindu_kerala": (
        "https://www.thehindu.com/news/states/kerala/feeder/default.rss"
    ),
    "source_indian_express_kerala": (
        "https://indianexpress.com/section/india/kerala/feed/"
    ),

    # --- MALAYALAM FEEDS ---
    "ml_satheeshan_govt": (
        "https://news.google.com/news/rss/search?q=%22Kerala%20government%22%20%22V%20D%20Satheeshan%22&hl=ml-IN&gl=IN&ceid=IN:ml"
    ),
}

# ==========================================
# 3. DATA LOADING
# Reads your promises.json directly.
# ==========================================
def load_promises():
    """Loads promises from promises.json and returns a condensed string for the AI."""
    print("📂 Loading promises from promises.json...")
    try:
        with open('promises.json', 'r', encoding='utf-8') as f:
            promises = json.load(f)

        # Remove [cite: xxxx] artifacts
        condensed = ""
        for p in promises:
            clean_promise = re.sub(r'\[cite:[^\]]+\]', '', p['promise']).strip()
            condensed += f"{p['id']} | {p['category']} | {clean_promise}\n"

        print(f"✅ Loaded {len(promises)} promises.")
        return condensed

    except FileNotFoundError:
        print("❌ promises.json not found. Make sure it's in the same folder as this script.")
        return ""
    except Exception as e:
        print(f"❌ Error loading promises.json: {e}")
        return ""

# ==========================================
# 4. AI SCHEMA
# ==========================================
class PromiseUpdate(BaseModel):
    match_found: bool = Field(
        description="True only if the article provides clear evidence of government action on a tracked promise."
    )
    promise_id: str = Field(
        description="The ID of the matched promise e.g. UDF-004. Empty string if no match."
    )
    proposed_status: str = Field(
        description="Must be exactly one of: 'In Progress', 'Fulfilled', 'Evaded'. Empty string if no match."
    )
    date_of_update: str = Field(
        description="Date of the event in DD MMM YYYY format. Empty string if no match."
    )
    update_description: str = Field(
        description="1-2 sentence factual summary of what happened. Empty string if no match."
    )
    source_quality: str = Field(
        description=(
            "Rate the source quality: "
            "'Tier1' (Gazette/GO), "
            "'Tier2' (Cabinet press release), "
            "'Tier3' (PTI/ANI in The Hindu/IE/BS/HT), "
            "'Insufficient' (social media, party website, opinion). "
            "Empty string if no match."
        )
    )

# ==========================================
# 5. SCRAPING
# ==========================================
def scrape_article_text(url):
    try:
        # allow_redirects=True is crucial for Google News links
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        soup = BeautifulSoup(response.content, 'html.parser')
        paragraphs = soup.find_all('p')
        text = " ".join([p.get_text() for p in paragraphs])
        return text[:5000]
    except Exception as e:
        print(f"  ⚠️  Could not scrape article: {e}")
        return None

# ==========================================
# 6. AI ANALYSIS
# ==========================================
def analyze_with_gemini(article_text, feed_category, promises_list):
    """Sends article text to Gemini and gets a structured promise match result."""
    prompt =f"""
    You are a political analyst monitoring the Kerala UDF government's performance against their manifesto.

    CONTEXT: This article came from a feed tracking '{feed_category}'.

    YOUR OBJECTIVE:
    Identify any news that signals meaningful government movement on the tracked promises. 
    You are looking for reports of administrative work, departmental initiatives, budget allocations, or formal declarations of policy.

    GUIDELINES:
    - "In Progress": The government has announced a plan, initiated a pilot project, or started administrative groundwork. (Includes official statements from Ministers or Cabinet).
    - "Fulfilled": Official Government Orders (GOs), passed bills, or confirmed on-ground implementation. 
    - "Evaded": Clear evidence that a promise has been deprioritized or countered by government action.

    PROMISES TO TRACK:
    {promises_list}

    ARTICLE TEXT:
    \"\"\"{article_text}\"\"\"

    TASK:
    Analyze the article. If it indicates significant movement or intent toward a promise, set 'match_found' to true. 
    Do not be overly restrictive—if the source is a credible news outlet reporting on government activity, include it.
    If no relevant movement is mentioned, set 'match_found' to false.
    """

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=PromiseUpdate,
            temperature=0.1
        )
    )
    return response.text

# ==========================================
# 7. TELEGRAM NOTIFICATION
# ==========================================
def send_telegram_alert(promise_id, status, description, source_url, source_quality):
    """Sends a push notification to your Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  🔔 Telegram skipped (no token set).")
        return

    emoji = {"Fulfilled": "✅", "In Progress": "🔄", "Evaded": "❌"}.get(status, "🚨")
    quality_emoji = {"Tier1": "🏆", "Tier2": "✔️", "Tier3": "📰", "Insufficient": "⚠️"}.get(source_quality, "")

    message = (
        f"{emoji} *UDF Tracker Alert*\n\n"
        f"📌 *Promise:* `{promise_id}`\n"
        f"🚦 *Status:* {status}\n"
        f"{quality_emoji} *Source Quality:* {source_quality}\n"
        f"📝 {description}\n\n"
        f"🔗 [Read Article]({source_url})"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }

    try:
        requests.post(url, json=payload, timeout=10)
        print("  📲 Telegram alert sent!")
    except Exception as e:
        print(f"  ⚠️  Telegram failed: {e}")

# ==========================================
# 8. SEEN ARTICLES CACHE
# Prevents the same article being analyzed twice.
# ==========================================
CACHE_FILE = "seen_articles.json"

def load_seen():
    try:
        with open(CACHE_FILE, 'r') as f:
            return set(json.load(f))
    except:
        return set()

def save_seen(seen):
    with open(CACHE_FILE, 'w') as f:
        json.dump(list(seen), f)

# ==========================================
# 9. MAIN RADAR LOOP
# ==========================================
def run_radar():
    print("=" * 50)
    print("📡  UDF KERALA PROMISE RADAR")
    print("=" * 50)

    promises_list = load_promises()
    if not promises_list:
        print("Stopping — no promises loaded.")
        return

    seen_articles = load_seen()
    new_matches = []

    for category, feed_url in RSS_FEEDS.items():
        print(f"\n🔍 [{category}]")
        feed = feedparser.parse(feed_url)

        if not feed.entries:
            print("  → No articles found in feed.")
            continue

        # Check latest 3 articles per feed
        for article in feed.entries[:3]:
            article_url = article.get('link', '')
            article_title = article.get('title', 'No title')

            # Skip if already seen
            if article_url in seen_articles:
                print(f"  ⏭  Already seen: {article_title[:60]}")
                continue

            print(f"  📰 Analyzing: {article_title[:70]}")
            article_text = scrape_article_text(article_url)

            if not article_text:
                seen_articles.add(article_url)
                continue

            json_result = analyze_with_gemini(article_text, category, promises_list)

            try:
                result = json.loads(json_result)

                if result.get("match_found"):
                    # Skip if source quality is insufficient
                    if result.get("source_quality") == "Insufficient":
                        print(f"  ⚠️  Match found but source quality insufficient — skipping.")
                        seen_articles.add(article_url)
                        continue

                    print(f"\n  ✅ MATCH: {result['promise_id']}")
                    print(f"     Status:  {result['proposed_status']}")
                    print(f"     Quality: {result['source_quality']}")
                    print(f"     Note:    {result['update_description']}")

                    new_matches.append({
                        "promise_id":   result['promise_id'],
                        "status":       result['proposed_status'],
                        "description":  result['update_description'],
                        "date":         result['date_of_update'],
                        "source_url":   article_url,
                        "source_quality": result['source_quality'],
                        "feed":         category,
                    })

                    send_telegram_alert(
                        promise_id=result['promise_id'],
                        status=result['proposed_status'],
                        description=result['update_description'],
                        source_url=article_url,
                        source_quality=result['source_quality']
                    )
                else:
                    print("  → Not relevant to any tracked promise.")

            except Exception as e:
                print(f"  ⚠️  Could not parse Gemini response: {e}")

            seen_articles.add(article_url)

    # Save cache
    save_seen(seen_articles)

    # Save matches log
    if new_matches:
        log_file = "matches_log.json"
        existing = []
        try:
            with open(log_file, 'r') as f:
                existing = json.load(f)
        except:
            pass
        existing.extend(new_matches)
        with open(log_file, 'w') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        print(f"\n💾 {len(new_matches)} new match(es) saved to {log_file}")
    else:
        print("\n🏁 Scan complete. No new matches found.")

    print("=" * 50)

if __name__ == "__main__":
    run_radar()