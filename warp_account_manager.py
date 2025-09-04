#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import json
import sqlite3
import requests
import time
import subprocess
import os
try:
    import winreg  # Windows-only
except Exception:
    winreg = None
import psutil
import urllib3
from pathlib import Path
from datetime import datetime, timezone
from languages import get_language_manager, _
from warp_bridge_server import WarpBridgeServer
try:
    from windows_bridge_config import WindowsBridgeConfig  # Windows-only
except Exception:
    WindowsBridgeConfig = None
import platform
IS_WINDOWS = sys.platform == "win32"

# SSL uyarılarını gizle (mitmproxy kullanırken)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
                             QWidget, QPushButton, QTableWidget, QTableWidgetItem,
                             QDialog, QTextEdit, QLabel, QMessageBox, QHeaderView,
                             QProgressDialog, QAbstractItemView, QStatusBar, QMenu, QAction, QScrollArea, QComboBox, QTabWidget)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QObject
from PyQt5.QtGui import QFont


def load_stylesheet(app):
    """Modern, kompakt QSS stilini uygular (varsa)."""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        style_path = os.path.join(base_dir, "style.qss")
        if os.path.exists(style_path):
            with open(style_path, "r", encoding="utf-8") as f:
                app.setStyleSheet(f.read())
    except Exception as e:
        print(f"{_('stylesheet_load_error', e)}")


class AccountManager:
    def __init__(self):
        self.db_path = "accounts.db"
        self.init_database()

    def init_database(self):
        """Veritabanını başlat ve tabloları oluştur"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                account_data TEXT NOT NULL,
                health_status TEXT DEFAULT 'healthy',
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Mevcut tabloya health_status sütunu ekle (eğer yoksa)
        try:
            cursor.execute('ALTER TABLE accounts ADD COLUMN health_status TEXT DEFAULT "healthy"')
        except sqlite3.OperationalError:
            # Sütun zaten var
            pass

        # Mevcut tabloya limit_info sütunu ekle (eğer yoksa)
        try:
            cursor.execute('ALTER TABLE accounts ADD COLUMN limit_info TEXT DEFAULT "Güncellenmedi"')
        except sqlite3.OperationalError:
            # Sütun zaten var
            pass
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS proxy_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')

        # Sertifika onay durumu için varsayılan değer ekle
        cursor.execute('''
            INSERT OR IGNORE INTO proxy_settings (key, value)
            VALUES ('certificate_approved', 'false')
        ''')
        conn.commit()
        conn.close()

    def add_account(self, account_json):
        """Hesap ekle"""
        try:
            account_data = json.loads(account_json)
            email = account_data.get('email')

            if not email:
                raise ValueError(_('email_not_found'))

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO accounts (email, account_data, last_updated)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (email, account_json))
            conn.commit()
            conn.close()
            return True, _('account_added_success')
        except json.JSONDecodeError:
            return False, _('invalid_json')
        except Exception as e:
            return False, f"{_('error')}: {str(e)}"

    def get_accounts(self):
        """Tüm hesapları getir"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT email, account_data FROM accounts ORDER BY email')
        accounts = cursor.fetchall()
        conn.close()
        return accounts

    def get_accounts_with_health(self):
        """Tüm hesapları sağlık durumu ile birlikte getir"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT email, account_data, health_status FROM accounts ORDER BY email')
        accounts = cursor.fetchall()
        conn.close()
        return accounts

    def update_account_health(self, email, health_status):
        """Hesabın sağlık durumunu güncelle"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE accounts SET health_status = ?, last_updated = CURRENT_TIMESTAMP
                WHERE email = ?
            ''', (health_status, email))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Sağlık durumu güncelleme hatası: {e}")
            return False

    def update_account_token(self, email, new_token_data):
        """Hesabın token bilgilerini güncelle"""
        try:
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
            print(f"Token güncelleme hatası: {e}")
            return False

    def update_account(self, email, updated_json):
        """Hesabın tüm bilgilerini güncelle (JSON string olarak)"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE accounts SET account_data = ?, last_updated = CURRENT_TIMESTAMP
                WHERE email = ?
            ''', (updated_json, email))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Hesap güncelleme hatası: {e}")
            return False

    def set_active_account(self, email):
        """Aktif hesabı ayarla"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO proxy_settings (key, value)
                VALUES ('active_account', ?)
            ''', (email,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Aktif hesap ayarlama hatası: {e}")
            return False

    def get_active_account(self):
        """Aktif hesabı getir"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM proxy_settings WHERE key = ?', ('active_account',))
            result = cursor.fetchone()
            conn.close()
            return result[0] if result else None
        except:
            return None

    def clear_active_account(self):
        """Aktif hesabı temizle"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM proxy_settings WHERE key = ?', ('active_account',))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Aktif hesap temizleme hatası: {e}")
            return False

    def delete_account(self, email):
        """Hesabı sil"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Hesabı sil
            cursor.execute('DELETE FROM accounts WHERE email = ?', (email,))

            # Eğer silinen hesap aktif hesapsa, aktif hesabı da temizle
            cursor.execute('SELECT value FROM proxy_settings WHERE key = ?', ('active_account',))
            result = cursor.fetchone()
            if result and result[0] == email:
                cursor.execute('DELETE FROM proxy_settings WHERE key = ?', ('active_account',))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Hesap silme hatası: {e}")
            return False

    def update_account_limit_info(self, email, limit_info):
        """Hesabın limit bilgilerini güncelle"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE accounts SET limit_info = ?, last_updated = CURRENT_TIMESTAMP
                WHERE email = ?
            ''', (limit_info, email))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Limit bilgisi güncelleme hatası: {e}")
            return False

    def get_accounts_with_health_and_limits(self):
        """Tüm hesapları sağlık durumu ve limit bilgisi ile birlikte getir"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT email, account_data, health_status, limit_info FROM accounts ORDER BY email')
        accounts = cursor.fetchall()
        conn.close()
        return accounts

    def is_certificate_approved(self):
        """Sertifika onayının daha önce verilip verilmediğini kontrol et"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM proxy_settings WHERE key = ?', ('certificate_approved',))
            result = cursor.fetchone()
            conn.close()
            return result and result[0] == 'true'
        except:
            return False

    def set_certificate_approved(self, approved=True):
        """Sertifika onayını veritabanına kaydet"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO proxy_settings (key, value)
                VALUES ('certificate_approved', ?)
            ''', ('true' if approved else 'false',))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Sertifika onay kaydetme hatası: {e}")
            return False


class WindowsProxyManager:
    """Windows proxy ayarlarını yönetir"""

    @staticmethod
    def set_proxy(proxy_server):
        """Windows proxy ayarını etkinleştir"""
        if not IS_WINDOWS or winreg is None:
            # On non-Windows, do nothing and report success (handled by env/proxy settings)
            return True
        try:
            # Registry anahtarını aç
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                               0, winreg.KEY_SET_VALUE)

            # Proxy ayarlarını yap
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, proxy_server)

            winreg.CloseKey(key)

            # Internet Explorer ayarlarını yenile (sessizce)
            try:
                subprocess.run(["rundll32.exe", "wininet.dll,InternetSetOption", "0", "37", "0", "0"],
                             shell=True, capture_output=True, timeout=5)
            except:
                # Eğer sessiz yenileme çalışmazsa, kullanıcıya bilgi ver
                pass

            return True
        except Exception as e:
            print(f"Proxy ayarlama hatası: {e}")
            return False

    @staticmethod
    def disable_proxy():
        """Windows proxy ayarını devre dışı bırak"""
        if not IS_WINDOWS or winreg is None:
            return True
        try:
            # Registry anahtarını aç
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                               0, winreg.KEY_SET_VALUE)

            # Proxy'yi devre dışı bırak
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)

            winreg.CloseKey(key)
            return True
        except Exception as e:
            print(f"Proxy devre dışı bırakma hatası: {e}")
            return False

    @staticmethod
    def is_proxy_enabled():
        """Proxy'nin etkin olup olmadığını kontrol et"""
        if not IS_WINDOWS or winreg is None:
            return False
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                               0, winreg.KEY_READ)

            proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
            winreg.CloseKey(key)

            return bool(proxy_enable)
        except:
            return False


class CertificateManager:
    """Mitmproxy sertifika yönetimi"""

    def __init__(self):
        self.mitmproxy_dir = Path.home() / ".mitmproxy"
        # Windows uses .cer, Linux commonly uses .pem
        self.cert_file = self.mitmproxy_dir / ("mitmproxy-ca-cert.cer" if IS_WINDOWS else "mitmproxy-ca-cert.pem")

    def check_certificate_exists(self):
        """Sertifika dosyası var mı kontrol et"""
        return self.cert_file.exists()

    def get_certificate_path(self):
        """Sertifika dosya yolunu döndür"""
        return str(self.cert_file)



    def install_certificate_automatically(self):
        """Sertifikayı otomatik olarak sisteme kur (Windows). Linux'ta sadece yol göster."""
        try:
            cert_path = self.get_certificate_path()
            if not self.check_certificate_exists():
                print(_('certificate_not_found'))
                return False

            print(_('cert_installing'))

            if IS_WINDOWS:
                # certutil komutu ile sertifikayı root store'a ekle
                cmd = ["certutil", "-addstore", "root", cert_path]
                result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
                if result.returncode == 0:
                    print(_('cert_installed_success'))
                    return True
                else:
                    print(_('cert_install_error').format(result.stderr))
                    return False
            else:
                # Linux: kullanıcıya manuel adımları göster (system-wide CA store değişkenlik gösterir)
                print("Linux: Please trust mitmproxy certificate manually, e.g. for Firefox/Chrome profile.")
                print(f"Certificate path: {cert_path}")
                return True

        except Exception as e:
            print(_('cert_install_error').format(str(e)))
            return False


class MitmProxyManager:
    """Mitmproxy sürecini yönetir"""

    def __init__(self):
        self.process = None
        self.port = 8080  # Orijinal port
        self.script_path = "warp_proxy_script.py"  # Asıl script'i kullanıyoruz
        self.debug_mode = True
        self.cert_manager = CertificateManager()

    def start(self, parent_window=None):
        """Mitmproxy'yi başlat"""
        try:
            if self.is_running():
                print("Mitmproxy zaten çalışıyor")
                return True

            # İlk çalıştırmada sertifika kontrolü yap
            if not self.cert_manager.check_certificate_exists():
                print(_('cert_creating'))

                # Sertifika oluşturmak için kısa bir mitmproxy çalıştır
                temp_cmd = ["mitmdump", "--set", "confdir=~/.mitmproxy", "-q"]
                try:
                    if parent_window:
                        parent_window.status_bar.showMessage(_('cert_creating'), 0)

                    popen_kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
                    if IS_WINDOWS and hasattr(subprocess, "CREATE_NO_WINDOW"):
                        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                    temp_process = subprocess.Popen(temp_cmd, **popen_kwargs)

                    # 5 saniye bekle ve süreci sonlandır
                    time.sleep(5)
                    temp_process.terminate()
                    temp_process.wait(timeout=3)

                    print("✅ Sertifika oluşturma tamamlandı")

                except Exception as e:
                    print(f"❌ Sertifika oluşturma hatası: {e}")

                # Sertifika oluştu mu kontrol et
                if not self.cert_manager.check_certificate_exists():
                    if parent_window:
                        parent_window.status_bar.showMessage(_('cert_creation_failed'), 5000)
                    return False
                else:
                    print(_('cert_created_success'))

            # Sertifika otomatik kurulumu
            if parent_window and not parent_window.account_manager.is_certificate_approved():
                print(_('cert_installing'))

                # Sertifikayı otomatik kur
                if self.cert_manager.install_certificate_automatically():
                    # Sertifika başarıyla kurulduysa onayı kaydet
                    parent_window.account_manager.set_certificate_approved(True)
                    parent_window.status_bar.showMessage(_('cert_installed_success'), 3000)
                else:
                    # Otomatik kurulum başarısız - manuel kurulum dialogu göster
                    dialog_result = self.show_manual_certificate_dialog(parent_window)
                    if dialog_result:
                        # Kullanıcı kurulumu tamamladı dedi
                        parent_window.account_manager.set_certificate_approved(True)
                    else:
                        return False


            # Mitmproxy komutunu hazırla
            cmd = [
                "mitmdump",
                "--listen-host", "127.0.0.1",  # IPv4'te dinle
                "-p", str(self.port),
                "-s", self.script_path,
                "--set", "confdir=~/.mitmproxy",
                "--set", "keep_host_header=true",    # Host header'ı koru
            ]

            print(f"Mitmproxy komutu: {' '.join(cmd)}")

            # Süreç başlat - debug moduna göre konsol penceresi
            if sys.platform == "win32":
                cmd_str = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in cmd)

                if self.debug_mode:
                    # Debug modu: Konsol penceresi görünür
                    print("Debug modu aktif - Mitmproxy konsol penceresi açılacak")
                    self.process = subprocess.Popen(
                        f'start "Mitmproxy Console (Debug)" cmd /k "{cmd_str}"',
                        shell=True
                    )
                else:
                    # Normal mod: Konsol penceresi gizli
                    print("Normal mod - Mitmproxy arka planda çalışacak")
                    self.process = subprocess.Popen(
                        cmd_str,
                        shell=True,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )

                # Windows'ta start komutu hemen döner, bu yüzden port kontrolü yapalım
                print("Mitmproxy başlatılıyor, port kontrol ediliyor...")
                for i in range(10):  # 10 saniye bekle
                    time.sleep(1)
                    if self.is_port_open("127.0.0.1", self.port):
                        print(f"Mitmproxy başarıyla başlatıldı - Port {self.port} açık")
                        return True
                    print(f"Port kontrol ediliyor... ({i+1}/10)")

                print("Mitmproxy başlatılamadı - port açılmadı")
                return False
            else:
                # Linux/Mac için normal başlatma
                self.process = subprocess.Popen(cmd)
                time.sleep(3)
                if self.process.poll() is None:
                    print(f"Mitmproxy başlatıldı (PID: {self.process.pid})")
                    return True
                else:
                    print("Mitmproxy başlatılamadı")
                    return False

        except Exception as e:
            print(f"Mitmproxy başlatma hatası: {e}")
            return False

    def stop(self):
        """Mitmproxy'yi durdur"""
        try:
            if self.process and self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=10)
                print("Mitmproxy durduruldu")
                return True

            # Eğer süreç referansı yoksa PID ile bul ve durdur
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if 'mitmdump' in proc.info['name'] and str(self.port) in ' '.join(proc.info['cmdline']):
                        proc.terminate()
                        proc.wait(timeout=10)
                        print(f"Mitmproxy durduruldu (PID: {proc.info['pid']})")
                        return True
                except:
                    continue

            return True
        except Exception as e:
            print(f"Mitmproxy durdurma hatası: {e}")
            return False

    def is_running(self):
        """Mitmproxy'nin çalışıp çalışmadığını kontrol et"""
        try:
            if self.process and self.process.poll() is None:
                return True

            # PID ile kontrol et
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if 'mitmdump' in proc.info['name'] and str(self.port) in ' '.join(proc.info['cmdline']):
                        return True
                except:
                    continue
            return False
        except:
            return False

    def get_proxy_url(self):
        """Proxy URL'ini döndür"""
        return f"127.0.0.1:{self.port}"

    def is_port_open(self, host, port):
        """Port'un açık olup olmadığını kontrol et"""
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except:
            return False

    def show_manual_certificate_dialog(self, parent_window):
        """Manuel sertifika kurulum dialogu göster"""
        try:
            dialog = ManualCertificateDialog(self.cert_manager.get_certificate_path(), parent_window)
            return dialog.exec_() == QDialog.Accepted
        except Exception as e:
            print(f"Manuel sertifika dialog hatası: {e}")
            return False


class ManualCertificateDialog(QDialog):
    """Manuel sertifika kurulum dialogu"""

    def __init__(self, cert_path, parent=None):
        super().__init__(parent)
        self.cert_path = cert_path
        self.setWindowTitle(_('cert_manual_title'))
        self.setGeometry(300, 300, 650, 550)
        self.setModal(True)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Başlık
        title = QLabel(_('cert_manual_title'))
        title.setFont(QFont("Arial", 14, QFont.Bold))
        title.setStyleSheet("color: #d32f2f; margin-bottom: 10px;")
        layout.addWidget(title)

        # Açıklama
        explanation = QLabel(_('cert_manual_explanation'))
        explanation.setWordWrap(True)
        explanation.setStyleSheet("background: #fff3cd; padding: 15px; border-radius: 8px; border: 1px solid #ffeaa7;")
        layout.addWidget(explanation)

        # Sertifika yolu
        path_label = QLabel(_('cert_manual_path'))
        path_label.setFont(QFont("Arial", 10, QFont.Bold))
        layout.addWidget(path_label)

        path_display = QLabel(self.cert_path)
        path_display.setStyleSheet("""
            background: #f5f5f5;
            padding: 10px;
            border-radius: 5px;
            border: 1px solid #ddd;
            font-family: 'Courier New', monospace;
            font-size: 11px;
        """)
        path_display.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(path_display)

        # Adımlar
        steps_label = QLabel(_('cert_manual_steps'))
        steps_label.setWordWrap(True)
        steps_label.setStyleSheet("background: white; padding: 15px; border-radius: 8px; border: 1px solid #ddd;")
        layout.addWidget(steps_label)

        # Butonlar
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        # Klasör aç butonu
        self.open_folder_button = QPushButton(_('cert_open_folder'))
        self.open_folder_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.open_folder_button.clicked.connect(self.open_certificate_folder)

        # Kurulum tamamlandı butonu
        self.completed_button = QPushButton(_('cert_manual_complete'))
        self.completed_button.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        self.completed_button.clicked.connect(self.accept)

        # İptal butonu
        cancel_button = QPushButton(_('cancel'))
        cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        cancel_button.clicked.connect(self.reject)

        button_layout.addWidget(self.open_folder_button)
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(self.completed_button)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def open_certificate_folder(self):
        """Sertifika klasörünü dosya gezgininde aç"""
        try:
            import os
            cert_dir = os.path.dirname(self.cert_path)
            if os.path.exists(cert_dir):
                if IS_WINDOWS:
                    subprocess.Popen(['explorer', cert_dir])
                elif sys.platform == 'darwin':
                    subprocess.Popen(['open', cert_dir])
                else:
                    subprocess.Popen(['xdg-open', cert_dir])
            else:
                QMessageBox.warning(self, _('error'), _('certificate_not_found'))
        except Exception as e:
            QMessageBox.warning(self, _('error'), _('file_open_error').format(str(e)))


class TokenWorker(QThread):
    """Tekil token yenileme işlemlerini arka planda yapar"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)  # success, message
    error = pyqtSignal(str)

    def __init__(self, email, account_data, proxy_enabled=False):
        super().__init__()
        self.email = email
        self.account_data = account_data
        self.account_manager = AccountManager()
        self.proxy_enabled = proxy_enabled

    def run(self):
        try:
            self.progress.emit(f"Token yenileniyor: {self.email}")

            if self.refresh_token():
                self.account_manager.update_account_health(self.email, 'healthy')
                self.finished.emit(True, f"{self.email} tokeni başarıyla yenilendi")
            else:
                self.account_manager.update_account_health(self.email, 'unhealthy')
                self.finished.emit(False, f"{self.email} tokeni yenilenemedi")

        except Exception as e:
            self.error.emit(f"Token yenileme hatası: {str(e)}")

    def refresh_token(self):
        """Firebase token yenileme"""
        try:
            refresh_token = self.account_data['stsTokenManager']['refreshToken']
            api_key = self.account_data['apiKey']

            url = f"https://securetoken.googleapis.com/v1/token?key={api_key}"
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'WarpAccountManager/1.0'
            }
            data = {
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token
            }

            # Proxy kullanmadan direkt bağlan
            proxies = {'http': None, 'https': None} if self.proxy_enabled else None
            response = requests.post(url, json=data, headers=headers, timeout=30,
                                   verify=not self.proxy_enabled, proxies=proxies)

            if response.status_code == 200:
                token_data = response.json()
                new_token_data = {
                    'accessToken': token_data['access_token'],
                    'refreshToken': token_data['refresh_token'],
                    'expirationTime': int(time.time() * 1000) + (int(token_data['expires_in']) * 1000)
                }

                return self.account_manager.update_account_token(self.email, new_token_data)
            return False
        except Exception as e:
            print(f"Token yenileme hatası: {e}")
            return False


class TokenRefreshWorker(QThread):
    """Token yenileme ve limit getirme işlemlerini arka planda yapar"""
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, accounts, proxy_enabled=False):
        super().__init__()
        self.accounts = accounts
        self.account_manager = AccountManager()
        self.proxy_enabled = proxy_enabled

    def run(self):
        results = []
        total_accounts = len(self.accounts)

        for i, (email, account_json, health_status) in enumerate(self.accounts):
            try:
                self.progress.emit(int((i / total_accounts) * 100), _('processing_account', email))

                # Banlanmış hesapları hariç tut
                if health_status == _('status_banned_key'):
                    self.account_manager.update_account_limit_info(email, _('status_na'))
                    results.append((email, _('status_banned'), _('status_na')))
                    continue

                account_data = json.loads(account_json)

                # Token süresini kontrol et
                expiration_time = account_data['stsTokenManager']['expirationTime']
                current_time = int(time.time() * 1000)

                if current_time >= expiration_time:
                    # Token süresi dolmuş, yenile
                    self.progress.emit(int((i / total_accounts) * 100), _('refreshing_token', email))
                    if not self.refresh_token(email, account_data):
                        # Token yenilenemedi - sağlıksız olarak işaretle
                        self.account_manager.update_account_health(email, _('status_unhealthy'))
                        self.account_manager.update_account_limit_info(email, _('status_na'))
                        results.append((email, _('token_refresh_failed', email), _('status_na')))
                        continue

                    # Güncellenmiş account_data'yı al
                    updated_accounts = self.account_manager.get_accounts()
                    for updated_email, updated_json in updated_accounts:
                        if updated_email == email:
                            account_data = json.loads(updated_json)
                            break

                # Limit bilgilerini getir
                limit_info = self.get_limit_info(account_data)
                if limit_info:
                    used = limit_info.get('requestsUsedSinceLastRefresh', 0)
                    total = limit_info.get('requestLimit', 0)
                    limit_text = f"{used}/{total}"
                    # Başarılı - sağlıklı olarak işaretle ve limit bilgisini kaydet
                    self.account_manager.update_account_health(email, _('status_healthy'))
                    self.account_manager.update_account_limit_info(email, limit_text)
                    results.append((email, _('success'), limit_text))
                else:
                    # Limit bilgisi alınamadı - sağlıksız olarak işaretle
                    self.account_manager.update_account_health(email, _('status_unhealthy'))
                    self.account_manager.update_account_limit_info(email, _('status_na'))
                    results.append((email, _('limit_info_failed'), _('status_na')))

            except Exception as e:
                self.account_manager.update_account_limit_info(email, _('status_na'))
                results.append((email, f"{_('error')}: {str(e)}", _('status_na')))

        self.finished.emit(results)

    def refresh_token(self, email, account_data):
        """Firebase token yenileme"""
        try:
            refresh_token = account_data['stsTokenManager']['refreshToken']
            api_key = account_data['apiKey']

            url = f"https://securetoken.googleapis.com/v1/token?key={api_key}"
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'WarpAccountManager/1.0'  # Özel User-Agent ile işaretliyoruz
            }
            data = {
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token
            }

            # Proxy kullanmadan direkt bağlan
            proxies = {'http': None, 'https': None} if self.proxy_enabled else None
            response = requests.post(url, json=data, headers=headers, timeout=30,
                                   verify=not self.proxy_enabled, proxies=proxies)

            if response.status_code == 200:
                token_data = response.json()
                new_token_data = {
                    'accessToken': token_data['access_token'],
                    'refreshToken': token_data['refresh_token'],
                    'expirationTime': int(time.time() * 1000) + (int(token_data['expires_in']) * 1000)
                }

                return self.account_manager.update_account_token(email, new_token_data)
            return False
        except Exception as e:
            print(f"Token yenileme hatası: {e}")
            return False

    def get_limit_info(self, account_data):
        """Warp API'den limit bilgilerini getir"""
        try:
            access_token = account_data['stsTokenManager']['accessToken']

            url = "https://app.warp.dev/graphql/v2?op=GetRequestLimitInfo"
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {access_token}',
                'X-Warp-Client-Version': 'v0.2025.08.27.08.11.stable_04',
                'X-Warp-Os-Category': ('Windows' if IS_WINDOWS else 'Linux'),
                'X-Warp-Os-Name': ('Windows' if IS_WINDOWS else 'Linux'),
                'X-Warp-Os-Version': ('10 (19045)' if IS_WINDOWS else platform.release()),
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate, br',
                'X-Warp-Manager-Request': 'true'  # Bizim uygulamamızdan gelen istek
            }

            query = """
            query GetRequestLimitInfo($requestContext: RequestContext!) {
              user(requestContext: $requestContext) {
                __typename
                ... on UserOutput {
                  user {
                    requestLimitInfo {
                      isUnlimited
                      nextRefreshTime
                      requestLimit
                      requestsUsedSinceLastRefresh
                      requestLimitRefreshDuration
                      isUnlimitedAutosuggestions
                      acceptedAutosuggestionsLimit
                      acceptedAutosuggestionsSinceLastRefresh
                      isUnlimitedVoice
                      voiceRequestLimit
                      voiceRequestsUsedSinceLastRefresh
                      voiceTokenLimit
                      voiceTokensUsedSinceLastRefresh
                      isUnlimitedCodebaseIndices
                      maxCodebaseIndices
                      maxFilesPerRepo
                      embeddingGenerationBatchSize
                    }
                  }
                }
                ... on UserFacingError {
                  error {
                    __typename
                    ... on SharedObjectsLimitExceeded {
                      limit
                      objectType
                      message
                    }
                    ... on PersonalObjectsLimitExceeded {
                      limit
                      objectType
                      message
                    }
                    ... on AccountDelinquencyError {
                      message
                    }
                    ... on GenericStringObjectUniqueKeyConflict {
                      message
                    }
                  }
                  responseContext {
                    serverVersion
                  }
                }
              }
            }
            """

            payload = {
                "query": query,
                "variables": {
                    "requestContext": {
                        "clientContext": {
                            "version": "v0.2025.08.27.08.11.stable_04"
                        },
                        "osContext": {
                            "category": ("Windows" if IS_WINDOWS else "Linux"),
                            "linuxKernelVersion": (None if IS_WINDOWS else platform.release()),
                            "name": ("Windows" if IS_WINDOWS else "Linux"),
                            "version": ("10 (19045)" if IS_WINDOWS else platform.release())
                        }
                    }
                },
                "operationName": "GetRequestLimitInfo"
            }

            # Proxy kullanmadan direkt bağlan
            proxies = {'http': None, 'https': None} if self.proxy_enabled else None
            response = requests.post(url, headers=headers, json=payload, timeout=30,
                                   verify=not self.proxy_enabled, proxies=proxies)

            if response.status_code == 200:
                data = response.json()
                if 'data' in data and 'user' in data['data']:
                    user_data = data['data']['user']
                    if user_data.get('__typename') == 'UserOutput':
                        return user_data['user']['requestLimitInfo']
            return None
        except Exception as e:
            print(f"Limit bilgisi alma hatası: {e}")
            return None


class AddAccountDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('add_account_title'))
        self.setGeometry(200, 200, 800, 600)
        self.init_ui()

    def init_ui(self):
        # Ana layout
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # Tab widget oluştur
        self.tab_widget = QTabWidget()

        # Manuel tab
        manual_tab = self.create_manual_tab()
        self.tab_widget.addTab(manual_tab, _('tab_manual'))

        # Otomatik tab
        auto_tab = self.create_auto_tab()
        self.tab_widget.addTab(auto_tab, _('tab_auto'))

        main_layout.addWidget(self.tab_widget)

        # Ana butonlar (her iki tab için ortak)
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)

        # Hesap oluşturma butonu (sol taraf)
        self.create_account_button = QPushButton(_('create_account'))
        self.create_account_button.setMinimumHeight(28)
        self.create_account_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.create_account_button.clicked.connect(self.open_account_creation_page)

        self.add_button = QPushButton(_('add'))
        self.add_button.setMinimumHeight(28)
        self.add_button.clicked.connect(self.accept)

        self.cancel_button = QPushButton(_('cancel'))
        self.cancel_button.setMinimumHeight(28)
        self.cancel_button.clicked.connect(self.reject)

        button_layout.addWidget(self.create_account_button)
        button_layout.addStretch()
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.cancel_button)

        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)

    def create_manual_tab(self):
        """Manuel JSON ekleme tabını oluştur"""
        tab_widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Başlık
        title_label = QLabel(_('manual_method_title'))
        title_label.setFont(QFont("Arial", 12, QFont.Bold))
        layout.addWidget(title_label)

        # Ana layout (sol-sağ)
        content_layout = QHBoxLayout()
        content_layout.setSpacing(12)

        # Sol panel (form)
        left_panel = QVBoxLayout()
        left_panel.setSpacing(8)

        # Açıklama
        instruction_label = QLabel(_('add_account_instruction'))
        instruction_label.setFont(QFont("Arial", 10))
        left_panel.addWidget(instruction_label)

        # Text edit
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText(_('add_account_placeholder'))
        left_panel.addWidget(self.text_edit)

        # Bilgi butonu
        self.info_button = QPushButton(_('how_to_get_json'))
        self.info_button.setMaximumWidth(220)
        self.info_button.clicked.connect(self.toggle_info_panel)
        left_panel.addWidget(self.info_button)

        content_layout.addLayout(left_panel, 1)

        # Sağ panel (info paneli) - başlangıçta gizli
        self.info_panel = self.create_info_panel()
        self.info_panel.hide()
        self.info_panel_visible = False
        content_layout.addWidget(self.info_panel, 1)

        layout.addLayout(content_layout)
        tab_widget.setLayout(layout)
        return tab_widget

    def create_auto_tab(self):
        """Chrome eklentisi otomatik ekleme tabını oluştur"""
        tab_widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Başlık
        title_label = QLabel(_('auto_method_title'))
        title_label.setFont(QFont("Arial", 12, QFont.Bold))
        layout.addWidget(title_label)

        # Scroll area
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout()
        scroll_layout.setContentsMargins(12, 12, 12, 12)
        scroll_layout.setSpacing(16)

        # Chrome eklentisi açıklaması
        chrome_title = QLabel(_('chrome_extension_title'))
        chrome_title.setFont(QFont("Arial", 11, QFont.Bold))
        scroll_layout.addWidget(chrome_title)

        chrome_desc = QLabel(_('chrome_extension_description'))
        chrome_desc.setWordWrap(True)
        chrome_desc.setStyleSheet("QLabel { color: #666; }")
        scroll_layout.addWidget(chrome_desc)

        # Adımlar
        steps_widget = QWidget()
        steps_widget.setStyleSheet("QWidget { background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 8px; padding: 12px; }")
        steps_layout = QVBoxLayout()
        steps_layout.setSpacing(8)

        steps = [
            _('chrome_extension_step_1'),
            _('chrome_extension_step_2'),
            _('chrome_extension_step_3'),
            _('chrome_extension_step_4')
        ]

        for step in steps:
            step_label = QLabel(step)
            step_label.setWordWrap(True)
            step_label.setStyleSheet("QLabel { margin: 4px 0; }")
            steps_layout.addWidget(step_label)

        steps_widget.setLayout(steps_layout)
        scroll_layout.addWidget(steps_widget)

        scroll_layout.addStretch()
        scroll_widget.setLayout(scroll_layout)
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)

        layout.addWidget(scroll_area)
        tab_widget.setLayout(layout)
        return tab_widget

    def create_info_panel(self):
        """Info panelini oluştur"""
        panel = QWidget()
        panel.setMaximumWidth(400)
        panel.setStyleSheet("QWidget { background-color: #f5f5f5; border: 1px solid #ddd; border-radius: 8px; padding: 8px; }")

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Başlık
        title = QLabel(_('json_info_title'))
        title.setFont(QFont("Arial", 11, QFont.Bold))
        layout.addWidget(title)

        # Adımlar
        steps_text = f"""
{_('step_1')}<br><br>
{_('step_2')}<br><br>
{_('step_3')}<br><br>
{_('step_4')}<br><br>
{_('step_5')}<br><br>
{_('step_6')}<br><br>
{_('step_7')}
        """

        steps_label = QLabel(steps_text)
        steps_label.setWordWrap(True)
        steps_label.setStyleSheet("QLabel { background: white; padding: 8px; border-radius: 4px; }")
        layout.addWidget(steps_label)

        # JavaScript kodu (gizli, sadece kopyala butonu)
        self.javascript_code = """(async () => {
  const request = indexedDB.open("firebaseLocalStorageDb");

  request.onsuccess = function (event) {
    const db = event.target.result;
    const tx = db.transaction("firebaseLocalStorage", "readonly");
    const store = tx.objectStore("firebaseLocalStorage");

    const getAllReq = store.getAll();

    getAllReq.onsuccess = function () {
      const results = getAllReq.result;

      // ilk kaydın value'sunu al
      const firstValue = results[0]?.value;
      console.log("Value (object):", firstValue);

      // JSON string'e çevir
      const valueString = JSON.stringify(firstValue, null, 2);

      // buton ekle
      const btn = document.createElement("button");
      btn.innerText = "-> Copy JSON <--";
      btn.style.position = "fixed";
      btn.style.top = "20px";
      btn.style.right = "20px";
      btn.style.zIndex = 9999;
      btn.onclick = () => {
        navigator.clipboard.writeText(valueString).then(() => {
          alert("Copied!");
        });
      };
      document.body.appendChild(btn);
    };
  };
})();"""

        # Kodu kopyala butonu
        self.copy_button = QPushButton(_('copy_javascript'))
        self.copy_button.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; border: none; padding: 8px; border-radius: 4px; font-weight: bold; }")
        self.copy_button.clicked.connect(self.copy_javascript_code)
        layout.addWidget(self.copy_button)

        layout.addStretch()
        panel.setLayout(layout)
        return panel

    def toggle_info_panel(self):
        """Info panelini aç/kapat"""
        self.info_panel_visible = not self.info_panel_visible

        if self.info_panel_visible:
            self.info_panel.show()
            self.info_button.setText(_('how_to_get_json_close'))
            # Dialog genişliğini artır
            self.resize(1100, 500)
        else:
            self.info_panel.hide()
            self.info_button.setText(_('how_to_get_json'))
            # Dialog genişliğini eski haline getir
            self.resize(700, 500)

    def copy_javascript_code(self):
        """JavaScript kodunu panoya kopyala"""
        try:
            from PyQt5.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(self.javascript_code)

            # Buton metnini geçici olarak değiştir
            original_text = self.copy_button.text()
            self.copy_button.setText(_('copied'))

            # 2 saniye sonra eski metne dön
            QTimer.singleShot(2000, lambda: self.copy_button.setText(original_text))

        except Exception as e:
            self.copy_button.setText(_('copy_error'))
            QTimer.singleShot(2000, lambda: self.copy_button.setText(_('copy_javascript')))

    def open_account_creation_page(self):
        """Hesap oluşturma sayfasını aç"""
        import webbrowser
        webbrowser.open("https://app.warp.dev/login/")

    def get_json_data(self):
        return self.text_edit.toPlainText().strip()


class HelpDialog(QDialog):
    """Yardım ve kullanım kılavuzu dialog'u"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('help_title'))
        self.setGeometry(250, 250, 700, 550)
        self.setModal(True)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Başlık
        title = QLabel(_('help_title'))
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setStyleSheet("color: #2196F3; margin-bottom: 15px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Scroll area için widget
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; }")

        content_widget = QWidget()
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(20)

        # Bölüm 1: Ne İşe Yarar?
        section1 = self.create_section(
            _('help_what_is'),
            _('help_what_is_content')
        )
        content_layout.addWidget(section1)

        # Bölüm 2: Nasıl Çalışır?
        section2 = self.create_section(
            _('help_how_works'),
            _('help_how_works_content')
        )
        content_layout.addWidget(section2)

        # Bölüm 3: Nasıl Kullanılır?
        section3 = self.create_section(
            _('help_how_to_use'),
            _('help_how_to_use_content')
        )
        content_layout.addWidget(section3)

        content_widget.setLayout(content_layout)
        scroll_area.setWidget(content_widget)
        layout.addWidget(scroll_area)

        # Kapat butonu
        close_button = QPushButton(_('close'))
        close_button.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 10px 30px;
                border-radius: 5px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        close_button.clicked.connect(self.accept)

        close_layout = QHBoxLayout()
        close_layout.addStretch()
        close_layout.addWidget(close_button)
        close_layout.addStretch()
        layout.addLayout(close_layout)

        self.setLayout(layout)

    def create_section(self, title, content):
        """Yardım bölümü oluştur"""
        section_widget = QWidget()
        section_widget.setStyleSheet("QWidget { background: white; border: 1px solid #ddd; border-radius: 8px; padding: 15px; }")

        section_layout = QVBoxLayout()
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(10)

        # Başlık
        title_label = QLabel(title)
        title_label.setFont(QFont("Arial", 12, QFont.Bold))
        title_label.setStyleSheet("color: #333; margin-bottom: 5px;")
        section_layout.addWidget(title_label)

        # İçerik
        content_label = QLabel(content)
        content_label.setWordWrap(True)
        content_label.setStyleSheet("color: #555; line-height: 1.4;")
        section_layout.addWidget(content_label)

        section_widget.setLayout(section_layout)
        return section_widget


class MainWindow(QMainWindow):
    # Bridge hesap ekleme sinyali
    bridge_account_added = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.account_manager = AccountManager()
        self.proxy_manager = MitmProxyManager()
        self.proxy_enabled = False

        # Proxy kapalıysa aktif hesabı temizle
        if IS_WINDOWS and WindowsProxyManager and not WindowsProxyManager.is_proxy_enabled():
            self.account_manager.clear_active_account()

        # Bridge sinyalini slot'a bağla
        self.bridge_account_added.connect(self.refresh_table_after_bridge_add)

        self.init_ui()
        self.load_accounts()

        # Bridge konfigürasyonu ve server başlat (UI yüklendikten sonra)
        self.setup_bridge_system()

        # Timer for checking proxy status
        self.proxy_timer = QTimer()
        self.proxy_timer.timeout.connect(self.check_proxy_status)
        self.proxy_timer.start(5000)  # Her 5 saniyede kontrol et

        # Timer for checking ban notifications
        self.ban_timer = QTimer()
        self.ban_timer.timeout.connect(self.check_ban_notifications)
        self.ban_timer.start(1000)  # Her 1 saniyede kontrol et

        # Timer for automatic token renewal
        self.token_renewal_timer = QTimer()
        self.token_renewal_timer.timeout.connect(self.auto_renew_tokens)
        self.token_renewal_timer.start(60000)  # Her 1 dakikada kontrol et (60000 ms)

        # Timer for active account refresh
        self.active_account_refresh_timer = QTimer()
        self.active_account_refresh_timer.timeout.connect(self.refresh_active_account)
        self.active_account_refresh_timer.start(60000)  # Her 60 saniyede aktif hesabı yenile

        # Timer for status message reset
        self.status_reset_timer = QTimer()
        self.status_reset_timer.setSingleShot(True)
        self.status_reset_timer.timeout.connect(self.reset_status_message)

        # İlk açılışta token kontrolü yap (hemen)
        QTimer.singleShot(0, self.auto_renew_tokens)

        # Token worker için değişkenler
        self.token_worker = None
        self.token_progress_dialog = None

    def setup_bridge_system(self):
        """Bridge sistem konfigürasyonu ve server başlatma"""
        try:
            print("🌉 Bridge sistemi başlatılıyor...")

            # Windows bridge konfigürasyonu kontrol et (Windows'ta)
            if IS_WINDOWS and WindowsBridgeConfig is not None:
                bridge_config = WindowsBridgeConfig()
                if not bridge_config.check_configuration():
                    print("⚙️  Bridge konfigürasyonu yapılıyor...")
                    bridge_config.setup_bridge_config()

            # Bridge server başlat (callback ile tablo yenileme)
            self.bridge_server = WarpBridgeServer(
                self.account_manager,
                on_account_added=self.on_account_added_via_bridge
            )
            if self.bridge_server.start():
                print("✅ Bridge sistemi hazır!")
            else:
                print("❌ Bridge server başlatılamadı!")

        except Exception as e:
            print(f"❌ Bridge sistem hatası: {e}")
            # Hata olsa bile uygulamaya devam et
            self.bridge_server = None

    def init_ui(self):
        self.setWindowTitle(_('app_title'))
        self.setGeometry(100, 100, 900, 650)  # Biraz daha büyük ve modern boyut
        self.setMinimumSize(750, 500)  # Minimum boyut ayarla

        # Status bar ekle
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

                # Spacer ekle - status mesajını ortalamak için
        spacer_label = QLabel("  ")  # Boş alan
        self.status_bar.addWidget(spacer_label)

        # Sağ köşeye Ruwis linki ekle
        self.ruwis_label = QLabel('<a href="https://github.com/ruwiss" style="color: #2196F3; text-decoration: none; font-weight: bold;">https://github.com/ruwiss</a>')
        self.ruwis_label.setOpenExternalLinks(True)
        self.ruwis_label.setStyleSheet("QLabel { padding: 2px 8px; }")
        self.status_bar.addPermanentWidget(self.ruwis_label)

        # Varsayılan status mesajı
        debug_mode = os.path.exists("debug.txt")
        if debug_mode:
            self.status_bar.showMessage(_('default_status_debug'))
        else:
            self.status_bar.showMessage(_('default_status'))

        # Ana widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Ana layout - Modern boşluklar
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)  # Daha geniş kenar boşlukları
        layout.setSpacing(12)  # Daha geniş elemanlar arası boşluk

        # Üst butonlar - Modern boşluklar
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)  # Butonlar arası daha geniş boşluk

        # Proxy butonları - başlat butonu artık gizli (hesap butonları ile birleştirildi)
        self.proxy_start_button = QPushButton(_('proxy_start'))
        self.proxy_start_button.setObjectName("StartButton")
        self.proxy_start_button.setMinimumHeight(36)  # Daha yüksek modern butonlar
        self.proxy_start_button.clicked.connect(self.start_proxy)
        self.proxy_start_button.setVisible(False)  # Artık gizli

        self.proxy_stop_button = QPushButton(_('proxy_stop'))
        self.proxy_stop_button.setObjectName("StopButton")
        self.proxy_stop_button.setMinimumHeight(36)  # Daha yüksek modern butonlar
        self.proxy_stop_button.clicked.connect(self.stop_proxy)
        self.proxy_stop_button.setVisible(False)  # Başlangıçta gizli

        # Diğer butonlar
        self.add_account_button = QPushButton(_('add_account'))
        self.add_account_button.setObjectName("AddButton")
        self.add_account_button.setMinimumHeight(36)  # Daha yüksek modern butonlar
        self.add_account_button.clicked.connect(self.add_account)

        self.refresh_limits_button = QPushButton(_('refresh_limits'))
        self.refresh_limits_button.setObjectName("RefreshButton")
        self.refresh_limits_button.setMinimumHeight(36)  # Daha yüksek modern butonlar
        self.refresh_limits_button.clicked.connect(self.refresh_limits)

        button_layout.addWidget(self.proxy_stop_button)
        button_layout.addWidget(self.add_account_button)
        button_layout.addWidget(self.refresh_limits_button)
        button_layout.addStretch()

        # Dil seçici
        self.language_combo = QComboBox()
        self.language_combo.addItems(['TR', 'EN'])
        self.language_combo.setCurrentText('TR' if get_language_manager().get_current_language() == 'tr' else 'EN')
        self.language_combo.setFixedWidth(65)
        self.language_combo.setFixedHeight(36)  # Modern buton yüksekliği ile uyumlu
        self.language_combo.setStyleSheet("""
            QComboBox {
                background-color: #f5f5f5;
                color: #666;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 4px 12px;
                font-size: 11px;
                font-weight: bold;
                text-align: center;
            }
            QComboBox:hover {
                background-color: #e8e8e8;
                color: #333;
                border-color: #bbb;
            }
            QComboBox::drop-down {
                border: none;
                width: 18px;
            }
            QComboBox::down-arrow {
                width: 10px;
                height: 10px;
                margin-right: 2px;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                border: 1px solid #ddd;
                selection-background-color: #000000;
                font-weight: bold;
                text-align: center;
            }
        """)
        self.language_combo.currentTextChanged.connect(self.change_language)
        button_layout.addWidget(self.language_combo)

        # Yardım butonu sağ tarafa
        self.help_button = QPushButton(_('help'))
        self.help_button.setFixedHeight(36)  # Modern buton yüksekliği ile uyumlu
        self.help_button.setStyleSheet("""
            QPushButton {
                background-color: #f5f5f5;
                color: #666;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 4px 12px;
                font-size: 11px;
                font-weight: normal;
            }
            QPushButton:hover {
                background-color: #e8e8e8;
                color: #333;
                border-color: #bbb;
            }
        """)
        self.help_button.setToolTip("Yardım ve Kullanım Kılavuzu")
        self.help_button.clicked.connect(self.show_help_dialog)
        button_layout.addWidget(self.help_button)

        layout.addLayout(button_layout)

        # Tablo
        self.table = QTableWidget()
        self.table.setColumnCount(4)  # Durum sütunu eklendi
        self.table.setHorizontalHeaderLabels([_('current'), _('email'), _('status'), _('limit')])

        # Tablo görünümünü modern ve kompaktlaştır
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)  # Biraz daha yüksek satırlar
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)

        # Modern tablo stilleri
        self.table.setStyleSheet("""
            QTableWidget {
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 12px;
                gridline-color: transparent;
                selection-background-color: #dbeafe;
                selection-color: #1e293b;
                outline: none;
            }
            QTableWidget::item {
                padding: 8px 12px;
                border: none;
                color: #334155;
                font-size: 10pt;
            }
        """)

        # Sağ tık menüsü ekle
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        # Tablo başlık ayarları
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)  # Durum sütunu sabit genişlik
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # Email sütunu esnek
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Status sütunu içeriğe göre
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Limit sütunu içeriğe göre
        header.resizeSection(0, 100)  # Durum sütunu 100px genişlik (modern butonlar için)
        header.setFixedHeight(40)  # Daha yüksek modern başlık

        layout.addWidget(self.table)

        central_widget.setLayout(layout)

    def load_accounts(self, preserve_limits=False):
        """Hesapları tabloya yükle"""
        accounts = self.account_manager.get_accounts_with_health_and_limits()

        self.table.setRowCount(len(accounts))
        active_account = self.account_manager.get_active_account()

        for row, (email, account_json, health_status, limit_info) in enumerate(accounts):
            # Aktivasyon butonu (Sütun 0) - Modern tasarım
            activation_button = QPushButton()
            activation_button.setFixedSize(80, 30)  # Daha büyük ve modern
            activation_button.setStyleSheet("""
                QPushButton {
                    border: 1px solid #e2e8f0;
                    border-radius: 15px;
                    font-weight: 600;
                    font-size: 10pt;
                    text-align: center;
                    padding: 4px 8px;
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                               stop: 0 #ffffff, stop: 1 #f8fafc);
                }
                QPushButton:hover {
                    border-width: 2px;
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                               stop: 0 #f8fafc, stop: 1 #f1f5f9);
                }
                QPushButton:pressed {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                               stop: 0 #e2e8f0, stop: 1 #cbd5e1);
                }
            """)

            # Buton durumunu ayarla
            is_active = (email == active_account)
            is_banned = (health_status == _('status_banned_key'))

            if is_banned:
                activation_button.setText(_('button_banned'))
                activation_button.setStyleSheet(activation_button.styleSheet() + """
                    QPushButton {
                        background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                                   stop: 0 #f9fafb, stop: 1 #f3f4f6);
                        color: #6b7280;
                        border-color: #d1d5db;
                        font-size: 9pt;
                    }
                """)
                activation_button.setEnabled(False)
            elif is_active:
                activation_button.setText(_('button_stop'))
                activation_button.setStyleSheet(activation_button.styleSheet() + """
                    QPushButton {
                        background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                                   stop: 0 #fef2f2, stop: 1 #fee2e2);
                        color: #dc2626;
                        border-color: #dc2626;
                        font-size: 9pt;
                        font-weight: 600;
                    }
                    QPushButton:hover {
                        background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                                   stop: 0 #fee2e2, stop: 1 #fecaca);
                        border-color: #b91c1c;
                    }
                """)
            else:
                activation_button.setText(_('button_start'))
                activation_button.setStyleSheet(activation_button.styleSheet() + """
                    QPushButton {
                        background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                                   stop: 0 #f0fdf4, stop: 1 #dcfce7);
                        color: #16a34a;
                        border-color: #16a34a;
                        font-size: 9pt;
                        font-weight: 600;
                    }
                    QPushButton:hover {
                        background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                                   stop: 0 #dcfce7, stop: 1 #bbf7d0);
                        border-color: #15803d;
                    }
                """)

            # Buton click handler'ını bağla
            activation_button.clicked.connect(lambda checked, e=email: self.toggle_account_activation(e))
            self.table.setCellWidget(row, 0, activation_button)

            # Email (Sütun 1)
            email_item = QTableWidgetItem(email)
            self.table.setItem(row, 1, email_item)

            # Durum (Sütun 2)
            try:
                # Banlanmış hesap kontrolü
                if health_status == _('status_banned_key'):
                    status = _('status_banned')
                else:
                    account_data = json.loads(account_json)
                    expiration_time = account_data['stsTokenManager']['expirationTime']
                    current_time = int(time.time() * 1000)

                    if current_time >= expiration_time:
                        status = _('status_token_expired')
                    else:
                        status = _('status_active')

                    # Aktif hesap ise belirt
                    if email == active_account:
                        status += _('status_proxy_active')

            except:
                status = _('status_error')

            status_item = QTableWidgetItem(status)
            status_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 2, status_item)

            # Limit (Sütun 3) - veritabanından al (varsayılan: "Güncellenmedi")
            limit_item = QTableWidgetItem(limit_info or _('status_not_updated'))
            limit_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 3, limit_item)

            # Satır arkaplan rengini ayarla
            from PyQt5.QtGui import QColor

            if health_status == 'banned':
                # Banlanmış hesap - soluk gri arkaplan
                color = QColor(156, 163, 175, 60)  # gray-400 with low opacity
            elif email == active_account:
                # Aktif hesap - mavi arkaplan
                color = QColor(59, 130, 246, 80)  # blue-500 with opacity
            elif health_status == 'unhealthy':
                # Sağlıksız hesap - kırmızı arkaplan
                color = QColor(239, 68, 68, 80)  # red-500 with opacity
            else:
                # Normal durum - varsayılan renk
                color = QColor(255, 255, 255, 0)  # transparent

            # Tüm sütunlara aynı arkaplan rengini uygula (buton hariç)
            for col in range(1, 4):  # Sütun 0 buton olduğu için 1'den başla
                item = self.table.item(row, col)
                if item:
                    item.setBackground(color)

    def toggle_account_activation(self, email):
        """Hesabın aktivasyon durumunu değiştir - gerekirse proxy'yi de başlat"""

        # Banlanmış hesap kontrolü
        accounts_with_health = self.account_manager.get_accounts_with_health()
        for acc_email, _, acc_health in accounts_with_health:
            if acc_email == email and acc_health == 'banned':
                self.show_status_message(f"{email} hesabı banlanmış - aktif edilemez", 5000)
                return

        # Aktif hesabı kontrol et
        active_account = self.account_manager.get_active_account()

        if email == active_account and self.proxy_enabled:
            # Hesap zaten aktif - deaktif et (proxy'yi de durdur)
            self.stop_proxy()
        else:
            # Hesap aktif değil veya proxy kapalı - proxy başlat ve hesabı aktif et
            if not self.proxy_enabled:
                # Önce proxy'yi başlat
                self.show_status_message(f"Proxy başlatılıyor ve {email} aktif ediliyor...", 2000)
                if self.start_proxy_and_activate_account(email):
                    return  # Başarılı - işlem tamamlandı
                else:
                    return  # Başarısız - hata mesajı zaten gösterildi
            else:
                # Proxy zaten aktif, sadece hesabı aktif et
                self.activate_account(email)

    def show_context_menu(self, position):
        """Sağ tık menüsünü göster"""
        item = self.table.itemAt(position)
        if item is None:
            return

        row = item.row()
        email_item = self.table.item(row, 1)  # Email artık 1. sütunda
        if not email_item:
            return

        email = email_item.text()

        # Hesap durumunu kontrol et
        accounts_with_health = self.account_manager.get_accounts_with_health()
        health_status = None
        for acc_email, _, acc_health in accounts_with_health:
            if acc_email == email:
                health_status = acc_health
                break

        # Menü oluştur
        menu = QMenu(self)

        # Aktif et/Deaktif et
        if self.proxy_enabled:
            active_account = self.account_manager.get_active_account()
            if email == active_account:
                deactivate_action = QAction("🔴 Deaktif Et", self)
                deactivate_action.triggered.connect(lambda: self.deactivate_account(email))
                menu.addAction(deactivate_action)
            else:
                if health_status != 'banned':
                    activate_action = QAction("🟢 Aktif Et", self)
                    activate_action.triggered.connect(lambda: self.activate_account(email))
                    menu.addAction(activate_action)

        menu.addSeparator()

        # Hesap sil
        delete_action = QAction("🗑️ Hesabı Sil", self)
        delete_action.triggered.connect(lambda: self.delete_account_with_confirmation(email))
        menu.addAction(delete_action)

        # Menüyü göster
        menu.exec_(self.table.mapToGlobal(position))

    def deactivate_account(self, email):
        """Hesabı deaktif et"""
        try:
            if self.account_manager.clear_active_account():
                self.load_accounts(preserve_limits=True)
                self.show_status_message(f"{email} hesabı deaktif edildi", 3000)
            else:
                self.show_status_message("Hesap deaktif edilemedi", 3000)
        except Exception as e:
            self.show_status_message(f"Hata: {str(e)}", 5000)

    def delete_account_with_confirmation(self, email):
        """Hesabı onay isteyerek sil"""
        try:
            reply = QMessageBox.question(self, "Hesap Sil",
                                       f"'{email}' hesabını silmek istediğinizden emin misiniz?\n\n"
                                       f"Bu işlem geri alınamaz!",
                                       QMessageBox.Yes | QMessageBox.No,
                                       QMessageBox.No)

            if reply == QMessageBox.Yes:
                if self.account_manager.delete_account(email):
                    self.load_accounts(preserve_limits=True)
                    self.show_status_message(f"{email} hesabı silindi", 3000)
                else:
                    self.show_status_message("Hesap silinemedi", 3000)
        except Exception as e:
            self.show_status_message(f"Silme hatası: {str(e)}", 5000)

    def add_account(self):
        """Hesap ekleme dialogunu aç"""
        dialog = AddAccountDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            json_data = dialog.get_json_data()
            if json_data:
                success, message = self.account_manager.add_account(json_data)
                if success:
                    self.load_accounts()
                    self.status_bar.showMessage(_('account_added_success'), 3000)
                else:
                    self.status_bar.showMessage(f"{_('error')}: {message}", 5000)

    def refresh_limits(self):
        """Limitleri güncelle"""
        accounts = self.account_manager.get_accounts_with_health()
        if not accounts:
            self.status_bar.showMessage(_('no_accounts_to_update'), 3000)
            return

        # Progress dialog
        self.progress_dialog = QProgressDialog(_('updating_limits'), _('cancel'), 0, 100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.show()

        # Worker thread başlat
        self.worker = TokenRefreshWorker(accounts, self.proxy_enabled)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.refresh_finished)
        self.worker.error.connect(self.refresh_error)
        self.worker.start()

        # Butonları devre dışı bırak
        self.refresh_limits_button.setEnabled(False)
        self.add_account_button.setEnabled(False)

    def update_progress(self, value, text):
        """Progress güncelle"""
        self.progress_dialog.setValue(value)
        self.progress_dialog.setLabelText(text)

    def refresh_finished(self, results):
        """Güncelleme tamamlandı"""
        self.progress_dialog.close()

        # Tabloyu yeniden yükle (veritabanından limit bilgileri otomatik gelecek)
        self.load_accounts()

        # Butonları aktif et
        self.refresh_limits_button.setEnabled(True)
        self.add_account_button.setEnabled(True)

        self.status_bar.showMessage(_('accounts_updated', len(results)), 3000)

    def refresh_error(self, error_message):
        """Güncelleme hatası"""
        self.progress_dialog.close()
        self.refresh_limits_button.setEnabled(True)
        self.add_account_button.setEnabled(True)
        self.status_bar.showMessage(f"{_('error')}: {error_message}", 5000)

    def start_proxy_and_activate_account(self, email):
        """Proxy'yi başlat ve hesabı aktif et"""
        try:
            # Mitmproxy'yi başlat
            print(f"Proxy başlatılıyor ve {email} aktif ediliyor...")

            # Progress dialog göster
            progress = QProgressDialog(_('proxy_starting_account').format(email), _('cancel'), 0, 0, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.show()
            QApplication.processEvents()

            if self.proxy_manager.start(parent_window=self):
                progress.setLabelText(_('proxy_configuring'))
                QApplication.processEvents()

                proxy_url = self.proxy_manager.get_proxy_url()
                print(f"Proxy URL: {proxy_url}")

                ok = True
                if IS_WINDOWS and WindowsProxyManager is not None:
                    ok = WindowsProxyManager.set_proxy(proxy_url)
                else:
                    # Linux: kullanıcıya tarayıcı/proxy ayarı bilgisini göster
                    self.status_bar.showMessage(f"Set your system/browser proxy to {proxy_url}", 5000)

                if ok:
                    progress.setLabelText(_('activating_account').format(email))
                    QApplication.processEvents()

                    self.proxy_enabled = True
                    self.proxy_start_button.setEnabled(False)
                    self.proxy_start_button.setText(_('proxy_active'))
                    self.proxy_stop_button.setVisible(True)  # Artık görünür yap
                    self.proxy_stop_button.setEnabled(True)

                    # Aktif hesap refresh timer'ını başlat
                    if hasattr(self, 'active_account_refresh_timer') and not self.active_account_refresh_timer.isActive():
                        self.active_account_refresh_timer.start(60000)

                    # Hesabı aktif et
                    self.activate_account(email)

                    progress.close()

                    self.status_bar.showMessage(_('proxy_started_account_activated').format(email), 5000)
                    print(f"Proxy başarıyla başlatıldı ve {email} aktif edildi!")
                    return True
                else:
                    progress.close()
                    print("Windows proxy ayarları yapılandırılamadı")
                    self.proxy_manager.stop()
                    self.status_bar.showMessage(_('windows_proxy_config_failed'), 5000)
                    return False
            else:
                progress.close()
                print("Mitmproxy başlatılamadı")
                self.status_bar.showMessage(_('mitmproxy_start_failed'), 5000)
                return False
        except Exception as e:
            if 'progress' in locals():
                progress.close()
            print(f"Proxy başlatma hatası: {e}")
            self.status_bar.showMessage(_('proxy_start_error').format(str(e)), 5000)
            return False

    def start_proxy(self):
        """Proxy'yi başlat (eski metod - sadece proxy başlatma için)"""
        try:
            # Mitmproxy'yi başlat
            print("Proxy başlatılıyor...")

            # Progress dialog göster
            progress = QProgressDialog(_('proxy_starting'), _('cancel'), 0, 0, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.show()
            QApplication.processEvents()

            if self.proxy_manager.start(parent_window=self):
                progress.setLabelText(_('proxy_configuring'))
                QApplication.processEvents()

                proxy_url = self.proxy_manager.get_proxy_url()
                print(f"Proxy URL: {proxy_url}")

                ok = True
                if IS_WINDOWS and WindowsProxyManager is not None:
                    ok = WindowsProxyManager.set_proxy(proxy_url)
                else:
                    self.status_bar.showMessage(f"Set your system/browser proxy to {proxy_url}", 5000)

                if ok:
                    progress.close()

                    self.proxy_enabled = True
                    self.proxy_start_button.setEnabled(False)
                    self.proxy_start_button.setText(_('proxy_active'))
                    self.proxy_stop_button.setVisible(True)  # Artık görünür yap
                    self.proxy_stop_button.setEnabled(True)

                    # Aktif hesap refresh timer'ını başlat
                    if hasattr(self, 'active_account_refresh_timer') and not self.active_account_refresh_timer.isActive():
                        self.active_account_refresh_timer.start(60000)

                    # Tabloyu güncelle
                    self.load_accounts()

                    self.status_bar.showMessage(f"Proxy başlatıldı: {proxy_url}", 5000)
                    print("Proxy başarıyla başlatıldı!")
                else:
                    progress.close()
                    print("Windows proxy ayarları yapılandırılamadı")
                    self.proxy_manager.stop()
                    self.status_bar.showMessage(_('windows_proxy_config_failed'), 5000)
            else:
                progress.close()
                print("Mitmproxy başlatılamadı")
                self.status_bar.showMessage(_('mitmproxy_start_failed'), 5000)
        except Exception as e:
            if 'progress' in locals():
                progress.close()
            print(f"Proxy başlatma hatası: {e}")
            self.status_bar.showMessage(_('proxy_start_error').format(str(e)), 5000)

    def stop_proxy(self):
        """Proxy'yi durdur"""
        try:
            # Windows proxy ayarlarını devre dışı bırak
            if IS_WINDOWS and WindowsProxyManager is not None:
                WindowsProxyManager.disable_proxy()

            # Mitmproxy'yi durdur
            self.proxy_manager.stop()

            # Aktif hesabı temizle
            self.account_manager.clear_active_account()

            # Aktif hesap refresh timer'ını durdur
            if hasattr(self, 'active_account_refresh_timer') and self.active_account_refresh_timer.isActive():
                self.active_account_refresh_timer.stop()
                print("🔄 Aktif hesap yenileme timer'ı durduruldu")

            self.proxy_enabled = False
            self.proxy_start_button.setEnabled(True)
            self.proxy_start_button.setText(_('proxy_start'))
            self.proxy_stop_button.setVisible(False)  # Gizle
            self.proxy_stop_button.setEnabled(False)

            # Tabloyu güncelle
            self.load_accounts(preserve_limits=True)

            self.status_bar.showMessage(_('proxy_stopped'), 3000)
        except Exception as e:
            self.status_bar.showMessage(_('proxy_stop_error').format(str(e)), 5000)

    def activate_account(self, email):
        """Hesabı aktif et"""
        try:
            # Önce hesap durumunu kontrol et
            accounts_with_health = self.account_manager.get_accounts_with_health()
            account_data = None
            health_status = None

            for acc_email, acc_json, acc_health in accounts_with_health:
                if acc_email == email:
                    account_data = json.loads(acc_json)
                    health_status = acc_health
                    break

            if not account_data:
                self.status_bar.showMessage(_('account_not_found'), 3000)
                return

            # Banlanmış hesap aktif edilemez
            if health_status == 'banned':
                self.status_bar.showMessage(_('account_banned_cannot_activate').format(email), 5000)
                return

            # Token süresi kontrolü
            current_time = int(time.time() * 1000)
            expiration_time = account_data['stsTokenManager']['expirationTime']

            if current_time >= expiration_time:
                # Token yenileme - thread'e taşı
                self.start_token_refresh(email, account_data)
                return

            # Token geçerli, hesabı direkt aktif et
            self._complete_account_activation(email)

        except Exception as e:
            self.status_bar.showMessage(_('account_activation_error').format(str(e)), 5000)

    def start_token_refresh(self, email, account_data):
        """Token yenileme işlemini thread'te başlat"""
        # Eğer başka bir token worker çalışıyorsa bekle
        if self.token_worker and self.token_worker.isRunning():
            self.status_bar.showMessage(_('token_refresh_in_progress'), 3000)
            return

        # Progress dialog göster
        self.token_progress_dialog = QProgressDialog(_('token_refreshing').format(email), _('cancel'), 0, 0, self)
        self.token_progress_dialog.setWindowModality(Qt.WindowModal)
        self.token_progress_dialog.show()

        # Token worker başlat
        self.token_worker = TokenWorker(email, account_data, self.proxy_enabled)
        self.token_worker.progress.connect(self.update_token_progress)
        self.token_worker.finished.connect(self.token_refresh_finished)
        self.token_worker.error.connect(self.token_refresh_error)
        self.token_worker.start()

    def update_token_progress(self, message):
        """Token yenileme progress güncelle"""
        if self.token_progress_dialog:
            self.token_progress_dialog.setLabelText(message)

    def token_refresh_finished(self, success, message):
        """Token yenileme tamamlandı"""
        if self.token_progress_dialog:
            self.token_progress_dialog.close()
            self.token_progress_dialog = None

        self.status_bar.showMessage(message, 3000)

        if success:
            # Token başarıyla yenilendi, hesabı aktif et
            email = self.token_worker.email
            self._complete_account_activation(email)

        # Worker'ı temizle
        self.token_worker = None

    def token_refresh_error(self, error_message):
        """Token yenileme hatası"""
        if self.token_progress_dialog:
            self.token_progress_dialog.close()
            self.token_progress_dialog = None

        self.status_bar.showMessage(_('token_refresh_error').format(error_message), 5000)
        self.token_worker = None

    def _complete_account_activation(self, email):
        """Hesap aktivasyonunu tamamla"""
        try:
            if self.account_manager.set_active_account(email):
                self.load_accounts(preserve_limits=True)
                self.status_bar.showMessage(_('account_activated').format(email), 3000)
                self.notify_proxy_active_account_change()

                # user_settings.json dosyası kontrolü ve gerekirse API çağrısı
                self.check_and_fetch_user_settings(email)
            else:
                self.status_bar.showMessage(_('account_activation_failed'), 3000)
        except Exception as e:
            self.status_bar.showMessage(_('account_activation_error').format(str(e)), 5000)

    def check_and_fetch_user_settings(self, email):
        """user_settings.json dosyası kontrolü ve gerekirse API çağrısı"""
        try:
            import os
            user_settings_path = "user_settings.json"

            # Dosya var mı kontrol et
            if not os.path.exists(user_settings_path):
                print(f"🔍 user_settings.json dosyası bulunamadı, {email} için API çağrısı yapılıyor...")
                self.fetch_and_save_user_settings(email)
            else:
                print(f"✅ user_settings.json dosyası mevcut, API çağrısı atlanıyor")
        except Exception as e:
            print(f"user_settings kontrol hatası: {e}")

    def fetch_and_save_user_settings(self, email):
        """GetUpdatedCloudObjects API çağrısı yapıp user_settings.json olarak kaydet"""
        try:
            # Aktif hesabın token'ini al
            accounts = self.account_manager.get_accounts()
            account_data = None

            for acc_email, acc_json in accounts:
                if acc_email == email:
                    account_data = json.loads(acc_json)
                    break

            if not account_data:
                print(f"❌ Hesap bulunamadı: {email}")
                return False

            access_token = account_data['stsTokenManager']['accessToken']

            # API isteği hazırla
            url = "https://app.warp.dev/graphql/v2?op=GetUpdatedCloudObjects"
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {access_token}',
                'X-Warp-Client-Version': 'v0.2025.09.01.20.54.stable_04',
                'X-Warp-Os-Category': 'Windows',
                'X-Warp-Os-Name': 'Windows',
                'X-Warp-Os-Version': '10 (19045)',
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive'
            }

            # GraphQL query ve variables
            payload = {
                "query": """query GetUpdatedCloudObjects($input: UpdatedCloudObjectsInput!, $requestContext: RequestContext!) {
  updatedCloudObjects(input: $input, requestContext: $requestContext) {
    __typename
    ... on UpdatedCloudObjectsOutput {
      actionHistories {
        actions {
          __typename
          ... on BundledActions {
            actionType
            count
            latestProcessedAtTimestamp
            latestTimestamp
            oldestTimestamp
          }
          ... on SingleAction {
            actionType
            processedAtTimestamp
            timestamp
          }
        }
        latestProcessedAtTimestamp
        latestTimestamp
        objectType
        uid
      }
      deletedObjectUids {
        folderUids
        genericStringObjectUids
        notebookUids
        workflowUids
      }
      folders {
        name
        metadata {
          creatorUid
          currentEditorUid
          isWelcomeObject
          lastEditorUid
          metadataLastUpdatedTs
          parent {
            __typename
            ... on FolderContainer {
              folderUid
            }
            ... on Space {
              uid
              type
            }
          }
          revisionTs
          trashedTs
          uid
        }
        permissions {
          guests {
            accessLevel
            source {
              __typename
              ... on FolderContainer {
                folderUid
              }
              ... on Space {
                uid
                type
              }
            }
            subject {
              __typename
              ... on UserGuest {
                firebaseUid
              }
              ... on PendingUserGuest {
                email
              }
            }
          }
          lastUpdatedTs
          anyoneLinkSharing {
            accessLevel
            source {
              __typename
              ... on FolderContainer {
                folderUid
              }
              ... on Space {
                uid
                type
              }
            }
          }
          space {
            uid
            type
          }
        }
        isWarpPack
      }
      genericStringObjects {
        format
        metadata {
          creatorUid
          currentEditorUid
          isWelcomeObject
          lastEditorUid
          metadataLastUpdatedTs
          parent {
            __typename
            ... on FolderContainer {
              folderUid
            }
            ... on Space {
              uid
              type
            }
          }
          revisionTs
          trashedTs
          uid
        }
        permissions {
          guests {
            accessLevel
            source {
              __typename
              ... on FolderContainer {
                folderUid
              }
              ... on Space {
                uid
                type
              }
            }
            subject {
              __typename
              ... on UserGuest {
                firebaseUid
              }
              ... on PendingUserGuest {
                email
              }
            }
          }
          lastUpdatedTs
          anyoneLinkSharing {
            accessLevel
            source {
              __typename
              ... on FolderContainer {
                folderUid
              }
              ... on Space {
                uid
                type
              }
            }
          }
          space {
            uid
            type
          }
        }
        serializedModel
      }
      notebooks {
        data
        title
        metadata {
          creatorUid
          currentEditorUid
          isWelcomeObject
          lastEditorUid
          metadataLastUpdatedTs
          parent {
            __typename
            ... on FolderContainer {
              folderUid
            }
            ... on Space {
              uid
              type
            }
          }
          revisionTs
          trashedTs
          uid
        }
        permissions {
          guests {
            accessLevel
            source {
              __typename
              ... on FolderContainer {
                folderUid
              }
              ... on Space {
                uid
                type
              }
            }
            subject {
              __typename
              ... on UserGuest {
                firebaseUid
              }
              ... on PendingUserGuest {
                email
              }
            }
          }
          lastUpdatedTs
          anyoneLinkSharing {
            accessLevel
            source {
              __typename
              ... on FolderContainer {
                folderUid
              }
              ... on Space {
                uid
                type
              }
            }
          }
          space {
            uid
            type
          }
        }
      }
      responseContext {
        serverVersion
      }
      userProfiles {
        displayName
        email
        photoUrl
        uid
      }
      workflows {
        data
        metadata {
          creatorUid
          currentEditorUid
          isWelcomeObject
          lastEditorUid
          metadataLastUpdatedTs
          parent {
            __typename
            ... on FolderContainer {
              folderUid
            }
            ... on Space {
              uid
              type
            }
          }
          revisionTs
          trashedTs
          uid
        }
        permissions {
          guests {
            accessLevel
            source {
              __typename
              ... on FolderContainer {
                folderUid
              }
              ... on Space {
                uid
                type
              }
            }
            subject {
              __typename
              ... on UserGuest {
                firebaseUid
              }
              ... on PendingUserGuest {
                email
              }
            }
          }
          lastUpdatedTs
          anyoneLinkSharing {
            accessLevel
            source {
              __typename
              ... on FolderContainer {
                folderUid
              }
              ... on Space {
                uid
                type
              }
            }
          }
          space {
            uid
            type
          }
        }
      }
    }
    ... on UserFacingError {
      error {
        __typename
        ... on SharedObjectsLimitExceeded {
          limit
          objectType
          message
        }
        ... on PersonalObjectsLimitExceeded {
          limit
          objectType
          message
        }
        ... on AccountDelinquencyError {
          message
        }
        ... on GenericStringObjectUniqueKeyConflict {
          message
        }
      }
      responseContext {
        serverVersion
      }
    }
  }
}""",
                "variables": {
                    "input": {
                        "folders": [
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:14:09.132139Z", "permissionsTs": "2025-09-04T15:14:09.132139Z", "revisionTs": "2025-09-04T15:14:09.132139Z", "uid": "EDD5BxHhckNftq2AqF16y0"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:15:51.073272Z", "permissionsTs": "2025-09-04T15:15:51.073272Z", "revisionTs": "2025-09-04T15:15:51.073272Z", "uid": "VtF6FwDkPcgMKjkEW0i011"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:17:17.397772Z", "permissionsTs": "2025-09-04T15:17:17.397772Z", "revisionTs": "2025-09-04T15:17:17.397772Z", "uid": "J13I26jNGbrV2OV8HUn7WJ"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:15:50.956728Z", "permissionsTs": "2025-09-04T15:15:50.956728Z", "revisionTs": "2025-09-04T15:15:50.956728Z", "uid": "8apsBUk0x5243ZYdCVu9lB"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:17:17.496422Z", "permissionsTs": "2025-09-04T15:17:17.496422Z", "revisionTs": "2025-09-04T15:17:17.496422Z", "uid": "m6ufDjY2pqQFk5Mz65BCNx"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:14:09.023623Z", "permissionsTs": "2025-09-04T15:14:09.023623Z", "revisionTs": "2025-09-04T15:14:09.023623Z", "uid": "kVsPIbczwIva4hLbHZMouT"}
                        ],
                        "forceRefresh": False,
                        "genericStringObjects": [
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:16:07.403093Z", "permissionsTs": None, "revisionTs": "2025-09-04T15:16:07.403093Z", "uid": "rYPkTIutkV8CjPI7T7oORM"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:17:53.983781Z", "permissionsTs": None, "revisionTs": "2025-09-04T15:17:53.983781Z", "uid": "P6to7VPbCHk0JwB3gqRGX6"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:15:03.045160Z", "permissionsTs": None, "revisionTs": "2025-09-04T15:15:03.045160Z", "uid": "pbwvZnbU8bJvmEIsKjXfBw"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:16:07.403093Z", "permissionsTs": None, "revisionTs": "2025-09-04T15:16:07.403093Z", "uid": "xrpRwHBwAI4nj21YHaVl7i"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:14:28.273803Z", "permissionsTs": "2025-09-04T15:14:28.273803Z", "revisionTs": "2025-09-04T15:14:28.273803Z", "uid": "5NqwjuMw606Zjk9d4bNbAo"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:15:02.982064Z", "permissionsTs": "2025-09-04T15:15:02.982064Z", "revisionTs": "2025-09-04T15:15:02.982064Z", "uid": "BCzdHbP76LQphANlQfUmVP"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:16:08.136555Z", "permissionsTs": None, "revisionTs": "2025-09-04T15:16:08.136555Z", "uid": "SGbrqUIVT2WfOUwLhj4yp0"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:14:27.597151Z", "permissionsTs": "2025-09-04T15:14:27.597151Z", "revisionTs": "2025-09-04T15:14:27.597151Z", "uid": "0IIBDzTfGNfA2GEkgF2QjN"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:14:28.273803Z", "permissionsTs": "2025-09-04T15:14:28.273803Z", "revisionTs": "2025-09-04T15:14:28.273803Z", "uid": "GcalSGa8Aprrcmvx5G2NLL"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:15:03.045160Z", "permissionsTs": None, "revisionTs": "2025-09-04T15:15:03.045160Z", "uid": "LDJfBBCEErAZSzg6hpCY4A"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:16:07.403093Z", "permissionsTs": None, "revisionTs": "2025-09-04T15:16:07.403093Z", "uid": "AHrIt6mfJi7NdsIBiSA0tz"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:14:27.597151Z", "permissionsTs": "2025-09-04T15:14:27.597151Z", "revisionTs": "2025-09-04T15:14:27.597151Z", "uid": "fkI3MiLCjKhHrGf9n6O0Yo"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:17:53.983781Z", "permissionsTs": None, "revisionTs": "2025-09-04T15:17:53.983781Z", "uid": "DZKY9uei132xJ5Mq5MBw6T"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:17:53.983781Z", "permissionsTs": None, "revisionTs": "2025-09-04T15:17:53.983781Z", "uid": "CkjKbSV08kRoYGUEY9LvfY"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:17:54.625539Z", "permissionsTs": None, "revisionTs": "2025-09-04T15:17:54.625539Z", "uid": "7oQYxEq7ZpEXDcE9t4EAYC"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:16:08.136555Z", "permissionsTs": None, "revisionTs": "2025-09-04T15:16:08.136555Z", "uid": "am8aJIQHuondndQFyfHa4i"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:14:27.597151Z", "permissionsTs": "2025-09-04T15:14:27.597151Z", "revisionTs": "2025-09-04T15:14:27.597151Z", "uid": "HGht23AnvjqHuT8UwCYNAO"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:17:54.625539Z", "permissionsTs": None, "revisionTs": "2025-09-04T15:17:54.625539Z", "uid": "V8mjwCcOVAvHOFXfy93rwI"}
                        ],
                        "notebooks": [
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:15:51.211785Z", "permissionsTs": "2025-09-04T15:15:51.211785Z", "revisionTs": "2025-09-04T15:15:51.211785Z", "uid": "UdtjGuGcUYIGpZjZlgC764"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:14:09.253619Z", "permissionsTs": "2025-09-04T15:14:09.253619Z", "revisionTs": "2025-09-04T15:14:09.253619Z", "uid": "bDbGHWpn4uca3EFGTH1U2Q"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:17:17.603173Z", "permissionsTs": "2025-09-04T15:17:17.603173Z", "revisionTs": "2025-09-04T15:17:17.603173Z", "uid": "jauSUuyNTBgbBuWiE8TUHY"}
                        ],
                        "workflows": [
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:17:17.552627Z", "permissionsTs": "2025-09-04T15:17:17.552627Z", "revisionTs": "2025-09-04T15:17:17.552627Z", "uid": "iwMafgTRhaYK0Iw3cse39R"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:17:17.552627Z", "permissionsTs": "2025-09-04T15:17:17.552627Z", "revisionTs": "2025-09-04T15:17:17.552627Z", "uid": "NWGQamxykgd5ypAdqqFKsM"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:14:09.192955Z", "permissionsTs": "2025-09-04T15:14:09.192955Z", "revisionTs": "2025-09-04T15:14:09.192955Z", "uid": "RqUpAjdKD6kRvIyVaDo1uB"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:17:17.552627Z", "permissionsTs": "2025-09-04T15:17:17.552627Z", "revisionTs": "2025-09-04T15:17:17.552627Z", "uid": "VVnHPmOGnL158geO9QjMzH"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:14:09.192955Z", "permissionsTs": "2025-09-04T15:14:09.192955Z", "revisionTs": "2025-09-04T15:14:09.192955Z", "uid": "D2H43FGrjjUj87Xtz4faGH"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:17:17.552627Z", "permissionsTs": "2025-09-04T15:17:17.552627Z", "revisionTs": "2025-09-04T15:17:17.552627Z", "uid": "MFyXwtpP1Yw6pcinj03n2n"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:17:17.552627Z", "permissionsTs": "2025-09-04T15:17:17.552627Z", "revisionTs": "2025-09-04T15:17:17.552627Z", "uid": "VXuPYgyHagWEFmRs3Nw7bs"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:14:09.192955Z", "permissionsTs": "2025-09-04T15:14:09.192955Z", "revisionTs": "2025-09-04T15:14:09.192955Z", "uid": "CfO2BNrKtpxosE7BarOhzF"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:15:51.140134Z", "permissionsTs": "2025-09-04T15:15:51.140134Z", "revisionTs": "2025-09-04T15:15:51.140134Z", "uid": "2qvtn32aHqe1h0tgjTXJLH"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:14:09.192955Z", "permissionsTs": "2025-09-04T15:14:09.192955Z", "revisionTs": "2025-09-04T15:14:09.192955Z", "uid": "JIzhs7KX6R7q1469U0OkAx"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:14:09.192955Z", "permissionsTs": "2025-09-04T15:14:09.192955Z", "revisionTs": "2025-09-04T15:14:09.192955Z", "uid": "EgE7149EOK5HZlg33UG55A"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:15:51.019199Z", "permissionsTs": "2025-09-04T15:15:51.019199Z", "revisionTs": "2025-09-04T15:15:51.019199Z", "uid": "v7gvOPIm5MDbfTiZfY1PrZ"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:15:51.140134Z", "permissionsTs": "2025-09-04T15:15:51.140134Z", "revisionTs": "2025-09-04T15:15:51.140134Z", "uid": "ZgbNP7xZFDMI2mlfufMpoH"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:17:17.454688Z", "permissionsTs": "2025-09-04T15:17:17.454688Z", "revisionTs": "2025-09-04T15:17:17.454688Z", "uid": "GKk36aCOvwgUnas8YGrm5t"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:15:51.140134Z", "permissionsTs": "2025-09-04T15:15:51.140134Z", "revisionTs": "2025-09-04T15:15:51.140134Z", "uid": "HZeCcSc8pdwBJCLVtBfcyO"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:17:17.552627Z", "permissionsTs": "2025-09-04T15:17:17.552627Z", "revisionTs": "2025-09-04T15:17:17.552627Z", "uid": "wkIO1y9MBx6qBtJm8hSX5H"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:15:51.019199Z", "permissionsTs": "2025-09-04T15:15:51.019199Z", "revisionTs": "2025-09-04T15:15:51.019199Z", "uid": "vQwM7UBNFCm08dYwvs1yBA"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:17:17.552627Z", "permissionsTs": "2025-09-04T15:17:17.552627Z", "revisionTs": "2025-09-04T15:17:17.552627Z", "uid": "EWkCGy5fVCn6LzKZ3aap7n"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:15:51.019199Z", "permissionsTs": "2025-09-04T15:15:51.019199Z", "revisionTs": "2025-09-04T15:15:51.019199Z", "uid": "1cYEBtjukUIbF4vhTGEL3C"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:15:51.140134Z", "permissionsTs": "2025-09-04T15:15:51.140134Z", "revisionTs": "2025-09-04T15:15:51.140134Z", "uid": "Hp7Rd4X9Cz1E1EuvwLSDRf"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:14:09.192955Z", "permissionsTs": "2025-09-04T15:14:09.192955Z", "revisionTs": "2025-09-04T15:14:09.192955Z", "uid": "gnT8FcrxNhqFBzuGr3Rpmr"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:14:09.083649Z", "permissionsTs": "2025-09-04T15:14:09.083649Z", "revisionTs": "2025-09-04T15:14:09.083649Z", "uid": "kDomyveR7d4nLXSmGGh5sm"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:15:51.140134Z", "permissionsTs": "2025-09-04T15:15:51.140134Z", "revisionTs": "2025-09-04T15:15:51.140134Z", "uid": "UpAfUQYo4UfUj0hay0REri"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:17:17.454688Z", "permissionsTs": "2025-09-04T15:17:17.454688Z", "revisionTs": "2025-09-04T15:17:17.454688Z", "uid": "PRy3g6EKx6HlA0CF4tBfFd"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:15:51.140134Z", "permissionsTs": "2025-09-04T15:15:51.140134Z", "revisionTs": "2025-09-04T15:15:51.140134Z", "uid": "Fm9NQzwF6U3lLIWMWAvtEY"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:17:17.454688Z", "permissionsTs": "2025-09-04T15:17:17.454688Z", "revisionTs": "2025-09-04T15:17:17.454688Z", "uid": "dWtnvCRrHazYVFBb9QMo1B"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:14:09.083649Z", "permissionsTs": "2025-09-04T15:14:09.083649Z", "revisionTs": "2025-09-04T15:14:09.083649Z", "uid": "mCl51EOXLpiExaHl1knxUB"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:14:09.192955Z", "permissionsTs": "2025-09-04T15:14:09.192955Z", "revisionTs": "2025-09-04T15:14:09.192955Z", "uid": "PVZgftdFpFR4BN2k9AmCBw"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:15:51.140134Z", "permissionsTs": "2025-09-04T15:15:51.140134Z", "revisionTs": "2025-09-04T15:15:51.140134Z", "uid": "wKSGpwXdQJgs4Bbl5ZGeEc"},
                            {"actionsTs": None, "metadataTs": "2025-09-04T15:14:09.083649Z", "permissionsTs": "2025-09-04T15:14:09.083649Z", "revisionTs": "2025-09-04T15:14:09.083649Z", "uid": "mJg9qgqMkWSYytyq8Z7yym"}
                        ]
                    },
                    "requestContext": {
                        "clientContext": {"version": "v0.2025.09.01.20.54.stable_04"},
                        "osContext": {"category": "Windows", "linuxKernelVersion": None, "name": "Windows", "version": "10 (19045)"}
                    }
                },
                "operationName": "GetUpdatedCloudObjects"
            }

            # Proxy kullanmadan direkt API çağrısı yap
            proxies = {'http': None, 'https': None}
            response = requests.post(url, headers=headers, json=payload, timeout=60, verify=False, proxies=proxies)

            if response.status_code == 200:
                user_settings_data = response.json()

                # user_settings.json dosyasına kaydet
                with open("user_settings.json", 'w', encoding='utf-8') as f:
                    json.dump(user_settings_data, f, indent=2, ensure_ascii=False)

                print(f"✅ user_settings.json dosyası başarıyla oluşturuldu ({email})")
                self.status_bar.showMessage(f"🔄 {email} için kullanıcı ayarları indirildi", 3000)
                return True
            else:
                print(f"❌ API isteği başarısız: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            print(f"user_settings fetch hatası: {e}")
            return False

    def notify_proxy_active_account_change(self):
        """Proxy script'e aktif hesap değişikliğini bildir"""
        try:
            # Proxy çalışıyor mu kontrol et
            if hasattr(self, 'proxy_manager') and self.proxy_manager.is_running():
                print("📢 Proxy'ye aktif hesap değişikliği bildiriliyor...")

                # Dosya bazlı trigger sistemi - daha güvenli
                import time
                trigger_file = "account_change_trigger.tmp"
                try:
                    with open(trigger_file, 'w') as f:
                        f.write(str(int(time.time())))
                    print("✅ Proxy trigger dosyası oluşturuldu")
                except Exception as e:
                    print(f"Trigger dosyası oluşturma hatası: {e}")

                print("✅ Proxy'ye hesap değişikliği bildirildi")
            else:
                print("ℹ️  Proxy çalışmıyor, hesap değişikliği bildirilemedi")
        except Exception as e:
            print(f"Proxy bildirim hatası: {e}")

    def refresh_account_token(self, email, account_data):
        """Tekil hesabın tokenini yenile"""
        try:
            refresh_token = account_data['stsTokenManager']['refreshToken']
            api_key = account_data['apiKey']

            url = f"https://securetoken.googleapis.com/v1/token?key={api_key}"
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'WarpAccountManager/1.0'  # Özel User-Agent ile işaretliyoruz
            }
            data = {
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token
            }

            # Proxy kullanmadan direkt bağlan
            proxies = {'http': None, 'https': None} if self.proxy_enabled else None
            response = requests.post(url, json=data, headers=headers, timeout=30,
                                   verify=not self.proxy_enabled, proxies=proxies)

            if response.status_code == 200:
                token_data = response.json()
                new_token_data = {
                    'accessToken': token_data['access_token'],
                    'refreshToken': token_data['refresh_token'],
                    'expirationTime': int(time.time() * 1000) + (int(token_data['expires_in']) * 1000)
                }

                return self.account_manager.update_account_token(email, new_token_data)
            return False
        except Exception as e:
            print(f"Token yenileme hatası: {e}")
            return False

    def check_proxy_status(self):
        """Proxy durumunu kontrol et"""
        if self.proxy_enabled:
            if not self.proxy_manager.is_running():
                # Proxy beklenmedik şekilde durmuş
                self.proxy_enabled = False
                self.proxy_start_button.setEnabled(True)
                self.proxy_start_button.setText(_('proxy_start'))
                self.proxy_stop_button.setVisible(False)  # Gizle
                self.proxy_stop_button.setEnabled(False)
                WindowsProxyManager.disable_proxy()
                self.account_manager.clear_active_account()
                self.load_accounts(preserve_limits=True)

                self.status_bar.showMessage(_('proxy_unexpected_stop'), 5000)

    def check_ban_notifications(self):
        """Ban bildirimlerini kontrol et"""
        try:
            import os

            ban_notification_file = "ban_notification.tmp"
            if os.path.exists(ban_notification_file):
                # Dosyayı oku
                with open(ban_notification_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()

                if content:
                    # Email ve timestamp'i ayır
                    parts = content.split('|')
                    if len(parts) >= 2:
                        banned_email = parts[0]
                        timestamp = parts[1]

                        print(f"Ban bildirimi alındı: {banned_email} (zaman: {timestamp})")

                        # Tabloyu yenile
                        self.load_accounts(preserve_limits=True)

                        # Kullanıcıya bilgi ver
                        self.show_status_message(f"⛔ {banned_email} hesabı banlandı!", 8000)

                # Dosyayı sil
                os.remove(ban_notification_file)
                print("Ban bildirim dosyası silindi")

        except Exception as e:
            # Hata durumunda sessizce devam et (dosya yoksa normal)
            pass

    def refresh_active_account(self):
        """Aktif hesabın token'ini ve limitini yenile - 60 saniyede bir çalışır"""
        try:
            # Proxy aktif değilse timer'ı durdur
            if not self.proxy_enabled:
                if self.active_account_refresh_timer.isActive():
                    self.active_account_refresh_timer.stop()
                    print("🔄 Aktif hesap yenileme timer'ı durduruldu (proxy kapalı)")
                return

            # Aktif hesabı al
            active_email = self.account_manager.get_active_account()
            if not active_email:
                return

            print(f"🔄 Aktif hesap yenileniyor: {active_email}")

            # Hesap bilgilerini al
            accounts_with_health = self.account_manager.get_accounts_with_health_and_limits()
            active_account_data = None
            health_status = None

            for email, account_json, acc_health, limit_info in accounts_with_health:
                if email == active_email:
                    active_account_data = json.loads(account_json)
                    health_status = acc_health
                    break

            if not active_account_data:
                print(f"❌ Aktif hesap bulunamadı: {active_email}")
                return

            # Banlanmış hesabı atla
            if health_status == 'banned':
                print(f"⛔ Aktif hesap banlanmış, atlanıyor: {active_email}")
                return

            # Token ve limit bilgilerini yenile
            self._refresh_single_active_account(active_email, active_account_data)

        except Exception as e:
            print(f"Aktif hesap yenileme hatası: {e}")

    def _refresh_single_active_account(self, email, account_data):
        """Tek bir aktif hesabın token'ini ve limitini yenile"""
        try:
            # Token yenile
            if self.renew_single_token(email, account_data):
                print(f"✅ Aktif hesap tokeni yenilendi: {email}")

                # Limit bilgilerini de güncelle
                self._update_active_account_limit(email)

                # Tabloyu güncelle
                self.load_accounts(preserve_limits=False)  # Limit bilgileri de güncellensin
            else:
                print(f"❌ Aktif hesap tokeni yenilenemedi: {email}")
                self.account_manager.update_account_health(email, 'unhealthy')

        except Exception as e:
            print(f"Aktif hesap yenileme hatası ({email}): {e}")

    def _update_active_account_limit(self, email):
        """Aktif hesabın limit bilgilerini güncelle"""
        try:
            # Hesap bilgilerini yeniden al
            accounts = self.account_manager.get_accounts()
            for acc_email, acc_json in accounts:
                if acc_email == email:
                    account_data = json.loads(acc_json)

                    # Limit bilgilerini al
                    limit_info = self._get_account_limit_info(account_data)
                    if limit_info:
                        used = limit_info.get('requestsUsedSinceLastRefresh', 0)
                        total = limit_info.get('requestLimit', 0)
                        limit_text = f"{used}/{total}"

                        self.account_manager.update_account_limit_info(email, limit_text)
                        print(f"✅ Aktif hesap limiti güncellendi: {email} - {limit_text}")
                    else:
                        self.account_manager.update_account_limit_info(email, "N/A")
                        print(f"⚠️ Aktif hesap limit bilgisi alınamadı: {email}")
                    break

        except Exception as e:
            print(f"Aktif hesap limit güncelleme hatası ({email}): {e}")

    def _get_account_limit_info(self, account_data):
        """Hesabın limit bilgilerini Warp API'den al"""
        try:
            access_token = account_data['stsTokenManager']['accessToken']

            url = "https://app.warp.dev/graphql/v2?op=GetRequestLimitInfo"
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {access_token}',
                'X-Warp-Client-Version': 'v0.2025.08.27.08.11.stable_04',
                'X-Warp-Os-Category': 'Windows',
                'X-Warp-Os-Name': 'Windows',
                'X-Warp-Os-Version': '10 (19045)',
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate, br',
                'X-Warp-Manager-Request': 'true'
            }

            query = """
            query GetRequestLimitInfo($requestContext: RequestContext!) {
              user(requestContext: $requestContext) {
                __typename
                ... on UserOutput {
                  user {
                    requestLimitInfo {
                      isUnlimited
                      nextRefreshTime
                      requestLimit
                      requestsUsedSinceLastRefresh
                      requestLimitRefreshDuration
                      isUnlimitedAutosuggestions
                      acceptedAutosuggestionsLimit
                      acceptedAutosuggestionsSinceLastRefresh
                      isUnlimitedVoice
                      voiceRequestLimit
                      voiceRequestsUsedSinceLastRefresh
                      voiceTokenLimit
                      voiceTokensUsedSinceLastRefresh
                      isUnlimitedCodebaseIndices
                      maxCodebaseIndices
                      maxFilesPerRepo
                      embeddingGenerationBatchSize
                    }
                  }
                }
                ... on UserFacingError {
                  error {
                    __typename
                    ... on SharedObjectsLimitExceeded {
                      limit
                      objectType
                      message
                    }
                    ... on PersonalObjectsLimitExceeded {
                      limit
                      objectType
                      message
                    }
                    ... on AccountDelinquencyError {
                      message
                    }
                    ... on GenericStringObjectUniqueKeyConflict {
                      message
                    }
                  }
                  responseContext {
                    serverVersion
                  }
                }
              }
            }
            """

            payload = {
                "query": query,
                "variables": {
                    "requestContext": {
                        "clientContext": {
                            "version": "v0.2025.08.27.08.11.stable_04"
                        },
                        "osContext": {
                            "category": "Windows",
                            "linuxKernelVersion": None,
                            "name": "Windows",
                            "version": "10 (19045)"
                        }
                    }
                },
                "operationName": "GetRequestLimitInfo"
            }

            # Proxy kullanmadan direkt bağlan
            proxies = {'http': None, 'https': None}
            response = requests.post(url, headers=headers, json=payload, timeout=30,
                                   verify=True, proxies=proxies)

            if response.status_code == 200:
                data = response.json()
                if 'data' in data and 'user' in data['data']:
                    user_data = data['data']['user']
                    if user_data.get('__typename') == 'UserOutput':
                        return user_data['user']['requestLimitInfo']
            return None
        except Exception as e:
            print(f"Limit bilgisi alma hatası: {e}")
            return None

    def auto_renew_tokens(self):
        """Otomatik token yenileme - dakikada 1 kez çalışır"""
        try:
            print("🔄 Otomatik token kontrol başlatılıyor...")

            # Tüm hesapları al
            accounts = self.account_manager.get_accounts_with_health_and_limits()

            if not accounts:
                return

            expired_count = 0
            renewed_count = 0

            for email, account_json, health_status, limit_info in accounts:
                # Banlanmış hesapları atla
                if health_status == 'banned':
                    continue

                try:
                    account_data = json.loads(account_json)
                    expiration_time = account_data['stsTokenManager']['expirationTime']
                    current_time = int(time.time() * 1000)

                    # Token süresi dolmuş mu kontrol et (1 dakika önce yenile)
                    buffer_time = 1 * 60 * 1000  # 1 dakika buffer
                    if current_time >= (expiration_time - buffer_time):
                        expired_count += 1
                        print(f"⏰ Token yakında dolacak: {email}")

                        # Token'ı yenile
                        if self.renew_single_token(email, account_data):
                            renewed_count += 1
                            print(f"✅ Token yenilendi: {email}")
                        else:
                            print(f"❌ Token yenilenemedi: {email}")

                except Exception as e:
                    print(f"Token kontrol hatası ({email}): {e}")
                    continue

            # Sonuç mesajı
            if expired_count > 0:
                if renewed_count > 0:
                    self.show_status_message(f"🔄 {renewed_count}/{expired_count} token yenilendi", 5000)
                    # Tabloyu güncelle
                    self.load_accounts(preserve_limits=True)
                else:
                    self.show_status_message(f"⚠️ {expired_count} token yenilenemedi", 5000)
            else:
                print("✅ Tüm tokenlar geçerli")

        except Exception as e:
            print(f"Otomatik token yenileme hatası: {e}")
            self.show_status_message("❌ Token kontrol hatası", 3000)

    def renew_single_token(self, email, account_data):
        """Tek bir hesabın token'ını yenile"""
        try:
            refresh_token = account_data['stsTokenManager']['refreshToken']

            # Firebase token yenileme API'si
            url = f"https://securetoken.googleapis.com/v1/token?key=AIzaSyBdy3O3S9hrdayLJxJ7mriBR4qgUaUygAs"

            payload = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            }

            headers = {
                "Content-Type": "application/json"
            }

            # Proxy'yi bypass et
            proxies = {'http': None, 'https': None}

            response = requests.post(url, json=payload, headers=headers,
                                   timeout=30, verify=True, proxies=proxies)

            if response.status_code == 200:
                token_data = response.json()

                # Yeni token bilgilerini güncelle
                new_access_token = token_data['access_token']
                new_refresh_token = token_data.get('refresh_token', refresh_token)
                expires_in = int(token_data['expires_in']) * 1000  # saniyeyi milisaniyeye çevir

                # Yeni expiration time hesapla
                new_expiration_time = int(time.time() * 1000) + expires_in

                # Account data'yı güncelle
                account_data['stsTokenManager']['accessToken'] = new_access_token
                account_data['stsTokenManager']['refreshToken'] = new_refresh_token
                account_data['stsTokenManager']['expirationTime'] = new_expiration_time

                # Veritabanına kaydet
                updated_json = json.dumps(account_data)
                self.account_manager.update_account(email, updated_json)

                return True
            else:
                print(f"Token yenileme hatası: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            print(f"Token yenileme hatası ({email}): {e}")
            return False

    def reset_status_message(self):
        """Status mesajını varsayılan haline döndür"""
        debug_mode = os.path.exists("debug.txt")
        if debug_mode:
            default_message = _('default_status_debug')
        else:
            default_message = _('default_status')

        self.status_bar.showMessage(default_message)

    def show_status_message(self, message, timeout=5000):
        """Status mesajı göster ve belirtilen süre sonra varsayılan mesaja dön"""
        self.status_bar.showMessage(message)

        # Reset timer'ını başlat
        if timeout > 0:
            self.status_reset_timer.start(timeout)

    def show_help_dialog(self):
        """Yardım ve kullanım kılavuzu dialog'unu göster"""
        dialog = HelpDialog(self)
        dialog.exec_()

    def change_language(self, language_text):
        """Dil değiştir ve UI'ı yenile"""
        language_code = 'tr' if language_text == 'TR' else 'en'
        get_language_manager().set_language(language_code)
        self.refresh_ui_texts()

    def refresh_ui_texts(self):
        """UI metinlerini yenile"""
        # Pencere başlığı
        self.setWindowTitle(_('app_title'))

        # Butonlar
        self.proxy_start_button.setText(_('proxy_start') if not self.proxy_enabled else _('proxy_active'))
        self.proxy_stop_button.setText(_('proxy_stop'))
        self.add_account_button.setText(_('add_account'))
        self.refresh_limits_button.setText(_('refresh_limits'))
        self.help_button.setText(_('help'))

        # Tablo başlıkları
        self.table.setHorizontalHeaderLabels([_('current'), _('email'), _('status'), _('limit')])

        # Status bar
        debug_mode = os.path.exists("debug.txt")
        if debug_mode:
            self.status_bar.showMessage(_('default_status_debug'))
        else:
            self.status_bar.showMessage(_('default_status'))

        # Tabloyu yeniden yükle
        self.load_accounts(preserve_limits=True)

    def on_account_added_via_bridge(self, email):
        """Bridge üzerinden hesap eklendiğinde tabloyu yenile"""
        try:
            print(f"🔄 Bridge: Tablo yenileniyor - {email}")
            # Thread-safe sinyal emit et
            self.bridge_account_added.emit(email)
            print("✅ Bridge: Tablo yenileme sinyali gönderildi")
        except Exception as e:
            print(f"❌ Bridge: Tablo yenileme hatası - {e}")

    def refresh_table_after_bridge_add(self, email):
        """Bridge sonrası tablo yenileme (ana thread'de çalışır)"""
        try:
            print(f"🔄 Ana thread'de tablo yenileniyor... ({email})")
            self.load_accounts(preserve_limits=True)

            # Kullanıcıya bildiri göster
            self.status_bar.showMessage(f"✅ Yeni hesap bridge ile eklendi: {email}", 5000)
            print("✅ Tablo başarıyla yenilendi")
        except Exception as e:
            print(f"❌ Ana thread tablo yenileme hatası: {e}")

    def closeEvent(self, event):
        """Uygulama kapanırken temizlik yap"""
        if self.proxy_enabled:
            self.stop_proxy()

        # Bridge server'ı durdur
        if hasattr(self, 'bridge_server'):
            self.bridge_server.stop()

        event.accept()


def main():
    app = QApplication(sys.argv)
    # Uygulama stili: modern ve kompakt
    load_stylesheet(app)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
