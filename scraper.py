from curl_cffi import requests
import json
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import pytz
import sys
import time

# --- CONFIGURATIE ---
ALLOWED_KEYWORDS = [
    "vtm", "vrt", "canvas", "ketnet", "play", "npo", "bbc", "national", "discovery", "tlc"
]

def get_belgium_date():
    tz = pytz.timezone('Europe/Brussels')
    return datetime.now(tz).strftime("%Y-%m-%d")

def get_overview_uuids():
    date = get_belgium_date()
    url = f"https://www.humo.be/tv-gids/api/v2/broadcasts/{date}"
    
    print(f"📡 Stap 1: Overzicht ophalen voor {date}...")
    
    try:
        # We doen ons voor als Chrome 120
        resp = requests.get(url, impersonate="chrome120", timeout=30)
        
        if resp.status_code != 200:
            print(f"❌ API Fout in Stap 1: HTTP {resp.status_code}")
            return []
            
        data = resp.json()
        tasks = []
        
        if 'channels' not in data:
            print("❌ Geen kanalen gevonden in de data.")
            return []

        print(f"✅ Stap 1 gelukt. UUID's verzamelen...")
        
        for ch in data['channels']:
            name = ch.get('name', '').lower()
            slug = name.replace(' ', '-')
            
            if any(k in name for k in ALLOWED_KEYWORDS):
                broadcasts = ch.get('broadcasts', [])
                for b in broadcasts:
                    uuid = b.get('id')
                    # We hebben de detail URL nodig voor Stap 2
                    url = f"https://www.humo.be/tv-gids/{slug}/uitzending/aflevering/{uuid}"
                    tasks.append((uuid, url))
        
        return tasks

    except Exception as e:
        print(f"❌ Fatale fout in Stap 1: {e}")
        return []

def scrape_detail(task):
    uuid, url = task
    try:
        # Ook hier doen we ons voor als Chrome
        # Timeout iets langer zetten voor tragere connecties
        resp = requests.get(url, impersonate="chrome120", timeout=20)
        
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
        
        # Tekstuele check
        texts = [
            details.get('subtitle', ''),
            details.get('alternativeDetailTitle', ''),
            details.get('synopsis', '')
        ]
        full_text = " ".join([t for t in texts if t]).lower()
        
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
    print("🚀 Script gestart (versie: curl_cffi)...")
    
    # STAP 1: Haal de lijst met UUID's
    tasks = get_overview_uuids()
    
    if not tasks:
        print("❌ Kon de lijst met programma's niet ophalen. Waarschijnlijk nog steeds geblokkeerd.")
        sys.exit(1)
        
    print(f"🔍 Stap 2: {len(tasks)} details scrapen (via Chrome vermomming)...")
    
    results = {}
    
    # STAP 2: Scrape details per UUID
    # We gebruiken 10 threads om niet te agressief te zijn
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = executor.map(scrape_detail, tasks)
        for res in futures:
            if res:
                results[res[0]] = res[1]

    print(f"💾 Klaar! {len(results)} items verrijkt.")
    
    with open('tv-enrichment.json', 'w') as f:
        json.dump(results, f, separators=(',', ':'))

if __name__ == "__main__":
    main()
