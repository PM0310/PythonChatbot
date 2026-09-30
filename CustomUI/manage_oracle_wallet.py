#!/usr/bin/env python3
"""
Oracle Wallet Manager - Extract and Manage Oracle Wallets
Usage: python manage_oracle_wallet.py --help
"""

import os
import sys
import json
import zipfile
import argparse
from pathlib import Path
from typing import Dict, List, Optional


class OracleWalletManager:
    """Manage Oracle Wallet extraction and configuration"""

    REQUIRED_FILES = ["cwallet.sso", "ewallet.p12", "tnsnames.ora", "sqlnet.ora"]

    def __init__(self, wallet_dir: str = r"C:\oracle\wallet"):
        self.wallet_dir = Path(wallet_dir)
        self.wallet_dir.mkdir(parents=True, exist_ok=True)

    def extract_wallet(self, zip_path: str) -> bool:
        """Extract wallet from ZIP file"""
        zip_path = Path(zip_path)

        if not zip_path.exists():
            print(f"❌ ERROR: Wallet ZIP not found: {zip_path}")
            return False

        print(f"📦 Extracting wallet from: {zip_path}")

        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(self.wallet_dir)
            print(f"✅ Wallet extracted to: {self.wallet_dir}")
            return self.verify_wallet()
        except Exception as e:
            print(f"❌ Error extracting wallet: {e}")
            return False

    def verify_wallet(self) -> bool:
        """Verify all required wallet files exist"""
        print("\n📋 Verifying wallet files...")

        all_found = True
        for file in self.REQUIRED_FILES:
            file_path = self.wallet_dir / file
            if file_path.exists():
                size = file_path.stat().st_size
                print(f"  ✅ {file} ({size:,} bytes)")
            else:
                print(f"  ❌ Missing: {file}")
                all_found = False

        if all_found:
            print("\n✅ All required wallet files found!")
        else:
            print("\n❌ Some wallet files are missing!")

        return all_found

    def read_wallet_file(self, filename: str) -> Optional[str]:
        """Read wallet file content"""
        file_path = self.wallet_dir / filename

        if not file_path.exists():
            return None

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception as e:
            print(f"❌ Error reading {filename}: {e}")
            return None

    def display_wallet_details(self):
        """Display wallet details"""
        print("\n" + "=" * 60)
        print("ORACLE WALLET DETAILS")
        print("=" * 60)

        # Display wallet location
        print(f"\n📁 Wallet Location: {self.wallet_dir}")

        # Display file list
        print("\n📄 Wallet Files:")
        for file in self.REQUIRED_FILES:
            file_path = self.wallet_dir / file
            if file_path.exists():
                size = file_path.stat().st_size
                print(f"   ✅ {file:<20} {size:>10,} bytes")

        # Display README
        readme_content = self.read_wallet_file("README.txt")
        if readme_content:
            print("\n" + "=" * 60)
            print("README.TXT")
            print("=" * 60)
            print(readme_content)

        # Display tnsnames.ora
        tns_content = self.read_wallet_file("tnsnames.ora")
        if tns_content:
            print("\n" + "=" * 60)
            print("TNSNAMES.ORA (Connection Strings)")
            print("=" * 60)
            print(tns_content[:2000])  # First 2000 chars
            if len(tns_content) > 2000:
                print("\n[... truncated for brevity ...]")

        # Display sqlnet.ora
        sqlnet_content = self.read_wallet_file("sqlnet.ora")
        if sqlnet_content:
            print("\n" + "=" * 60)
            print("SQLNET.ORA (Configuration)")
            print("=" * 60)
            print(sqlnet_content)

    def extract_service_names(self) -> List[str]:
        """Extract service names from tnsnames.ora"""
        import re

        tns_content = self.read_wallet_file("tnsnames.ora")
        if not tns_content:
            return []

        # Find service names (lines ending with =)
        pattern = r"^(\w+)\s*="
        services = re.findall(pattern, tns_content, re.MULTILINE)
        return services

    def extract_connection_details(self) -> Dict:
        """Extract connection details from tnsnames.ora"""
        import re

        tns_content = self.read_wallet_file("tnsnames.ora")
        if not tns_content:
            return {}

        details = {}

        # Extract host
        host_match = re.search(r"host=([^\)]+)", tns_content)
        if host_match:
            details["host"] = host_match.group(1).strip()

        # Extract port
        port_match = re.search(r"port=(\d+)", tns_content)
        if port_match:
            details["port"] = int(port_match.group(1))

        # Extract service names
        services = self.extract_service_names()
        if services:
            details["services"] = services
            details["default_service"] = services[0]

        return details

    def create_config_file(self, output_path: Optional[str] = None):
        """Create configuration file"""
        if output_path is None:
            output_path = self.wallet_dir / "wallet_config.json"
        else:
            output_path = Path(output_path)

        connection_details = self.extract_connection_details()
        services = self.extract_service_names()

        config = {
            "wallet": {
                "location": str(self.wallet_dir),
                "verified": self.verify_wallet(),
                "files": list(self.wallet_dir.glob("*")),
            },
            "connection": {
                "host": connection_details.get("host", ""),
                "port": connection_details.get("port", 1522),
                "services": services,
                "default_service": services[0] if services else "adwc_low",
            },
            "database": {"user": "admin", "default_role": "DWROLE"},
            "environment": {
                "TNS_ADMIN": str(self.wallet_dir),
                "ORACLE_HOME": r"C:\oracle\client",
            },
        }

        # Convert Path objects to strings for JSON
        config["wallet"]["files"] = [str(f) for f in config["wallet"]["files"]]

        try:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            print(f"\n✅ Configuration file created: {output_path}")
            print("\nContents:")
            print(json.dumps(config, indent=2))
        except Exception as e:
            print(f"❌ Error creating config file: {e}")

    def set_environment(self):
        """Set environment variables"""
        print(f"\n🔧 Setting environment variables...")

        # Set TNS_ADMIN
        os.environ["TNS_ADMIN"] = str(self.wallet_dir)
        print(f"   ✅ TNS_ADMIN = {os.environ['TNS_ADMIN']}")

        # For Windows, also show how to set permanently
        print("\n📝 To set permanently in Windows:")
        print(f'   setx TNS_ADMIN "{self.wallet_dir}"')

        return True

    def find_wallets(self) -> List[Path]:
        """Find wallet files on system"""
        print("\n🔍 Searching for wallet files...")

        wallet_files = []

        # Search common locations
        search_paths = [
            Path("C:\\oracle\\wallet"),
            Path("C:\\Users").expanduser(),
            Path("C:\\Downloads"),
            Path("C:\\"),
        ]

        for search_path in search_paths:
            if search_path.exists():
                # Search for wallet ZIPs
                wallet_zips = list(search_path.glob("**/Wallet*.zip"))
                wallet_files.extend(wallet_zips)

                # Search for wallet directories
                wallet_dirs = list(search_path.glob("**/wallet"))
                wallet_files.extend(wallet_dirs)

        # Remove duplicates and limit results
        wallet_files = list(set(wallet_files))[:20]

        if wallet_files:
            print(f"\n✅ Found {len(wallet_files)} wallet files:\n")
            for wallet in wallet_files:
                if wallet.is_file():
                    size = wallet.stat().st_size
                    print(f"   📦 {wallet} ({size:,} bytes)")
                else:
                    print(f"   📁 {wallet}/")
        else:
            print("\n❌ No wallet files found on system")

        return wallet_files


def main():
    parser = argparse.ArgumentParser(
        description="Oracle Wallet Manager - Extract and configure Oracle Wallets"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Extract command
    extract_parser = subparsers.add_parser(
        "extract", help="Extract wallet from ZIP file"
    )
    extract_parser.add_argument("zipfile", help="Path to wallet ZIP file")
    extract_parser.add_argument(
        "--dest", default=r"C:\oracle\wallet", help="Destination directory"
    )

    # Display command
    subparsers.add_parser("display", help="Display wallet details")

    # Services command
    subparsers.add_parser("services", help="List available services")

    # Config command
    config_parser = subparsers.add_parser("config", help="Create config file")
    config_parser.add_argument(
        "--output",
        default=None,
        help="Output path for config file (default: wallet_config.json)",
    )

    # Environment command
    subparsers.add_parser("env", help="Set environment variables")

    # Find command
    subparsers.add_parser("find", help="Find wallet files on system")

    # Verify command
    subparsers.add_parser("verify", help="Verify wallet integrity")

    args = parser.parse_args()

    # Create manager
    wallet_dir = getattr(args, "dest", r"C:\oracle\wallet")
    manager = OracleWalletManager(wallet_dir)

    if args.command == "extract":
        manager.extract_wallet(args.zipfile)
    elif args.command == "display":
        manager.display_wallet_details()
    elif args.command == "services":
        services = manager.extract_service_names()
        print("\n📋 Available Service Names:")
        for service in services:
            print(f"   • {service}")
    elif args.command == "config":
        manager.create_config_file(args.output)
    elif args.command == "env":
        manager.set_environment()
    elif args.command == "find":
        manager.find_wallets()
    elif args.command == "verify":
        manager.verify_wallet()
    else:
        print("Oracle Wallet Manager")
        print("=" * 60)
        print("\nUsage Examples:")
        print("\n1. Extract wallet:")
        print("   python manage_oracle_wallet.py extract C:\\Downloads\\Wallet_ADW.zip")
        print("\n2. Display wallet details:")
        print("   python manage_oracle_wallet.py display")
        print("\n3. List services:")
        print("   python manage_oracle_wallet.py services")
        print("\n4. Create config file:")
        print("   python manage_oracle_wallet.py config")
        print("\n5. Set environment:")
        print("   python manage_oracle_wallet.py env")
        print("\n6. Find wallet files:")
        print("   python manage_oracle_wallet.py find")
        print("\n7. Verify wallet:")
        print("   python manage_oracle_wallet.py verify")


if __name__ == "__main__":
    main()
