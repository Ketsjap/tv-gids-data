import requests
import json
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import pytz
import sys

# --- CONFIGURATIE ---
# Gebruik een echte User-Agent om niet geblokkeerd te worden
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# De kanalen die we willen (fuzzy match)
ALLOWED_KEYWORDS = [
    "vtm", "vrt", "canvas", "ketnet", "play", "npo", "bbc", "national", "discovery", "tlc"
]

def get_belgium_date():
    """Haalt de huidige datum in België op (belangrijk voor GitHub servers!)"""
    tz = pytz.timezone('Europe/Brussels')
    return datetime.now(tz).strftime("%Y-%m-%d")

def get_overview_uuids():
    date = get_belgium_date()
    url = f"https://www.humo.be/tv-gids/api/v2/broadcasts/{date}"
    
    print(f"📡 API Aanroepen: {url}")
    
    try:
        resp = requests.get(url, headers=HEADERS)
        if resp.status_code != 200:
            print(f"❌ API Fout: HTTP {resp.status_code}")
            return []
            
        data = resp.json()
        tasks = []
        
        if 'channels' not in data:
            print("❌ Geen 'channels' gevonden in API response.")
            return []

        print(f"✅ API geladen. Kanalen scannen...")
        
        for ch in data['channels']:
            name = ch.get('name', '').lower()
            slug = name.replace(' ', '-') # Maak URL vriendelijk
            
            # Check of dit een kanaal is dat we willen
            if any(k in name for k in ALLOWED_KEYWORDS):
                broadcasts = ch.get('broadcasts', [])
                count = len(broadcasts)
                # print(f"   -> {name}: {count} uitzendingen") # Uncomment voor debug
                
                for b in broadcasts:
                    uuid = b.get('id')
                    # Bouw URL (Humo structuur)
                    url = f"https://www.humo.be/tv-gids/{slug}/uitzending/aflevering/{uuid}"
                    tasks.append((uuid, url))
        
        return tasks

    except Exception as e:
        print(f"❌ Fatale fout in overview: {e}")
        return []

def scrape_detail(task):
    uuid, url = task
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        
        # 404 is normaal (niet elke uuid heeft een detailpagina)
        if resp.status_code == 404:
            return None
        
        # Andere fouten zijn wel interessant
        if resp.status_code != 200:
            print(f"⚠️ {url} -> HTTP {resp.status_code}")
            return None

        html = resp.text
        
        # Regex zoektocht
        match = re.search(r'window\.__EPG_REDUX_DATA__=(.*?);', html)
        if not match:
            # Soms is de pagina wel geladen, maar staat de data anders
            return None

        # JSON parsen
        data = json.loads(match.group(1))
        
        # De data zit in 'details' -> uuid
        details = data.get('details', {}).get(uuid, {})
        
        season = details.get('seasonOrder')
        episode = details.get('order')
        
        # Alleen opslaan als we nuttige info hebben
        if season is None and episode is None:
            return None

        # Slimme "Nieuw Seizoen" detectie
        is_new = (episode == 1)
        
        # Check ook tekstuele hints
        texts_to_check = [
            details.get('subtitle', ''),
            details.get('alternativeDetailTitle', ''),
            details.get('synopsis', '') # Soms staat het in de synopsis
        ]
        full_text = " ".join([t for t in texts_to_check if t]).lower()
        
        if "nieuw seizoen" in full_text or "start seizoen" in full_text:
            is_new = True

        return uuid, {
            "s": season,
            "ep": episode,
            "is_new": is_new
        }

    except Exception as e:
        # print(f"⚠️ Error scraping {url}: {e}")
        return None

def main():
    print("🚀 Script gestart...")
    tasks = get_overview_uuids()
    
    if not tasks:
        print("❌ Geen taken gevonden. Stoppen.")
        sys.exit(1) # Forceer een error in GitHub Actions zodat je een rode mail krijgt
        
    print(f"🔍 {len(tasks)} detailpagina's scrapen (max 20 tegelijk)...")
    
    results = {}
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = executor.map(scrape_detail, tasks)
        for res in futures:
            if res:
                results[res[0]] = res[1]

    print(f"💾 {len(results)} items succesvol verrijkt.")
    
    # Opslaan
    with open('tv-enrichment.json', 'w') as f:
        json.dump(results, f, separators=(',', ':'))

if __name__ == "__main__":
    main()
