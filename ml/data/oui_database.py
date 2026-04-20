"""OUI (Organizationally Unique Identifier) database for MAC vendor lookup."""

from __future__ import annotations


class OUIDatabase:
    """MAC address vendor lookup using built-in OUI prefix dictionary.

    Provides fast O(1) lookup of device manufacturer from the first three
    octets of a MAC address.
    """

    def __init__(self) -> None:
        self._db: dict[str, str] = {}
        self._load_builtin()

    def lookup(self, mac: str) -> str | None:
        """Look up vendor by MAC prefix (first 3 octets).

        Args:
            mac: Full MAC address in colon or dash separated format,
                 e.g. "AA:BB:CC:DD:EE:FF" or "AA-BB-CC-DD-EE-FF".

        Returns:
            Vendor name string or None if not found.
        """
        normalized = mac.upper().replace("-", ":").strip()
        prefix = normalized[:8]  # "AA:BB:CC"
        return self._db.get(prefix)

    def _load_builtin(self) -> None:
        """Load top 50+ common WiFi device OUI prefixes."""
        entries: dict[str, str] = {
            # Apple
            "AC:DE:48": "Apple",
            "A4:83:E7": "Apple",
            "F0:18:98": "Apple",
            "DC:A9:04": "Apple",
            "78:7B:8A": "Apple",
            "3C:22:FB": "Apple",
            "14:7D:DA": "Apple",
            # Samsung
            "8C:F5:A3": "Samsung",
            "AC:5F:3E": "Samsung",
            "50:01:BB": "Samsung",
            "C0:BD:D1": "Samsung",
            "78:BD:BC": "Samsung",
            # Google / Nest
            "F4:F5:D8": "Google",
            "54:60:09": "Google",
            "A4:77:33": "Google",
            "30:FD:38": "Google",
            # Intel
            "68:17:29": "Intel",
            "B4:6B:FC": "Intel",
            "8C:8D:28": "Intel",
            "34:13:E8": "Intel",
            "48:51:B7": "Intel",
            # Broadcom
            "20:10:7A": "Broadcom",
            "00:10:18": "Broadcom",
            "00:1B:E9": "Broadcom",
            # Qualcomm / QCA
            "9C:F3:87": "Qualcomm",
            "00:03:7F": "Qualcomm",
            "B4:CB:57": "Qualcomm",
            # Cisco / Meraki
            "00:1A:A1": "Cisco",
            "00:1B:0D": "Cisco",
            "F8:C2:88": "Cisco",
            "00:18:0A": "Cisco-Meraki",
            "0C:8D:DB": "Cisco-Meraki",
            # TP-Link
            "50:C7:BF": "TP-Link",
            "EC:08:6B": "TP-Link",
            "B0:BE:76": "TP-Link",
            "60:32:B1": "TP-Link",
            # Netgear
            "C4:04:15": "Netgear",
            "A4:2B:8C": "Netgear",
            "28:C6:8E": "Netgear",
            # Espressif (ESP32/ESP8266)
            "24:6F:28": "Espressif",
            "AC:67:B2": "Espressif",
            "30:AE:A4": "Espressif",
            "A4:CF:12": "Espressif",
            # Raspberry Pi Foundation
            "B8:27:EB": "Raspberry Pi",
            "DC:A6:32": "Raspberry Pi",
            "E4:5F:01": "Raspberry Pi",
            # Huawei
            "48:46:FB": "Huawei",
            "88:66:A5": "Huawei",
            "4C:B1:6C": "Huawei",
            # Xiaomi
            "28:6C:07": "Xiaomi",
            "64:CC:2E": "Xiaomi",
            "78:11:DC": "Xiaomi",
            # Amazon (Ring, Echo, Fire)
            "F0:F0:A4": "Amazon",
            "74:C2:46": "Amazon",
            "A0:02:DC": "Amazon",
            # Microsoft (Xbox, Surface)
            "7C:ED:8D": "Microsoft",
            "28:18:78": "Microsoft",
            # Ubiquiti
            "FC:EC:DA": "Ubiquiti",
            "24:5A:4C": "Ubiquiti",
            "80:2A:A8": "Ubiquiti",
            # Aruba / HPE
            "00:0B:86": "Aruba",
            "24:DE:C6": "Aruba",
            "D8:C7:C8": "Aruba",
            # Ruckus
            "C4:10:8A": "Ruckus",
            "74:91:1A": "Ruckus",
            # MediaTek
            "00:0C:E7": "MediaTek",
            "C4:01:7C": "MediaTek",
            # Realtek
            "00:E0:4C": "Realtek",
            "48:5B:39": "Realtek",
            "52:54:00": "Realtek",
            # Sony
            "AC:9B:0A": "Sony",
            "FC:0F:E6": "Sony",
            # LG
            "C4:9A:02": "LG",
            "10:68:3F": "LG",
            # OnePlus / OPPO
            "94:65:2D": "OnePlus",
            "C0:EE:FB": "OPPO",
            # D-Link
            "1C:7E:E5": "D-Link",
            "B8:A3:86": "D-Link",
            # Asus
            "04:D4:C4": "Asus",
            "2C:FD:A1": "Asus",
            # Motorola / Lenovo
            "C8:14:51": "Motorola",
            "EC:2E:4E": "Lenovo",
        }
        self._db = entries

    @property
    def vendor_count(self) -> int:
        """Return number of OUI entries in the database."""
        return len(self._db)

    def all_vendors(self) -> set[str]:
        """Return the set of unique vendor names."""
        return set(self._db.values())
