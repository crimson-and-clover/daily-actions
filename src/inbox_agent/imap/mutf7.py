"""
IMAP Modified UTF-7 编解码器 (RFC 3501 Section 5.1.3)

【为什么需要解码？】
根据 IMAP4rev1 规范 (RFC 3501)，邮箱目录名称（Mailbox Names）中的国际化字符（如中文"商业推广"、"系统通知"）
必须采用 Modified UTF-7 (mUTF-7) 格式传输。例如 Gmail 中文邮箱中的：
- "商业推广" 在 IMAP 协议中体现为 "&V4NXPpCu-"
- "系统通知" 在 IMAP 协议中体现为 "&V4NXPpDF-"
- "草稿" 在 IMAP 协议中体现为 "&g0l6Pw-"
若不进行解码，用户看到的文件夹名将是一串不可读的乱码字符。

【为什么不直接用第三方库？】
Python 标准库的 codecs 仅支持 RFC 2152 规定的普通 UTF-7（以 '+' 引导、使用 '/' 的 Base64），
而 RFC 3501 的 IMAP Modified UTF-7 改用了 '&' 作为引导符，并用 ',' 替代了 '/' 以免与目录路径分隔符冲突。
市面上虽有第三方库（如 `mutf7` 或庞大的 `imapclient`），但本模块用数十行标准库代码即可零依赖、高效、安全地完成编解码，
避免为了简单的目录名称转码额外引入外部重型依赖。
"""

import binascii


def mutf7_decode(s: str) -> str:
    """
    IMAP Modified UTF-7 解码 (RFC 3501)
    将类似 '&V4NXPpCu-' 的 IMAP 目录编码还原为可读字符串（如 '商业推广'）
    """
    res = []
    i = 0
    while i < len(s):
        if s[i] == "&":
            j = s.find("-", i)
            if j == -1:
                res.append(s[i:])
                break
            if j == i + 1:
                res.append("&")
            else:
                b64 = s[i + 1 : j].replace(",", "/")
                pad = len(b64) % 4
                if pad:
                    b64 += "=" * (4 - pad)
                try:
                    raw = binascii.a2b_base64(b64)
                    res.append(raw.decode("utf-16-be", errors="ignore"))
                except Exception:
                    res.append(s[i : j + 1])
            i = j + 1
        else:
            res.append(s[i])
            i += 1
    return "".join(res)


def mutf7_encode(s: str) -> str:
    """
    IMAP Modified UTF-7 编码 (RFC 3501)
    将中文字符串转换为合规的 IMAP 目录名称（用于在 Gmail 中创建或选择中文文件夹）
    """
    res = []
    b_buf = []
    for c in s:
        if 0x20 <= ord(c) <= 0x7E:
            if b_buf:
                b_str = "".join(b_buf).encode("utf-16-be")
                b64 = binascii.b2a_base64(b_str).decode("ascii").rstrip("\n").replace("/", ",").rstrip("=")
                res.append("&" + b64 + "-")
                b_buf = []
            if c == "&":
                res.append("&-")
            else:
                res.append(c)
        else:
            b_buf.append(c)
    if b_buf:
        b_str = "".join(b_buf).encode("utf-16-be")
        b64 = binascii.b2a_base64(b_str).decode("ascii").rstrip("\n").replace("/", ",").rstrip("=")
        res.append("&" + b64 + "-")
    return "".join(res)
