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
    # 🔥 VERANDERING: We roepen niet de API aan, maar de menselijke HTML pagina
    url = f"https://www.humo.be/tv-gids/{date}"
    
    print(f"📡 Stap 1: HTML Pagina ophalen: {url}...")
    
    try:
        # Headers om echt op een browser te lijken
        headers = {
            "Referer": "https://www.humo.be/tv-gids",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        }
        
        # Impersonate Chrome 110 (iets ouder, vaak stabieler)
        resp = requests.get(url, headers=headers, impersonate="chrome110", timeout=30)
        
        if resp.status_code != 200:
            print(f"❌ Fout in Stap 1: HTTP {resp.status_code}")
            return []

        # Nu vissen we de JSON uit de HTML, net zoals bij de details
        html = resp.text
        match = re.search(r'window\.__EPG_REDUX_DATA__=(.*?);', html)
        if not match:
            print("❌ Kon de Redux data niet vinden in de overzichtspagina.")
            return []
            
        data = json.loads(match.group(1))
        tasks = []
        
        # De structuur in de HTML Redux state kan iets anders zijn dan de API
        # We zoeken naar 'channels' in de root of onder 'tvGuide'
        channels = data.get('channels') or data.get('tvGuide', {}).get('channels')
        
        if not channels:
            # Soms zit het dieper verpakt
            print("⚠️ Structuur anders dan verwacht, zoeken in hele JSON...")
            # Fallback: zoek gewoon ergens naar een lijst die op kanalen lijkt
            pass 

        if channels:
            print(f"✅ Stap 1 gelukt. {len(channels)} kanalen gevonden.")
            for ch in channels:
                name = ch.get('name', '').lower()
                slug = name.replace(' ', '-')
                
                if any(k in name for k in ALLOWED_KEYWORDS):
                    broadcasts = ch.get('broadcasts', [])
                    for b in broadcasts:
                        uuid = b.get('id')
                        # URL bouwen voor Stap 2
                        url = f"https://www.humo.be/tv-gids/{slug}/uitzending/aflevering/{uuid}"
                        tasks.append((uuid, url))
        else:
            print("❌ Geen kanalen gevonden in de JSON.")
            return []
        
        return tasks

    except Exception as e:
        print(f"❌ Fatale fout in Stap 1: {e}")
        return []

def scrape_detail(task):
    uuid, url = task
    try:
        # Stap 2 blijft hetzelfde
        resp = requests.get(url, impersonate="chrome110", timeout=20)
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
    print("🚀 Script gestart (HTML Scrape Mode)...")
    
    tasks = get_overview_uuids()
    
    if not tasks:
        print("❌ Mislukt. Geen programma's gevonden.")
        sys.exit(1)
        
    print(f"🔍 Stap 2: {len(tasks)} details scrapen...")
    
    results = {}
    
    # Iets conservatiever: 8 threads
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = executor.map(scrape_detail, tasks)
        for res in futures:
            if res:
                results[res[0]] = res[1]

    print(f"💾 Klaar! {len(results)} items verrijkt.")
    
    with open('tv-enrichment.json', 'w') as f:
        json.dump(results, f, separators=(',', ':'))

if __name__ == "__main__":
    main()
