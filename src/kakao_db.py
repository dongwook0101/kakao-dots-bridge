"""Business-account-only SQLCipher reader. Key derivation ported from kakaocli (MIT).

No writes to KakaoTalk's database, no login credentials, no personal-container fallback.
"""
from __future__ import annotations
import base64
import ctypes as C
import hashlib
import json
from pathlib import Path
import plistlib
import re
import subprocess

BUNDLE = "com.kakao.KakaoTalkDevMac"
APP = "/Applications/KakaoTalkNew.app"
ROOT = Path.home() / "Library/Application Support" / BUNDLE
PREFS = Path.home() / "Library/Preferences"


class AccountError(RuntimeError):
    pass


def active_hash():
    hashes = set()
    for p in PREFS.glob(BUNDLE + ".*.plist"):
        data = plistlib.loads(p.read_bytes())
        hashes.update(k.split(":", 1)[1] for k, v in data.items()
                      if k.startswith("DESIGNATEDFRIENDSREVISION:") and v)
    if len(hashes) != 1:
        raise AccountError("업무용 카카오톡의 활성 계정을 확인할 수 없습니다.")
    return next(iter(hashes))


def derive(uid):
    raw = subprocess.check_output(["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], text=True)
    uuid = re.search(r'"IOPlatformUUID" = "([^"]+)"', raw)[1]
    hashed = base64.b64encode(hashlib.sha1(uuid.encode()).digest() + hashlib.sha256(uuid.encode()).digest()).decode()
    name = hashlib.pbkdf2_hmac("sha256", ".".join([".", "F", str(uid), "A", "F", uuid[::-1], ".", "|"]).encode(), hashed[::-1].encode(), 100000, 128).hex()[28:106]
    parts = ["A", hashed, "|", "F", uuid[:5], "H", str(uid), "|", uuid[7:]]
    key = hashlib.pbkdf2_hmac("sha256", "F".join(parts)[::-1].encode(), uuid[int(len(uuid) * .3):].encode(), 100000, 128).hex()
    return ROOT / name, key


class Cipher:
    def __init__(self, path, key):
        self.lib = C.CDLL("/opt/homebrew/opt/sqlcipher/lib/libsqlcipher.dylib")
        l = self.lib
        l.sqlite3_open_v2.argtypes = [C.c_char_p, C.POINTER(C.c_void_p), C.c_int, C.c_char_p]
        l.sqlite3_prepare_v2.argtypes = [C.c_void_p, C.c_char_p, C.c_int, C.POINTER(C.c_void_p), C.c_void_p]
        l.sqlite3_step.argtypes = [C.c_void_p]
        l.sqlite3_finalize.argtypes = [C.c_void_p]
        l.sqlite3_close.argtypes = [C.c_void_p]
        l.sqlite3_column_count.argtypes = [C.c_void_p]
        l.sqlite3_column_type.argtypes = [C.c_void_p, C.c_int]
        l.sqlite3_column_int64.argtypes = [C.c_void_p, C.c_int]; l.sqlite3_column_int64.restype = C.c_longlong
        l.sqlite3_column_double.argtypes = [C.c_void_p, C.c_int]; l.sqlite3_column_double.restype = C.c_double
        l.sqlite3_column_text.argtypes = [C.c_void_p, C.c_int]; l.sqlite3_column_text.restype = C.c_char_p
        l.sqlite3_column_name.argtypes = [C.c_void_p, C.c_int]; l.sqlite3_column_name.restype = C.c_char_p
        l.sqlite3_errmsg.argtypes = [C.c_void_p]; l.sqlite3_errmsg.restype = C.c_char_p
        l.sqlite3_bind_int64.argtypes = [C.c_void_p, C.c_int, C.c_longlong]
        l.sqlite3_bind_text.argtypes = [C.c_void_p, C.c_int, C.c_char_p, C.c_int, C.c_void_p]
        self.db = C.c_void_p()
        if l.sqlite3_open_v2(str(path).encode(), C.byref(self.db), 1, None):  # SQLITE_OPEN_READONLY
            raise AccountError("업무용 DB를 읽기 전용으로 열지 못했습니다.")
        try:
            self.query("PRAGMA cipher_default_compatibility=3")
            self.query("PRAGMA key='" + key + "'")
            self.query("PRAGMA query_only=ON")
            self.query("PRAGMA busy_timeout=3000")
            self.query("SELECT COUNT(*) FROM sqlite_master")
        except Exception:
            self.close()
            raise AccountError("업무용 DB 복호화를 확인하지 못했습니다.") from None

    def close(self):
        if self.db:
            self.lib.sqlite3_close(self.db); self.db = C.c_void_p()

    def query(self, sql, params=()):
        stmt = C.c_void_p(); l = self.lib
        if l.sqlite3_prepare_v2(self.db, sql.encode(), -1, C.byref(stmt), None):
            raise RuntimeError(l.sqlite3_errmsg(self.db).decode())
        try:
            for i, p in enumerate(params, 1):
                if isinstance(p, int):
                    rc = l.sqlite3_bind_int64(stmt, i, p)
                else:
                    rc = l.sqlite3_bind_text(stmt, i, str(p).encode(), -1, C.c_void_p(-1))
                if rc: raise RuntimeError("SQL parameter bind failed")
            cols = [l.sqlite3_column_name(stmt, i).decode() for i in range(l.sqlite3_column_count(stmt))]
            out = []
            while True:
                rc = l.sqlite3_step(stmt)
                if rc == 101: break
                if rc != 100: raise RuntimeError(l.sqlite3_errmsg(self.db).decode())
                row = {}
                for i, name in enumerate(cols):
                    t = l.sqlite3_column_type(stmt, i)
                    if t == 1: v = l.sqlite3_column_int64(stmt, i)
                    elif t == 2: v = l.sqlite3_column_double(stmt, i)
                    elif t == 3: v = l.sqlite3_column_text(stmt, i).decode("utf-8", errors="replace")
                    else: v = None
                    row[name] = v
                out.append(row)
            return out
        finally:
            l.sqlite3_finalize(stmt)


class BusinessDB:
    def __init__(self, config):
        self.config = config
        self.uid = int(config["user_id"])
        if config["bundle_id"] != BUNDLE or config["app_path"] != APP:
            raise AccountError("업무 계정 고정 설정이 일치하지 않습니다.")
        self.expected_hash = hashlib.sha512(str(self.uid).encode()).hexdigest()
        self.path, self.key = derive(self.uid)
        if self.path.resolve() != Path(config["database"]).resolve() or self.path.parent.resolve() != ROOT.resolve():
            raise AccountError("업무용 DB 경로가 일치하지 않습니다.")

    def guard(self):
        if active_hash() != self.expected_hash:
            raise AccountError("카카오톡 업무 계정이 바뀌었습니다. 수집과 전송을 중단합니다.")
        if not self.path.is_file(): raise AccountError("업무용 DB가 없습니다.")
        with open(Path(APP) / "Contents/Info.plist", "rb") as f:
            if plistlib.load(f).get("CFBundleIdentifier") != BUNDLE:
                raise AccountError("업무용 앱 식별자가 바뀌었습니다.")
        processes = subprocess.check_output(["/bin/ps", "-axo", "pid=,comm="], text=True)
        expected_exe = APP + "/Contents/MacOS/KakaoTalkDev"
        pids = [line.strip().split(None, 1)[0] for line in processes.splitlines()
                if len(line.strip().split(None, 1)) == 2 and line.strip().split(None, 1)[1] == expected_exe]
        if len(pids) != 1:
            raise AccountError("업무용 카카오톡을 실행하고 로그인해 주세요.")
        opened = subprocess.run(["/usr/sbin/lsof", "-p", pids[0], "-Fn"], capture_output=True, text=True, timeout=5)
        if "n" + str(self.path) not in opened.stdout.splitlines():
            raise AccountError("실행 중인 업무용 앱이 승인된 계정의 DB를 사용하지 않습니다.")

    def read(self, sql, params=()):
        self.guard()
        db = Cipher(self.path, self.key)
        try:
            own = db.query("SELECT DISTINCT userId FROM NTChatContext")
            if not own or {int(r["userId"]) for r in own} != {self.uid}:
                raise AccountError("DB의 계정이 승인된 업무 계정과 다릅니다.")
            return db.query(sql, params)
        finally: db.close()

    def chats(self):
        return self.read("""SELECT CAST(r.chatId AS TEXT) chat_id, r.type,
          COALESCE(NULLIF(r.chatName,''), NULLIF(u.friendNickName,''), NULLIF(u.displayName,''), u.nickName, '이름 확인 필요') name,
          r.activeMembersCount member_count, r.countOfNewMessage unread_count, r.lastUpdatedAt updated_at,
          CAST(r.directChatMemberUserId AS TEXT) peer_id
          FROM NTChatRoom r LEFT JOIN NTUser u ON r.directChatMemberUserId=u.userId AND u.linkId=0
          ORDER BY r.lastUpdatedAt DESC""")

    def messages(self, chat_id=None, limit=30):
        where = "WHERE m.chatId=?" if chat_id is not None else ""
        params = [int(chat_id)] if chat_id is not None else []
        params.append(max(1, min(int(limit), 10000)))
        rows = self.read(f"""SELECT CAST(m.logId AS TEXT) message_id, CAST(m.chatId AS TEXT) chat_id,
          CAST(m.authorId AS TEXT) sender_id, COALESCE(NULLIF(u.friendNickName,''), NULLIF(u.displayName,''), u.nickName, '알 수 없음') sender,
          m.message text, m.type message_type, m.sentAt sent_at,
          m.rowid source_rowid FROM NTChatMessage m
          LEFT JOIN NTUser u ON m.authorId=u.userId AND u.linkId=0
          {where} ORDER BY m.rowid DESC LIMIT ?""", params)
        for r in rows: r["is_from_me"] = r["sender_id"] == str(self.uid)
        return rows[::-1]

    def fingerprint(self, chat_id):
        return hashlib.sha256(json.dumps(self.messages(chat_id, 20), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
