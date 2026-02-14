import cloudscraper
import json
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import pytz
import sys
import time

# --- CONFIGURATIE ---
# We gebruiken cloudscraper om de 403 blokkade te omzeilen
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

ALLOWED_KEYWORDS = [
    "vtm", "vrt", "canvas", "ketnet", "play", "npo", "bbc", "national", "discovery", "tlc"
]

def get_belgium_date():
    tz = pytz.timezone('Europe/Brussels')
    return datetime.now(tz).strftime("%Y-%m-%d")

def get_overview_uuids():
    date = get_belgium_date()
    url = f"https://www.humo.be/tv-gids/api/v2/broadcasts/{date}"
    
    print(f"📡 API Aanroepen: {url}")
    
    try:
        # Gebruik scraper.get() ipv requests.get()
        resp = scraper.get(url)
        
        if resp.status_code != 200:
            print(f"❌ API Fout: HTTP {resp.status_code} - {resp.reason}")
            # Als cloudscraper faalt, print de body om te zien waarom (vaak Cloudflare captcha)
            if resp.status_code == 403:
                print("⚠️ Nog steeds geblokkeerd. Probeer de User-Agent te tweaken.")
            return []
            
        data = resp.json()
        tasks = []
        
        if 'channels' not in data:
            print("❌ Geen 'channels' gevonden in API response.")
            return []

        print(f"✅ API geladen. Kanalen scannen...")
        
        for ch in data['channels']:
            name = ch.get('name', '').lower()
            slug = name.replace(' ', '-')
            
            if any(k in name for k in ALLOWED_KEYWORDS):
                broadcasts = ch.get('broadcasts', [])
                for b in broadcasts:
                    uuid = b.get('id')
                    url = f"https://www.humo.be/tv-gids/{slug}/uitzending/aflevering/{uuid}"
                    tasks.append((uuid, url))
        
        return tasks

    except Exception as e:
        print(f"❌ Fatale fout in overview: {e}")
        return []

def scrape_detail(task):
    uuid, url = task
    try:
        # Pauzeer heel even om de server niet te DDOS'en (helpt tegen blokkades)
        time.sleep(0.1) 
        
        resp = scraper.get(url, timeout=15)
        
        if resp.status_code == 404: return None
        if resp.status_code != 200: return None

        html = resp.text
        match = re.search(r'window\.__EPG_REDUX_DATA__=(.*?);', html)
        if not match: return None

        data = json.loads(match.group(1))
        details = data.get('details', {}).get(uuid, {})
        
        season = details.get('seasonOrder')
        episode = details.get('order')
        
        if season is None and episode is None: return None

        is_new = (episode == 1)
        texts_to_check = [
            details.get('subtitle', ''),
            details.get('alternativeDetailTitle', ''),
            details.get('synopsis', '')
        ]
        full_text = " ".join([t for t in texts_to_check if t]).lower()
        
        if "nieuw seizoen" in full_text or "start seizoen" in full_text:
            is_new = True

        return uuid, {
            "s": season,
            "ep": episode,
            "is_new": is_new
        }

    except Exception:
        return None

def main():
    print("🚀 Script gestart met Cloudscraper...")
    tasks = get_overview_uuids()
    
    if not tasks:
        print("❌ Geen taken gevonden. Stoppen.")
        sys.exit(1)
        
    print(f"🔍 {len(tasks)} detailpagina's scrapen...")
    
    results = {}
    # Iets minder workers om de server niet boos te maken
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = executor.map(scrape_detail, tasks)
        for res in futures:
            if res:
                results[res[0]] = res[1]

    print(f"💾 {len(results)} items succesvol verrijkt.")
    
    with open('tv-enrichment.json', 'w') as f:
        json.dump(results, f, separators=(',', ':'))

if __name__ == "__main__":
    main()
