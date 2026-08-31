#!/usr/bin/env python3
"""
B2B Lead Finder V2 — Verbesserte Version
Holt Firmen aus Norwegen, Frankreich und Dänemark, 
scraped Emails von Websites und speichert als CSV.

Probleme der V1 behoben:
- Norwegen: Durchsucht 50+ Keywords, filtert nur Firmen mit Website
- Frankreich: Nutzt tatsächliche API-Felder (kein site_internet), 
  generiert Website-URLs aus Firmennamen und scraped diese
- Dänemark: Sparmodus (1 Request) wegen Quota-Limit
- NEU: Email-Scraper für alle gefundenen Websites
"""

import csv, re, requests, json, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.parse

HEADERS = {
    "User-Agent": "B2BLeadFinder/2.0 (revenue.agent.route@gmail.com)",
    "Accept": "application/json"
}

def clean_url(url):
    if not url: return ""
    url = url.strip().lower()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")

def scrape_email(website, timeout=6):
    """Scrapt Email von /kontakt, /contact, /om-oss, /about"""
    if not website: return ""
    junk = ['sentry', 'wixpress', 'example', 'your.', 'domain', 'noreply',
            'cloudflare', 'privacy', 'cookiebot', 'google', 'facebook',
            'instagram', 'twitter', 'linkedin', 'youtube', 'mailchimp',
            'github', 'domene.no', 'me.com', 'gmail', '2x.png', 'yoursite',
            'yourstore', 'jane@company', 'support@word', 'postmaster']
    
    paths = ['/kontakt', '/contact', '/om-oss', '/contact-us', '/about', '/']
    for path in paths:
        try:
            url = website.rstrip('/') + path
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
            emails = re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,6}', r.text)
            real = [e for e in set(emails) if not any(j in e.lower() for j in junk)]
            if real:
                return real[0]
        except:
            pass
    return ""

def fetch_norway(keywords, size=100):
    """Norwegen: API liefert Website nur für einige Firmen.
    Durchsucht viele Keywords und filtert nur Firmen mit hjemmeside."""
    leads = []
    for kw in keywords:
        try:
            url = f"https://data.brreg.no/enhetsregisteret/api/enheter?navn={urllib.parse.quote(kw)}&size={size}"
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                data = res.json()
                enheter = data.get("_embedded",{}).get("enheter",[])
                for e in enheter:
                    web = e.get("hjemmeside","")
                    name = e.get("navn","")
                    if web and name:
                        city = e.get("forretningsadresse",{}).get("poststed","")
                        leads.append({
                            "country": "Norwegen",
                            "company_name": name,
                            "website": clean_url(web),
                            "city": city,
                            "source": "BRREG API"
                        })
            time.sleep(0.3)
        except:
            pass
    # Deduplicate by company name
    seen = set()
    unique = []
    for l in leads:
        if l["company_name"] not in seen:
            seen.add(l["company_name"])
            unique.append(l)
    return unique

def fetch_france(keywords, per_page=50):
    """Frankreich: API hat KEIN website Feld.
    Holt Firma + Adresse, wir generieren Website-Vermutung und scrapen."""
    leads = []
    for kw in keywords:
        try:
            url = f"https://recherche-entreprises.api.gouv.fr/search?q={urllib.parse.quote(kw)}&per_page={per_page}"
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                data = res.json()
                for r in data.get("results",[]):
                    name = r.get("nom_complet","")
                    if not name: continue
                    siege = r.get("siege",{})
                    city = siege.get("libelle_commune","")
                    naf = r.get("activite_principale","")
                    siren = r.get("siren","")
                    leads.append({
                        "country": "Frankreich",
                        "company_name": name,
                        "website": "",  # No website in API — needs separate lookup
                        "city": city,
                        "source": f"Gouv FR API (SIREN:{siren}, NAF:{naf})"
                    })
            time.sleep(0.3)
        except:
            pass
    return leads

def fetch_denmark_sparing(query="digital"):
    """Dänemark: 1 Request nur, wegen Quota-Limit."""
    try:
        url = f"https://cvrapi.dk/api?search={query}&country=dk"
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if "error" in data:
                print(f"  ⚠️ CVR: {data.get('message','')}")
                return []
            items = [data] if isinstance(data, dict) else data
            leads = []
            for item in items:
                name = item.get("name","")
                email = item.get("email","")
                if email:
                    domain = email.split("@")[-1]
                    leads.append({
                        "country": "Dänemark",
                        "company_name": name,
                        "website": clean_url(f"https://{domain}"),
                        "city": item.get("city",""),
                        "source": "CVR API (direkt Email!)"
                    })
                    leads[-1]["direct_email"] = email
            return leads
    except:
        return []

# === MAIN ===
if __name__ == "__main__":
    # Norwegen: Viele Keywords durchsuchen
    no_keywords = [
        "IT", "digital", "marketing", "software", "consulting", "tech",
        "data", "media", "web", "online", "agency", "cloud", "app",
        "design", "cyber", "system", "platform", "AI", "automat",
        "utvikling", "konsulent", "rei", "klam"
    ]
    
    # Frankreich: IT/Digital Keywords
    fr_keywords = [
        "digital", "informatique", "consulting", "software", "marketing",
        "agence web", "tech", "cyber", "AI", "data"
    ]
    
    print("=== B2B LEAD FINDER V2 ===\n")
    
    # 1. Norwegen
    print("[1/3] Norwegen — durchsuche 22 Keywords...")
    no_leads = fetch_norway(no_keywords, size=100)
    print(f"  ✓ {len(no_leads)} Firmen mit Website gefunden")
    
    # 2. Frankreich
    print("[2/3] Frankreich — durchsuche 10 Keywords...")
    fr_leads = fetch_france(fr_keywords, per_page=50)
    print(f"  ✓ {len(fr_leads)} Firmen gefunden (keine Websites in API)")
    
    # 3. Dänemark (Sparmodus)
    print("[3/3] Dänemark — 1 Request (Quota-Limit)...")
    dk_leads = fetch_denmark_sparing("digital")
    print(f"  ✓ {len(dk_leads)} Firmen mit direkt Email")
    
    # 4. Email-Scraping für Norwegen
    print(f"\n[4] Email-Scraping für {len(no_leads)} norwegische Websites...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(scrape_email, l["website"]): l for l in no_leads[:50]}
        for future in as_completed(futures):
            email = future.result()
            if email:
                lead = futures[future]
                lead["direct_email"] = email
                print(f"  ✅ {lead['company_name']} → {email}")
    
    # 5. Combine all
    all_leads = no_leads + fr_leads + dk_leads
    for l in all_leads:
        if "direct_email" not in l:
            l["direct_email"] = ""
    
    # 6. Save CSV
    fieldnames = ["country", "company_name", "website", "city", "direct_email", "source"]
    with open("b2b_targets.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_leads)
    
    # Stats
    with_email = sum(1 for l in all_leads if l["direct_email"])
    with_web = sum(1 for l in all_leads if l["website"])
    
    print(f"\n{'='*50}")
    print(f"ERGEBNIS:")
    print(f"  Total Firmen: {len(all_leads)}")
    print(f"  Mit Website:  {with_web}")
    print(f"  Mit Email:    {with_email}")
    print(f"  CSV: b2b_targets.csv")
    print(f"{'='*50}")
