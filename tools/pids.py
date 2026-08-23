"""SAE J1979 サービス01 標準 PID の定義表。

各エントリ: pid -> (データバイト数, 名称, 変換式 or None, 単位)
変換式は data(bytes) を受け取り数値を返す。ビットマップ等、単純な数値に
落ちないものは None（生バイトのみ記録する）。
"""


def _u16(d):
    return (d[0] << 8) | d[1]


PIDS = {
    0x01: (4, "Monitor status since DTCs cleared", None, ""),
    0x02: (2, "Freeze DTC", None, ""),
    0x03: (2, "Fuel system status", None, ""),
    0x04: (1, "Calculated engine load", lambda d: d[0] * 100 / 255, "%"),
    0x05: (1, "Engine coolant temperature", lambda d: d[0] - 40, "degC"),
    0x06: (1, "Short term fuel trim b1", lambda d: (d[0] - 128) * 100 / 128, "%"),
    0x07: (1, "Long term fuel trim b1", lambda d: (d[0] - 128) * 100 / 128, "%"),
    0x08: (1, "Short term fuel trim b2", lambda d: (d[0] - 128) * 100 / 128, "%"),
    0x09: (1, "Long term fuel trim b2", lambda d: (d[0] - 128) * 100 / 128, "%"),
    0x0A: (1, "Fuel pressure", lambda d: d[0] * 3, "kPa"),
    0x0B: (1, "Intake manifold absolute pressure", lambda d: d[0], "kPa"),
    0x0C: (2, "Engine speed", lambda d: _u16(d) / 4, "rpm"),
    0x0D: (1, "Vehicle speed", lambda d: d[0], "km/h"),
    0x0E: (1, "Timing advance", lambda d: d[0] / 2 - 64, "deg"),
    0x0F: (1, "Intake air temperature", lambda d: d[0] - 40, "degC"),
    0x10: (2, "MAF air flow rate", lambda d: _u16(d) / 100, "g/s"),
    0x11: (1, "Throttle position", lambda d: d[0] * 100 / 255, "%"),
    0x12: (1, "Commanded secondary air status", None, ""),
    0x13: (1, "O2 sensors present (2 banks)", None, ""),
    0x14: (2, "O2 S1 voltage / STFT", lambda d: d[0] / 200, "V"),
    0x15: (2, "O2 S2 voltage / STFT", lambda d: d[0] / 200, "V"),
    0x16: (2, "O2 S3 voltage / STFT", lambda d: d[0] / 200, "V"),
    0x17: (2, "O2 S4 voltage / STFT", lambda d: d[0] / 200, "V"),
    0x18: (2, "O2 S5 voltage / STFT", lambda d: d[0] / 200, "V"),
    0x19: (2, "O2 S6 voltage / STFT", lambda d: d[0] / 200, "V"),
    0x1A: (2, "O2 S7 voltage / STFT", lambda d: d[0] / 200, "V"),
    0x1B: (2, "O2 S8 voltage / STFT", lambda d: d[0] / 200, "V"),
    0x1C: (1, "OBD standards conformance", None, ""),
    0x1D: (1, "O2 sensors present (4 banks)", None, ""),
    0x1E: (1, "Auxiliary input status", None, ""),
    0x1F: (2, "Run time since engine start", lambda d: _u16(d), "s"),
    0x21: (2, "Distance with MIL on", lambda d: _u16(d), "km"),
    0x22: (2, "Fuel rail pressure (rel. manifold)", lambda d: _u16(d) * 0.079, "kPa"),
    0x23: (2, "Fuel rail gauge pressure", lambda d: _u16(d) * 10, "kPa"),
    0x24: (4, "O2 S1 lambda / voltage", lambda d: _u16(d[0:2]) / 32768, "ratio"),
    0x25: (4, "O2 S2 lambda / voltage", lambda d: _u16(d[0:2]) / 32768, "ratio"),
    0x26: (4, "O2 S3 lambda / voltage", lambda d: _u16(d[0:2]) / 32768, "ratio"),
    0x27: (4, "O2 S4 lambda / voltage", lambda d: _u16(d[0:2]) / 32768, "ratio"),
    0x28: (4, "O2 S5 lambda / voltage", lambda d: _u16(d[0:2]) / 32768, "ratio"),
    0x29: (4, "O2 S6 lambda / voltage", lambda d: _u16(d[0:2]) / 32768, "ratio"),
    0x2A: (4, "O2 S7 lambda / voltage", lambda d: _u16(d[0:2]) / 32768, "ratio"),
    0x2B: (4, "O2 S8 lambda / voltage", lambda d: _u16(d[0:2]) / 32768, "ratio"),
    0x2C: (1, "Commanded EGR", lambda d: d[0] * 100 / 255, "%"),
    0x2D: (1, "EGR error", lambda d: (d[0] - 128) * 100 / 128, "%"),
    0x2E: (1, "Commanded evaporative purge", lambda d: d[0] * 100 / 255, "%"),
    0x2F: (1, "Fuel tank level input", lambda d: d[0] * 100 / 255, "%"),
    0x30: (1, "Warm-ups since codes cleared", lambda d: d[0], "count"),
    0x31: (2, "Distance since codes cleared", lambda d: _u16(d), "km"),
    0x32: (2, "Evap system vapor pressure", lambda d: _s16(d) / 4, "Pa"),
    0x33: (1, "Absolute barometric pressure", lambda d: d[0], "kPa"),
    0x34: (4, "O2 S1 lambda / current", lambda d: _u16(d[0:2]) / 32768, "ratio"),
    0x35: (4, "O2 S2 lambda / current", lambda d: _u16(d[0:2]) / 32768, "ratio"),
    0x36: (4, "O2 S3 lambda / current", lambda d: _u16(d[0:2]) / 32768, "ratio"),
    0x37: (4, "O2 S4 lambda / current", lambda d: _u16(d[0:2]) / 32768, "ratio"),
    0x38: (4, "O2 S5 lambda / current", lambda d: _u16(d[0:2]) / 32768, "ratio"),
    0x39: (4, "O2 S6 lambda / current", lambda d: _u16(d[0:2]) / 32768, "ratio"),
    0x3A: (4, "O2 S7 lambda / current", lambda d: _u16(d[0:2]) / 32768, "ratio"),
    0x3B: (4, "O2 S8 lambda / current", lambda d: _u16(d[0:2]) / 32768, "ratio"),
    0x3C: (2, "Catalyst temperature b1s1", lambda d: _u16(d) / 10 - 40, "degC"),
    0x3D: (2, "Catalyst temperature b2s1", lambda d: _u16(d) / 10 - 40, "degC"),
    0x3E: (2, "Catalyst temperature b1s2", lambda d: _u16(d) / 10 - 40, "degC"),
    0x3F: (2, "Catalyst temperature b2s2", lambda d: _u16(d) / 10 - 40, "degC"),
    0x41: (4, "Monitor status this drive cycle", None, ""),
    0x42: (2, "Control module voltage", lambda d: _u16(d) / 1000, "V"),
    0x43: (2, "Absolute load value", lambda d: _u16(d) * 100 / 255, "%"),
    0x44: (2, "Commanded equivalence ratio", lambda d: _u16(d) / 32768, "ratio"),
    0x45: (1, "Relative throttle position", lambda d: d[0] * 100 / 255, "%"),
    0x46: (1, "Ambient air temperature", lambda d: d[0] - 40, "degC"),
    0x47: (1, "Absolute throttle position B", lambda d: d[0] * 100 / 255, "%"),
    0x48: (1, "Absolute throttle position C", lambda d: d[0] * 100 / 255, "%"),
    0x49: (1, "Accelerator pedal position D", lambda d: d[0] * 100 / 255, "%"),
    0x4A: (1, "Accelerator pedal position E", lambda d: d[0] * 100 / 255, "%"),
    0x4B: (1, "Accelerator pedal position F", lambda d: d[0] * 100 / 255, "%"),
    0x4C: (1, "Commanded throttle actuator", lambda d: d[0] * 100 / 255, "%"),
    0x4D: (2, "Time run with MIL on", lambda d: _u16(d), "min"),
    0x4E: (2, "Time since codes cleared", lambda d: _u16(d), "min"),
    0x4F: (4, "Max values (lambda/V/mA/kPa)", None, ""),
    0x50: (4, "Max MAF air flow rate", lambda d: d[0] * 10, "g/s"),
    0x51: (1, "Fuel type", None, ""),
    0x52: (1, "Ethanol fuel percent", lambda d: d[0] * 100 / 255, "%"),
    0x53: (2, "Absolute evap vapor pressure", lambda d: _u16(d) / 200, "kPa"),
    0x54: (2, "Evap system vapor pressure", lambda d: _s16(d), "Pa"),
    0x59: (2, "Fuel rail absolute pressure", lambda d: _u16(d) * 10, "kPa"),
    0x5A: (1, "Relative accelerator pedal position", lambda d: d[0] * 100 / 255, "%"),
    0x5B: (1, "Hybrid battery pack remaining life", lambda d: d[0] * 100 / 255, "%"),
    0x5C: (1, "Engine oil temperature", lambda d: d[0] - 40, "degC"),
    0x5D: (2, "Fuel injection timing", lambda d: (_u16(d) - 26880) / 128, "deg"),
    0x5E: (2, "Engine fuel rate", lambda d: _u16(d) / 20, "L/h"),
    0x5F: (1, "Emission requirements designation", None, ""),
    0x65: (2, "Auxiliary input/output supported", None, ""),
    0x61: (1, "Driver's demand torque", lambda d: d[0] - 125, "%"),
    0x62: (1, "Actual engine torque", lambda d: d[0] - 125, "%"),
    0x63: (2, "Engine reference torque", lambda d: _u16(d), "Nm"),
}


def _s16(d):
    v = (d[0] << 8) | d[1]
    return v - 65536 if v & 0x8000 else v


def describe(pid, data):
    """PID と生データから (名称, 値, 単位) を返す。未知 PID は名称 '?'。"""
    ent = PIDS.get(pid)
    if not ent:
        return ("?", None, "")
    nbytes, name, fn, unit = ent
    if fn is None or len(data) < nbytes:
        return (name, None, unit)
    try:
        return (name, round(fn(data[:nbytes]), 3), unit)
    except Exception:
        return (name, None, unit)


def expected_len(pid):
    ent = PIDS.get(pid)
    return ent[0] if ent else None
