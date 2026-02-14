from playwright.sync_api import sync_playwright
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

def get_overview_uuids_with_browser():
    date = get_belgium_date()
    url = f"https://www.humo.be/tv-gids/{date}/zenders" # De 'zenders' view laadt vaak meer data
    
    print(f"📡 Stap 1: Browser starten naar {url}...")
    
    tasks = []
    
    with sync_playwright() as p:
        # Start een onzichtbare browser (headless)
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            # Ga naar de pagina
            page.goto(url, timeout=60000)
            
            # Wacht even tot de grid geladen is (3 seconden)
            page.wait_for_timeout(3000)
            
            # Scroll naar beneden om lazy-loading te triggeren
            for _ in range(5):
                page.mouse.wheel(0, 1000)
                page.wait_for_timeout(500)

            # Zoek alle links die '/uitzending/' bevatten
            # Dit zijn de blokjes in de gids
            links = page.query_selector_all("a[href*='/uitzending/']")
            
            print(f"   -> {len(links)} links gevonden op de pagina.")
            
            for link in links:
                href = link.get_attribute("href")
                # href is vaak relatief, bv: /tv-gids/vtm/uitzending/film/b48a...
                
                # Filter op zenders
                if not any(k in href for k in ALLOWED_KEYWORDS):
                    continue
                
                # Haal UUID uit de URL
                # Formaat is meestal .../uitzending/type/UUID
                parts = href.split('/')
                uuid = parts[-1]
                
                # Bouw de volledige URL
                full_url = f"https://www.humo.be{href}"
                
                # Voeg toe aan takenlijst (gebruik een set om dubbels te voorkomen later)
                tasks.append((uuid, full_url))
                
        except Exception as e:
            print(f"❌ Browser fout: {e}")
        finally:
            browser.close()
            
    # Dubbels verwijderen (UUID is uniek)
    unique_tasks = list({t[0]: t for t in tasks}.values())
    return unique_tasks

def scrape_detail(task):
    uuid, url = task
    try:
        # Stap 2 doen we nog steeds met curl_cffi, dat is sneller dan 500x een browser openen
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
    print("🚀 Script gestart (Browser Mode)...")
    
    # STAP 1: Browser gebruiken om links te vinden
    tasks = get_overview_uuids_with_browser()
    
    if not tasks:
        print("❌ Geen programma's gevonden via de browser.")
        sys.exit(1)
        
    print(f"🔍 Stap 2: {len(tasks)} details scrapen...")
    
    results = {}
    
    # STAP 2: Details ophalen
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
