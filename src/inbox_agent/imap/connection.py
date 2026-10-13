"""
IMAP 传输层连接管理 (Connection)
封装 imapclient.IMAPClient 生命周期：连接、认证、保活与上下文目录切换 (Fail-Fast)
"""

from imapclient import IMAPClient


class ImapConnection:
    """管理与 IMAP 服务器的底层连接与会话状态"""

    def __init__(
        self,
        username: str,
        password: str,
        host: str = "imap.gmail.com",
        port: int = 993,
    ):
        self.username = username.strip()
        self.password = password.replace(" ", "").strip()
        self.host = host
        self.port = port
        self._client: IMAPClient | None = None
        self.current_folder: str | None = None

    @property
    def client(self) -> IMAPClient:
        """获取底层 IMAPClient 实例，未连接时直接抛出异常 (Fail-Fast)"""
        if self._client is None:
            raise ConnectionError("IMAP 未连接，请先调用 connect()")
        return self._client

    def is_connected(self) -> bool:
        """检查连接对象是否存在"""
        return self._client is not None

    def connect(self) -> None:
        """建立 SSL 连接并完成登录认证，失败直接抛出异常 (Fail-Fast)"""
        if not self.username or not self.password:
            raise ValueError("缺少 Gmail 认证用户名或密码")

        self._client = IMAPClient(self.host, port=self.port, ssl=True, use_uid=True)
        self._client.login(self.username, self.password)

    def select_folder(self, folder: str, readonly: bool = False) -> None:
        """选择并进入目标目录上下文，失败直接抛出异常 (Fail-Fast)"""
        self.client.select_folder(folder, readonly=readonly)
        self.current_folder = folder

    def noop(self) -> None:
        """发送 NOOP 心跳保活，失败直接抛出异常 (Fail-Fast)"""
        self.client.noop()

    def close(self) -> None:
        """安全登出并释放连接资源"""
        if self._client is not None:
            client = self._client
            self._client = None
            self.current_folder = None
            client.logout()
