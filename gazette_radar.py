print("⚙️ DEBUG: Python is successfully reading the file...")

import os
import re
import json
import requests
import urllib3
import time
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta


# Disable SSL warnings (common necessity for gov.in domains)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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
# 1. CONFIGURATION
# ==========================================
load_env_file()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

print("⚙️ DEBUG: Initializing Gemini Client...")
client = genai.Client(api_key=GEMINI_API_KEY)

COMPOSE_URL = "https://compose.kerala.gov.in/egazettelink1"

# ==========================================
# 2. DATA LOADING & AI SCHEMA
# ==========================================
def load_promises():
    """Loads promises directly from promises.json."""
    print("📂 Loading promises from promises.json...")
    try:
        with open('promises.json', 'r', encoding='utf-8') as f:
            promises = json.load(f)
            condensed = ""
            for p in promises:
                clean_promise = re.sub(r'\]+\]', '', p['promise']).strip()
                condensed += f"{p['id']} | {p['category']} | {clean_promise}\n"
            return condensed
    except FileNotFoundError:
        print("❌ promises.json not found in this folder.")
        return ""
    except Exception as e:
        print(f"❌ Error loading promises.json: {e}")
        return ""

class GazetteMatch(BaseModel):
    match_found: bool = Field(description="True if any of the gazette subjects officially fulfill a tracked promise.")
    promise_id: str = Field(description="The ID of the matched promise, e.g., UDF-004. Empty string if no match.")
    matched_subject: str = Field(description="The exact text of the Gazette Subject that matched.")
    matched_url: str = Field(description="The download URL associated with the matched subject.")

# ==========================================
# 3. SCRAPING & AI FUNCTIONS
# ==========================================
def analyze_subjects_with_gemini(subjects_list_text, promises_list):
    prompt = f"""
    You are a strict political auditor monitoring the Kerala UDF government.
    
    CRITICAL INSTRUCTION: You are analyzing a list of subjects from the latest Kerala Government Gazettes.
    Translate and analyze the text internally. 
    
    TASK:
    Do any of these Gazette Subjects indicate an official Government Order (GO) or enacted bill that strictly fulfills any of the specific tracked promises?
    (Note: A gazette notification is the highest level of proof. If it matches, it means the promise is 'Fulfilled').
    
    PROMISES TO TRACK:
    {promises_list}
    
    LATEST GAZETTE SUBJECTS:
    {subjects_list_text}
    
    If one of the subjects fulfills a promise, output the details. If none of the subjects match, set match_found to false.
    """

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=GazetteMatch,
            temperature=0.1
        )
    )
    return response.text

def send_telegram_alert(promise_id, subject_text, source_url):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    message = (
        f"🏛️ *GAZETTE MATCH FOUND!*\n\n"
        f"📌 *Promise ID:* {promise_id}\n"
        f"🚦 *New Status:* FULFILLED (Official Order Issued)\n"
        f"📝 *Subject:* {subject_text}\n\n"
        f"🔗 [Download/View Gazette PDF]({source_url})"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
        print("📲 Telegram alert sent!")
    except Exception as e:
        print(f"⚠️ Failed to send Telegram message: {e}")

# ==========================================
# 4. MAIN GAZETTE RADAR LOOP
# ==========================================
def run_gazette_radar():
    print("====================================")
    print("🏛️ STARTING COMPOSE GAZETTE RADAR...")
    print("====================================")
    
    promises_list = load_promises() 
    if not promises_list:
        return

    print("📡 Launching Browser to search Gazettes...")
    recent_gazettes = []
    
    try:
        with sync_playwright() as p:
            # Keep this headless=False while testing, change to True for server deployment
            browser = p.chromium.launch(headless=True) 
            page = browser.new_page()
            
            # STEP 1: Establish session to bypass security redirects
            print("📡 Establishing session at home page...")
            page.goto("https://compose.kerala.gov.in/home")
            page.wait_for_timeout(2000) 
            
            # STEP 2: Go to target Gazette page
            print("📡 Navigating to Gazette page...")
            page.goto(COMPOSE_URL)
            page.wait_for_timeout(2000)
            
            # STEP 3: Setup the 3-Day Lookback Window
            # Playwright requires YYYY-MM-DD for <input type="date">
            end_date_obj = datetime.now()
            start_date_obj = end_date_obj - timedelta(days=3)
            
            # Format for the Playwright filler (YYYY-MM-DD)
            end_date_iso = end_date_obj.strftime("%Y-%m-%d")
            start_date_iso = start_date_obj.strftime("%Y-%m-%d")
            
            # Format just for the print statement (DD-MM-YYYY)
            print_start = start_date_obj.strftime("%d-%m-%Y")
            print_end = end_date_obj.strftime("%d-%m-%Y")
            
            print(f"📡 Executing search for Gazettes from {print_start} to {print_end}...")
            
            # Target the date boxes
            date_inputs = page.get_by_placeholder("dd-mm-yyyy")
            
            # Fill From Date (3 days ago) using ISO format
            date_inputs.nth(0).fill(start_date_iso)
            # Fill To Date (Today) using ISO format
            date_inputs.nth(1).fill(end_date_iso)
            
            # Click the exact search button
            page.locator('a[onclick*="displaysearchresult"]').click()
            
            # 🛑 STEP 4: CRITICAL WAIT COMMAND
            print("⏳ Waiting for the results to populate...")
            page.wait_for_selector('table', timeout=15000) 
            page.wait_for_timeout(3000) # Give it 3 full seconds to let the JavaScript render the rows
            
            # STEP 5: Grab the final HTML
            soup = BeautifulSoup(page.content(), 'html.parser')
            browser.close()
            
            # Find EVERY table on the page, not just the first one
            all_tables = soup.find_all('table')
            print(f"⚙️ DEBUG: Found {len(all_tables)} tables in the HTML.")

            for t_idx, table in enumerate(all_tables):
                rows = table.find_all('tr')
                
                for row in rows:
                    cols = row.find_all('td')
                    
                    # If the row has at least 5 columns, it's our data table!
                    if len(cols) >= 5: 
                        dept = cols[3].get_text(strip=True)
                        subj = cols[4].get_text(strip=True)
                        
                        # Safely try to find the link tag
                        link_tag = None
                        if len(cols) > 5 and cols[5].find('a'):
                            link_tag = cols[5].find('a')
                        elif cols[4].find('a'):
                            link_tag = cols[4].find('a')
                            
                        pdf_link = link_tag['href'] if link_tag and link_tag.has_attr('href') else ""
                        
                        # Filter out empty rows or header rows
                        if "Subject" not in subj and len(subj) > 5:
                            recent_gazettes.append({
                                "department": dept,
                                "subject": subj,
                                "url": f"https://compose.kerala.gov.in{pdf_link}" if pdf_link.startswith('/') else pdf_link
                            })

        if not recent_gazettes:
            print("⚠️ No gazettes found for the given date range.")
            return

        print(f"✅ Extracted {len(recent_gazettes)} recent Gazette subjects.")
        
        subjects_for_ai = ""
        for idx, g in enumerate(recent_gazettes):
            subjects_for_ai += f"[{idx+1}] Dept: {g['department']} | Subject: {g['subject']}\n"
            
        print("🤖 Sending subjects to Gemini...")
        json_result = None
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                json_result = analyze_subjects_with_gemini(subjects_for_ai, promises_list)
                break  # If successful, break out of the retry loop!
                
            except Exception as e:
                error_msg = str(e)
                if "503" in error_msg or "UNAVAILABLE" in error_msg or "429" in error_msg:
                    print(f"⚠️ Gemini API busy (Attempt {attempt + 1}/{max_retries}). Waiting 15 seconds...")
                    time.sleep(15)
                    if attempt == max_retries - 1:
                        print("❌ Gemini API is completely jammed today. Shutting down gracefully.")
                        return # Exit the function, try again tomorrow
                else:
                    # If it's a different kind of error, print it and stop
                    print(f"❌ AI Analysis failed: {e}")
                    return
        
        # If the loop finished but json_result is still None, something went wrong
        if not json_result:
            return
        
        result_dict = json.loads(json_result)
        if result_dict.get("match_found"):
            print(f"\n🏆 MATCH FOUND: {result_dict.get('promise_id')}")
            send_telegram_alert(
                promise_id=result_dict.get('promise_id'),
                subject_text=result_dict.get('matched_subject'),
                source_url=result_dict.get('matched_url')
            )
        else:
            print("  -> AI Analysis: No tracked promises found in recent Gazettes.")

    except Exception as e:
        print(f"❌ Error during radar execution: {e}")

    print("\n🏁 Gazette Radar Scan Complete.")
    
# THIS IS THE CRITICAL BLOCK THAT TELLS PYTHON TO RUN THE CODE
if __name__ == "__main__":
    print("⚙️ DEBUG: Reached the main execution block.")
    run_gazette_radar()
