"""
IMAP Modified UTF-7 编解码适配层 (RFC 3501 Section 5.1.3)
"""

from imapclient import imap_utf7


def mutf7_encode(s: str) -> str:
    """将 Unicode 字符串编码为 Modified UTF-7 字符串"""
    if not s:
        return ""
    encoded = imap_utf7.encode(s)
    return encoded.decode("ascii") if isinstance(encoded, bytes) else str(encoded)


def mutf7_decode(s: str | bytes) -> str:
    """将 Modified UTF-7 字节或字符串解码为 Unicode 字符串"""
    if not s:
        return ""
    s_bytes = s.encode("ascii", errors="ignore") if isinstance(s, str) else s
    try:
        return imap_utf7.decode(s_bytes)
    except Exception:
        return str(s)
