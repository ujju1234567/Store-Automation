"""
bin_master.py - Aerospace Store BIN Location Recommendation Engine
Recommends storage BIN and warehouse zone based on document verification,
material grade, component type, and aerospace compliance rules.
"""

import os
import json

# Pre-defined Aerospace Storage Bin Mapping
DEFAULT_BIN_MAP = {
    # Materials / Raw Stock
    "ALUMINUM": {"zone": "RAW-AL (Aluminum Store)", "bin": "BIN-AL-A01", "rack": "Rack A, Shelf 1"},
    "TITANIUM": {"zone": "RAW-TI (Titanium Vault)", "bin": "BIN-TI-V01", "rack": "Vault Zone 1"},
    "STEEL":    {"zone": "RAW-ST (Steel Yard)", "bin": "BIN-ST-S05", "rack": "Yard Row 5"},
    "INCONEL":  {"zone": "EXOTIC (Exotic Alloys)", "bin": "BIN-EX-I02", "rack": "Rack I, Shelf 2"},
    
    # Fasteners & Hardware
    "FASTENER": {"zone": "HARDWARE (Standard Store)", "bin": "BIN-FAS-B12", "rack": "Bin Rack B, Drawer 12"},
    "BOLT":     {"zone": "HARDWARE (Standard Store)", "bin": "BIN-FAS-B14", "rack": "Bin Rack B, Drawer 14"},
    "NUT":      {"zone": "HARDWARE (Standard Store)", "bin": "BIN-FAS-N02", "rack": "Bin Rack N, Drawer 2"},
    "RIVET":    {"zone": "HARDWARE (Standard Store)", "bin": "BIN-FAS-R08", "rack": "Bin Rack R, Drawer 8"},

    # Default / Quarantine
    "QUARANTINE": {"zone": "QC-HOLD (Quarantine Zone)", "bin": "BIN-QC-HOLD", "rack": "Red Cage STN-01"},
    "GENERAL":    {"zone": "GEN-RECEIVING", "bin": "BIN-GEN-R01", "rack": "Receiving Staging Bay 1"},
}


def determine_bin_location(extracted_fields: dict, is_approved: bool, quarantine_reason: str = "") -> dict:
    """
    Determines the appropriate BIN location for received items.
    
    If document comparison is NOT approved or critical certificate (CoC/MTC) is missing,
    routes to QUARANTINE BIN (QC-HOLD).
    
    Otherwise routes based on Part Description, Material Grade, or Material Type.
    """
    if not is_approved:
        return {
            "status": "QUARANTINE",
            "zone": DEFAULT_BIN_MAP["QUARANTINE"]["zone"],
            "bin": DEFAULT_BIN_MAP["QUARANTINE"]["bin"],
            "rack": DEFAULT_BIN_MAP["QUARANTINE"]["rack"],
            "reason": quarantine_reason or "Document discrepancy / Non-conforming verification",
            "instruction": "⚠️ Place physical parts in RED QUARANTINE CAGE for Quality Engineering review."
        }
    
    part_num = (extracted_fields.get("part_number") or "").upper()
    part_desc = (extracted_fields.get("part_description") or "").upper()
    raw_text = json.dumps(extracted_fields).upper()
    
    # Check material keywords
    if any(k in raw_text for k in ["ALUMINUM", "ALU", "7075", "6061", "2024", "AMS 4027"]):
        match = DEFAULT_BIN_MAP["ALUMINUM"]
    elif any(k in raw_text for k in ["TITANIUM", "TI-6AL-4V", "AMS 4911"]):
        match = DEFAULT_BIN_MAP["TITANIUM"]
    elif any(k in raw_text for k in ["STEEL", "STAINLESS", "17-4PH", "316L", "AMS 5643"]):
        match = DEFAULT_BIN_MAP["STEEL"]
    elif any(k in raw_text for k in ["INCONEL", "INC718"]):
        match = DEFAULT_BIN_MAP["INCONEL"]
    elif any(k in raw_text for k in ["FASTENER", "BOLT", "NUT", "RIVET", "SCREW", "WASHER"]):
        match = DEFAULT_BIN_MAP["FASTENER"]
    else:
        match = DEFAULT_BIN_MAP["GENERAL"]

    return {
        "status": "APPROVED",
        "zone": match["zone"],
        "bin": match["bin"],
        "rack": match["rack"],
        "reason": "Document verification 100% passed",
        "instruction": f"✅ Move parts to Warehouse Zone: {match['zone']} -> BIN {match['bin']}"
    }
