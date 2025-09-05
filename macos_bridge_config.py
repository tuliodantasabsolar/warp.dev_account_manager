#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
macOS Bridge Configuration - Native messaging setup for Chrome extension
"""

import os
import sys
import json
from pathlib import Path


class MacOSBridgeConfig:
    def __init__(self):
        self.extension_id = "warp-account-bridge-v1"
        self.app_name = "com.warp.account.bridge"
        self.native_messaging_dir = Path.home() / "Library/Application Support/Google/Chrome/NativeMessagingHosts"

    def is_admin(self):
        """Check if running as administrator (root)"""
        return os.getuid() == 0

    def setup_localhost_access(self):
        """Configure macOS for localhost access from extensions"""
        try:
            print("🔧 Chrome extension manifest localhost access...")

            # Chrome extension uses externally_connectable in manifest
            # No additional macOS-specific registry settings needed
            print("✅ Manifest-based localhost access active")
            print("📋 Extension manifest has externally_connectable configuration")

            return True

        except Exception as e:
            print(f"❌ Localhost access setup error: {e}")
            return False

    def create_native_messaging_manifest(self):
        """Create native messaging host manifest for macOS"""
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

            # Create manifest directory if it doesn't exist
            self.native_messaging_dir.mkdir(parents=True, exist_ok=True)

            manifest_path = self.native_messaging_dir / f"{self.app_name}.json"
            with open(manifest_path, 'w') as f:
                json.dump(manifest, f, indent=2)

            print(f"✅ Native messaging manifest created: {manifest_path}")
            return str(manifest_path)

        except Exception as e:
            print(f"❌ Manifest creation error: {e}")
            return None

    def register_native_host(self):
        """Register native messaging host (macOS uses file-based registration)"""
        try:
            manifest_path = self.create_native_messaging_manifest()
            if not manifest_path:
                return False

            print(f"✅ Native host registered: {manifest_path}")
            return True

        except Exception as e:
            print(f"❌ Native host registration error: {e}")
            return False

    def setup_bridge_config(self):
        """Complete bridge configuration for macOS"""
        print("🌉 macOS Bridge configuration starting...")

        # 1. Localhost access setup
        localhost_ok = self.setup_localhost_access()

        # 2. Native messaging host registration
        native_ok = self.register_native_host()

        if localhost_ok and native_ok:
            print("✅ Bridge configuration completed!")
            print("\n📋 Next steps:")
            print("1. Restart Chrome")
            print("2. Load extension from chrome://extensions/ page")
            print("3. Start Warp Account Manager")
            return True
        else:
            print("❌ Bridge configuration failed!")
            return False

    def check_configuration(self):
        """Check if bridge is properly configured"""
        try:
            print("🔍 Checking bridge configuration...")

            # Check if manifest file exists
            manifest_path = self.native_messaging_dir / f"{self.app_name}.json"
            if manifest_path.exists():
                print("✅ Native messaging manifest found")
                return True
            else:
                print("❌ Native messaging manifest not found")
                return False

        except Exception as e:
            print(f"❌ Configuration check error: {e}")
            return False

    def remove_configuration(self):
        """Remove bridge configuration (cleanup)"""
        try:
            print("🧹 Cleaning up bridge configuration...")

            # Remove manifest file
            manifest_path = self.native_messaging_dir / f"{self.app_name}.json"
            if manifest_path.exists():
                manifest_path.unlink()
                print("✅ Manifest file removed")
            else:
                print("⚠️  Manifest file not found")

            return True

        except Exception as e:
            print(f"❌ Cleanup error: {e}")
            return False


def setup_bridge():
    """Setup bridge configuration"""
    config = MacOSBridgeConfig()
    return config.setup_bridge_config()

def check_bridge():
    """Check bridge configuration"""
    config = MacOSBridgeConfig()
    return config.check_configuration()

def remove_bridge():
    """Remove bridge configuration"""
    config = MacOSBridgeConfig()
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
            print("Usage: python macos_bridge_config.py [setup|check|remove]")
    else:
        # Default: setup
        setup_bridge()