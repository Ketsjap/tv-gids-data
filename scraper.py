from playwright.sync_api import sync_playwright
from curl_cffi import requests
import json
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import pytz
import sys
import time
import os

# --- CONFIGURATIE ---
ALLOWED_KEYWORDS = [
    "vtm", "vrt", "canvas", "ketnet", "play", "npo", "bbc", "national", "discovery", "tlc"
]

def get_belgium_date():
    tz = pytz.timezone('Europe/Brussels')
    return datetime.now(tz).strftime("%Y-%m-%d")

def get_overview_uuids_with_browser():
    date = get_belgium_date()
    # We gaan naar de hoofdpagina, dat is vaak stabieler
    url = f"https://www.humo.be/tv-gids/{date}"
    
    print(f"📡 Stap 1: Browser starten naar {url}...")
    
    tasks = []
    
    with sync_playwright() as p:
        # Launch options: Headless, maar met specifieke args om detectie te verminderen
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080}, # Groot scherm simuleren
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.new_page()
        
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            print("   -> Pagina geladen. Zoeken naar cookie banner...")

            # 🍪 PROBEER COOKIES TE ACCEPTEREN
            try:
                # DPG Media gebruikt vaak een iframe of shadow dom, of gewoon buttons
                # We proberen een paar generieke selectors
                accept_button = page.get_by_role("button", name="Alles accepteren")
                if accept_button.is_visible():
                    accept_button.click()
                    print("   -> 🍪 Cookies geaccepteerd!")
                    page.wait_for_timeout(2000) # Even wachten op reload
                else:
                    # Soms is het 'Akkoord' of 'Verdergaan'
                    page.locator("button:has-text('aanvaarden')").click(timeout=2000)
                    print("   -> 🍪 Cookies (alt) geaccepteerd!")
            except:
                print("   -> Geen cookie banner gevonden (of timeout). We gaan door.")

            # Scrollen om lazy loading te triggeren
            print("   -> Scrollen...")
            for _ in range(5):
                page.mouse.wheel(0, 1000)
                page.wait_for_timeout(1000)
            
            # MAAK SCREENSHOT VOOR DEBUGGING (wordt geupload naar GitHub)
            page.screenshot(path="debug_page.png", full_page=True)
            print("   -> 📸 Screenshot gemaakt (debug_page.png)")

            # Zoek links. De selector is iets breder gemaakt.
            # We zoeken naar links die '/uitzending/' of '/programma/' bevatten
            links = page.locator("a[href*='/tv-gids/']").all()
            
            print(f"   -> {len(links)} ruwe links gevonden. Filteren...")
            
            for link in links:
                try:
                    href = link.get_attribute("href")
                    if not href: continue
                    
                    # Filter op onze zenders
                    if not any(k in href for k in ALLOWED_KEYWORDS):
                        continue
                        
                    # We willen alleen detail links, geen navigatie links
                    if "/uitzending/" in href or "/programma/" in href:
                         # UUID eruit vissen (laatste deel van URL)
                         parts = href.split('/')
                         # Soms eindigt het op een slash
                         uuid = parts[-1] if parts[-1] else parts[-2]
                         
                         # Check of het eruit ziet als een UUID of ID (lange string of cijfers)
                         if len(uuid) > 5:
                             full_url = f"https://www.humo.be{href}"
                             tasks.append((uuid, full_url))
                except:
                    continue
                
        except Exception as e:
            print(f"❌ Browser fout: {e}")
            page.screenshot(path="error_page.png")
        finally:
            browser.close()
            
    # Unieke taken overhouden
    unique_tasks = list({t[0]: t for t in tasks}.values())
    return unique_tasks

def scrape_detail(task):
    uuid, url = task
    try:
        # We gebruiken requests met impersonate voor de details (sneller)
        resp = requests.get(url, impersonate="chrome110", timeout=20)
        
        if resp.status_code != 200: return None

        html = resp.text
        match = re.search(r'window\.__EPG_REDUX_DATA__=(.*?);', html)
        if not match: return None

        data = json.loads(match.group(1))
        # Soms zit het direct in details, soms moeten we zoeken
        details_map = data.get('details', {})
        details = details_map.get(uuid, {})
        
        # Als we niets vinden, check of de UUID misschien anders is in de map
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
    print("🚀 Script gestart (Browser + Cookie Fix)...")
    
    tasks = get_overview_uuids_with_browser()
    
    if not tasks:
        print("❌ Nog steeds 0 programma's. Check de screenshot in GitHub Actions Artifacts!")
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
