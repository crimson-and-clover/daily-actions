"""
Inbox Agent 邮箱交互客户端 (IMAP)
支持安全读取未读/近期邮件、移动垃圾邮件至垃圾箱、清理 90 天以上低价值邮件
"""

import binascii
import email
import email.message
import imaplib
import re
import sys
from datetime import timedelta
from email.header import decode_header

from inbox_agent.config import FETCH_DAYS_LIMIT, MAX_EMAILS_PER_RUN, PRUNE_DAYS, get_now_bjt


def mutf7_decode(s: str) -> str:
    """IMAP Modified UTF-7 解码 (RFC 3501)"""
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
    """IMAP Modified UTF-7 编码 (RFC 3501)，用于创建中文目录"""
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


def parse_folder_name_from_list_line(line) -> tuple[str, str]:
    """
    解析 imap.list() 返回的单行，提取 flags 和 folder_name。
    RFC 3501 LIST 格式形如: (\\HasNoChildren \\Spam) "/" "[Gmail]/&V4NXPpCu-"
    返回: (flags_str, folder_name)
    """
    if isinstance(line, bytes):
        raw_str = line.decode("utf-8", errors="ignore")
    else:
        raw_str = str(line)

    # 匹配 flags: (\Flag1 \Flag2)
    flags = ""
    flags_match = re.search(r"\(([^)]*)\)", raw_str)
    if flags_match:
        flags = flags_match.group(1)

    # 提取最后的 folder 路径 (可能带双引号或不带)
    # 取最后一个引号内的内容，或者最后一个空格之后的内容
    quoted_matches = re.findall(r'"([^"]+)"', raw_str)
    if quoted_matches:
        folder_name = quoted_matches[-1]
    else:
        folder_name = raw_str.strip().split()[-1]

    return flags, folder_name


def decode_str(header_val: str) -> str:
    """解码邮件主题与发件人等 RFC2047 头部"""
    if not header_val:
        return ""
    try:
        decoded_seq = decode_header(header_val)
        parts = []
        for content, enc in decoded_seq:
            if isinstance(content, bytes):
                parts.append(content.decode(enc or "utf-8", errors="ignore"))
            else:
                parts.append(str(content))
        return "".join(parts).strip()
    except Exception:
        return str(header_val).strip()


def extract_unsubscribe_link(msg: email.message.Message, raw_html: str = "") -> str:
    """提取邮件中的一键退订链接 (支持 RFC 2369 List-Unsubscribe 头部以及正文 HTML 链接)"""
    # 1. 优先提取标准 List-Unsubscribe 头部
    list_unsub = msg.get("List-Unsubscribe", "")
    if list_unsub:
        urls = re.findall(r"<https?://[^>]+>", list_unsub)
        if urls:
            return urls[0].strip("<>")

    # 2. 从 HTML 源码中正则提取退订相关链接
    if raw_html:
        matches = re.findall(r'<a[^>]+href=["\'](https?://[^"\']+)["\'][^>]*>([\s\S]*?)</a>', raw_html, flags=re.IGNORECASE)
        for link, text in matches:
            text_lower = text.lower()
            link_lower = link.lower()
            if any(kw in text_lower or kw in link_lower for kw in ["退订", "unsubscribe", "opt-out", "optout", "取消订阅"]):
                return link

        direct_urls = re.findall(r'https?://[^\s"\'<>]+(?:unsubscribe|unsub|optout)[^\s"\'<>]*', raw_html, flags=re.IGNORECASE)
        if direct_urls:
            return direct_urls[0]

    return ""


def extract_email_body_and_html(msg: email.message.Message) -> tuple[str, str]:
    """提取邮件的纯文本正文与原始 HTML"""
    text_body = ""
    html_body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdisp = str(part.get("Content-Disposition"))
            if ctype == "text/plain" and not text_body and "attachment" not in cdisp:
                payload = part.get_payload(decode=True)
                if payload:
                    text_body = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
            elif ctype == "text/html" and not html_body and "attachment" not in cdisp:
                payload = part.get_payload(decode=True)
                if payload:
                    html_body = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            decoded = payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")
            if msg.get_content_type() == "text/html":
                html_body = decoded
            else:
                text_body = decoded

    raw_source = text_body if text_body else html_body
    cleaned = re.sub(r"<style[\s\S]*?</style>", "", raw_source, flags=re.IGNORECASE)
    cleaned = re.sub(r"<script[\s\S]*?</script>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:6000], html_body


def extract_email_body(msg: email.message.Message) -> str:
    cleaned, _ = extract_email_body_and_html(msg)
    return cleaned


class GmailClient:
    """Gmail IMAP 客户端封装"""

    def __init__(self, username: str, password: str):
        self.username = username.strip()
        self.password = password.replace(" ", "").strip()
        self.imap = None
        self._trash_folder = None
        self._promotions_folder = None
        self._notifications_folder = None
        self._spam_folder = None
        self._drafts_folder = None

    def connect(self) -> bool:
        if not self.username or not self.password:
            print("[IMAP Error] 缺少 GMAIL_USER 或 GMAIL_APP_PASS 凭据", file=sys.stderr)
            return False
        try:
            self.imap = imaplib.IMAP4_SSL("imap.gmail.com", port=993)
            self.imap.login(self.username, self.password)
            return True
        except Exception as e:
            print(f"[IMAP Error] 登录 Gmail 失败: {e}", file=sys.stderr)
            return False

    def ensure_connected(self) -> bool:
        """检查 IMAP 活跃状态，如因闲置超时断开则自动重连并切回 INBOX"""
        if self.imap:
            try:
                status, _ = self.imap.noop()
                if status == "OK":
                    return True
            except Exception:
                pass
        print("[IMAP 提示] 检测到 IMAP 连接闲置断开或未连接，正在重连 Gmail...")
        if self.connect():
            try:
                self.imap.select("INBOX")
                return True
            except Exception:
                pass
        return False

    def noop(self):
        """心跳保活：防止长时间大模型研判期间 IMAP 连接因闲置超时断开"""
        if not self.imap:
            return
        try:
            self.imap.noop()
        except Exception:
            self.ensure_connected()

    def close(self):
        if self.imap:
            try:
                self.imap.close()
            except Exception:
                pass
            try:
                self.imap.logout()
            except Exception:
                pass

    def fetch_recent_emails(
        self,
        days: int = FETCH_DAYS_LIMIT,
        max_count: int = MAX_EMAILS_PER_RUN,
        is_processed_func=None,
    ) -> list[dict]:
        """抓取收件箱 (INBOX) 中未处理邮件，从最新到最旧优先处理 (单次最多 max_count 封)"""
        if not self.imap:
            return []

        status, _ = self.imap.select("INBOX")
        if status != "OK":
            print("[IMAP Error] 无法访问 INBOX", file=sys.stderr)
            return []

        # 优先检索全部邮件，以便能回溯积压的历史邮件
        status, data = self.imap.uid("SEARCH", None, "ALL")
        if status != "OK" or not data or not data[0]:
            print("[IMAP] 收件箱暂无邮件")
            return []

        email_ids = data[0].split()
        # IMAP UID 默认升序 (旧 -> 新)
        # 反转为从新到旧 (新 -> 旧)，优先从最新邮件开始处理
        email_ids.reverse()

        results = []
        for eid in email_ids:
            if len(results) >= max_count:
                break

            try:
                # 若提供了已处理判断函数，先快速 peek Message-ID 进行去重跳过，避免拉取整封邮件
                if is_processed_func:
                    res, hdata = self.imap.uid("FETCH", eid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
                    if res == "OK" and hdata and hdata[0] and isinstance(hdata[0], tuple):
                        msg_header = email.message_from_bytes(hdata[0][1])
                        m_id = (msg_header.get("Message-ID") or "").strip()
                        if m_id and is_processed_func(m_id):
                            continue

                res, msg_data = self.imap.uid("FETCH", eid, "(RFC822)")
                if res != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                message_id = msg.get("Message-ID", "").strip() or f"gen_{eid.decode()}_{get_now_bjt().timestamp()}"
                if is_processed_func and is_processed_func(message_id):
                    continue

                subject = decode_str(msg.get("Subject", "无主题"))
                from_addr = decode_str(msg.get("From", "未知发件人"))
                date_header = decode_str(msg.get("Date", ""))
                body_snippet, html_body = extract_email_body_and_html(msg)
                unsub_link = extract_unsubscribe_link(msg, html_body)

                results.append(
                    {
                        "uid": eid.decode(),
                        "message_id": message_id,
                        "subject": subject,
                        "from": from_addr,
                        "date": date_header,
                        "snippet": body_snippet,
                        "unsubscribe_link": unsub_link,
                    }
                )
            except Exception as e:
                print(f"[IMAP Warning] 读取单封邮件 ({eid}) 失败: {e}")
                continue

        return results

    def fetch_old_emails(
        self,
        days: int = PRUNE_DAYS,
        max_count: int = 100,
        is_processed_func=None,
    ) -> list[dict]:
        """
        抓取收件箱 (INBOX) 中超过 `days` 天 (默认 90 天) 的历史积压邮件。
        排序规则：严格从最旧到较新 (旧 -> 新)，优先处理最早的历史邮件。
        """
        if not self.ensure_connected():
            return []

        status, _ = self.imap.select("INBOX")
        if status != "OK":
            print("[IMAP Error] 无法访问 INBOX", file=sys.stderr)
            return []

        before_date = (get_now_bjt() - timedelta(days=days)).strftime("%d-%b-%Y")
        status, data = self.imap.uid("SEARCH", None, f'(BEFORE "{before_date}")')
        if status != "OK" or not data or not data[0]:
            print(f"[IMAP] 收件箱中没有超过 {days} 天的历史邮件")
            return []

        email_ids = data[0].split()
        # IMAP UID 默认就是升序 (旧 -> 新)
        # 这里不进行 reverse，确保优先从最早的历史邮件开始处理！

        results = []
        for eid in email_ids:
            if len(results) >= max_count:
                break

            try:
                # 若已处理过，快速 peek Message-ID 跳过
                if is_processed_func:
                    res, hdata = self.imap.uid("FETCH", eid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
                    if res == "OK" and hdata and hdata[0] and isinstance(hdata[0], tuple):
                        msg_header = email.message_from_bytes(hdata[0][1])
                        m_id = (msg_header.get("Message-ID") or "").strip()
                        if m_id and is_processed_func(m_id):
                            continue

                res, msg_data = self.imap.uid("FETCH", eid, "(RFC822)")
                if res != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                message_id = msg.get("Message-ID", "").strip() or f"gen_old_{eid.decode()}_{get_now_bjt().timestamp()}"
                if is_processed_func and is_processed_func(message_id):
                    continue

                subject = decode_str(msg.get("Subject", "无主题"))
                from_addr = decode_str(msg.get("From", "未知发件人"))
                date_header = decode_str(msg.get("Date", ""))
                body_snippet, html_body = extract_email_body_and_html(msg)
                unsub_link = extract_unsubscribe_link(msg, html_body)

                results.append(
                    {
                        "uid": eid.decode(),
                        "message_id": message_id,
                        "subject": subject,
                        "from": from_addr,
                        "date": date_header,
                        "snippet": body_snippet,
                        "unsubscribe_link": unsub_link,
                    }
                )
            except Exception as e:
                print(f"[IMAP Warning] 读取历史邮件 ({eid}) 失败: {e}")
                continue

        return results

    def _ensure_folder(self, folder_name: str) -> str:
        """检查并确保目标文件夹/标签存在，不存在则自动创建 (自动兼容 UTF-8 与 IMAP mUTF-7)"""
        if not self.imap:
            return folder_name

        status, folder_list = self.imap.list()
        encoded_name = mutf7_encode(folder_name)
        if status == "OK" and folder_list:
            for f in folder_list:
                _, name = parse_folder_name_from_list_line(f)
                decoded_name = mutf7_decode(name)
                if (
                    name.lower() == folder_name.lower()
                    or name.lower() == encoded_name.lower()
                    or decoded_name.lower() == folder_name.lower()
                    or name.endswith("/" + folder_name)
                    or name.endswith("/" + encoded_name)
                    or decoded_name.endswith("/" + folder_name)
                ):
                    return name

        # 若不存在，使用 mUTF-7 编码尝试自动创建中文文件夹
        try:
            self.imap.create(encoded_name)
            return encoded_name
        except Exception:
            pass
        return encoded_name

    def get_promotions_folder_name(self) -> str:
        """检测商业营销推广目录名称 (优先匹配用户中文标签 '商业推广' / '推广邮件' 或 Gmail 自带分类)"""
        if self._promotions_folder:
            return self._promotions_folder
        if not self.ensure_connected():
            return self._ensure_folder("商业推广")
        try:
            status, folder_list = self.imap.list()
            if status == "OK" and folder_list:
                for f in folder_list:
                    _, name = parse_folder_name_from_list_line(f)
                    decoded_name = mutf7_decode(name)
                    # 匹配用户已有的中文推广标签
                    if any(kw in decoded_name for kw in ["商业推广", "推广邮件", "促销内容", "广告邮件", "推广"]):
                        self._promotions_folder = name
                        return name
        except Exception as e:
            print(f"[IMAP Warning] 获取商业推广目录失败: {e}")
        # 默认创建或使用中文目录 "商业推广"
        self._promotions_folder = self._ensure_folder("商业推广")
        return self._promotions_folder

    def get_notifications_folder_name(self) -> str:
        """检测系统服务通知目录名称 (优先匹配用户中文标签 '系统通知' / '通知' 等)"""
        if self._notifications_folder:
            return self._notifications_folder
        if not self.ensure_connected():
            return self._ensure_folder("系统通知")
        try:
            status, folder_list = self.imap.list()
            if status == "OK" and folder_list:
                for f in folder_list:
                    _, name = parse_folder_name_from_list_line(f)
                    decoded_name = mutf7_decode(name)
                    # 匹配用户已有的中文通知标签 (如 '系统通知', '服务通知', '通知')
                    if any(kw in decoded_name for kw in ["系统通知", "服务通知", "通知", "资讯"]):
                        self._notifications_folder = name
                        return name
        except Exception as e:
            print(f"[IMAP Warning] 获取系统通知目录失败: {e}")
        # 默认创建或使用中文目录 "系统通知"
        self._notifications_folder = self._ensure_folder("系统通知")
        return self._notifications_folder

    def archive_emails(self, email_uids: list[str], folder_name: str = "Archive") -> int:
        """重要/营销邮件安全归档到独立目录，并在 INBOX SELECTED 状态下执行"""
        if not email_uids or not self.ensure_connected():
            return 0

        target_folder = self._ensure_folder(folder_name)
        # 强制选定 INBOX，避免在 AUTH 状态下执行 COPY 报错
        try:
            self.imap.select("INBOX")
        except Exception:
            self.ensure_connected()
            self.imap.select("INBOX")

        archived_count = 0
        for uid in email_uids:
            try:
                res, _ = self.imap.uid("COPY", uid, target_folder)
                if res == "OK":
                    self.imap.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
                    archived_count += 1
            except Exception as e:
                print(f"[IMAP Warning] 归档邮件到 {target_folder} 失败 ({uid}): {e}")
                try:
                    self.ensure_connected()
                    self.imap.select("INBOX")
                except Exception:
                    pass

        try:
            self.imap.expunge()
        except Exception:
            pass

        return archived_count

    def get_spam_folder_name(self) -> str:
        """检测垃圾箱名称 (基于 RFC 6154 Special-Use 属性自适应中英文等各语言环境)"""
        if self._spam_folder:
            return self._spam_folder
        if not self.ensure_connected():
            return "[Gmail]/Spam"
        try:
            status, folder_list = self.imap.list()
            if status == "OK" and folder_list:
                for f in folder_list:
                    flags, name = parse_folder_name_from_list_line(f)
                    flags_lower = flags.lower()
                    name_lower = name.lower()
                    # 优先匹配 RFC 6154 SPECIAL-USE 属性 \Spam 或 \Junk
                    if r"\spam" in flags_lower or r"\junk" in flags_lower:
                        self._spam_folder = name
                        return name
                    # 备用：匹配名称包含 spam 或 垃圾邮件 (或 mUTF-7 编码 &v4nxp)
                    if "spam" in name_lower or "垃圾" in name or "&v4nxp" in name_lower:
                        self._spam_folder = name
                        return name
        except Exception as e:
            print(f"[IMAP Warning] 获取垃圾箱目录失败: {e}")
        self._spam_folder = "[Gmail]/Spam"
        return self._spam_folder

    def get_trash_folder_name(self) -> str:
        """检测回收站/废纸篓名称 (基于 RFC 6154 Special-Use 属性自适应中英文环境)"""
        if self._trash_folder:
            return self._trash_folder
        if not self.ensure_connected():
            return "[Gmail]/Trash"
        try:
            status, folder_list = self.imap.list()
            if status == "OK" and folder_list:
                for f in folder_list:
                    flags, name = parse_folder_name_from_list_line(f)
                    flags_lower = flags.lower()
                    name_lower = name.lower()
                    # 优先匹配 RFC 6154 SPECIAL-USE 属性 \Trash
                    if r"\trash" in flags_lower:
                        self._trash_folder = name
                        return name
                    # 备用：匹配名称包含 trash、已删除、废件箱
                    if "trash" in name_lower or "已删除" in name or "废件" in name or "&v4nxpq-" in name_lower:
                        self._trash_folder = name
                        return name
        except Exception as e:
            print(f"[IMAP Warning] 获取回收站目录失败: {e}")
        self._trash_folder = "[Gmail]/Trash"
        return self._trash_folder

    def fetch_recent_spam_emails(self, days: int = FETCH_DAYS_LIMIT, max_count: int = 30) -> list[dict]:
        """抓取垃圾箱中最近 N 天内的邮件，用于排查 Google 是否误杀 (False Positives)"""
        if not self.ensure_connected():
            return []

        spam_folder = self.get_spam_folder_name()
        status, _ = self.imap.select(spam_folder)
        if status != "OK":
            status, _ = self.imap.select(f'"{spam_folder}"')
        if status != "OK":
            print(f"[IMAP Warning] 无法访问垃圾箱目录: {spam_folder}", file=sys.stderr)
            # 无论成功失败，恢复选定 INBOX 保持连接在 SELECTED 状态
            self.imap.select("INBOX")
            return []

        try:
            since_date = (get_now_bjt() - timedelta(days=days)).strftime("%d-%b-%Y")
            search_query = f'(SINCE "{since_date}")'

            status, data = self.imap.uid("SEARCH", None, search_query)
            if status != "OK" or not data or not data[0]:
                return []

            email_ids = data[0].split()
            email_ids = email_ids[-max_count:]
            email_ids.reverse()

            results = []
            for eid in email_ids:
                try:
                    res, msg_data = self.imap.uid("FETCH", eid, "(RFC822)")
                    if res != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                        continue

                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    message_id = msg.get("Message-ID", "").strip() or f"gen_spam_{eid.decode()}_{get_now_bjt().timestamp()}"
                    subject = decode_str(msg.get("Subject", "无主题"))
                    from_addr = decode_str(msg.get("From", "未知发件人"))
                    date_header = decode_str(msg.get("Date", ""))
                    body_snippet, html_body = extract_email_body_and_html(msg)
                    unsub_link = extract_unsubscribe_link(msg, html_body)

                    results.append(
                        {
                            "uid": eid.decode(),
                            "message_id": message_id,
                            "subject": subject,
                            "from": from_addr,
                            "date": date_header,
                            "snippet": body_snippet,
                            "unsubscribe_link": unsub_link,
                            "is_from_spam": True,
                        }
                    )
                except Exception as e:
                    print(f"[IMAP Warning] 读取垃圾箱单封邮件 ({eid}) 失败: {e}")
                    continue

            return results
        finally:
            # 检查完毕后必定切回 INBOX，保证处于 SELECTED(INBOX) 状态供后续归档操作
            self.imap.select("INBOX")

    def rescue_from_spam(self, email_uid: str, target_folder: str = "INBOX") -> bool:
        """从垃圾箱中拯救被 Google 误判的邮件，放回 INBOX 或指定目录 (如 商业推广)"""
        if not self.ensure_connected():
            return False

        spam_folder = self.get_spam_folder_name()
        status, _ = self.imap.select(spam_folder)
        if status != "OK":
            status, _ = self.imap.select(f'"{spam_folder}"')
        if status != "OK":
            self.imap.select("INBOX")
            return False

        if target_folder != "INBOX":
            target_folder = self._ensure_folder(target_folder)

        try:
            res, _ = self.imap.uid("COPY", email_uid, target_folder)
            if res == "OK":
                self.imap.uid("STORE", email_uid, "+FLAGS", "(\\Deleted)")
                self.imap.expunge()
                return True
        except Exception as e:
            print(f"[IMAP Warning] 从垃圾箱捞回误判邮件失败 ({email_uid}): {e}")
        finally:
            self.imap.select("INBOX")

        return False

    def move_to_spam(self, email_uids: list[str]) -> int:
        """深度托管：将垃圾邮件移动到 Gmail 垃圾邮件分类箱"""
        if not email_uids or not self.ensure_connected():
            return 0

        dest_folder = self.get_spam_folder_name()
        # 强制选定 INBOX
        try:
            self.imap.select("INBOX")
        except Exception:
            self.ensure_connected()
            self.imap.select("INBOX")

        moved_count = 0
        for uid in email_uids:
            try:
                res, _ = self.imap.uid("COPY", uid, dest_folder)
                if res == "OK":
                    self.imap.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
                    moved_count += 1
            except Exception as e:
                print(f"[IMAP Warning] 移入垃圾箱失败 ({uid}): {e}")
                try:
                    self.ensure_connected()
                    self.imap.select("INBOX")
                except Exception:
                    pass

        try:
            self.imap.expunge()
        except Exception:
            pass

        return moved_count

    def move_to_trash(self, email_uids: list[str]) -> int:
        """删除动作放入废纸篓/回收站"""
        if not email_uids or not self.ensure_connected():
            return 0

        dest_folder = self.get_trash_folder_name()
        # 强制选定 INBOX
        try:
            self.imap.select("INBOX")
        except Exception:
            self.ensure_connected()
            self.imap.select("INBOX")

        moved_count = 0
        for uid in email_uids:
            try:
                res, _ = self.imap.uid("COPY", uid, dest_folder)
                if res == "OK":
                    self.imap.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
                    moved_count += 1
            except Exception as e:
                print(f"[IMAP Warning] 移入回收站失败 ({uid}): {e}")
                try:
                    self.ensure_connected()
                    self.imap.select("INBOX")
                except Exception:
                    pass

        try:
            self.imap.expunge()
        except Exception:
            pass

        return moved_count

    def prune_old_low_value_emails(self, days: int = PRUNE_DAYS) -> int:
        """90 天以上低价值邮件删除动作：自动寻找收件箱中 90 天以前的旧通知/旧邮件，统一安全移动到废纸篓"""
        if not self.imap:
            return 0

        st, _ = self.imap.select("INBOX")
        if st != "OK":
            return 0

        before_date = (get_now_bjt() - timedelta(days=days)).strftime("%d-%b-%Y")
        st, data = self.imap.search(None, f'(BEFORE "{before_date}")')
        if st != "OK" or not data or not data[0]:
            return 0

        old_ids = data[0].split()
        old_uids = [oid.decode() for oid in old_ids[:50]]
        return self.move_to_trash(old_uids)

    def get_drafts_folder_name(self) -> str:
        """检测草稿箱名称 (基于 RFC 6154 Special-Use 属性自适应中英文环境)"""
        if self._drafts_folder:
            return self._drafts_folder
        if not self.ensure_connected():
            return "[Gmail]/Drafts"
        try:
            status, folder_list = self.imap.list()
            if status == "OK" and folder_list:
                for f in folder_list:
                    flags, name = parse_folder_name_from_list_line(f)
                    flags_lower = flags.lower()
                    name_lower = name.lower()
                    if r"\drafts" in flags_lower:
                        self._drafts_folder = name
                        return name
                    if "draft" in name_lower or "草稿" in name or "&g0l6pw-" in name_lower:
                        self._drafts_folder = name
                        return name
        except Exception as e:
            print(f"[IMAP Warning] 获取草稿箱目录失败: {e}")
        self._drafts_folder = "[Gmail]/Drafts"
        return self._drafts_folder

    def create_draft(self, to: list[str] | str, subject: str, body: str, in_reply_to: str = "") -> dict:
        """在 Gmail 草稿箱创建一封草稿邮件"""
        if not self.ensure_connected():
            return {"status": "error", "message": "IMAP 未连接"}
        import time
        from email.header import Header
        from email.message import EmailMessage

        draft_folder = self.get_drafts_folder_name()
        msg = EmailMessage()
        msg["From"] = self.username
        msg["To"] = ", ".join(to) if isinstance(to, list) else str(to)
        msg["Subject"] = Header(subject, "utf-8").encode()
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg.set_content(body)

        try:
            res, _ = self.imap.append(
                draft_folder,
                r"(\Draft \Seen)",
                imaplib.Time2Internaldate(time.time()),
                msg.as_bytes(),
            )
            if res == "OK":
                return {
                    "status": "success",
                    "message": f"草稿已成功保存至 {mutf7_decode(draft_folder)}",
                    "to": to,
                    "subject": subject,
                }
            return {"status": "error", "message": f"IMAP append 失败: {res}"}
        except Exception as e:
            return {"status": "error", "message": f"创建草稿异常: {e}"}

    def search_emails(self, query: str = "", folder: str = "INBOX", unread_only: bool = False, sender: str = "", limit: int = 10) -> list[dict]:
        """按关键词、发件人、未读状态检索邮件元数据"""
        if not self.ensure_connected():
            return []
        try:
            st, _ = self.imap.select(folder)
            if st != "OK":
                return []

            criteria = []
            if unread_only:
                criteria.append("UNSEEN")
            if sender:
                criteria.extend(["FROM", f'"{sender}"'])

            search_str = " ".join(criteria) if criteria else "ALL"
            if query:
                try:
                    res, data = self.imap.uid("SEARCH", None, f'X-GM-RAW "{query}"')
                    if res != "OK" or not data or not data[0]:
                        res, data = self.imap.uid("SEARCH", None, f'(TEXT "{query}")')
                except Exception:
                    res, data = self.imap.uid("SEARCH", None, f'(TEXT "{query}")')
            else:
                res, data = self.imap.uid("SEARCH", None, search_str)

            if res != "OK" or not data or not data[0]:
                return []

            uids = data[0].split()
            selected_uids = [u.decode() for u in reversed(uids)][:limit]
            results = []
            for uid in selected_uids:
                try:
                    fetch_res, fetch_data = self.imap.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE MESSAGE-ID)] BODY.PEEK[TEXT]<0.600>)")
                    if fetch_res != "OK" or not fetch_data:
                        continue
                    raw_header = b""
                    raw_snippet = b""
                    for part in fetch_data:
                        if isinstance(part, tuple) and len(part) >= 2:
                            if b"HEADER" in part[0]:
                                raw_header = part[1]
                            elif b"TEXT" in part[0]:
                                raw_snippet = part[1]
                    msg = email.message_from_bytes(raw_header)
                    subject = decode_str(msg.get("Subject", "无主题"))
                    from_addr = decode_str(msg.get("From", "未知发件人"))
                    date_str = msg.get("Date", "")
                    message_id = msg.get("Message-ID", "")
                    clean_snip = raw_snippet.decode("utf-8", errors="ignore").replace("\r", " ").replace("\n", " ").strip()[:200]
                    results.append({
                        "uid": uid,
                        "folder": folder,
                        "subject": subject,
                        "from": from_addr,
                        "date": date_str,
                        "message_id": message_id,
                        "snippet": clean_snip,
                    })
                except Exception:
                    continue
            return results
        except Exception as e:
            print(f"[IMAP Warning] 搜索邮件失败: {e}")
            return []

    def read_email_content(self, email_uid: str, folder: str = "INBOX", max_length: int = 4000) -> dict:
        """按 UID 读取单封邮件的完整正文及附件信息"""
        if not self.ensure_connected():
            return {"status": "error", "message": "IMAP 未连接"}
        try:
            st, _ = self.imap.select(folder)
            if st != "OK":
                return {"status": "error", "message": f"无法选择文件夹 {folder}"}

            res, data = self.imap.uid("FETCH", email_uid, "(RFC822)")
            if res != "OK" or not data or not data[0]:
                return {"status": "error", "message": f"未找到 UID 为 {email_uid} 的邮件"}

            raw_email = None
            for item in data:
                if isinstance(item, tuple) and len(item) >= 2:
                    raw_email = item[1]
                    break
            if not raw_email:
                return {"status": "error", "message": "未能读取到邮件原始内容"}

            msg = email.message_from_bytes(raw_email)
            subject = decode_str(msg.get("Subject", "无主题"))
            from_addr = decode_str(msg.get("From", "未知发件人"))
            to_addr = decode_str(msg.get("To", ""))
            date_str = msg.get("Date", "")
            message_id = msg.get("Message-ID", "")

            body_text, raw_html = extract_email_body_and_html(msg)
            unsub_link = extract_unsubscribe_link(msg, raw_html)

            attachments = []
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                filename = part.get_filename()
                if filename:
                    fname = decode_str(filename)
                    payload = part.get_payload(decode=True) or b""
                    attachments.append({
                        "filename": fname,
                        "content_type": part.get_content_type(),
                        "size_bytes": len(payload),
                    })

            truncated = False
            if len(body_text) > max_length:
                body_text = body_text[:max_length] + f"\n\n[正文已截断，总长度 {len(body_text)} 字符]"
                truncated = True

            return {
                "status": "success",
                "uid": email_uid,
                "folder": folder,
                "subject": subject,
                "from": from_addr,
                "to": to_addr,
                "date": date_str,
                "message_id": message_id,
                "body": body_text,
                "attachments": attachments,
                "unsubscribe_link": unsub_link,
                "truncated": truncated,
            }
        except Exception as e:
            return {"status": "error", "message": f"读取邮件正文失败: {e}"}

    def mark_email_flags(self, email_uids: list[str], is_read: bool | None = None, is_starred: bool | None = None, folder: str = "INBOX") -> dict:
        """标记邮件已读/未读或星标状态"""
        if not email_uids or not self.ensure_connected():
            return {"status": "error", "message": "UID 为空或 IMAP 未连接"}
        try:
            st, _ = self.imap.select(folder)
            if st != "OK":
                return {"status": "error", "message": f"无法选择文件夹 {folder}"}
            uid_str = ",".join(str(u) for u in email_uids)
            if is_read is True:
                self.imap.uid("STORE", uid_str, "+FLAGS", "(\\Seen)")
            elif is_read is False:
                self.imap.uid("STORE", uid_str, "-FLAGS", "(\\Seen)")
            if is_starred is True:
                self.imap.uid("STORE", uid_str, "+FLAGS", "(\\Flagged)")
            elif is_starred is False:
                self.imap.uid("STORE", uid_str, "-FLAGS", "(\\Flagged)")
            return {"status": "success", "modified_count": len(email_uids), "uids": email_uids}
        except Exception as e:
            return {"status": "error", "message": f"标记邮件失败: {e}"}

    def list_folders(self) -> list[dict]:
        """获取所有可用文件夹列表及其解码名称"""
        if not self.ensure_connected():
            return []
        try:
            status, folder_list = self.imap.list()
            if status != "OK" or not folder_list:
                return []
            results = []
            for f in folder_list:
                flags, name = parse_folder_name_from_list_line(f)
                results.append({
                    "raw_name": name,
                    "display_name": mutf7_decode(name),
                    "flags": flags,
                })
            return results
        except Exception as e:
            print(f"[IMAP Warning] 列出文件夹失败: {e}")
            return []
