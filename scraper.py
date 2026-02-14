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

# Hier slaan we de onderschepte data in op
captured_uuids = []

def handle_response(response):
    """Luistert naar netwerkverkeer en pakt de API json"""
    try:
        # We zoeken naar responses van de broadcasts API
        if "api/v2/broadcasts" in response.url and response.status == 200:
            print(f"📡 API Response onderschept: {response.url}")
            try:
                data = response.json()
                
                if 'channels' in data:
                    print(f"   -> JSON bevat {len(data['channels'])} kanalen. Parsen...")
                    
                    for ch in data['channels']:
                        name = ch.get('name', '').lower()
                        slug = name.replace(' ', '-')
                        
                        # Filter op zenders
                        if any(k in name for k in ALLOWED_KEYWORDS):
                            broadcasts = ch.get('broadcasts', [])
                            for b in broadcasts:
                                uuid = b.get('id')
                                # Bouw de URL voor stap 2
                                url = f"https://www.humo.be/tv-gids/{slug}/uitzending/aflevering/{uuid}"
                                captured_uuids.append((uuid, url))
            except:
                pass # Geen JSON of parse error
    except:
        pass

def get_uuids_via_network_sniffing():
    url = "https://www.humo.be/tv-gids"
    print(f"📡 Stap 1: Browser starten en luisteren naar API verkeer...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        
        # ACTIVEER DE "SNIFFER"
        page.on("response", handle_response)
        
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            print("   -> Pagina aan het laden...")
            
            # Wacht even en accepteer cookies (zodat de API call zeker vertrekt)
            try:
                page.wait_for_timeout(2000)
                btn = page.get_by_role("button", name="Akkoord")
                if btn.is_visible():
                    btn.click()
                    print("   -> 🍪 Cookies geaccepteerd")
                    page.wait_for_timeout(2000)
            except: pass
            
            # Scrollen is vaak nodig om de API call te triggeren
            print("   -> Scrollen om data te forceren...")
            for _ in range(5):
                page.mouse.wheel(0, 1000)
                page.wait_for_timeout(1000)
            
            # Als we nog geen data hebben, klik op 'Nu & Straks' om een refresh te forceren
            if len(captured_uuids) == 0:
                print("   -> Nog geen data, we klikken op 'Zenders'...")
                try:
                    page.goto("https://www.humo.be/tv-gids/zenders", timeout=30000)
                    page.wait_for_timeout(4000)
                except: pass

        except Exception as e:
            print(f"❌ Browser fout: {e}")
        finally:
            browser.close()
            
    # Uniek maken
    unique_tasks = list({t[0]: t for t in captured_uuids}.values())
    return unique_tasks

def scrape_detail(task):
    uuid, url = task
    try:
        # Stap 2 blijft via curl_cffi (snel en efficiënt)
        resp = requests.get(url, impersonate="chrome110", timeout=20)
        
        if resp.status_code != 200: return None

        html = resp.text
        match = re.search(r'window\.__EPG_REDUX_DATA__=(.*?);', html)
        if not match: return None

        data = json.loads(match.group(1))
        details_map = data.get('details', {})
        details = details_map.get(uuid, {})
        
        if not details and len(details_map) == 1:
             details = list(details_map.values())[0]

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
    print("🚀 Script gestart (Network Sniffer Mode)...")
    
    tasks = get_uuids_via_network_sniffing()
    
    if not tasks:
        print("❌ Geen API data onderschept. Humo heeft iets veranderd.")
        sys.exit(1)
        
    print(f"🔍 Stap 2: {len(tasks)} details scrapen...")
    
    results = {}
    
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
