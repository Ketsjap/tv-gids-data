from playwright.sync_api import sync_playwright
from curl_cffi import requests
import json
import re
from concurrent.futures import ThreadPoolExecutor
import sys
import time

# --- CONFIGURATIE ---
ALLOWED_KEYWORDS = [
    "vtm", "vrt", "canvas", "ketnet", "play", "npo", "bbc", "national", "discovery", "tlc"
]

def get_overview_uuids_with_browser():
    # 🔥 FIX 1: We gaan naar de root URL. Humo redirect zelf naar de juiste datum.
    # Dit voorkomt 404 fouten als de datum-berekening net misloopt.
    url = "https://www.humo.be/tv-gids"
    
    print(f"📡 Stap 1: Browser starten naar {url}...")
    
    tasks = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        
        try:
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            print("   -> Pagina geladen. Wachten op cookie banner...")
            
            # Wacht expliciet tot de pagina stabiel is
            page.wait_for_timeout(3000)

            # 🍪 COOKIE FIX: Geen regex meer, gebruik de exacte 'name' property
            try:
                # DPG gebruikt vaak shadow-dom of iframes, maar get_by_role kijkt daar dwars doorheen
                accept_button = page.get_by_role("button", name="Akkoord")
                
                if accept_button.is_visible():
                    print("   -> 🍪 'Akkoord' knop gevonden! Klikken...")
                    accept_button.click()
                    # Wacht op de reload die vaak volgt na cookies accepteren
                    page.wait_for_timeout(4000)
                else:
                    print("   -> ⚠️ Geen 'Akkoord' knop direct zichtbaar. Probeer fallback...")
                    # Fallback voor als het toch in een iframe zit dat get_by_role mist
                    frames = page.frames
                    clicked = False
                    for frame in frames:
                        btn = frame.get_by_role("button", name="Akkoord")
                        if btn.is_visible():
                            btn.click()
                            print("   -> 🍪 'Akkoord' in iframe geklikt!")
                            clicked = True
                            page.wait_for_timeout(4000)
                            break
                    
                    if not clicked:
                        print("   -> Geen klikbare banner gevonden. Misschien zijn we er al?")

            except Exception as e:
                print(f"   -> Fout bij klikken cookies: {e}")

            # Screenshot NA de klikpoging (voor debugging)
            page.screenshot(path="debug_after_click.png", full_page=True)

            print("   -> Scrollen door de gids om lazy-loading te triggeren...")
            # We scrollen iets agressiever
            for _ in range(8):
                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(800)
            
            # Zoek links - Specifiek naar uitzendingen
            # We pakken de href attributen
            links = page.evaluate("""() => {
                return Array.from(document.querySelectorAll("a[href*='/uitzending/'], a[href*='/programma/']"))
                            .map(a => a.href)
            }""")
            
            print(f"   -> {len(links)} links gevonden op de pagina.")
            
            for href in links:
                try:
                    # Filter op zenders
                    if not any(k in href for k in ALLOWED_KEYWORDS):
                        continue
                    
                    # UUID extractie
                    parts = href.split('/')
                    # Filter lege onderdelen en pak de laatste
                    parts = [p for p in parts if p]
                    uuid = parts[-1]
                    
                    # Simpele check of het een UUID lijkt (langer dan 5 chars)
                    if len(uuid) > 5:
                        tasks.append((uuid, href))
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
    print("🚀 Script gestart (Target: 'Akkoord' zonder regex)...")
    
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
