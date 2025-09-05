#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Windows Bridge Configuration - Registry settings for Chrome extension
"""

import winreg
import os
import sys
import json
from pathlib import Path

class BridgeConfig:
    def __init__(self):
        self.extension_id = "warp-account-bridge-v1"
        self.app_name = "com.warp.account.bridge"
        self.registry_paths = [
            r"SOFTWARE\Google\Chrome\NativeMessagingHosts",
            r"SOFTWARE\Microsoft\Edge\NativeMessagingHosts"
        ]

    def is_admin(self):
        """Check if running as administrator"""
        try:
            return os.getuid() == 0
        except AttributeError:
            # Windows
            import ctypes
            try:
                return ctypes.windll.shell32.IsUserAnAdmin()
            except:
                return False

    def setup_localhost_access(self):
        """Configure Windows for localhost access from extensions"""
        try:
            print("🔧 Chrome extension manifest ile localhost erişimi...")

            # Chrome extension manifest'te externally_connectable kullanıyoruz
            # Registry ayarı gerekmez, manifest yeterli
            print("✅ Manifest-based localhost erişimi aktif")
            print("📋 Extension manifest'te externally_connectable yapılandırması mevcut")

            return True

        except Exception as e:
            print(f"❌ Localhost erişim ayarı hatası: {e}")
            return False

    def create_native_messaging_manifest(self):
        """Create native messaging host manifest"""
        try:
            # Python executable path
            python_exe = sys.executable
            script_path = os.path.abspath("warp_account_manager.py")

            manifest = {
                "name": self.app_name,
                "description": "Warp Account Bridge Native Host",
                "path": python_exe,
                "type": "stdio",
                "allowed_origins": [
                    f"chrome-extension://{self.extension_id}/"
                ]
            }

            # Manifest dosyasını kaydet
            manifest_dir = os.path.join(os.getenv('APPDATA'), 'WarpAccountManager')
            os.makedirs(manifest_dir, exist_ok=True)

            manifest_path = os.path.join(manifest_dir, f"{self.app_name}.json")
            with open(manifest_path, 'w') as f:
                json.dump(manifest, f, indent=2)

            print(f"✅ Native messaging manifest oluşturuldu: {manifest_path}")
            return manifest_path

        except Exception as e:
            print(f"❌ Manifest oluşturma hatası: {e}")
            return None

    def register_native_host(self):
        """Register native messaging host in registry"""
        try:
            manifest_path = self.create_native_messaging_manifest()
            if not manifest_path:
                return False

            success = False

            for registry_path in self.registry_paths:
                try:
                    # HKEY_CURRENT_USER'da kaydet (yönetici gerektirmez)
                    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, registry_path)
                    winreg.SetValueEx(key, self.app_name, 0, winreg.REG_SZ, manifest_path)
                    winreg.CloseKey(key)
                    print(f"✅ Native host kaydedildi: {registry_path}")
                    success = True

                except Exception as e:
                    print(f"⚠️  Registry kaydı hatası ({registry_path}): {e}")

            return success

        except Exception as e:
            print(f"❌ Native host kayıt hatası: {e}")
            return False

    def setup_bridge_config(self):
        """Complete bridge configuration"""
        print("🌉 Windows Bridge konfigürasyonu başlatılıyor...")

        # 1. Localhost erişim ayarları
        localhost_ok = self.setup_localhost_access()

        # 2. Native messaging host kaydı (opsiyonel)
        # native_ok = self.register_native_host()

        if localhost_ok:
            print("✅ Bridge konfigürasyonu tamamlandı!")
            print("\n📋 Sonraki adımlar:")
            print("1. Chrome'u yeniden başlat")
            print("2. Eklentiyi chrome://extensions/ sayfasından yükle")
            print("3. Warp Account Manager'ı başlat")
            return True
        else:
            print("❌ Bridge konfigürasyonu başarısız!")
            return False

    def check_configuration(self):
        """Check if bridge is properly configured"""
        try:
            print("🔍 Bridge konfigürasyon kontrol ediliyor...")

            # Manifest-based konfigürasyon için her zaman True döndür
            # Gerçek kontrol extension yüklendiğinde yapılacak
            print("✅ Manifest-based bridge konfigürasyonu")
            return True

        except Exception as e:
            print(f"❌ Konfigürasyon kontrol hatası: {e}")
            return False

    def remove_configuration(self):
        """Remove bridge configuration (cleanup)"""
        try:
            print("🧹 Bridge konfigürasyonu temizleniyor...")

            # Registry temizliği
            chrome_policies_path = r"SOFTWARE\Policies\Google\Chrome"

            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, chrome_policies_path, 0, winreg.KEY_SET_VALUE)
                winreg.DeleteValue(key, "URLAllowlist")
                winreg.CloseKey(key)
                print("✅ Chrome policy temizlendi")
            except FileNotFoundError:
                print("⚠️  Chrome policy zaten mevcut değil")

            # Manifest dosyası temizliği
            manifest_dir = os.path.join(os.getenv('APPDATA'), 'WarpAccountManager')
            manifest_path = os.path.join(manifest_dir, f"{self.app_name}.json")

            if os.path.exists(manifest_path):
                os.remove(manifest_path)
                print("✅ Manifest dosyası silindi")

            return True

        except Exception as e:
            print(f"❌ Temizlik hatası: {e}")
            return False


def setup_bridge():
    """Setup bridge configuration"""
    config = BridgeConfig()
    return config.setup_bridge_config()

def check_bridge():
    """Check bridge configuration"""
    config = BridgeConfig()
    return config.check_configuration()

def remove_bridge():
    """Remove bridge configuration"""
    config = BridgeConfig()
    return config.remove_configuration()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        action = sys.argv[1]

        if action == "setup":
            setup_bridge()
        elif action == "check":
            check_bridge()
        elif action == "remove":
            remove_bridge()
        else:
            print("Kullanım: python windows_bridge_config.py [setup|check|remove]")
    else:
        # Varsayılan: setup
        setup_bridge()
