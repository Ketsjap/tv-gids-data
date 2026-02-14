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
    url = "https://www.humo.be/tv-gids"
    print(f"📡 Stap 1: Browser starten naar {url}...")
    
    tasks = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            print("   -> Pagina geladen. Wachten op banner...")
            page.wait_for_timeout(3000)

            # 🍪 COOKIE HUNTER
            clicked = False
            try:
                # Probeer 'Akkoord' knop
                btn = page.locator("button, a").filter(has_text=re.compile("(?i)^Akkoord$"))
                if btn.count() > 0 and btn.first.is_visible():
                    btn.first.click()
                    print("   -> 🍪 'Akkoord' geklikt!")
                    clicked = True
            except: pass
            
            if not clicked:
                # Fallback: iframes
                for frame in page.frames:
                    try:
                        btn = frame.locator("button, a").filter(has_text=re.compile("(?i)^Akkoord$"))
                        if btn.count() > 0 and btn.first.is_visible():
                            btn.first.click()
                            print(f"   -> 🍪 'Akkoord' geklikt in iframe!")
                            clicked = True
                            break
                    except: continue

            if clicked:
                page.wait_for_timeout(3000)

            # Screenshot ter controle
            page.screenshot(path="debug_grid.png", full_page=True)

            print("   -> Scrollen door de gids...")
            # Iets agressiever scrollen om alles te laden
            for _ in range(8):
                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(800)
            
            # 🔥 NIEUWE STRATEGIE: Pak ALLE links, filter later
            # We kijken specifiek naar links die een 'href' hebben
            links = page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a[href]')).map(a => a.href)
            }""")
            
            print(f"   -> {len(links)} totale links gevonden. Nu filteren...")
            
            for href in links:
                # Moet een Humo link zijn en een van onze zenders bevatten
                if "humo.be" not in href: continue
                
                # Check zender
                if not any(k in href for k in ALLOWED_KEYWORDS): continue
                
                # Check of het een programma-link is
                # Humo gebruikt soms /tv-gids/.../uitzending/... en soms /tv-gids/programma/...
                if "/uitzending/" in href or "/programma/" in href:
                    
                    # UUID extractie: pak het laatste deel dat geen lege string is
                    parts = [p for p in href.split('/') if p]
                    uuid = parts[-1]
                    
                    # UUID is meestal lang (hash) of numeriek ID
                    if len(uuid) > 5:
                         tasks.append((uuid, href))
                
        except Exception as e:
            print(f"❌ Browser fout: {e}")
        finally:
            browser.close()
            
    # Uniek maken
    unique_tasks = list({t[0]: t for t in tasks}.values())
    return unique_tasks

def scrape_detail(task):
    uuid, url = task
    try:
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
    print("🚀 Script gestart (Link Harvest Mode)...")
    
    tasks = get_overview_uuids_with_browser()
    
    if not tasks:
        print("❌ Geen TV-programma's gevonden. Bekijk 'debug_grid.png'.")
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
