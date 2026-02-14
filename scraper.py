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
    # We gaan naar de zenders-specifieke pagina, die laadt soms beter
    url = f"https://www.humo.be/tv-gids/{date}/zenders"
    
    print(f"📡 Stap 1: Browser starten naar {url}...")
    
    tasks = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # We zetten een grote viewport zodat de knop zeker in beeld is
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            print("   -> Pagina geladen. Wachten op cookie banner...")
            
            # Wacht even expliciet tot de overlay er is
            page.wait_for_timeout(3000)

            # 🍪 COOKIE FIX VOOR DE SCREENSHOT
            try:
                # We zoeken naar de knop met tekst "Akkoord" (ongeacht hoofdletters)
                # We klikken op de eerste die we vinden die zichtbaar is
                accept_button = page.locator("button", has_text=re.compile("(?i)akkoord"))
                
                if accept_button.count() > 0 and accept_button.first.is_visible():
                    print("   -> 🍪 'Akkoord' knop gevonden! Klikken...")
                    accept_button.first.click()
                    page.wait_for_timeout(3000) # Wachten tot banner weg is
                else:
                    print("   -> ⚠️ Geen 'Akkoord' knop gevonden. We proberen de frames...")
                    # Soms zit DPG in een iframe
                    for frame in page.frames:
                        btn = frame.locator("button", has_text=re.compile("(?i)akkoord"))
                        if btn.count() > 0 and btn.first.is_visible():
                            print("   -> 🍪 'Akkoord' gevonden in iframe! Klikken...")
                            btn.first.click()
                            page.wait_for_timeout(3000)
                            break
            except Exception as e:
                print(f"   -> Fout bij klikken cookies: {e}")

            # Even checken of we erdoor zijn door een screenshot te maken (overschrijft de oude)
            page.screenshot(path="debug_after_click.png", full_page=True)

            # Scrollen om lazy loading te triggeren (Humo laadt pas als je scrollt)
            print("   -> Scrollen door de gids...")
            for _ in range(5):
                page.mouse.wheel(0, 1000)
                page.wait_for_timeout(1000)
            
            # Zoek links
            # We zoeken specifiek naar links die naar een detailpagina leiden
            links = page.locator("a[href*='/uitzending/'], a[href*='/programma/']").all()
            
            print(f"   -> {len(links)} links gevonden op de pagina.")
            
            for link in links:
                try:
                    href = link.get_attribute("href")
                    if not href: continue
                    
                    if not any(k in href for k in ALLOWED_KEYWORDS):
                        continue
                        
                    parts = href.split('/')
                    # Pak het laatste deel dat niet leeg is
                    uuid = next((p for p in reversed(parts) if p), None)
                    
                    # UUIDs zijn meestal lang (bv. hashes) of numeriek
                    if uuid and len(uuid) > 5:
                        full_url = f"https://www.humo.be{href}"
                        tasks.append((uuid, full_url))
                except:
                    continue
                
        except Exception as e:
            print(f"❌ Browser fout: {e}")
            page.screenshot(path="error_page.png")
        finally:
            browser.close()
            
    # Unieke taken
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
    print("🚀 Script gestart (Target: 'Akkoord')...")
    
    tasks = get_overview_uuids_with_browser()
    
    if not tasks:
        print("❌ Geen programma's. Check 'debug_after_click.png' in Artifacts!")
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
