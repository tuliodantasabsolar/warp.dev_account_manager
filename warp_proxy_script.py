#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Mitmproxy script for intercepting and modifying Warp API requests
"""

import json
import sqlite3
import time
import urllib3
import re
import random
import string
from mitmproxy import http
from mitmproxy.script import concurrent
from languages import get_language_manager, _

# SSL uyarılarını gizle
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def randomize_uuid_string(uuid_str):
    """
    UUID string'ini rastgele değiştir - harfler hexadecimal harflerle, sayılar rastgele sayılarla değiştirilir
    Tire (-) karakterleri korunur, büyük/küçük harf formatı korunur

    Args:
        uuid_str (str): UUID formatındaki string (örn: 4d22323e-1ce9-44c1-a922-112a718ea3fc)

    Returns:
        str: Rastgele değiştirilmiş UUID string
    """
    hex_digits_lower = '0123456789abcdef'
    hex_digits_upper = '0123456789ABCDEF'

    result = []
    for char in uuid_str:
        if char == '-':
            # Tire karakterini koru
            result.append(char)
        elif char.isdigit():
            # Sayıyı rastgele hexadecimal karakter ile değiştir (sayı veya a-f)
            result.append(random.choice(hex_digits_lower))
        elif char in 'abcdef':
            # Küçük hexadecimal harfi rastgele küçük hexadecimal harf ile değiştir
            result.append(random.choice(hex_digits_lower))
        elif char in 'ABCDEF':
            # Büyük hexadecimal harfi rastgele büyük hexadecimal harf ile değiştir
            result.append(random.choice(hex_digits_upper))
        else:
            # Diğer karakterleri olduğu gibi bırak (güvenlik için)
            result.append(char)

    return ''.join(result)


def generate_experiment_id():
    """Warp Experiment ID formatında UUID üret"""
    # 931df166-756c-4d4c-b486-4231224bc531 formatında
    # 8-4-4-4-12 hex karakter yapısı
    def hex_chunk(length):
        return ''.join(random.choice('0123456789abcdef') for _ in range(length))

    return f"{hex_chunk(8)}-{hex_chunk(4)}-{hex_chunk(4)}-{hex_chunk(4)}-{hex_chunk(12)}"

class WarpProxyHandler:
    def __init__(self):
        self.db_path = "accounts.db"
        self.active_token = None
        self.active_email = None
        self.token_expiry = None
        self.last_trigger_check = 0
        self.last_token_check = 0
        self.user_settings_cache = None

    def get_active_account(self):
        """Aktif hesabı veritabanından al"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Önce aktif hesabı al
            cursor.execute('SELECT value FROM proxy_settings WHERE key = ?', ('active_account',))
            active_result = cursor.fetchone()

            if active_result:
                active_email = active_result[0]
                # Sonra hesap verilerini al
                cursor.execute('SELECT account_data FROM accounts WHERE email = ?', (active_email,))
                account_result = cursor.fetchone()

                if account_result:
                    account_data = json.loads(account_result[0])
                    conn.close()
                    return active_email, account_data

            conn.close()
            return None, None
        except Exception as e:
            print(f"Aktif hesap alma hatası: {e}")
            return None, None

    def update_active_token(self):
        """Aktif hesabın token bilgilerini güncelle"""
        try:
            print("🔍 Aktif hesap kontrol ediliyor...")
            email, account_data = self.get_active_account()
            if not account_data:
                print("❌ Aktif hesap bulunamadı")
                self.active_token = None
                self.active_email = None
                return False

            old_email = self.active_email

            current_time = int(time.time() * 1000)
            token_expiry = account_data['stsTokenManager']['expirationTime']

            # Token süresi 1 dakikadan az kaldıysa yenile
            if current_time >= (token_expiry - 60000):  # 1 dakika = 60000ms
                print(f"Token yenileniyor: {email}")
                if self.refresh_token(email, account_data):
                    # Güncellenmiş verileri al
                    email, account_data = self.get_active_account()
                    if account_data:
                        self.active_token = account_data['stsTokenManager']['accessToken']
                        self.token_expiry = account_data['stsTokenManager']['expirationTime']
                        self.active_email = email
                        print(f"Token yenilendi: {email}")
                        return True
                return False
            else:
                self.active_token = account_data['stsTokenManager']['accessToken']
                self.token_expiry = token_expiry
                self.active_email = email

                if old_email != email:
                    print(f"🔄 Aktif hesap değişti: {old_email} → {email}")
                else:
                    print(f"✅ Token aktif: {email}")
                return True
        except Exception as e:
            print(f"Token güncelleme hatası: {e}")
            return False

    def check_account_change_trigger(self):
        """Hesap değişiklik trigger dosyasını kontrol et"""
        try:
            trigger_file = "account_change_trigger.tmp"
            import os

            if os.path.exists(trigger_file):
                # Dosyanın değiştirilme zamanını kontrol et
                mtime = os.path.getmtime(trigger_file)
                print(f"📁 Trigger dosyası bulundu - mtime: {mtime}, last_check: {self.last_trigger_check}")
                if mtime > self.last_trigger_check:
                    print("🔄 Hesap değişiklik trigger tespit edildi!")
                    self.last_trigger_check = mtime

                    # Trigger dosyasını sil
                    try:
                        os.remove(trigger_file)
                        print("🗑️  Trigger dosyası silindi")
                    except Exception as e:
                        print(f"Trigger dosyası silinme hatası: {e}")

                    # Token güncelle
                    print("🔄 Token güncelleniyor...")
                    self.update_active_token()
                    return True
                else:
                    print("⏸️  Trigger dosyası zaten işlenmiş, atlanıyor")
            return False
        except Exception as e:
            print(f"Trigger kontrol hatası: {e}")
            return False

    def refresh_token(self, email, account_data):
        """Firebase token yenileme"""
        try:
            import requests

            refresh_token = account_data['stsTokenManager']['refreshToken']
            api_key = account_data['apiKey']

            url = f"https://securetoken.googleapis.com/v1/token?key={api_key}"
            data = {
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token
            }

            # Proxy kullanmadan direkt bağlan
            proxies = {'http': None, 'https': None}
            response = requests.post(url, json=data, timeout=30, verify=False, proxies=proxies)

            if response.status_code == 200:
                token_data = response.json()
                new_token_data = {
                    'accessToken': token_data['access_token'],
                    'refreshToken': token_data['refresh_token'],
                    'expirationTime': int(time.time() * 1000) + (int(token_data['expires_in']) * 1000)
                }

                # Veritabanını güncelle
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute('SELECT account_data FROM accounts WHERE email = ?', (email,))
                result = cursor.fetchone()

                if result:
                    account_data = json.loads(result[0])
                    account_data['stsTokenManager'].update(new_token_data)

                    cursor.execute('''
                        UPDATE accounts SET account_data = ?, last_updated = CURRENT_TIMESTAMP
                        WHERE email = ?
                    ''', (json.dumps(account_data), email))
                    conn.commit()

                conn.close()
                return True
            return False
        except Exception as e:
            print(f"Token yenileme hatası: {e}")
            return False

    def mark_account_as_banned(self, email):
        """Hesabı banlanmış olarak işaretle"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Hesabın health_status'unu 'banned' olarak güncelle
            cursor.execute('''
                UPDATE accounts SET health_status = 'banned', last_updated = CURRENT_TIMESTAMP
                WHERE email = ?
            ''', (email,))
            conn.commit()
            conn.close()

            print(f"Hesap banlanmış olarak işaretlendi: {email}")

            # Aktif hesabı temizle (banlanmış hesap aktif kalamaz)
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM proxy_settings WHERE key = ?', ('active_account',))
            conn.commit()
            conn.close()

            # Handler'daki aktif hesap bilgilerini temizle
            self.active_token = None
            self.active_email = None
            self.token_expiry = None

            print("Banlanmış hesap aktif hesap listesinden çıkarıldı")

            # GUI'ye ban bildirimini gönder
            self.notify_gui_about_ban(email)
            return True

        except Exception as e:
            print(f"Hesap ban işaretleme hatası: {e}")
            return False

    def notify_gui_about_ban(self, email):
        """GUI'ye ban bildirimini dosya üzerinden gönder"""
        try:
            import os
            import time

            # Ban bildirim dosyası oluştur
            ban_notification_file = "ban_notification.tmp"
            with open(ban_notification_file, 'w', encoding='utf-8') as f:
                f.write(f"{email}|{int(time.time())}")

            print(f"Ban bildirimi dosyası oluşturuldu: {ban_notification_file}")
        except Exception as e:
            print(f"Ban bildirimi gönderme hatası: {e}")

    def load_user_settings(self):
        """user_settings.json dosyasını yükle"""
        try:
            import os
            if os.path.exists("user_settings.json"):
                with open("user_settings.json", 'r', encoding='utf-8') as f:
                    self.user_settings_cache = json.load(f)
                print("✅ user_settings.json dosyası başarıyla yüklendi")
                return True
            else:
                print("⚠️ user_settings.json dosyası bulunamadı")
                self.user_settings_cache = None
                return False
        except Exception as e:
            print(f"user_settings.json yükleme hatası: {e}")
            self.user_settings_cache = None
            return False

    def refresh_user_settings(self):
        """user_settings.json dosyasını yeniden yükle"""
        print("🔄 user_settings.json yeniden yükleniyor...")
        return self.load_user_settings()

# Global handler instance
handler = WarpProxyHandler()

def is_relevant_request(flow: http.HTTPFlow) -> bool:
    """İsteğin bizi ilgilendirip ilgilendirmediğini kontrol et"""

    # Firebase token yenileme isteklerini User-Agent ile kontrol et ve hariç tut
    if ("securetoken.googleapis.com" in flow.request.pretty_host and
        flow.request.headers.get("User-Agent") == "WarpAccountManager/1.0"):
        return False

    # WarpAccountManager'dan gelen istekleri kontrol et ve hariç tut
    if flow.request.headers.get("X-Warp-Manager-Request") == "true":
        return False

    # Sadece belirli domainleri işle
    relevant_domains = [
        "app.warp.dev",
        "dataplane.rudderstack.com"  # Bloklamak için
    ]

    # Warp ile ilgili olmayan istekleri sessizce geçir (internet erişimini engelleme)
    if not any(domain in flow.request.pretty_host for domain in relevant_domains):
        return False

    return True

@concurrent
def request(flow: http.HTTPFlow) -> None:
    """İstek yakalandığında çalışır"""

    # İlgisiz istekleri hemen filtrele - sessizce geç (internet erişimine müdahale etme)
    if not is_relevant_request(flow):
        # Warp ile ilgili olmayan tüm trafiği direkt geçir
        return

    request_url = flow.request.pretty_url

    # *.dataplane.rudderstack.com isteklerini blokla
    if "dataplane.rudderstack.com" in flow.request.pretty_host:
        print(f"🚫 Rudderstack isteği bloklandı: {request_url}")
        flow.response = http.Response.make(
            204,  # No Content
            b"",
            {"Content-Type": "text/plain"}
        )
        return

    print(f"🌐 Warp isteği: {flow.request.method} {flow.request.pretty_url}")

    # CreateGenericStringObject isteği tespiti - user_settings.json güncelleme trigger'ı
    if ("/graphql/v2?op=CreateGenericStringObject" in request_url and
        flow.request.method == "POST"):
        print("🔄 CreateGenericStringObject isteği tespit edildi - user_settings.json güncelleniyor...")
        handler.refresh_user_settings()

    # Hesap değişiklik trigger kontrolü (her request'te)
    if handler.check_account_change_trigger():
        print("🔄 Trigger tespit edildi ve token güncellendi!")

    # Aktif hesap bilgisini göster
    print(f"📧 Şu anki aktif hesap: {handler.active_email}")

    # Her dakika token kontrolü yap
    current_time = time.time()
    if current_time - handler.last_token_check > 60:  # 60 saniye
        print("⏰ Token kontrol zamanı geldi, güncelleniyor...")
        handler.update_active_token()
        handler.last_token_check = current_time

    # Aktif hesap kontrolü
    if not handler.active_email:
        print("❓ Aktif hesap bulunamadı, token kontrol ediliyor...")
        handler.update_active_token()

    # Authorization header'ını değiştir
    if handler.active_token:
        old_auth = flow.request.headers.get("Authorization", "Yok")
        new_auth = f"Bearer {handler.active_token}"
        flow.request.headers["Authorization"] = new_auth

        print(f"🔑 Authorization header güncellendi: {handler.active_email}")

        # Token'ların gerçekten farklı olup olmadığını kontrol et
        if old_auth == new_auth:
            print("   ⚠️  UYARI: Eski ve yeni token AYNI!")
        else:
            print("   ✅ Token başarıyla değiştirildi")

        # Token'ın son kısmını da göster
        if len(handler.active_token) > 100:
            print(f"   Token sonu: ...{handler.active_token[-20:]}")

    else:
        print("❌ AKTİF TOKEN BULUNAMADI - HEADER DEĞİŞTİRİLMEDİ!")
        print(f"   Aktif email: {handler.active_email}")
        print(f"   Token durumu: {handler.active_token is not None}")

    # Tüm app.warp.dev istekleri için X-Warp-Experiment-Id header'ını kontrol et ve randomize et
    existing_experiment_id = flow.request.headers.get("X-Warp-Experiment-Id")
    if existing_experiment_id:
        new_experiment_id = generate_experiment_id()
        flow.request.headers["X-Warp-Experiment-Id"] = new_experiment_id

        print(f"🧪 Experiment ID değiştirildi ({flow.request.path}):")

def responseheaders(flow: http.HTTPFlow) -> None:
    """Response headers alındığında çalışır - streaming'i kontrol eder"""
    # İlgisiz istekleri hemen filtrele - sessizce geç
    if not is_relevant_request(flow):
        return

    # /ai/multi-agent endpoint'i için streaming'i etkinleştir
    if "/ai/multi-agent" in flow.request.path:
        flow.response.stream = True
        print(f"[{time.strftime('%H:%M:%S')}] Streaming etkinleştirildi: {flow.request.pretty_url}")
    else:
        flow.response.stream = False

@concurrent
def response(flow: http.HTTPFlow) -> None:
    """Yanıt alındığında çalışır"""

    # Firebase token yenileme isteklerini User-Agent ile kontrol et
    if ("securetoken.googleapis.com" in flow.request.pretty_host and
        flow.request.headers.get("User-Agent") == "WarpAccountManager/1.0"):
        return

    # Sadece app.warp.dev domainini işle
    if "app.warp.dev" not in flow.request.pretty_host:
        return

    # İlgisiz istekleri hemen filtrele - sessizce geç (internet erişimine müdahale etme)
    if not is_relevant_request(flow):
        return

    # WarpAccountManager'dan gelen istekleri hariç tut
    if flow.request.headers.get("X-Warp-Manager-Request") == "true":
        return

    print(f"📡 Warp yanıtı: {flow.response.status_code} - {flow.request.pretty_url}")

    # GetUpdatedCloudObjects isteği için cached response kullan
    if ("/graphql/v2?op=GetUpdatedCloudObjects" in flow.request.pretty_url and
        flow.request.method == "POST" and
        flow.response.status_code == 200 and
        handler.user_settings_cache is not None):
        print("🔄 GetUpdatedCloudObjects response'u cached veriler ile değiştiriliyor...")
        try:
            # Cached veriyi JSON string'e çevir
            cached_response = json.dumps(handler.user_settings_cache, ensure_ascii=False)

            # Response'u değiştir
            flow.response.content = cached_response.encode('utf-8')
            flow.response.headers["Content-Length"] = str(len(flow.response.content))
            flow.response.headers["Content-Type"] = "application/json"

            print("✅ GetUpdatedCloudObjects response'u başarıyla değiştirildi")
        except Exception as e:
            print(f"❌ Response değiştirme hatası: {e}")

    # /ai/multi-agent endpoint'inde 403 hatası - hesap banlanmış
    if "/ai/multi-agent" in flow.request.path and flow.response.status_code == 403:
        print("⛔ 403 FORBIDDEN - Hesap banlanmış tespit edildi!")
        if handler.active_email:
            print(f"Banlanmış hesap: {handler.active_email}")
            handler.mark_account_as_banned(handler.active_email)
        else:
            print("Aktif hesap bulunamadı, ban işareti konulamadı")

    # Eğer 401 hatası alındıysa token yenilemeyi dene
    if flow.response.status_code == 401:
        print("401 hatası alındı, token yenileniyor...")
        if handler.update_active_token():
            print("Token yenilendi, isteği tekrar dene")

# Başlangıçta aktif hesabı yükle
def load(loader):
    """Script başladığında çalışır"""
    print("Warp Proxy Script başlatıldı")
    print("Veritabanı bağlantısı kontrol ediliyor...")
    handler.update_active_token()
    if handler.active_email:
        print(f"Aktif hesap yüklendi: {handler.active_email}")
        print(f"Token var: {handler.active_token is not None}")
    else:
        print("Aktif hesap bulunamadı - Bir hesabı aktif etmeyi unutmayın!")

    # user_settings.json dosyasını yükle
    print("user_settings.json dosyası yükleniyor...")
    handler.load_user_settings()

def done():
    """Script durdurulduğunda çalışır"""
    print("Warp Proxy Script durduruldu")
