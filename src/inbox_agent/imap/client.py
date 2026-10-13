"""
Gmail IMAP 客户端交互层 (Client)
提供针对 Gmail 的 IMAP 连接管理、邮件获取、移动归档、草稿创建与状态标记
"""

import email
import imaplib
import sys
import time
from datetime import timedelta
from email.header import Header
from email.message import EmailMessage

from inbox_agent.config import FETCH_DAYS_LIMIT, MAX_EMAILS_PER_RUN, PRUNE_DAYS, get_now_bjt
from inbox_agent.imap.mutf7 import mutf7_decode, mutf7_encode
from inbox_agent.imap.parser import (
    decode_str,
    extract_email_body_and_html,
    extract_unsubscribe_link,
    parse_folder_name_from_list_line,
)


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
        print("[IMAP Warning] 检测到连接已断开或超时，正在重新连接...", file=sys.stderr)
        if self.connect():
            try:
                self.imap.select("INBOX")
                return True
            except Exception:
                return False
        return False

    def noop(self):
        """发送 NOOP 心跳保活"""
        if self.imap:
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
            self.imap = None

    def fetch_recent_emails(
        self,
        days: int = FETCH_DAYS_LIMIT,
        max_count: int = MAX_EMAILS_PER_RUN,
        is_processed_func=None,
    ) -> list[dict]:
        """按时间倒序抓取收件箱近期邮件"""
        if not self.ensure_connected():
            return []

        status, _ = self.imap.select("INBOX")
        if status != "OK":
            return []

        since_date = (get_now_bjt() - timedelta(days=days)).strftime("%d-%b-%Y")
        status, data = self.imap.search(None, f'(SINCE "{since_date}")')
        if status != "OK" or not data or not data[0]:
            return []

        msg_ids = data[0].split()
        reversed_ids = list(reversed(msg_ids))

        results = []
        for msg_id in reversed_ids:
            if len(results) >= max_count:
                break

            try:
                # 仅获取头部，检查是否已处理
                res, header_data = self.imap.fetch(
                    msg_id, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)] UID)"
                )
                if res != "OK" or not header_data:
                    continue

                raw_header = b""
                uid = ""
                for part in header_data:
                    if isinstance(part, tuple) and len(part) >= 2:
                        raw_header = part[1]
                    elif isinstance(part, bytes):
                        part_str = part.decode("utf-8", errors="ignore")
                        if "UID" in part_str:
                            tokens = part_str.split()
                            if "UID" in tokens:
                                uid_idx = tokens.index("UID") + 1
                                if uid_idx < len(tokens):
                                    uid = tokens[uid_idx].rstrip(")")

                parsed_hdr = email.message_from_bytes(raw_header)
                message_id = parsed_hdr.get("Message-ID", "").strip()

                if is_processed_func and is_processed_func(message_id):
                    continue

                # 未处理邮件抓取完整正文
                res, full_data = self.imap.fetch(msg_id, "(RFC822 UID)")
                if res != "OK" or not full_data:
                    continue

                raw_email = None
                for part in full_data:
                    if isinstance(part, tuple) and len(part) >= 2:
                        raw_email = part[1]
                    elif isinstance(part, bytes):
                        part_str = part.decode("utf-8", errors="ignore")
                        if "UID" in part_str:
                            tokens = part_str.split()
                            if "UID" in tokens:
                                uid_idx = tokens.index("UID") + 1
                                if uid_idx < len(tokens):
                                    uid = tokens[uid_idx].rstrip(")")

                if not raw_email:
                    continue

                msg = email.message_from_bytes(raw_email)
                subject = decode_str(msg.get("Subject", "无主题"))
                from_addr = decode_str(msg.get("From", "未知发件人"))
                date_str = msg.get("Date", "")
                if not message_id:
                    message_id = msg.get("Message-ID", "")

                body_text, raw_html = extract_email_body_and_html(msg)
                unsub_link = extract_unsubscribe_link(msg, raw_html)

                results.append({
                    "id": msg_id.decode(),
                    "uid": uid,
                    "message_id": message_id,
                    "subject": subject,
                    "from": from_addr,
                    "date": date_str,
                    "snippet": body_text[:1000],
                    "body": body_text,
                    "unsubscribe_link": unsub_link,
                })
            except Exception as e:
                print(f"[IMAP Warning] 解析邮件异常 (ID {msg_id}): {e}", file=sys.stderr)
                continue

        return results

    def fetch_old_emails(
        self,
        days: int = PRUNE_DAYS,
        max_count: int = 100,
        is_processed_func=None,
    ) -> list[dict]:
        """抓取 N 天以前的历史积压邮件 (旧 -> 新)"""
        if not self.ensure_connected():
            return []

        status, _ = self.imap.select("INBOX")
        if status != "OK":
            return []

        before_date = (get_now_bjt() - timedelta(days=days)).strftime("%d-%b-%Y")
        status, data = self.imap.search(None, f'(BEFORE "{before_date}")')
        if status != "OK" or not data or not data[0]:
            return []

        old_msg_ids = data[0].split()
        results = []
        for msg_id in old_msg_ids:
            if len(results) >= max_count:
                break
            try:
                res, header_data = self.imap.fetch(
                    msg_id, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)] UID)"
                )
                if res != "OK" or not header_data:
                    continue

                raw_header = b""
                uid = ""
                for part in header_data:
                    if isinstance(part, tuple) and len(part) >= 2:
                        raw_header = part[1]
                    elif isinstance(part, bytes):
                        part_str = part.decode("utf-8", errors="ignore")
                        if "UID" in part_str:
                            tokens = part_str.split()
                            if "UID" in tokens:
                                uid_idx = tokens.index("UID") + 1
                                if uid_idx < len(tokens):
                                    uid = tokens[uid_idx].rstrip(")")

                parsed_hdr = email.message_from_bytes(raw_header)
                message_id = parsed_hdr.get("Message-ID", "").strip()

                if is_processed_func and is_processed_func(message_id):
                    continue

                res, full_data = self.imap.fetch(msg_id, "(RFC822 UID)")
                if res != "OK" or not full_data:
                    continue

                raw_email = None
                for part in full_data:
                    if isinstance(part, tuple) and len(part) >= 2:
                        raw_email = part[1]
                    elif isinstance(part, bytes):
                        part_str = part.decode("utf-8", errors="ignore")
                        if "UID" in part_str:
                            tokens = part_str.split()
                            if "UID" in tokens:
                                uid_idx = tokens.index("UID") + 1
                                if uid_idx < len(tokens):
                                    uid = tokens[uid_idx].rstrip(")")

                if not raw_email:
                    continue

                msg = email.message_from_bytes(raw_email)
                subject = decode_str(msg.get("Subject", "无主题"))
                from_addr = decode_str(msg.get("From", "未知发件人"))
                date_str = msg.get("Date", "")
                if not message_id:
                    message_id = msg.get("Message-ID", "")

                body_text, raw_html = extract_email_body_and_html(msg)
                unsub_link = extract_unsubscribe_link(msg, raw_html)

                results.append({
                    "id": msg_id.decode(),
                    "uid": uid,
                    "message_id": message_id,
                    "subject": subject,
                    "from": from_addr,
                    "date": date_str,
                    "snippet": body_text[:1000],
                    "body": body_text,
                    "unsubscribe_link": unsub_link,
                })
            except Exception as e:
                print(f"[IMAP Warning] 提取历史邮件异常 (ID {msg_id}): {e}", file=sys.stderr)
                continue

        return results

    def _ensure_folder(self, folder_name: str) -> str:
        """确保目标文件夹存在，若不存在则使用 mUTF-7 编码自动创建"""
        if not self.ensure_connected():
            return folder_name
        encoded_name = mutf7_encode(folder_name)
        status, folder_list = self.imap.list()
        if status == "OK" and folder_list:
            for f in folder_list:
                _, name = parse_folder_name_from_list_line(f)
                if (
                    name == folder_name
                    or name == encoded_name
                    or mutf7_decode(name) == folder_name
                ):
                    return name

        try:
            res, _ = self.imap.create(encoded_name)
            if res == "OK":
                return encoded_name
        except Exception:
            pass
        return folder_name

    def get_promotions_folder_name(self) -> str:
        """检测商业推广分类目录名称"""
        if self._promotions_folder:
            return self._promotions_folder
        if not self.ensure_connected():
            return "商业推广"
        try:
            status, folder_list = self.imap.list()
            if status == "OK" and folder_list:
                for f in folder_list:
                    _, name = parse_folder_name_from_list_line(f)
                    decoded = mutf7_decode(name).lower()
                    if "商业推广" in decoded or "promotions" in decoded or "推广" in decoded:
                        self._promotions_folder = name
                        return name
        except Exception:
            pass
        self._promotions_folder = self._ensure_folder("商业推广")
        return self._promotions_folder

    def get_notifications_folder_name(self) -> str:
        """检测系统通知分类目录名称"""
        if self._notifications_folder:
            return self._notifications_folder
        if not self.ensure_connected():
            return "系统通知"
        try:
            status, folder_list = self.imap.list()
            if status == "OK" and folder_list:
                for f in folder_list:
                    _, name = parse_folder_name_from_list_line(f)
                    decoded = mutf7_decode(name).lower()
                    if (
                        "系统通知" in decoded
                        or "notifications" in decoded
                        or "服务通知" in decoded
                    ):
                        self._notifications_folder = name
                        return name
        except Exception:
            pass
        self._notifications_folder = self._ensure_folder("系统通知")
        return self._notifications_folder

    def get_spam_folder_name(self) -> str:
        """检测垃圾邮件目录名称 (基于 RFC 6154 Special-Use 属性自适应中英文环境)"""
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
                    if r"\spam" in flags_lower or r"\junk" in flags_lower:
                        self._spam_folder = name
                        return name
                    if "spam" in name_lower or "垃圾" in name or "&v4nxp" in name_lower:
                        self._spam_folder = name
                        return name
        except Exception as e:
            print(f"[IMAP Warning] 获取垃圾箱目录失败: {e}")
        self._spam_folder = "[Gmail]/Spam"
        return self._spam_folder

    def get_trash_folder_name(self) -> str:
        """检测废纸篓/回收站目录名称"""
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
                    if r"\trash" in flags_lower:
                        self._trash_folder = name
                        return name
                    if (
                        "trash" in name_lower
                        or "已删除" in name
                        or "废件" in name
                        or "&v4nxpq-" in name_lower
                    ):
                        self._trash_folder = name
                        return name
        except Exception as e:
            print(f"[IMAP Warning] 获取回收站目录失败: {e}")
        self._trash_folder = "[Gmail]/Trash"
        return self._trash_folder

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

    def archive_emails(self, email_uids: list[str], folder_name: str = "Archive") -> int:
        """将邮件安全移出 INBOX 归档至目标分类文件夹"""
        if not email_uids or not self.ensure_connected():
            return 0

        target_folder = self._ensure_folder(folder_name)
        try:
            self.imap.select("INBOX")
        except Exception:
            self.ensure_connected()
            self.imap.select("INBOX")

        moved_count = 0
        for uid in email_uids:
            try:
                res, _ = self.imap.uid("COPY", uid, target_folder)
                if res == "OK":
                    self.imap.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
                    moved_count += 1
            except Exception as e:
                print(f"[IMAP Warning] 归档移动失败 ({uid}): {e}")
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

    def fetch_recent_spam_emails(
        self, days: int = FETCH_DAYS_LIMIT, max_count: int = 30
    ) -> list[dict]:
        """抓取垃圾箱中最近 N 天内的邮件，用于排查 Google 拦截是否误杀"""
        if not self.ensure_connected():
            return []

        spam_folder = self.get_spam_folder_name()
        status, _ = self.imap.select(spam_folder)
        if status != "OK":
            return []

        since_date = (get_now_bjt() - timedelta(days=days)).strftime("%d-%b-%Y")
        status, data = self.imap.search(None, f'(SINCE "{since_date}")')
        if status != "OK" or not data or not data[0]:
            return []

        msg_ids = data[0].split()
        reversed_ids = list(reversed(msg_ids))[:max_count]

        results = []
        for msg_id in reversed_ids:
            try:
                res, full_data = self.imap.fetch(msg_id, "(RFC822 UID)")
                if res != "OK" or not full_data:
                    continue

                raw_email = None
                uid = ""
                for part in full_data:
                    if isinstance(part, tuple) and len(part) >= 2:
                        raw_email = part[1]
                    elif isinstance(part, bytes):
                        part_str = part.decode("utf-8", errors="ignore")
                        if "UID" in part_str:
                            tokens = part_str.split()
                            if "UID" in tokens:
                                uid_idx = tokens.index("UID") + 1
                                if uid_idx < len(tokens):
                                    uid = tokens[uid_idx].rstrip(")")

                if not raw_email:
                    continue

                msg = email.message_from_bytes(raw_email)
                subject = decode_str(msg.get("Subject", "无主题"))
                from_addr = decode_str(msg.get("From", "未知发件人"))
                date_str = msg.get("Date", "")
                message_id = msg.get("Message-ID", "")

                body_text, raw_html = extract_email_body_and_html(msg)
                unsub_link = extract_unsubscribe_link(msg, raw_html)

                results.append({
                    "id": msg_id.decode(),
                    "uid": uid,
                    "message_id": message_id,
                    "subject": subject,
                    "from": from_addr,
                    "date": date_str,
                    "snippet": body_text[:1000],
                    "body": body_text,
                    "unsubscribe_link": unsub_link,
                })
            except Exception as e:
                print(f"[IMAP Warning] 抓取垃圾邮件异常 (ID {msg_id}): {e}", file=sys.stderr)
                continue

        return results

    def rescue_from_spam(self, email_uid: str, target_folder: str = "INBOX") -> bool:
        """将邮件从垃圾箱中解救移回目标文件夹"""
        if not email_uid or not self.ensure_connected():
            return False

        spam_folder = self.get_spam_folder_name()
        dest_folder = (
            self._ensure_folder(target_folder) if target_folder != "INBOX" else "INBOX"
        )

        try:
            st, _ = self.imap.select(spam_folder)
            if st != "OK":
                return False
            res, _ = self.imap.uid("COPY", email_uid, dest_folder)
            if res == "OK":
                self.imap.uid("STORE", email_uid, "+FLAGS", "(\\Deleted)")
                self.imap.expunge()
                return True
        except Exception as e:
            print(f"[IMAP Warning] 误杀解救移动失败 ({email_uid}): {e}")
        return False

    def move_to_spam(self, email_uids: list[str]) -> int:
        """移入垃圾箱"""
        if not email_uids or not self.ensure_connected():
            return 0

        dest_folder = self.get_spam_folder_name()
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
                print(f"[IMAP Warning] 移入垃圾邮件失败 ({uid}): {e}")
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
        """移入废纸篓/回收站"""
        if not email_uids or not self.ensure_connected():
            return 0

        dest_folder = self.get_trash_folder_name()
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
        """清理 90 天以上低价值邮件"""
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

    def create_draft(
        self, to: list[str] | str, subject: str, body: str, in_reply_to: str = ""
    ) -> dict:
        """在 Gmail 草稿箱创建一封草稿邮件"""
        if not self.ensure_connected():
            return {"status": "error", "message": "IMAP 未连接"}

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

    def search_emails(
        self,
        query: str = "",
        folder: str = "INBOX",
        unread_only: bool = False,
        sender: str = "",
        limit: int = 10,
    ) -> list[dict]:
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
                    fetch_res, fetch_data = self.imap.uid(
                        "FETCH",
                        uid,
                        "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE MESSAGE-ID)] BODY.PEEK[TEXT]<0.600>)",
                    )
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
                    clean_snip = (
                        raw_snippet.decode("utf-8", errors="ignore")
                        .replace("\r", " ")
                        .replace("\n", " ")
                        .strip()[:200]
                    )
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

    def read_email_content(
        self, email_uid: str, folder: str = "INBOX", max_length: int = 4000
    ) -> dict:
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
                body_text = (
                    body_text[:max_length]
                    + f"\n\n[正文已截断，总长度 {len(body_text)} 字符]"
                )
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

    def mark_email_flags(
        self,
        email_uids: list[str],
        is_read: bool | None = None,
        is_starred: bool | None = None,
        folder: str = "INBOX",
    ) -> dict:
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
            return {
                "status": "success",
                "modified_count": len(email_uids),
                "uids": email_uids,
            }
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
