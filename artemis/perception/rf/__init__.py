"""
artemis/perception/rf — RF perception package.

Exports:
- RTLSDRListener: RTL-SDR hardware driver
- RFFingerprinter: Protocol fingerprinting from IQ samples
"""

from artemis.perception.rf.rtlsdr_listener import RTLSDRListener

try:
    from artemis.perception.rf.fingerprinter import (
        RFFingerprinter,
        FingerprintResult,
        Protocol,
        fingerprint_iq,
    )
    __all__ = [
        "RTLSDRListener",
        "RFFingerprinter",
        "FingerprintResult",
        "Protocol",
        "fingerprint_iq",
    ]
except ImportError:
    __all__ = ["RTLSDRListener"]