import requests
import json
import os
import re
import sys
import time
import random
import string
import urllib3
from urllib.parse import urlparse, parse_qs
from datetime import datetime

# Try to import BeautifulSoup for Option 7
try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

# Disable SSL Warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# Global Variables
# ==========================================
HOST_URL = ""
USERNAME = ""
PASSWORD = ""
MAC_ADDRESS = ""
AUTH_TYPE = "" 
EPG_URL = "" 
EXP_DATE_STR = "Unknown"
START_DATE_STR = "Unknown"
CACHE_DIR = "/storage/emulated/0/Download/IPTV_Cache"

class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    PURPLE = '\033[95m'
    RESET = '\033[0m'
    BOLD = '\033[1m'
    WHITE = '\033[97m'

# ==========================================
# 🛠️ Helper Functions
# ==========================================
def generate_random_id(length=13):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def generate_serial(length=14):
    return ''.join(random.choices(string.digits, k=length))

def timestamp_to_date(ts):
    if not ts: return "Unlimited"
    try: return datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d')
    except: return "Unknown"

def calculate_days_left(exp_date_str_or_ts):
    if not exp_date_str_or_ts: return 9999
    try:
        if str(exp_date_str_or_ts).isdigit():
             exp = datetime.fromtimestamp(int(exp_date_str_or_ts))
        else:
             exp = datetime.strptime(str(exp_date_str_or_ts), '%Y-%m-%d %H:%M:%S')
        now = datetime.now()
        return (exp - now).days
    except: return 0

def parse_m3u_link(url):
    try:
        parsed = urlparse(url.strip())
        qs = parse_qs(parsed.query)
        host = f"{parsed.scheme}://{parsed.netloc}"
        user = qs.get('username', [None])[0]
        password = qs.get('password', [None])[0]
        return host, user, password
    except: return None, None, None

def parse_stream_link(url):
    try:
        parsed = urlparse(url.strip())
        path_parts = parsed.path.strip("/").split("/")
        prefixes = ['movie', 'series', 'live']
        if len(path_parts) >= 4 and path_parts[0] in prefixes:
            username = path_parts[1]
            password = path_parts[2]
            host = f"{parsed.scheme}://{parsed.netloc}"
            return host, username, password
        elif len(path_parts) >= 3:
            username = path_parts[0]
            password = path_parts[1]
            host = f"{parsed.scheme}://{parsed.netloc}"
            return host, username, password
        else: return None, None, None
    except: return None, None, None

def get_server_name_for_file():
    try:
        clean = HOST_URL.replace("http://", "").replace("https://", "")
        if ":" in clean: clean = clean.split(":")[0]
        if "/" in clean: clean = clean.split("/")[0]
        parts = clean.split('.')
        if len(parts) > 1 and not parts[-1].isdigit(): clean = ".".join(parts[:-1])
        clean = clean.replace(".", "")
        clean = re.sub(r'[\\/*?:"<>|]', "_", clean)
        return clean
    except: return "Server"

def save_m3u(content_list):
    if not content_list: 
        print(f"{Colors.RED}❌ No results found.{Colors.RESET}")
        return
    
    android_path = "/storage/emulated/0/Download"
    target_folder = android_path if os.path.exists(android_path) else os.getcwd()
    
    server_name = get_server_name_for_file()
    safe_date = EXP_DATE_STR.replace("/", "-").replace(":", "-")
    
    final_filename_str = f"{server_name}_{safe_date}.m3u"
    full_path = os.path.join(target_folder, final_filename_str)
    
    if os.path.exists(full_path):
        name, ext = os.path.splitext(final_filename_str)
        c = 1
        while True:
            new_path = os.path.join(target_folder, f"{name}_{c}{ext}")
            if not os.path.exists(new_path):
                full_path = new_path
                break
            c += 1
            
    header = "#EXTM3U"
    if EPG_URL: header += f' x-tvg-url="{EPG_URL}"'
    
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(header + "\n" + "\n".join(content_list))
    print(f"{Colors.GREEN}📂 Saved to: {Colors.BOLD}{full_path}{Colors.RESET}")

def get_headers():
    return {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# ==========================================
# 🧩 Core Parsing & Checking Logic (Shared)
# ==========================================
def extract_accounts_from_text(lines):
    accounts_to_check = []
    
    # --- STRATEGY 1: Block Parsing (URL/USER/PASS) ---
    c_host, c_user, c_pass = None, None, None
    for line in lines:
        url_match = re.search(r'(?:URL|Host|Server)\s*[:=]\s*(https?://[^\s]+)', line, re.IGNORECASE)
        if url_match:
            c_host = url_match.group(1).strip()
            c_user, c_pass = None, None
            continue
            
        user_match = re.search(r'(?:USER|Username)\s*[:=]\s*([^\s]+)', line, re.IGNORECASE)
        if user_match: c_user = user_match.group(1).strip()
        
        pass_match = re.search(r'(?:PASS|Password)\s*[:=]\s*([^\s]+)', line, re.IGNORECASE)
        if pass_match: c_pass = pass_match.group(1).strip()
            
        if c_host and c_user and c_pass:
            accounts_to_check.append({'h': c_host, 'u': c_user, 'p': c_pass})
            c_host, c_user, c_pass = None, None, None

    # --- STRATEGY 2: Standard M3U Links ---
    for line in lines:
        h, u, p = parse_m3u_link(line)
        if not h: h, u, p = parse_stream_link(line)
        if h and u and p:
            if not any(a['h'] == h and a['u'] == u for a in accounts_to_check):
                accounts_to_check.append({'h': h, 'u': u, 'p': p})
    
    return accounts_to_check

def process_bulk_check(accounts_to_check):
    global HOST_URL, USERNAME, PASSWORD, AUTH_TYPE
    
    if not accounts_to_check:
        print(f"{Colors.RED}❌ No valid accounts/links found.{Colors.RESET}")
        return "DONE"

    print(f"\n{Colors.PURPLE}🚀 Checking {len(accounts_to_check)} accounts...{Colors.RESET}")
    valid_accounts = []
    
    for i, acc in enumerate(accounts_to_check):
        h, u, p = acc['h'], acc['u'], acc['p']
        try:
            if not h.startswith("http"): h = "http://" + h
            
            check_url = f"{h}/player_api.php?username={u}&password={p}"
            r = requests.get(check_url, headers={'User-Agent':'Mozilla/5.0'}, timeout=5, verify=False)
            
            if r.status_code == 200:
                d = r.json()
                inf = d.get('user_info', {})
                if inf.get('status') == 'Active':
                    exp = timestamp_to_date(inf.get('exp_date'))
                    days = calculate_days_left(inf.get('exp_date'))
                    
                    print(f"{Colors.GREEN}✅ [{i+1}] Active | {days}d | {h.replace('http://','').split('/')[0]}{Colors.RESET}")
                    valid_accounts.append({
                        'h': h, 'u': u, 'p': p, 
                        'exp': exp, 'days': days,
                        'full_info': f"URL : {h}\nUSER : {u}\nPASS : {p}\nEXP  : {exp} ({days} days)"
                    })
                else:
                    print(f"{Colors.RED}❌ [{i+1}] Inactive{Colors.RESET}")
            else:
                print(f"{Colors.RED}❌ [{i+1}] Error {r.status_code}{Colors.RESET}")
        except:
            print(f"{Colors.RED}❌ [{i+1}] Timeout{Colors.RESET}")

    # --- AUTO SAVE ---
    if valid_accounts:
        save_path = "/storage/emulated/0/Download"
        if not os.path.exists(save_path): save_path = os.getcwd()
        
        filename = f"Xtream_Scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        full_path = os.path.join(save_path, filename)
        
        try:
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write("==================================================\n")
                f.write(f"XTREAM SCAN REPORT - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
                f.write("==================================================\n\n")
                for va in valid_accounts:
                    f.write(va['full_info'] + "\n" + "-"*30 + "\n")
            print(f"\n{Colors.GREEN}💾 RESULTS SAVED TO: {full_path}{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}❌ Save failed: {e}{Colors.RESET}")

        # --- SELECTION MENU ---
        print("\n" + "="*40)
        print(f"{Colors.BOLD}🎉 FOUND: {len(valid_accounts)} Working Accounts{Colors.RESET}")
        print("="*40)
        for i, a in enumerate(valid_accounts):
             print(f"[{i+1}] {a['days']} Days | {a['u']} | {a['h'].replace('http://','').split('/')[0]}")
        
        choice = input(f"\n{Colors.YELLOW}Select Account (1-{len(valid_accounts)}) to Login or Enter to Exit: {Colors.RESET}").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(valid_accounts):
            sel = valid_accounts[int(choice)-1]
            HOST_URL = sel['h']
            USERNAME = sel['u']
            PASSWORD = sel['p']
            AUTH_TYPE = 'user'
            check_account_info()
            return "LOGGED_IN"
            
    return "DONE"

# ==========================================
# 🧪 Bulk Checker (Option 5)
# ==========================================
def opt_bulk_checker():
    print(f"\n{Colors.CYAN}=== 🧪 BULK XTREAM CHECKER (Auto-Save) ==={Colors.RESET}")
    print(f"{Colors.YELLOW}📝 Paste content (Links or URL/USER/PASS). Type 'done' to start:{Colors.RESET}")
    
    lines = []
    while True:
        try:
            line = input()
            if line.strip().lower() in ['done', 'exit']: break
            lines.append(line.strip())
        except EOFError: break
    
    accounts = extract_accounts_from_text(lines)
    return process_bulk_check(accounts)

# ==========================================
# 🕷️ Web Scraper (Option 7)
# ==========================================
def opt_web_scraper():
    if not BS4_AVAILABLE:
        print(f"\n{Colors.RED}❌ 'bs4' library not found.{Colors.RESET}")
        print(f"{Colors.YELLOW}Please install it using: pip install beautifulsoup4{Colors.RESET}")
        return "DONE"
        
    print(f"\n{Colors.CYAN}=== 🕷️ WEB PAGE SCRAPER & CHECKER ==={Colors.RESET}")
    url = input(f"{Colors.YELLOW}🔗 Enter Webpage URL: {Colors.RESET}").strip()
    
    if not url.startswith("http"):
        url = "https://" + url
        
    print(f"{Colors.PURPLE}⏳ Fetching page...{Colors.RESET}")
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15, verify=False)
        if response.status_code != 200:
            print(f"{Colors.RED}❌ Failed to fetch page (Status: {response.status_code}){Colors.RESET}")
            return "DONE"
            
        soup = BeautifulSoup(response.text, "html.parser")
        
        # 1. Extract plain text (lines) to find URL:USER:PASS blocks
        page_text_lines = soup.get_text(separator="\n").split("\n")
        
        # 2. Extract href links to find m3u links
        links = soup.find_all("a", href=True)
        href_lines = [link["href"] for link in links]
        
        # Combine everything
        all_lines = page_text_lines + href_lines
        # Filter empty lines
        all_lines = [line.strip() for line in all_lines if line.strip()]
        
        print(f"{Colors.CYAN}✅ Page Parsed. Extracting Accounts...{Colors.RESET}")
        
        # Use the shared extractor
        accounts = extract_accounts_from_text(all_lines)
        
        if not accounts:
            print(f"{Colors.RED}❌ No Accounts/M3U Links found in page.{Colors.RESET}")
            return "DONE"
            
        # Pass to the shared checker
        return process_bulk_check(accounts)
        
    except Exception as e:
        print(f"{Colors.RED}❌ Error: {e}{Colors.RESET}")
        return "DONE"

# ==========================================
# 🧠 SMART CONTEXT PARSER (Option 6)
# ==========================================
def parse_mixed_content(full_text):
    lines = full_text.split('\n')
    entries = {}
    current_host = None
    url_pattern = re.compile(r'(https?://[a-zA-Z0-9.-]+(?::\d+)?(?:/[a-zA-Z0-9._/-]*)?)')
    mac_pattern = re.compile(r'([0-9A-Fa-f]{2}[:][0-9A-Fa-f]{2}[:][0-9A-Fa-f]{2}[:][0-9A-Fa-f]{2}[:][0-9A-Fa-f]{2}[:][0-9A-Fa-f]{2})')

    print(f"{Colors.PURPLE}⚙️ Analyzing Structure...{Colors.RESET}")

    for line in lines:
        line = line.strip()
        if not line: continue
        found_url = url_pattern.search(line)
        if found_url:
            raw_url = found_url.group(1)
            clean_url = raw_url.rstrip('/')
            if clean_url.endswith('/c'): clean_url = clean_url[:-2]
            current_host = clean_url
            if current_host not in entries: entries[current_host] = []
        found_mac = mac_pattern.search(line)
        if found_mac:
            mac = found_mac.group(1).upper()
            if current_host:
                if mac not in entries[current_host]: entries[current_host].append(mac)
    return entries

# ==========================================
# 🛡️ 511 TOKEN SOLVER (Option 6)
# ==========================================
def solve_511_puzzle(host, mac):
    session = requests.Session()
    portal_root = host
    if not portal_root.endswith('/c'):
        if "/stalker_portal" in portal_root and not portal_root.endswith("/"): portal_root += "/c/"
        elif not portal_root.endswith("/"): portal_root += "/c/"
    else: portal_root += "/" 
    portal_root = portal_root.replace("//c//", "/c/") 

    dev_id = generate_random_id(13); dev_id2 = generate_random_id(13)
    serial = generate_serial(14); sig = generate_random_id(32)
    headers = {
        'User-Agent': 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 set-top box AppleWebKit/533.3',
        'Referer': portal_root,
        'Cookie': f"mac={mac}; stb_lang=en; timezone=Europe/London;",
        'X-User-Agent': 'Model: MAG254; Link: WiFi', 'Accept': '*/*'
    }

    token = None
    endpoints = [f"{portal_root}portal.php", f"{portal_root}load.php", f"{portal_root}c/portal.php"]
    params = {'type': 'stb', 'action': 'handshake', 'token': '', 'mac': mac, 'deviceId': dev_id, 'deviceId2': dev_id2, 'signature': sig, 'serial': serial}

    for ep in endpoints:
        try:
            r = session.get(ep, params=params, headers=headers, timeout=5, verify=False)
            if r.status_code == 200:
                js = r.json()
                if 'js' in js and 'token' in js['js']: token = js['js']['token']; break
        except: pass
        if token: break

    if not token: return False, "Handshake Failed"

    headers['Authorization'] = f"Bearer {token}"
    try:
        api_url = f"{portal_root}portal.php"
        r = session.get(api_url, params={'type':'stb','action':'get_profile'}, headers=headers, timeout=5, verify=False)
        if r.status_code == 200:
            data = r.json()
            user_info = data.get('js', data)
            if 'id' in user_info or 'login' in user_info:
                exp_ts = None
                if 'expire_billing_date' in user_info: exp_ts = user_info['expire_billing_date']
                elif 'exp_date' in user_info: exp_ts = user_info['exp_date']
                elif 'services_expiration' in user_info: exp_ts = user_info['services_expiration']
                
                final_date = "Unknown"; days_left = "?"
                if exp_ts:
                    try:
                        if str(exp_ts).isdigit():
                             if int(exp_ts) == 0: final_date = "Unlimited"; days_left = "∞"
                             else: final_date = timestamp_to_date(exp_ts); days_left = calculate_days_left(exp_ts)
                        else: final_date = str(exp_ts); days_left = calculate_days_left(final_date)
                    except: pass
                return True, {'exp': final_date, 'days': days_left, 'token': token}
            else: return False, "Blocked/Expired"
        elif r.status_code == 403: return False, "Geo-Blocked (403)"
        elif r.status_code == 511: return False, "Token Invalid (511)"
    except: pass
    return False, "Connection Error"

# ==========================================
# 🔄 MAC TO M3U CONVERTER (Integrated)
# ==========================================
def convert_mac_to_m3u_stalker(host, mac, token=None):
    """
    Connects to Stalker Portal, fetches Genres & Channels, and saves them as M3U.
    Uses 'play/live.php' format as requested.
    """
    print(f"\n{Colors.CYAN}=== 🔄 MAC TO M3U CONVERTER ==={Colors.RESET}")
    print(f"Target: {host}")
    print(f"MAC: {mac}")
    
    session = requests.Session()
    
    # Ensure portal URL ends correctly for API usage
    # We need base portal URL for portal.php
    portal_base = host.rstrip('/')
    if not portal_base.endswith('/c'): 
        if '/stalker_portal' in portal_base and not portal_base.endswith('/c'):
            portal_base += '/c'
        elif not portal_base.endswith('/c'):
             # Try appending /c if not present (heuristic)
             # But first check if portal.php is at root
             pass 

    # Headers setup
    headers = {
        'User-Agent': 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 set-top box AppleWebKit/533.3',
        'Cookie': f"mac={mac}; stb_lang=en; timezone=Europe/London;",
        'Referer': portal_base + '/'
    }
    
    if token:
        headers['Authorization'] = f"Bearer {token}"
        print(f"{Colors.GREEN}🔑 Using Token for Auth.{Colors.RESET}")

    # 1. Helper to fetch JSON
    def fetch_json(url):
        try:
            r = session.get(url, headers=headers, timeout=10, verify=False)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            # print(f"{Colors.RED}❌ Error fetching: {e}{Colors.RESET}") # Debug
            return None

    # 2. Get Genres
    # Try different locations for portal.php
    possible_apis = [
        f"{portal_base}/portal.php",
        f"{portal_base}/c/portal.php",
        f"{host}/portal.php"
    ]
    
    genres_data = None
    working_api = None
    
    print(f"{Colors.YELLOW}⏳ Fetching Categories...{Colors.RESET}")
    
    for api in possible_apis:
        url = f"{api}?type=itv&mac={mac}&action=get_genres&JsHttpRequest=1-xml"
        data = fetch_json(url)
        if data and isinstance(data, dict) and "js" in data:
            genres_data = data["js"]
            working_api = api
            break
            
    if not genres_data:
        print(f"{Colors.RED}❌ Failed to fetch genres. Server might be protected or incompatible.{Colors.RESET}")
        return

    # 3. Create Save Folder
    save_base = "/storage/emulated/0/Download"
    if not os.path.exists(save_base): save_base = os.getcwd()
    
    server_folder_name = host.replace("http://","").replace("https://","").split("/")[0].replace(":","_")
    save_dir = os.path.join(save_base, f"Stalker_M3U_{server_folder_name}")
    os.makedirs(save_dir, exist_ok=True)
    
    print(f"{Colors.GREEN}✅ Found {len(genres_data)} Categories.{Colors.RESET}")
    print(f"{Colors.PURPLE}🚀 Downloading Channels...{Colors.RESET}")

    total_channels = 0
    
    # 4. Loop Genres and Get Channels
    for genre in genres_data:
        gid = genre["id"]
        gtitle = genre["title"]
        safe_title = re.sub(r'[\\/*?:"<>|]', "_", gtitle).strip()
        
        # Fetch Channels
        url = f"{working_api}?type=itv&mac={mac}&action=get_ordered_list&genre={gid}&JsHttpRequest=1-xml"
        c_data = fetch_json(url)
        
        if c_data and "js" in c_data and "data" in c_data["js"]:
            channels = c_data["js"]["data"]
            if not channels: continue
            
            # Build M3U Content
            m3u_lines = ["#EXTM3U"]
            for ch in channels:
                name = ch.get('name', 'Unknown')
                cmd = ch.get('cmd', '')
                
                # Requested format: play/live.php
                # Note: stream ID is often inside 'cmd' like 'ffmpeg http://...' or just 'http://...'
                # But the user snippet used ch.get('id'). We stick to user logic.
                stream_id = ch.get('id')
                
                # Construct Link (User Request Format)
                # Some servers use /play/live.php, others different paths.
                # We use the host base.
                link = f"{host}/play/live.php?mac={mac}&stream={stream_id}&extension=ts"
                
                m3u_lines.append(f'#EXTINF:-1 group-title="{gtitle}",{name}\n{link}')
            
            # Save File
            fname = os.path.join(save_dir, f"{safe_title}.m3u")
            try:
                with open(fname, "w", encoding="utf-8") as f:
                    f.write("\n".join(m3u_lines))
                print(f"   📂 Saved: {safe_title} ({len(channels)} ch)")
                total_channels += len(channels)
            except: pass
            
    print(f"\n{Colors.CYAN}🎉 Done! Extracted {total_channels} channels.{Colors.RESET}")
    print(f"{Colors.YELLOW}📂 Files saved in: {save_dir}{Colors.RESET}")
    input("Press Enter to continue...")


# ==========================================
# 🕵️‍♂️ MAC Address Bulk Scanner
# ==========================================
def opt_mac_bulk_scanner():
    global HOST_URL, MAC_ADDRESS, USERNAME, PASSWORD, AUTH_TYPE
    print(f"\n{Colors.CYAN}=== 🕵️‍♂️ SMART MAC SCANNER (511 SOLVER) ==={Colors.RESET}")
    print(f"{Colors.YELLOW}📝 Paste text (Portals & MACs). Type 'done' to start:{Colors.RESET}")
    
    lines = []
    while True:
        try:
            line = input()
            if line.strip().lower() == 'done': break
            lines.append(line)
        except EOFError: break
    
    full_text = "\n".join(lines)
    entries_by_host = parse_mixed_content(full_text)
    
    if not entries_by_host:
        print(f"{Colors.RED}❌ No valid Portal/MAC combinations found.{Colors.RESET}")
        return

    total_macs = sum(len(v) for v in entries_by_host.values())
    print(f"{Colors.GREEN}✅ Found {len(entries_by_host)} Portals and {total_macs} MACs.{Colors.RESET}\n")

    valid_accounts = []
    file_output_lines = []

    for host, macs in entries_by_host.items():
        disp_host = host.replace("http://", "").split("/")[0]
        print(f"{Colors.CYAN}🌐 Scanning: {disp_host} ({len(macs)} MACs){Colors.RESET}")
        
        for mac in macs:
            print(f"   👉 Checking {mac}...", end="\r")
            success = False
            # Try Xtream first
            try:
                r = requests.get(f"{host}/player_api.php?device_mac={mac}", timeout=4, verify=False, headers={'User-Agent':'Mozilla/5.0'})
                if r.status_code == 200:
                    info = r.json().get('user_info', {})
                    if info.get('status') == 'Active':
                        days = "Unknown"; exp_str = "Unknown"
                        try: 
                            exp_ts = info.get('exp_date')
                            exp_str = timestamp_to_date(exp_ts)
                            days = calculate_days_left(exp_ts)
                        except: pass
                        
                        print(f"   ✅ {mac} | 📺 Xtream | {days} Days ({exp_str})    ")
                        valid_accounts.append({'host': host, 'mac': mac, 'days': days, 'type': 'xtream', 'exp': exp_str, 'token': None})
                        file_output_lines.append(f"{host} | {mac} | {exp_str} | Xtream")
                        success = True
            except: pass

            # Try Stalker if Xtream failed
            if not success:
                is_valid, data = solve_511_puzzle(host, mac)
                if is_valid:
                    print(f"   ✅ {mac} | ⚠️ Stalker | {data['days']} Days ({data['exp']})   ")
                    # Store Token for later use
                    valid_accounts.append({'host': host, 'mac': mac, 'days': data['days'], 'type': 'stalker', 'exp': data['exp'], 'token': data['token']})
                    file_output_lines.append(f"{host} | {mac} | {data['exp']} | Stalker")
                    success = True
                else: pass

    if valid_accounts:
        save_path = "/storage/emulated/0/Download"
        if not os.path.exists(save_path): save_path = os.getcwd()
        filename = f"MAC_SCAN_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        try:
            with open(os.path.join(save_path, filename), 'w', encoding='utf-8') as f:
                f.write("SCAN REPORT\n\n" + "\n".join(file_output_lines))
            print(f"\n{Colors.GREEN}💾 Results Saved: {filename}{Colors.RESET}")
        except: pass

    print("\n" + "="*40)
    print(f"{Colors.BOLD}🎉 FOUND: {len(valid_accounts)} Working{Colors.RESET}")
    print("="*40)
    
    if not valid_accounts: return
    
    for i, a in enumerate(valid_accounts):
        print(f"[{i+1}] {a['mac']} | {a['days']}d | {a['type']} | {a['host'].replace('http://','').split('/')[0]}")
    
    choice = input(f"\n{Colors.YELLOW}Select to Use (1-{len(valid_accounts)}) or Enter to Back: {Colors.RESET}").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(valid_accounts):
        sel = valid_accounts[int(choice)-1]
        HOST_URL = sel['host']
        AUTH_TYPE = 'mac'
        MAC_ADDRESS = sel['mac']
        
        # STALKER SPECIFIC MENU
        if sel['type'] == 'stalker':
             print(f"\n{Colors.CYAN}⚠️ Stalker Account Selected{Colors.RESET}")
             print("[1] Login & Extract Info (Standard)")
             print("[2] 🔄 Convert to M3U (Stalker Mode - Download Playlist)")
             
             sub_c = input(f"{Colors.YELLOW}>> Select (1-2): {Colors.RESET}").strip()
             if sub_c == '2':
                 convert_mac_to_m3u_stalker(HOST_URL, MAC_ADDRESS, sel.get('token'))
                 return "DONE" # Return to main menu after download
        
        check_account_info()
        return "LOGGED_IN"

# ==========================================
# 🔐 Connection
# ==========================================
def recover_mac():
    global USERNAME, PASSWORD, AUTH_TYPE
    try:
        r = requests.get(f"{HOST_URL}/get.php?type=m3u_plus&deviceMac={MAC_ADDRESS}", timeout=15, verify=False)
        h, u, p = parse_m3u_link(r.url)
        if u and p: USERNAME, PASSWORD, AUTH_TYPE = u, p, 'user'; return True
    except: return False
    return False

def check_account_info():
    global HOST_URL, USERNAME, PASSWORD, EPG_URL, EXP_DATE_STR, START_DATE_STR
    print(f"\n{Colors.YELLOW}⏳ Connecting...{Colors.RESET}")
    url = f"{HOST_URL}/player_api.php?device_mac={MAC_ADDRESS}" if AUTH_TYPE == 'mac' else f"{HOST_URL}/player_api.php?username={USERNAME}&password={PASSWORD}"
    
    try:
        r = requests.get(url, headers=get_headers(), timeout=30, verify=False)
        if r.status_code != 200:
            if "http://" in HOST_URL: HOST_URL = HOST_URL.replace("http://", "https://"); return check_account_info()
            if AUTH_TYPE == 'mac' and recover_mac(): return check_account_info()
            print(f"{Colors.RED}⚠️ API Access Limited.{Colors.RESET} You are logged in via MAC.")
            return True
        
        try: data = r.json()
        except: return True

        if not isinstance(data, dict):
            if AUTH_TYPE == 'mac' and recover_mac(): return check_account_info()
            return True

        info = data.get('user_info', {})
        if AUTH_TYPE == 'mac' and info.get('username'): 
            USERNAME, PASSWORD = info.get('username'), info.get('password')
            print(f"{Colors.CYAN}🔓 MAC Decrypted.{Colors.RESET}")
        
        EPG_URL = f"{HOST_URL}/xmltv.php?username={USERNAME}&password={PASSWORD}"
        exp_ts = info.get('exp_date'); created_ts = info.get('created_at')
        EXP_DATE_STR = timestamp_to_date(exp_ts); START_DATE_STR = timestamp_to_date(created_ts)
        DAYS_LEFT = calculate_days_left(exp_ts)
        
        days_color = Colors.GREEN
        if DAYS_LEFT < 30: days_color = Colors.YELLOW
        if DAYS_LEFT < 7: days_color = Colors.RED

        print(f"\n{Colors.GREEN}========================================{Colors.RESET}")
        print(f"{Colors.BOLD}📊 ACCOUNT INFO ({get_server_name_for_file()}){Colors.RESET}")
        print(f"{Colors.GREEN}========================================{Colors.RESET}")
        print(f"📡 Status    : {Colors.CYAN}{info.get('status','Unknown')}{Colors.RESET}")
        print(f"📅 Start Date: {Colors.WHITE}{START_DATE_STR}{Colors.RESET}")
        print(f"🛑 End Date  : {Colors.RED}{EXP_DATE_STR}{Colors.RESET}")
        print(f"⏳ Remaining : {days_color}{DAYS_LEFT} Days{Colors.RESET}")
        print(f"🔌 Active    : {info.get('active_cons','0')} / {info.get('max_connections','0')}")
        print(f"{Colors.GREEN}========================================{Colors.RESET}\n")
        return True
    except: return True

def get_data(action, desc):
    print(f"{Colors.YELLOW}⏳ Loading {desc}...{Colors.RESET}", end="\r")
    try:
        r = requests.get(f"{HOST_URL}/player_api.php?username={USERNAME}&password={PASSWORD}&action={action}", timeout=45, verify=False)
        d = r.json()
        if isinstance(d, list): 
            sys.stdout.write("\033[K"); print(f"{Colors.GREEN}✅ Loaded {len(d)} items.{Colors.RESET}")
            return d
    except: pass
    return []

# ==========================================
# 🧱 SHARED LOGIC
# ==========================================
def is_arabic_sport(name, cat_lower):
    name_lower = name.lower()
    special_allowed = ['alwan', 'ألوان', 'الوان', 'fajr', 'elfajr', 'alfajr', 'الفجر', 'thamania', 'ثمانية']
    arabic_brands = ['ssc', 'alkass', 'al kass', 'الكاس', 'الكأس', 'on time', 'ontime', 'اون تايم', 'أون تايم', 'watan', 'وطن', 'arryadia', 'الرياضية المغربية', 'bein', 'بين', 'بي ان', 'ad sport', 'adsport', 'abu dhabi', 'ابوظبي', 'أبو ظبي', 'caf', 'كاف']
    sport_words = ['sport', 'sbort', 'soccer', 'football', 'koora', 'kora', 'رياض', 'سبورت', 'كرة']
    ar_cat_indicators = ['arabic', 'arab', 'عربي', 'عربية', ' ar ', '|ar|', '[ar]', '(ar)', ' ar:', ':ar']
    foreign_blacklist = ['sky', 'bt sport', 'fox', 'espn', 'dazn', 'eurosport', 'eleven', 'premier', 'super sport', 'canal', 'arena', 'sport tv', 'ziggo', 'viaplay', 'nova', 'polsat', 'tnt', 'tsn', 'optus', 'cosmote', 's sport', 'match', 'setanta', 'dazn', 'magenta', 'astro', 'sportdigital', 'polsat']
    foreign_flags = [' uk', ' us', ' usa', ' de', ' ger', ' it', ' ita', ' sp', ' esp', ' es', ' tr', ' tur', ' pl', ' pol', ' pt', ' por', ' nl', ' ru', ' swe', ' gr', ' il', ' al', ' ro', ' exyu', ' fr ', 'french']
    content_blacklist = ['movie', 'aflam', 'aflem', 'film', 'أفلام', 'افلام', 'series', 'serial', 'mosalsalat', 'musalsalat', 'مسلسل', 'kids', 'cartoon', 'anime', 'أطفال', 'اطفال', 'كرتون', 'zee', 'z alwan', 'zi alwan', 'زي الوان', 'music', 'aghani', 'song', 'news', 'akhbar', 'xxx', 'porn', 'adult']
    arab_countries = ['egypt', 'nile', 'dubai', 'sharjah', 'oman', 'kuwait', 'jordan', 'iraq', 'bahrain', 'morocco', 'qatar', 'lebanon', 'algeria', 'tunisia', 'syria', 'sudan', 'saudi', 'ksa', 'uae', 'مصر', 'النيل', 'دبي', 'الشارقة', 'عمان', 'الكويت', 'الاردن', 'العراق', 'البحرين', 'المغربية', 'قطر', 'لبنان', 'الجزائر', 'تونس', 'سوريا', 'السودان', 'السعودية', 'الإمارات']

    is_target = False; is_special = False
    if any(b in name_lower for b in special_allowed):
        is_target = True; is_special = True
        if 'zee' in name_lower or 'z alwan' in name_lower or 'zi alwan' in name_lower: is_target = False; is_special = False
    elif any(b in name_lower for b in arabic_brands):
        if ('bein' in name_lower or 'abu dhabi' in name_lower or 'ad ' in name_lower):
            if any(w in name_lower for w in sport_words + ['max', 'ماكس']): is_target = True
        else: is_target = True
    elif any(ind in cat_lower for ind in ar_cat_indicators):
        if any(w in name_lower for w in sport_words + ['max', 'ماكس']): is_target = True
    else:
        has_arab = any(c in name_lower for c in arab_countries)
        has_sport = any(w in name_lower for w in sport_words)
        if has_arab and has_sport: is_target = True

    if is_target:
        if any(b in name_lower for b in foreign_blacklist): is_target = False
        if is_target and not is_special:
            safe_name = f" {name_lower} "
            for flag in foreign_flags:
                if flag + " " in safe_name or safe_name.endswith(flag): is_target = False; break
        if is_target and not is_special:
            if any(b in name_lower or b in cat_lower for b in content_blacklist): is_target = False
    return is_target

# ==========================================
# 1️⃣ Option 1: Smart Hierarchical Sorter
# ==========================================
def opt_sports_quality_sorter():
    print(f"\n{Colors.PURPLE}=== ⚽ Arabic Sports (Hierarchical: CAF -> Low -> 4K) ==={Colors.RESET}")
    streams = get_data("get_live_streams", "Channels")
    cats = get_data("get_live_categories", "Categories")
    if not streams: return
    cat_map = {i['category_id']: i['category_name'] for i in cats}
    
    caf_buckets = { "LOW": [], "SD": [], "HD": [], "FHD": [], "4K": [], "UNK": [] }
    main_buckets = { "LOW": [], "SD": [], "HD": [], "FHD": [], "4K": [], "UNK": [] }
    
    foreign_cat_indicators = [
        '|fr|', '[fr]', ' fr ', 'french', 'france', '|uk|', '[uk]', ' uk ', 'english', 'kingdom', 'usa', 'united',
        '|de|', '[de]', 'germany', 'deutsch', 'allemagne', '|tr|', '[tr]', 'turkey', 'turkish', 'turk',
        '|it|', '[it]', 'italy', 'italia', '|es|', '[es]', 'spain', 'espana', '|pt|', '[pt]', 'portugal',
        '|pl|', '[pl]', 'poland', 'polska', '|ru|', '[ru]', 'russia', '|nl|', '[nl]', 'netherland', 'holland',
        'ex-yu', 'exyu', 'albania', 'balkan', 'kurdistan', 'persian', 'iran', 'india', 'pakistan'
    ]

    count = 0
    print(f"{Colors.CYAN}⚙️ Analyzing Quality & CAF/MAX Hierarchy (Strict)...{Colors.RESET}")

    for s in streams:
        if not isinstance(s, dict): continue
        name = str(s.get('name', ''))
        cat_original = str(cat_map.get(s.get('category_id'), "Other"))
        cat_lower = cat_original.lower()
        
        is_foreign_cat = False
        for ind in foreign_cat_indicators:
            if ind in cat_lower: is_foreign_cat = True; break
        if is_foreign_cat: continue

        if is_arabic_sport(name, cat_lower):
            link = f"{HOST_URL}/live/{USERNAME}/{PASSWORD}/{s.get('stream_id')}.m3u8"
            epg = s.get("epg_channel_id", "")
            tvg = f'tvg-id="{epg}"' if epg else ""
            icon = s.get("stream_icon", "")
            
            name_lower = name.lower()
            quality_group = "UNK" 
            if any(k in name_lower for k in ['low', 'lq', 'mob', 'mobile', 'weak', 'sd low', 'ₗₒ', 'ₗqw']): quality_group = "LOW"
            elif any(k in name_lower for k in ['4k', 'uhd', '2160', '⁴ᴷ', '4ₖ']): quality_group = "4K"
            elif any(k in name_lower for k in ['fhd', '1080', 'hevc', 'h265', 'ᶠᴴᴰ', 'full hd', 'fullhd']): quality_group = "FHD"
            elif any(k in name_lower for k in ['hd', '720', 'ᴴᴰ', 'ʰᵈ']): quality_group = "HD"
            elif any(k in name_lower for k in ['sd', '576', '480', 'ˢᴰ', 'ˢᵈ']): quality_group = "SD"
            
            is_caf_max = False
            if 'max' in name_lower or 'ماكس' in name_lower or 'caf' in name_lower:
                foreign_caf_flags = ['fr', 'french', 'tr', 'tur', 'pl', 'pol', 'sp', 'es']
                is_clean_caf = True
                for flag in foreign_caf_flags:
                    if f" {flag} " in f" {name_lower} " or name_lower.endswith(f" {flag}"): is_clean_caf = False; break
                if is_clean_caf: is_caf_max = True

            if is_caf_max:
                q_disp = quality_group if quality_group != 'UNK' else "SD"
                prefix = "🏆"
                if q_disp == "4K": prefix = "🌟 4K"
                elif q_disp == "LOW": prefix = "📱 LOW"
                display_group = f"CAF ➤ {prefix} {q_disp}"
                entry = f'#EXTINF:-1 {tvg} tvg-logo="{icon}" group-title="{display_group}",{name}\n{link}'
                caf_buckets[quality_group].append(entry)
            else:
                clean_cat = cat_original
                for q in ['FHD', 'HD', 'SD', '4K', 'HEVC', 'LOW', 'Mobile', '⁴ᴷ', 'ᶠᴴᴰ', 'ᴴᴰ', 'ˢᴰ']:
                    clean_cat = re.sub(rf'\[?{q}\]?', '', clean_cat, flags=re.IGNORECASE).strip()
                prefix = "📺"
                if quality_group == "4K": prefix = "🌟 4K"
                elif quality_group == "FHD": prefix = "💎 FHD"
                elif quality_group == "HD": prefix = "🖥️ HD"
                elif quality_group == "SD": prefix = "📺 SD"
                elif quality_group == "LOW": prefix = "📱 LOW"
                elif quality_group == "UNK": prefix = "❓ UNK"
                display_group = f"{prefix} ➤ {clean_cat}"
                entry = f'#EXTINF:-1 {tvg} tvg-logo="{icon}" group-title="{display_group}",{name}\n{link}'
                main_buckets[quality_group].append(entry)
            count += 1
            
    caf_sorted = (caf_buckets['LOW'] + caf_buckets['SD'] + caf_buckets['HD'] + caf_buckets['FHD'] + caf_buckets['4K'] + caf_buckets['UNK'])
    main_sorted = (main_buckets['LOW'] + main_buckets['SD'] + main_buckets['HD'] + main_buckets['FHD'] + main_buckets['4K'] + main_buckets['UNK'])
    final_playlist = caf_sorted + main_sorted
    save_m3u(final_playlist)
    print(f"ℹ️ Smart Channels Extracted: {count}")

# ==========================================
# 2️⃣ Option 2: Original Strict Sorter
# ==========================================
def opt_sports_filter():
    print(f"\n{Colors.PURPLE}=== ⚽ Strict Arabic Sports (Original Groups) ==={Colors.RESET}")
    streams = get_data("get_live_streams", "Channels")
    cats = get_data("get_live_categories", "Categories")
    if not streams: return
    cat_map = {i['category_id']: i['category_name'] for i in cats}
    playlist = []
    count = 0
    foreign_cat_indicators = ['|fr|', '[fr]', ' fr ', 'french', '|uk|', '[uk]', ' uk ', 'english', '|us|', '[us]', ' usa ', '|de|', 'germany', '|tr|', 'turkey', '|it|', 'italy', '|es|', 'spain', '|pt|', 'portugal', 'persian', 'iran']

    for s in streams:
        if not isinstance(s, dict): continue
        name = str(s.get('name', ''))
        cat = str(cat_map.get(s.get('category_id'), "Other"))
        
        is_foreign_cat = False
        for ind in foreign_cat_indicators:
            if ind in cat.lower(): is_foreign_cat = True; break
        if is_foreign_cat: continue

        if is_arabic_sport(name, cat.lower()):
            link = f"{HOST_URL}/live/{USERNAME}/{PASSWORD}/{s.get('stream_id')}.m3u8"
            epg = s.get("epg_channel_id", "")
            tvg = f'tvg-id="{epg}"' if epg else ""
            entry = f'#EXTINF:-1 {tvg} tvg-logo="{s.get("stream_icon")}" group-title="{cat}",{name}\n{link}'
            playlist.append(entry)
            count += 1
    save_m3u(playlist)
    print(f"ℹ️ Channels Found: {count}")

# ==========================================
# Other VOD Options
# ==========================================
def opt_vod(mode, type_):
    action_s, action_c = ("get_vod_streams", "get_vod_categories") if type_ == "mov" else ("get_series", "get_series_categories")
    label = "Movies" if type_ == "mov" else "Series"
    print(f"\n{Colors.CYAN}=== Processing {label} ({mode}) ==={Colors.RESET}")
    data = get_data(action_s, "Content")
    cats = get_data(action_c, "Categories")
    if not data: return
    cat_map = {i['category_id']: i['category_name'] for i in cats}
    playlist = []
    ar_keys = ['ar', 'arabic', 'arab', 'egypt', 'syria', 'kuwait', 'ksa']
    sub_keys = ['sub', 'trans', 'mutarjam', 'mt']
    for item in data:
        if not isinstance(item, dict): continue
        cat = str(cat_map.get(item.get('category_id'), "Other"))
        cat_low = cat.lower()
        link = f"{HOST_URL}/movie/{USERNAME}/{PASSWORD}/{item.get('stream_id')}.{item.get('container_extension','mp4')}" if type_=="mov" else "http://series-info"
        entry = f'#EXTINF:-1 tvg-logo="{item.get("stream_icon")}" group-title="{cat}",{item.get("name")}\n{link}'
        add = False
        if mode == "ALL": add = True
        elif mode == "ARABIC" and any(k in cat_low for k in ar_keys): add = True
        elif mode == "SUB" and (any(k in cat_low for k in sub_keys) or (not any(k in cat_low for k in ar_keys) and "en" in cat_low)): add = True
        if add: playlist.append(entry)
    save_m3u(playlist)

# ==========================================
# 🚀 MAIN APP
# ==========================================
def run_app():
    global HOST_URL, USERNAME, PASSWORD, MAC_ADDRESS, AUTH_TYPE
    
    print("\n" + "="*40)
    print(f"{Colors.BOLD}{Colors.CYAN}📺 IPTV TERMINATOR PRO (511 SOLVER EDITION){Colors.RESET}")
    print("="*40)
    print("[1] Login via M3U Link")
    print(f"{Colors.GREEN}[2] Direct Stream Link (Movie/Live/Series){Colors.RESET}")
    print("[3] Login via User & Password")
    print("[4] Login via MAC Address")
    print(f"{Colors.PURPLE}[5] 🧪 Bulk Xtream & Link Checker (Smart Text){Colors.RESET}")
    print(f"{Colors.CYAN}[6] 🕵️‍♂️ Smart MAC Scanner (Portals + 511 Solver){Colors.RESET}")
    print(f"{Colors.YELLOW}[7] 🕷️ Web Page Scraper & Checker{Colors.RESET}")
    
    ch = input(f"\n{Colors.YELLOW}>> Select Option (1-7): {Colors.RESET}").strip()
    
    logged_in_signal = False 

    if ch == '5': 
        result = opt_bulk_checker()
        if result == "LOGGED_IN": logged_in_signal = True
        else: return
    
    elif ch == '6':
        result = opt_mac_bulk_scanner()
        if result == "LOGGED_IN": logged_in_signal = True 
        else: return
    
    elif ch == '7':
        result = opt_web_scraper()
        if result == "LOGGED_IN": logged_in_signal = True 
        else: return

    elif ch == '1':
        AUTH_TYPE = 'user'
        l = input("🔗 Paste Link: ").strip()
        h, u, p = parse_m3u_link(l)
        if h: HOST_URL, USERNAME, PASSWORD = h, u, p
        else: print(f"{Colors.RED}Invalid Link{Colors.RESET}"); return
    elif ch == '2':
        AUTH_TYPE = 'user'
        l = input("🔗 Paste Direct Stream Link: ").strip()
        h, u, p = parse_stream_link(l)
        if h and u and p:
            HOST_URL, USERNAME, PASSWORD = h, u, p
            print(f"{Colors.GREEN}✅ Link Converted! Logged in as: {u}{Colors.RESET}")
        else: print(f"{Colors.RED}Invalid Format{Colors.RESET}"); return
    elif ch == '3':
        AUTH_TYPE = 'user'
        HOST_URL = input("🌐 Host URL: ").strip()
        USERNAME = input("👤 Username: ").strip()
        PASSWORD = input("🔑 Password: ").strip()
    elif ch == '4':
        AUTH_TYPE = 'mac'
        HOST_URL = input("🌐 Portal URL: ").strip()
        MAC_ADDRESS = input("📟 MAC Address: ").strip()
    elif not logged_in_signal: return
    
    if not logged_in_signal:
        if not HOST_URL.startswith("http"): HOST_URL = "http://" + HOST_URL
        HOST_URL = HOST_URL.rstrip("/")
        if not check_account_info(): time.sleep(2); return

    while True:
        print("\n" + "-"*40)
        print(f"{Colors.BOLD}--- EXTRACTION MENU ---{Colors.RESET}")
        print(f"{Colors.GREEN}[1] ⚽ Smart Sports (Hierarchical: CAF -> Low -> 4K){Colors.RESET}")
        print("[2] ⚽ Strict Arabic Sports (Original Groups)")
        print("[3] 🎬 Arabic Movies")
        print("[4] 🎬 Translated Movies")
        print("[5] 📺 Arabic Series")
        print("[6] 📺 Translated Series")
        print("[7] 📂 All Movies")
        print("[8] 📂 All Series")
        print("[0] 🔙 Back")
        
        c = input(f"\n{Colors.YELLOW}>> Select (0-8): {Colors.RESET}")
        if c=='1': opt_sports_quality_sorter()
        elif c=='2': opt_sports_filter()
        elif c=='3': opt_vod("ARABIC", "mov")
        elif c=='4': opt_vod("SUB", "mov")
        elif c=='5': opt_vod("ARABIC", "ser")
        elif c=='6': opt_vod("SUB", "ser")
        elif c=='7': opt_vod("ALL", "mov")
        elif c=='8': opt_vod("ALL", "ser")
        elif c=='0': return

if __name__ == "__main__":
    while True:
        try: run_app()
        except KeyboardInterrupt: sys.exit()
        except Exception as e: time.sleep(1)