import flet as ft
from urllib.parse import urlparse, parse_qs
from datetime import datetime
import threading

# ملاحظة: لم نقم باستيراد requests هنا لتجنب الشاشة البيضاء عند الإقلاع

def main(page: ft.Page):
    page.title = "IPTV Terminator"
    page.theme_mode = ft.ThemeMode.DARK
    page.scroll = ft.ScrollMode.ADAPTIVE
    page.window_width = 360
    page.window_height = 640

    # --- UI Elements ---
    txt_host = ft.TextField(label="Host URL", hint_text="http://site.com:8080", prefix_icon=ft.icons.WEB)
    txt_user = ft.TextField(label="Username", prefix_icon=ft.icons.PERSON)
    txt_pass = ft.TextField(label="Password", password=True, can_reveal_password=True, prefix_icon=ft.icons.LOCK)
    
    txt_debug = ft.Text("Ready...", color=ft.colors.GREY) # عنصر لعرض الأخطاء
    
    result_container = ft.Container(padding=10, border_radius=10, visible=False, content=ft.Column())
    progress_ring = ft.ProgressRing(visible=False)

    # --- Logic ---

    def log(msg, color=ft.colors.WHITE):
        txt_debug.value = str(msg)
        txt_debug.color = color
        page.update()

    def run_check(host, user, password):
        try:
            # --- هنا الحيلة: نستدعي المكتبة فقط عند الحاجة ---
            import requests
            # ------------------------------------------------
            
            if not host.startswith("http"): host = "http://" + host
            url = f"{host}/player_api.php?username={user}&password={password}"
            
            headers = {'User-Agent': 'IPTV Terminator Flet'}
            response = requests.get(url, headers=headers, timeout=10)
            data = response.json()
            
            display_results(data, host)
            
        except ImportError:
            log("Error: Library 'requests' not found in APK!", ft.colors.RED)
            reset_ui()
        except Exception as ex:
            log(f"Error: {str(ex)}", ft.colors.RED)
            reset_ui()

    def check_click(e):
        if not txt_host.value or not txt_user.value or not txt_pass.value:
            log("Please fill all fields", ft.colors.RED)
            return
            
        btn_check.disabled = True
        progress_ring.visible = True
        result_container.visible = False
        log("Checking...", ft.colors.BLUE)
        page.update()
        
        threading.Thread(target=run_check, args=(txt_host.value, txt_user.value, txt_pass.value)).start()

    def reset_ui():
        btn_check.disabled = False
        progress_ring.visible = False
        page.update()

    def display_results(data, host):
        info = data.get('user_info', {})
        status = info.get('status')
        
        if status == 'Active':
            exp = "Unlimited"
            if info.get('exp_date'):
                try: exp = datetime.fromtimestamp(int(info.get('exp_date'))).strftime('%Y-%m-%d')
                except: pass
                
            content = [
                ft.Text("✅ LOGIN SUCCESS", color=ft.colors.GREEN, weight="bold", size=20),
                ft.Text(f"Status: {status}"),
                ft.Text(f"Exp: {exp}"),
                ft.Text(f"Active: {info.get('active_cons')} / {info.get('max_connections')}"),
            ]
            result_container.bgcolor = ft.colors.GREEN_900
            log("Success!", ft.colors.GREEN)
        else:
            content = [ft.Text("❌ FAILED", color=ft.colors.RED, weight="bold"), ft.Text(f"Status: {status}")]
            result_container.bgcolor = ft.colors.RED_900
            log("Failed", ft.colors.RED)

        result_container.content.controls = content
        result_container.visible = True
        reset_ui()

    btn_check = ft.ElevatedButton("Check Account", on_click=check_click, bgcolor=ft.colors.BLUE_700, color="white")

    page.add(
        ft.Column([
            ft.Icon(ft.icons.ANDROID, size=50, color="blue"),
            ft.Text("IPTV Terminator", size=20, weight="bold"),
            txt_host, txt_user, txt_pass,
            btn_check,
            progress_ring,
            txt_debug,
            result_container
        ], horizontal_alignment="center")
    )

ft.app(target=main)
