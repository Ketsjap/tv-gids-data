import requests
import json
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import time

# Configuratie
ALLOWED_CHANNELS = [
    "vtm", "vtm-2", "vtm-3", "vtm-4", "vtm-gold", "vtm-non-stop-dokters",
    "vrt-1", "canvas", "ketnet",
    "play-4", "play-5", "play-6", "play-7",
    "npo-1", "npo-2", "npo-3",
    "bbc-one", "bbc-two", "bbc-first",
    "national-geographic", "discovery", "tlc"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def get_overview_uuids():
    today = datetime.now().strftime("%Y-%m-%d")
    url = f"https://www.humo.be/tv-gids/api/v2/broadcasts/{today}"
    print(f"📡 Ophalen overzicht voor {today}...")
    try:
        resp = requests.get(url, headers=HEADERS)
        data = resp.json()
        tasks = []
        if 'channels' in data:
            for ch in data['channels']:
                ch_name = ch.get('name', '').lower().replace(' ', '-')
                if any(ac in ch_name for ac in ALLOWED_CHANNELS):
                    for b in ch.get('broadcasts', []):
                        uuid = b.get('id')
                        link = f"https://www.humo.be/tv-gids/{ch_name}/uitzending/aflevering/{uuid}"
                        tasks.append((uuid, link))
        return tasks
    except Exception as e:
        print(f"❌ Fout: {e}")
        return []

def scrape_detail(task):
    uuid, url = task
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200: return None
        
        match = re.search(r'window\.__EPG_REDUX_DATA__=(.*?);', resp.text)
        if not match: return None

        data = json.loads(match.group(1))
        details = data.get('details', {}).get(uuid, {})
        
        season = details.get('seasonOrder')
        episode = details.get('order')
        
        if season is None and episode is None: return None

        is_new = (episode == 1)
        title_blob = (details.get('subtitle') or "") + (details.get('alternativeDetailTitle') or "")
        if "nieuw seizoen" in title_blob.lower(): is_new = True

        return uuid, {"s": season, "ep": episode, "is_new": is_new}
    except:
        return None

def main():
    tasks = get_overview_uuids()
    print(f"🚀 Start scraping {len(tasks)} items...")
    results = {}
    
    # 20 tegelijk scrapen
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = executor.map(scrape_detail, tasks)
        for res in futures:
            if res:
                results[res[0]] = res[1]

    print(f"💾 {len(results)} items gevonden.")
    with open('tv-enrichment.json', 'w') as f:
        json.dump(results, f, separators=(',', ':'))

if __name__ == "__main__":
    main()
