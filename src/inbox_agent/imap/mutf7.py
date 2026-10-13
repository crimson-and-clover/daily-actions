"""
IMAP Modified UTF-7 编解码适配层 (RFC 3501 Section 5.1.3)
底层引入标准成熟的第三方库 `imapclient.imap_utf7` 实现稳定可靠的转码，避免手写解析边界出错。
提供给 GmailClient 内部专享，外部调用方对转码完全无感知。
"""

from imapclient import imap_utf7


def mutf7_encode(s: str) -> str:
    """将 Unicode 字符串编码为 IMAP 协议合规的 Modified UTF-7 字符串"""
    if not s:
        return ""
    encoded = imap_utf7.encode(s)
    return encoded.decode("ascii") if isinstance(encoded, bytes) else str(encoded)


def mutf7_decode(s: str | bytes) -> str:
    """将 IMAP Modified UTF-7 字节或字符串解码还原为正常 Unicode 字符串"""
    if not s:
        return ""
    if isinstance(s, str):
        # 针对已经是 str 类型的 mUTF-7 串转换为 ascii bytes 进行标准解码
        s_bytes = s.encode("ascii", errors="ignore")
    else:
        s_bytes = s
    try:
        return imap_utf7.decode(s_bytes)
    except Exception:
        return str(s)
