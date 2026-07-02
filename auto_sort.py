# -*- coding: utf-8 -*-
"""
파일 자동 정리 프로그램  (트레이 / 실행취소 / 토스트 / 자동시작 / 연습모드)
==========================================================================
'정리할 폴더'를 감시하다가, 파일 이름을 보고 규칙에 맞는 폴더로 옮깁니다.

주요 기능
 - 새 폴더가 필요하면 알람 + 확인 창(이름 수정/건너뛰기)
 - 키워드 여러 개 걸리면 폴더 안의 폴더로 (예: 진흥원\서부초등학교)
 - 트레이 아이콘으로 조용히 실행 (우클릭 메뉴)
 - 실행취소(방금 정리 되돌리기)
 - 윈도우 토스트 알림
 - 윈도우 시작 시 자동 실행 등록/해제
 - 연습 모드(실제로 안 옮기고 어디 갈지만 알려줌)
 - 규칙(rules.txt) 수정 시 재시작 없이 즉시 적용
 - 임시/잠금 파일(.tmp, .crdownload, ~$ 등) 자동 무시
"""

import os
import sys
import re
import time
import queue
import shutil
import threading
from datetime import datetime

# ---- 필수 ----
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("[오류] 'watchdog' 가 필요합니다.  cmd 에서:  pip install watchdog")
    input("엔터를 누르면 종료...")
    sys.exit(1)

# ---- 선택(없으면 자동으로 기본 동작으로 대체) ----
try:
    import tkinter as tk
    HAS_TK = True
except Exception:
    HAS_TK = False

try:
    import winsound
    HAS_SOUND = True
except Exception:
    HAS_SOUND = False

try:
    import pystray
    from pystray import MenuItem as Item, Menu
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except Exception:
    HAS_TRAY = False

try:
    from winotify import Notification
    HAS_TOAST = True
except Exception:
    HAS_TOAST = False

try:
    import winreg
    HAS_REG = True
except Exception:
    HAS_REG = False

try:
    import ctypes
    HAS_CTYPES = True
except Exception:
    HAS_CTYPES = False


# ============================================================
# 설정
# ============================================================
# 감시할 폴더 목록.
#  - 비워두면 '폴더목록.txt' 파일을 읽습니다. (메모장으로 폴더만 적으면 됨)
#  - 둘 다 비어있으면 이 프로그램 폴더의 '정리함' 을 사용합니다.
#  여기에 직접 적을 수도 있습니다. 예:
#  WATCH_FOLDERS = [r"C:\Users\사용자이름\Downloads", r"C:\Users\사용자이름\Documents"]
WATCH_FOLDERS = []
DEFAULT_FOLDER = "기타"          # 규칙에 안 맞는 파일을 넣을 폴더 (비우면 그대로 둠)
MULTI_MATCH_MODE = "nest"       # "nest"=폴더 안의 폴더 / "first"=하나만

# ★ 분류 방식
#   "auto"  : 파일 이름의 단어를 자동으로 인식해서 폴더로 만듦 (규칙 미리 안 적어도 됨)
#   "rules" : rules.txt 에 적은 규칙대로만 분류
CLASSIFY_MODE = "auto"
# [자동 모드] 폴더 깊이:  1 = 맨 앞 단어 1개만 폴더로
#                        2 = 앞 단어 2개를 '폴더 안의 폴더'로
#                        0 = 모든 단어를 '폴더 안의 폴더'로
AUTO_DEPTH = 1
# [자동 모드] 숫자/날짜로만 된 단어(2026, 06, 153022 등)는 폴더 이름으로 쓰지 않음
AUTO_SKIP_NUMERIC = True

ASK_BEFORE_CREATE = True        # 새 폴더 만들 때 확인 창
PLAY_ALARM_SOUND = True         # 새 폴더 확인 시 알람음
TOAST_ON_MOVE = True            # 정리될 때마다 토스트 알림
HIDE_CONSOLE = True             # 트레이가 있으면 검은 창 숨김

# ★ 기존 폴더로 보내기(분배) 모드
#   True  : 정리함에 넣은 파일을, 아래 '보낼곳'들 안에 '이미 있는 같은 이름 폴더'로 보냄
#           (못 찾으면 기존처럼 정리함 안에 새 폴더를 만들어 정리)
#   False : 끄면, 항상 감시 폴더 안에 하위 폴더를 만들어 정리 (예측 쉬움 · 기본값)
#   ※ 설정 창의 체크박스로도 켜고 끌 수 있습니다.
SEND_TO_EXISTING = False
# 기존 폴더를 '어느 폴더들 안에서' 찾을지. 비우면 '보낼곳목록.txt' 를 읽고,
# 그것도 비어있으면 기본으로 내 '문서' 폴더에서 찾습니다.
DEST_ROOTS = []
SEARCH_MAX_DEPTH = 5            # 보낼곳 안에서 폴더를 몇 단계까지 들어가 찾을지
INDEX_TTL = 60                 # 폴더 목록을 다시 훑기까지의 간격(초) — 속도를 위해 잠깐 기억해 둠

# 무시할 파일 패턴 (다운로드/잠금/임시 파일)
IGNORE_SUFFIX = (".tmp", ".crdownload", ".part", ".partial", ".download", ".!ut")
IGNORE_PREFIX = ("~$", ".~")
# ============================================================


# exe(PyInstaller)로 묶였을 때는 exe가 있는 폴더를, 평소엔 이 파일이 있는 폴더를 기준으로 함
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RULES_FILE = os.path.join(BASE_DIR, "rules.txt")
FOLDERS_FILE = os.path.join(BASE_DIR, "폴더목록.txt")
DEST_FILE = os.path.join(BASE_DIR, "보낼곳목록.txt")
SETTINGS_FILE = os.path.join(BASE_DIR, "앱설정.txt")
LOG_FILE = os.path.join(BASE_DIR, "정리기록.txt")
APP_NAME = "FileAutoSort"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

# '폴더목록.txt' 가 없을 때 자동으로 만들어 줄 안내 내용
FOLDERS_FILE_TEMPLATE = (
    "# 정리할(감시할) 폴더를 한 줄에 하나씩 적으세요.\n"
    "# '#' 으로 시작하는 줄은 설명이라 무시됩니다.\n"
    "# 예:\n"
    "#   C:\\Users\\사용자이름\\Downloads\n"
    "#   C:\\Users\\사용자이름\\Documents\n"
    "# (OneDrive 바탕화면이면)  C:\\Users\\사용자이름\\OneDrive\\바탕 화면\\스캔서류\n"
    "#\n"
    "# 주의: C:\\ 같은 드라이브 전체나 윈도우 시스템 폴더는 적지 마세요. (자동 차단됨)\n"
    "# 수정 후 저장하고 프로그램을 다시 켜면 적용됩니다.\n"
    "\n"
)

# '보낼곳목록.txt' 가 없을 때 자동으로 만들어 줄 안내 내용
DEST_FILE_TEMPLATE = (
    "# '기존 폴더로 보내기'에서 뒤질 폴더(보낼곳)를 한 줄에 하나씩 적으세요.\n"
    "# 정리함에 넣은 파일과 같은 이름의 폴더를 '이 안에서' 찾아 그리로 보냅니다.\n"
    "# '#' 으로 시작하는 줄은 설명이라 무시됩니다.\n"
    "# 아무것도 안 적으면 기본으로 '내 문서' 폴더에서 찾습니다.\n"
    "# 예:\n"
    "#   C:\\Users\\사용자이름\\Documents\n"
    "#   D:\\업무자료\n"
    "#\n"
    "# 주의: C:\\ 전체나 시스템 폴더는 적지 마세요. (자동 차단됨)\n"
    "# 너무 크고 깊은 폴더를 넣으면 첫 검색이 느릴 수 있습니다.\n"
    "# 수정 후 저장하고 프로그램을 다시 켜면 적용됩니다.\n"
    "\n"
)

active_folders = []      # 실제로 감시 중인 폴더들 (안전검사 통과한 것만)
dest_roots = []          # '기존 폴더 찾기'에서 뒤질 루트 폴더들
_index_cache = {"time": 0.0, "data": {}}
file_queue = queue.Queue()
move_lock = threading.Lock()
undo_stack = []          # (현재경로, 원래폴더, 원래이름)
tk_root = None
tray_icon = None
observer = None          # 폴더 감시자 (설정에서 폴더 바꾸면 다시 등록하려고 전역으로 둠)

state = {
    "running": True,
    "paused": False,
    "dry_run": False,
    "console_visible": True,
    "open_settings": False,   # 트레이에서 설정창 열기 요청 플래그 (메인 스레드가 처리)
    "pending_onboarding": False,  # 첫 실행 설정 후 안내 창을 띄울지 (메인 스레드가 처리)
}
_rules_cache = {"mtime": None, "rules": []}


# ----------------------------- 공통 -----------------------------
def log(message):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {message}"
    try:
        print(line)
    except Exception:
        pass  # 콘솔 없는 exe 모드에서는 화면 출력이 없을 수 있음
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_app_settings():
    """설정 창에서 바꾼 값들을 프로그램 시작 시 불러옵니다 (없으면 코드 기본값 유지)."""
    global SEND_TO_EXISTING, PLAY_ALARM_SOUND, AUTO_DEPTH
    if not os.path.exists(SETTINGS_FILE):
        return
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = [x.strip() for x in line.split("=", 1)]
                key = key.lower()
                if key == "send_to_existing":
                    SEND_TO_EXISTING = val.lower() in ("1", "true", "on", "y", "yes")
                elif key == "alarm":
                    PLAY_ALARM_SOUND = val.lower() in ("1", "true", "on", "y", "yes")
                elif key == "auto_depth":
                    try:
                        AUTO_DEPTH = int(val)
                    except ValueError:
                        pass
    except Exception as ex:
        log(f"[경고] 설정 불러오기 실패: {ex}")


def save_app_settings():
    """현재 설정 값을 파일에 저장합니다 (다음 실행 때 그대로 적용됨)."""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            f.write("# 이 파일은 설정 창에서 자동으로 저장됩니다. 직접 고치지 않아도 됩니다.\n")
            f.write(f"send_to_existing = {'true' if SEND_TO_EXISTING else 'false'}\n")
            f.write(f"alarm = {'true' if PLAY_ALARM_SOUND else 'false'}\n")
            f.write(f"auto_depth = {AUTO_DEPTH}\n")
    except Exception as ex:
        log(f"[경고] 설정 저장 실패: {ex}")


def notify(title, message):
    """토스트 알림(가능하면) + 로그."""
    if HAS_TOAST:
        try:
            Notification(app_id="파일 자동 정리", title=title, msg=message).show()
            return
        except Exception:
            pass
    # 토스트가 안 되면 비프음으로 대체
    if PLAY_ALARM_SOUND and HAS_SOUND:
        try:
            winsound.MessageBeep()
        except Exception:
            pass


def play_alarm():
    if not (PLAY_ALARM_SOUND and HAS_SOUND):
        return
    try:
        for _ in range(3):
            winsound.Beep(880, 150)
            time.sleep(0.05)
    except Exception:
        try:
            winsound.MessageBeep()
        except Exception:
            pass


# ----------------------------- 감시 폴더 -----------------------------
def is_dangerous_folder(path):
    """C드라이브 루트나 시스템 폴더처럼 감시하면 안 되는 곳인지 검사."""
    try:
        low = os.path.abspath(path).lower().rstrip("\\/")
    except Exception:
        return True
    # 드라이브 루트 (c:, d: ...)
    if re.fullmatch(r"[a-z]:", low):
        return True
    sysroot = os.environ.get("SystemRoot", r"C:\Windows").lower().rstrip("\\/")
    sysdrive = os.environ.get("SystemDrive", "C:").lower()
    danger = [
        sysroot,
        sysdrive + "\\program files",
        sysdrive + "\\program files (x86)",
        sysdrive + "\\programdata",
        sysdrive + "\\windows",
    ]
    for d in danger:
        if low == d or low.startswith(d + "\\"):
            return True
    return False


def load_watch_folders():
    """
    감시할 폴더 목록을 정합니다.
    우선순위: 코드의 WATCH_FOLDERS  ->  폴더목록.txt  ->  기본 '정리함'
    위험 폴더(C드라이브 루트/시스템)는 자동으로 제외합니다.
    """
    candidates = list(WATCH_FOLDERS)
    if not candidates and os.path.exists(FOLDERS_FILE):
        with open(FOLDERS_FILE, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip().strip('"')
                if line and not line.startswith("#"):
                    candidates.append(line)

    result = []
    for p in candidates:
        p = os.path.expandvars(os.path.expanduser(p))
        if is_dangerous_folder(p):
            log(f"[차단] 위험한 폴더라 감시하지 않음: {p}")
            notify("감시 제외", f"위험 폴더는 건너뜁니다:\n{p}")
            continue
        if not os.path.isdir(p):
            log(f"[경고] 폴더가 없어 건너뜀: {p}")
            continue
        ap = os.path.abspath(p)
        if ap not in result:
            result.append(ap)

    if not result:
        default = os.path.join(BASE_DIR, "정리함")
        try:
            os.makedirs(default, exist_ok=True)
            result.append(default)
        except Exception as ex:
            log(f"[경고] 기본 '정리함' 폴더를 만들 수 없음(저장 불가 위치일 수 있음): {ex}")
    return result


def load_dest_roots():
    """
    '기존 폴더 찾기'에서 뒤질 루트 폴더들을 정합니다.
    우선순위: 코드의 DEST_ROOTS  ->  보낼곳목록.txt  ->  기본 '내 문서'
    위험 폴더는 자동 제외합니다.
    """
    candidates = list(DEST_ROOTS)
    if not candidates and os.path.exists(DEST_FILE):
        with open(DEST_FILE, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip().strip('"')
                if line and not line.startswith("#"):
                    candidates.append(line)
    if not candidates:
        candidates.append(os.path.expanduser("~/Documents"))  # 기본: 내 문서

    result = []
    for p in candidates:
        p = os.path.expandvars(os.path.expanduser(p))
        if is_dangerous_folder(p):
            log(f"[차단] 위험 폴더는 보낼곳에서 제외: {p}")
            continue
        if os.path.isdir(p):
            ap = os.path.abspath(p)
            if ap not in result:
                result.append(ap)
        else:
            log(f"[경고] 보낼곳 폴더 없음, 건너뜀: {p}")
    return result


def get_folder_index(force=False):
    """
    보낼곳 루트들 안의 '폴더 이름 -> 실제 경로 목록' 색인을 만듭니다.
    매번 새로 훑으면 느리므로 INDEX_TTL 초 동안은 기억해 둡니다.
    """
    now = time.time()
    if not force and _index_cache["data"] and (now - _index_cache["time"] < INDEX_TTL):
        return _index_cache["data"]

    data = {}
    for root in dest_roots:
        base_depth = root.rstrip("\\/").count(os.sep)
        for dirpath, dirnames, _ in os.walk(root):
            depth = dirpath.count(os.sep) - base_depth
            if depth >= SEARCH_MAX_DEPTH:
                dirnames[:] = []  # 더 깊이 들어가지 않음
            # 숨김/시스템/위험 폴더 제외
            keep = []
            for d in dirnames:
                if d.startswith(".") or d.startswith("~"):
                    continue
                full = os.path.join(dirpath, d)
                if is_dangerous_folder(full):
                    continue
                keep.append(d)
                data.setdefault(d.lower(), []).append(full)
            dirnames[:] = keep
    _index_cache["data"] = data
    _index_cache["time"] = now
    return data


def candidate_words(filename, rules):
    """
    '기존 폴더로 보내기'에서 찾을 단어들.
    파일 이름의 아무 단어에나 반응하면 엉뚱한 폴더로 새어나가므로,
    실제 분류에 쓰이는 '대표 폴더 이름'의 단계들만 후보로 씁니다.
    (예: 20260617_춘천고등학교_견적서 → 대표단어 '춘천고등학교'만 확인,
         '견적서'처럼 뒤에 붙은 일반 단어로는 보내지 않음)
    """
    words = []
    folder_name = match_folder(filename, rules)
    if folder_name:
        for part in folder_name.replace("/", os.sep).split(os.sep):
            part = part.strip()
            if part and part not in words:
                words.append(part)
    return words


def find_existing_folder(filename, rules):
    """파일 이름과 일치하는 '이미 존재하는 폴더'를 찾아 경로를 돌려줍니다. 없으면 None."""
    if not dest_roots:
        return None
    index = get_folder_index()
    for w in candidate_words(filename, rules):
        paths = index.get(w.lower())
        if paths:
            # 같은 이름이 여러 곳이면 '가장 얕은(루트에 가까운)' 폴더 선택
            return min(paths, key=lambda p: (p.count(os.sep), len(p)))
    return None


# ----------------------------- 규칙 -----------------------------
def load_rules():
    rules = []
    if not os.path.exists(RULES_FILE):
        log(f"[경고] 규칙 파일 없음: {RULES_FILE}")
        return rules
    with open(RULES_FILE, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, folder = line.split("=", 1)
            k = k.strip().lower()
            folder = folder.strip()
            if k and folder:
                rules.append((k, folder, k.startswith(".")))
    return rules


def get_rules(force=False):
    """rules.txt 가 바뀌면 자동으로 다시 읽습니다 (즉시 적용)."""
    try:
        m = os.path.getmtime(RULES_FILE)
    except OSError:
        m = None
    if force or m != _rules_cache["mtime"]:
        _rules_cache["rules"] = load_rules()
        _rules_cache["mtime"] = m
        log(f"규칙 적용: {len(_rules_cache['rules'])}개")
    return _rules_cache["rules"]


def auto_folder_from_name(filename):
    """파일 이름에서 단어를 뽑아 폴더 경로를 만듭니다. (규칙 없이 자동)"""
    name = os.path.splitext(filename)[0]
    # 구분기호( _ - 공백 . () [] 등 )로 단어를 나눕니다.
    tokens = re.split(r"[\s_\-\.\(\)\[\]{}]+", name)
    words = []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        if AUTO_SKIP_NUMERIC and re.fullmatch(r"[0-9]+", t):
            continue  # 숫자/날짜만 있는 토막은 폴더로 안 씀
        words.append(t)
    if not words:
        return None
    if AUTO_DEPTH and AUTO_DEPTH > 0:
        words = words[:AUTO_DEPTH]
    return os.path.join(*words)


def match_folder(filename, rules):
    name = filename.lower()
    ext = os.path.splitext(name)[1]

    # 1) rules.txt 에 적은 단어 규칙 (자동 모드에서도 '예외/우선'으로 적용)
    matched = []
    for k, folder, is_ext in rules:
        if is_ext:
            continue
        if k in name and folder not in matched:
            matched.append(folder)
    if matched:
        return os.path.join(*matched) if MULTI_MATCH_MODE == "nest" else matched[0]

    # 2) 확장자 규칙
    for k, folder, is_ext in rules:
        if is_ext and ext == k:
            return folder

    # 3) 자동 모드면, 규칙에 없어도 파일 이름의 단어로 폴더를 만듦
    if CLASSIFY_MODE == "auto":
        return auto_folder_from_name(filename)

    return None


# ----------------------------- 파일 처리 -----------------------------
def is_ignored(filename):
    low = filename.lower()
    if low.startswith(IGNORE_PREFIX):
        return True
    if low.endswith(IGNORE_SUFFIX):
        return True
    return False


def wait_until_ready(filepath, timeout=30):
    last, stable, waited = -1, 0, 0
    while waited < timeout:
        if not os.path.exists(filepath):
            return False
        try:
            size = os.path.getsize(filepath)
        except OSError:
            time.sleep(0.5); waited += 0.5; continue
        if size == last:
            stable += 1
            if stable >= 2:
                return True
        else:
            stable, last = 0, size
        time.sleep(0.5); waited += 0.5
    return True


def unique_path(folder, filename):
    target = os.path.join(folder, filename)
    if not os.path.exists(target):
        return target
    name, ext = os.path.splitext(filename)
    i = 1
    while True:
        cand = os.path.join(folder, f"{name} ({i}){ext}")
        if not os.path.exists(cand):
            return cand
        i += 1


def ask_folder_dialog(filename, proposed):
    play_alarm()
    if not HAS_TK or tk_root is None:
        return proposed
    result = {"folder": None}
    dlg = tk.Toplevel(tk_root)
    dlg.title("새 폴더 만들기 - 확인")
    dlg.attributes("-topmost", True)
    dlg.resizable(False, False)
    try:
        dlg.lift(); dlg.focus_force()
    except Exception:
        pass
    tk.Label(dlg, text="규칙에 맞는 폴더가 없어 새로 만들려고 합니다.",
             font=("맑은 고딕", 10, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
    tk.Label(dlg, text=f"파일:  {filename}", font=("맑은 고딕", 9)).pack(anchor="w", padx=14)
    tk.Label(dlg, text="만들 폴더 (수정 가능,  \\ 로 하위 폴더):",
             font=("맑은 고딕", 9)).pack(anchor="w", padx=14, pady=(10, 2))
    var = tk.StringVar(value=proposed)
    e = tk.Entry(dlg, textvariable=var, width=46, font=("맑은 고딕", 10))
    e.pack(padx=14); e.focus_set(); e.icursor("end")

    def ok():
        result["folder"] = var.get().strip() or proposed
        dlg.destroy()

    def skip():
        result["folder"] = None
        dlg.destroy()

    bf = tk.Frame(dlg)
    tk.Button(bf, text="이 폴더로 이동 (Enter)", width=20, command=ok).pack(side="left", padx=4)
    tk.Button(bf, text="정리 안 함 (Esc)", width=16, command=skip).pack(side="left", padx=4)
    bf.pack(pady=14)
    dlg.bind("<Return>", lambda ev: ok())
    dlg.bind("<Escape>", lambda ev: skip())
    dlg.protocol("WM_DELETE_WINDOW", skip)
    tk_root.wait_window(dlg)
    return result["folder"]


def sort_file(filepath, base_folder):
    filename = os.path.basename(filepath)
    if os.path.abspath(filepath) in (
        os.path.abspath(LOG_FILE), os.path.abspath(RULES_FILE), os.path.abspath(FOLDERS_FILE)
    ):
        return
    if is_ignored(filename):
        return
    if not wait_until_ready(filepath):
        return
    if not os.path.exists(filepath):
        return

    rules = get_rules()
    folder_name = match_folder(filename, rules)
    if folder_name is None:
        if not DEFAULT_FOLDER:
            return
        folder_name = DEFAULT_FOLDER

    # ★ 기존 폴더로 보내기: 드라이브에 이미 있는 같은 이름 폴더를 먼저 찾음
    existing = None
    if SEND_TO_EXISTING:
        existing = find_existing_folder(filename, rules)

    # 연습 모드: 실제로 안 옮기고 알려만 줌
    if state["dry_run"]:
        if existing:
            log(f"[연습] {filename}  ->  (기존) {existing}  (실제 이동 안 함)")
            if TOAST_ON_MOVE:
                notify("연습 모드", f"{filename}\n→ 기존 폴더: {os.path.basename(existing)} (예정)")
        else:
            log(f"[연습] {filename}  ->  {folder_name}\\  (실제 이동 안 함)")
            if TOAST_ON_MOVE:
                notify("연습 모드", f"{filename}\n→ {folder_name} (예정)")
        return

    # 기존 폴더를 찾았으면 그리로 바로 이동 (새 폴더 안 만듦)
    if existing:
        with move_lock:
            try:
                target = unique_path(existing, filename)
                shutil.move(filepath, target)
                undo_stack.append((target, base_folder, filename))
                if len(undo_stack) > 100:
                    undo_stack.pop(0)
                log(f"이동(기존 폴더): {filename}  ->  {existing}")
                if TOAST_ON_MOVE:
                    notify("정리 완료", f"{filename}\n→ {os.path.basename(existing)} (기존 폴더)")
            except Exception as ex:
                log(f"[실패] {filename}: {ex}")
        return

    dest_folder = os.path.join(base_folder, folder_name)
    if not os.path.exists(dest_folder):
        if ASK_BEFORE_CREATE:
            chosen = ask_folder_dialog(filename, folder_name)
            if chosen is None:
                log(f"[건너뜀] 사용자 선택: {filename}")
                return
            folder_name = chosen
            dest_folder = os.path.join(base_folder, folder_name)
        try:
            os.makedirs(dest_folder, exist_ok=True)
            log(f"새 폴더 생성: {folder_name}\\")
        except Exception as ex:
            log(f"[실패] 폴더 생성: {ex}")
            return

    with move_lock:
        try:
            target = unique_path(dest_folder, filename)
            shutil.move(filepath, target)
            undo_stack.append((target, base_folder, filename))
            if len(undo_stack) > 100:
                undo_stack.pop(0)
            log(f"이동: {filename}  ->  {folder_name}\\")
            if TOAST_ON_MOVE:
                notify("정리 완료", f"{filename}\n→ {folder_name}")
        except Exception as ex:
            log(f"[실패] {filename}: {ex}")


def do_undo():
    """가장 최근 정리 1건을 되돌립니다."""
    with move_lock:
        if not undo_stack:
            notify("실행취소", "되돌릴 정리 기록이 없습니다.")
            return
        current, back_folder, orig_name = undo_stack.pop()
        if not os.path.exists(current):
            notify("실행취소", "파일을 찾을 수 없어 되돌리지 못했습니다.")
            return
        try:
            target = unique_path(back_folder, orig_name)
            moved_from = os.path.dirname(current)
            shutil.move(current, target)
            # 비어버린 폴더는 정리
            try:
                if moved_from != back_folder and not os.listdir(moved_from):
                    os.rmdir(moved_from)
            except Exception:
                pass
            log(f"실행취소: {orig_name}  되돌림")
            notify("실행취소 완료", f"{orig_name} 을(를) 되돌렸습니다.")
        except Exception as ex:
            log(f"[실패] 실행취소: {ex}")
            notify("실행취소 실패", str(ex))


def enqueue_existing():
    for base in active_folders:
        try:
            for entry in os.listdir(base):
                full = os.path.join(base, entry)
                if os.path.isfile(full):
                    file_queue.put((full, base))
        except Exception as ex:
            log(f"[경고] 폴더 읽기 실패 {base}: {ex}")


# ----------------------------- 콘솔/자동시작 -----------------------------
def set_console(visible):
    if not (HIDE_CONSOLE and HAS_CTYPES):
        return
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 5 if visible else 0)
            state["console_visible"] = visible
    except Exception:
        pass


def autostart_enabled():
    if not HAS_REG:
        return False
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY)
        winreg.QueryValueEx(k, APP_NAME)
        winreg.CloseKey(k)
        return True
    except Exception:
        return False


def set_autostart(enable):
    if not HAS_REG:
        return
    try:
        if getattr(sys, "frozen", False):
            cmd = f'"{sys.executable}"'  # exe 자체를 등록
        else:
            pyw = os.path.join(sys.exec_prefix, "pythonw.exe")
            if not os.path.exists(pyw):
                pyw = sys.executable
            cmd = f'"{pyw}" "{os.path.abspath(__file__)}"'
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
        if enable:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, cmd)
            log("자동 실행 등록됨")
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
                log("자동 실행 해제됨")
            except FileNotFoundError:
                pass
        winreg.CloseKey(k)
    except Exception as ex:
        log(f"[실패] 자동실행 설정: {ex}")


# ----------------------------- 설정창 (클릭으로 폴더 고르기) -----------------------------
def known_folder(kind):
    """다운로드/문서/바탕화면 등 흔한 폴더의 실제 경로를 추정합니다."""
    home = os.path.expanduser("~")
    cands = {
        "downloads": [os.path.join(home, "Downloads"), os.path.join(home, "다운로드")],
        "documents": [os.path.join(home, "Documents"),
                      os.path.join(home, "OneDrive", "Documents"),
                      os.path.join(home, "OneDrive", "문서"),
                      os.path.join(home, "문서")],
        "desktop": [os.path.join(home, "Desktop"),
                    os.path.join(home, "OneDrive", "Desktop"),
                    os.path.join(home, "OneDrive", "바탕 화면"),
                    os.path.join(home, "바탕 화면")],
    }.get(kind, [])
    for c in cands:
        if os.path.isdir(c):
            return c
    return cands[0] if cands else home


def write_folder_list(path, folders, header):
    """폴더 목록을 txt 파일로 저장합니다."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(header)
            for d in folders:
                f.write(d + "\n")
    except Exception as ex:
        log(f"[실패] 목록 저장 {path}: {ex}")


def apply_settings(watch_list, dest_list):
    """설정을 파일에 저장하고, 재시작 없이 바로 적용합니다."""
    global active_folders, dest_roots

    write_folder_list(
        FOLDERS_FILE, watch_list,
        "# 정리할(감시할) 폴더 목록 - 설정창에서 저장됨\n"
        "# 여기에 파일을 넣으면 자동으로 정리됩니다.\n\n",
    )
    write_folder_list(
        DEST_FILE, dest_list,
        "# '기존 폴더로 보내기'에서 찾을 폴더 목록 - 설정창에서 저장됨\n\n",
    )

    active_folders = load_watch_folders()
    dest_roots = load_dest_roots() if SEND_TO_EXISTING else []
    _index_cache["time"] = 0.0  # 폴더 색인 새로 만들도록

    # 감시자 다시 등록
    global observer
    if observer is not None:
        try:
            observer.unschedule_all()
            for base in active_folders:
                observer.schedule(Handler(base), base, recursive=False)
        except Exception as ex:
            log(f"[경고] 감시 재설정 실패: {ex}")
    enqueue_existing()
    log("설정이 적용되었습니다.")


def open_settings_window():
    """경로를 몰라도 버튼으로 폴더를 고르는 설정 창. (메인 스레드에서 호출)"""
    if not HAS_TK or tk_root is None:
        return
    import tkinter.filedialog as filedialog
    from tkinter import messagebox

    win = tk.Toplevel(tk_root)
    win.title("파일 자동 정리 - 설정")
    win.attributes("-topmost", True)
    win.geometry("560x640")
    try:
        win.lift(); win.focus_force()
    except Exception:
        pass

    FONT = ("맑은 고딕", 10)
    FONT_B = ("맑은 고딕", 11, "bold")

    def make_folder_section(parent, title, desc, initial, quick=True):
        frame = tk.LabelFrame(parent, text=title, font=FONT_B, padx=10, pady=8)
        frame.pack(fill="x", padx=12, pady=8)
        tk.Label(frame, text=desc, font=("맑은 고딕", 9), fg="#555",
                 justify="left", wraplength=500).pack(anchor="w", pady=(0, 6))
        lb = tk.Listbox(frame, height=4, font=("맑은 고딕", 9))
        lb.pack(fill="x")
        for d in initial:
            lb.insert("end", d)

        def add_dir():
            d = filedialog.askdirectory(title="폴더를 고르세요")
            if d:
                d = os.path.normpath(d)
                if is_dangerous_folder(d):
                    messagebox.showwarning("사용할 수 없는 폴더",
                                           "드라이브 전체나 시스템 폴더는 쓸 수 없어요.\n"
                                           "다운로드·문서 같은 내 폴더를 골라주세요.")
                    return
                if d not in lb.get(0, "end"):
                    lb.insert("end", d)

        def add_known(kind):
            d = known_folder(kind)
            if d and d not in lb.get(0, "end"):
                lb.insert("end", d)

        def remove_sel():
            for i in reversed(lb.curselection()):
                lb.delete(i)

        btns = tk.Frame(frame)
        btns.pack(fill="x", pady=(6, 0))
        tk.Button(btns, text="＋ 폴더 추가(직접 고르기)", command=add_dir).pack(side="left")
        tk.Button(btns, text="선택 삭제", command=remove_sel).pack(side="right")

        if quick:
            qf = tk.Frame(frame)
            qf.pack(fill="x", pady=(6, 0))
            tk.Label(qf, text="빠른 추가:", font=("맑은 고딕", 9)).pack(side="left")
            tk.Button(qf, text="다운로드", command=lambda: add_known("downloads")).pack(side="left", padx=3)
            tk.Button(qf, text="문서", command=lambda: add_known("documents")).pack(side="left", padx=3)
            tk.Button(qf, text="바탕화면", command=lambda: add_known("desktop")).pack(side="left", padx=3)
        return lb

    tk.Label(win, text="파일을 어디에 넣고, 어디로 정리할지 폴더만 골라주세요.",
             font=FONT_B).pack(anchor="w", padx=12, pady=(12, 0))

    watch_lb = make_folder_section(
        win, "1. 정리할 폴더",
        "여기에 넣은 파일들이 이름을 보고 자동으로 하위 폴더로 정리됩니다.",
        active_folders,
    )
    dest_lb = make_folder_section(
        win, "2. 보낼 곳 (선택)",
        "정리함에 넣은 파일을, 이 폴더들 안에 '이미 있는 같은 이름 폴더'로 보냅니다. "
        "없으면 비워두어도 됩니다.",
        dest_roots,
    )

    # 간단 옵션
    opt = tk.LabelFrame(win, text="옵션", font=FONT_B, padx=10, pady=6)
    opt.pack(fill="x", padx=12, pady=8)
    v_send = tk.BooleanVar(value=SEND_TO_EXISTING)
    v_alarm = tk.BooleanVar(value=PLAY_ALARM_SOUND)
    tk.Checkbutton(opt, text="이미 있는 폴더로 보내기 사용", variable=v_send, font=FONT).pack(anchor="w")
    tk.Checkbutton(opt, text="새 폴더 만들 때 알람 소리", variable=v_alarm, font=FONT).pack(anchor="w")

    tk.Label(opt, text="폴더 깊이 — 파일 이름으로 폴더를 몇 단계까지 만들지",
             font=FONT).pack(anchor="w", pady=(8, 0))
    tk.Label(opt, text="예)  20260617_춘천고등학교_견적서.xlsx",
             font=("맑은 고딕", 9), fg="#555").pack(anchor="w")
    v_depth = tk.IntVar(value=AUTO_DEPTH if AUTO_DEPTH in (0, 1, 2) else 1)
    drow = tk.Frame(opt); drow.pack(anchor="w")
    tk.Radiobutton(drow, text="한 단계 (춘천고등학교)", variable=v_depth, value=1, font=FONT).pack(side="left")
    tk.Radiobutton(drow, text="두 단계 (춘천고등학교\\견적서)", variable=v_depth, value=2, font=FONT).pack(side="left")
    tk.Radiobutton(drow, text="전부", variable=v_depth, value=0, font=FONT).pack(side="left")

    def save_and_close():
        global SEND_TO_EXISTING, PLAY_ALARM_SOUND, AUTO_DEPTH
        SEND_TO_EXISTING = v_send.get()
        PLAY_ALARM_SOUND = v_alarm.get()
        AUTO_DEPTH = v_depth.get()
        save_app_settings()  # 껐다 켜도 유지되도록 저장
        apply_settings(list(watch_lb.get(0, "end")), list(dest_lb.get(0, "end")))
        try:
            messagebox.showinfo("저장됨", "설정이 저장되고 바로 적용되었습니다.")
        except Exception:
            pass
        win.destroy()

    bar = tk.Frame(win)
    bar.pack(fill="x", padx=12, pady=12)
    tk.Button(bar, text="저장하고 닫기", font=FONT_B, height=1,
              command=save_and_close).pack(side="right")
    tk.Button(bar, text="취소", command=win.destroy).pack(side="right", padx=8)

    tk_root.wait_window(win)


# ----------------------------- 저장 위치 점검 / 첫 실행 안내 -----------------------------
def base_dir_writable():
    """프로그램 폴더에 파일을 쓸 수 있는지(설정·기록을 저장할 수 있는지) 확인."""
    try:
        test = os.path.join(BASE_DIR, ".write_test.tmp")
        with open(test, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(test)
        return True
    except Exception:
        return False


def warn_if_readonly_location():
    """
    설정/기록을 저장할 수 없는 위치에서 실행되면 크게 안내합니다.
    (흔한 원인) ZIP을 풀지 않고 그 안에서 바로 실행 / Program Files 같은 보호된 폴더에 둠.
    """
    if base_dir_writable():
        return
    log(f"[경고] 저장할 수 없는 위치에서 실행 중: {BASE_DIR}")
    msg = (
        "이 프로그램이 있는 폴더에 설정과 기록을 저장할 수 없어요.\n\n"
        f"현재 위치:\n{BASE_DIR}\n\n"
        "보통 아래 두 경우입니다:\n"
        "  • ZIP 압축을 풀지 않고 그 안에서 바로 실행한 경우\n"
        "  • Program Files 같은 보호된 폴더에 둔 경우\n\n"
        "압축을 완전히 푼 뒤, 프로그램 파일 전부를 '바탕화면'이나 '문서' 같은\n"
        "평범한 폴더로 옮기고 다시 실행해 주세요.\n"
        "(지금 이대로도 정리는 되지만, 설정과 되돌리기 기록이 저장되지 않습니다.)"
    )
    if HAS_TK and tk_root is not None:
        try:
            from tkinter import messagebox
            messagebox.showwarning("저장할 수 없는 위치", msg)
        except Exception:
            pass
    else:
        try:
            print("\n[경고] " + msg + "\n")
        except Exception:
            pass
    notify("저장할 수 없는 위치",
           "설정·기록이 저장되지 않아요. 프로그램 파일을 바탕화면/문서로 옮겨 주세요.")


def show_onboarding():
    """
    첫 실행 직후 딱 한 번: (1) 트레이(숨은 아이콘) 위치 안내
    (2) 지금은 '연습 모드'임을 알리고, 바로 실제 정리를 켤지 물어봄.
    """
    tray_hint = HAS_TRAY

    # 창을 놓쳐도 힌트가 남도록 토스트로도 한 번
    if tray_hint:
        notify("여기 숨어서 일해요",
               "오른쪽 아래 시계 옆( '^' 안 )의 노란 폴더 아이콘을 클릭하면 설정이 열려요.")

    if not (HAS_TK and tk_root is not None):
        log("[안내] 지금은 연습 모드입니다. 실제 정리를 켜려면 나중에 연습 모드를 끄세요.")
        return

    win = tk.Toplevel(tk_root)
    win.title("준비 완료 — 꼭 읽어주세요")
    win.attributes("-topmost", True)
    win.resizable(False, False)
    try:
        win.lift(); win.focus_force()
    except Exception:
        pass

    FONT_T = ("맑은 고딕", 12, "bold")
    FONT_B = ("맑은 고딕", 10, "bold")
    FONT   = ("맑은 고딕", 10)
    FONT_S = ("맑은 고딕", 9)

    pad = tk.Frame(win, padx=16, pady=14)
    pad.pack(fill="both", expand=True)

    tk.Label(pad, text="설정이 저장됐어요!", font=FONT_T).pack(anchor="w")

    if tray_hint:
        tk.Label(pad,
                 text="이제 이 프로그램은 화면 오른쪽 아래 시계 옆에 숨어서 조용히 일해요.",
                 font=FONT, justify="left", wraplength=440).pack(anchor="w", pady=(8, 2))
        tk.Label(pad,
                 text="안 보이면 시계 옆의  '^'  를 누르면 노란 폴더 아이콘이 나와요.\n"
                      "   • 왼쪽 클릭 → 설정 열기\n"
                      "   • 오른쪽 클릭 → 메뉴 (일시정지 · 되돌리기 · 종료)",
                 font=FONT_S, fg="#444", justify="left").pack(anchor="w")
        tk.Label(pad, text="↘  화면 오른쪽 아래예요",
                 font=FONT_B, fg="#c07a00").pack(anchor="e", pady=(4, 0))
    else:
        tk.Label(pad,
                 text="이 검은 창이 켜져 있는 동안 정리가 동작해요. 끄려면 창을 닫으세요.",
                 font=FONT, justify="left", wraplength=440).pack(anchor="w", pady=(8, 2))

    tk.Frame(pad, height=1, bg="#dddddd").pack(fill="x", pady=12)

    tk.Label(pad, text="처음이니 '연습 모드'로 시작할게요.", font=FONT_B).pack(anchor="w")
    tk.Label(pad,
             text="정리할 폴더에 파일을 넣어보면, 실제로 옮기지 않고 '어디로 갈지'만 알려줘요.\n"
                  "확인해 보고 마음에 들면 아래 [바로 정리 시작] 을 누르세요.",
             font=FONT_S, fg="#444", justify="left").pack(anchor="w", pady=(2, 12))

    def keep_practice():
        state["dry_run"] = True
        win.destroy()
        if tray_hint:
            notify("연습 모드 켜짐",
                   "실제로는 옮기지 않고 어디로 갈지만 알려줘요. "
                   "실제 정리는 노란 아이콘 우클릭 → '연습 모드' 를 끄면 시작돼요.")
        else:
            notify("연습 모드 켜짐", "실제로는 옮기지 않아요. 나중에 실제 정리를 켤 수 있어요.")

    def start_real():
        state["dry_run"] = False
        win.destroy()
        if tray_hint:
            notify("정리 시작",
                   "이제부터 파일을 실제로 정리해요. 되돌리려면 노란 아이콘 우클릭 → '방금 정리 되돌리기'.")
        else:
            notify("정리 시작", "이제부터 파일을 실제로 정리해요.")

    bar = tk.Frame(pad)
    bar.pack(fill="x", pady=(4, 0))
    tk.Button(bar, text="연습 모드로 먼저 해볼래요", font=FONT,
              command=keep_practice).pack(side="left")
    tk.Button(bar, text="바로 정리 시작", font=FONT_B,
              command=start_real).pack(side="right")

    # 화면 오른쪽 아래(트레이 근처)에 배치해서 화살표가 자연스럽게 향하도록
    try:
        win.update_idletasks()
        w, h = win.winfo_width(), win.winfo_height()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        x = max(0, sw - w - 24)
        y = max(0, sh - h - 64)   # 작업표시줄 위쪽
        win.geometry(f"+{x}+{y}")
    except Exception:
        pass

    tk_root.wait_window(win)


# ----------------------------- 트레이 -----------------------------
def make_icon_image():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([8, 14, 30, 24], fill=(245, 200, 70))
    d.rectangle([8, 20, 56, 52], fill=(245, 200, 70), outline=(170, 130, 30), width=2)
    return img


def build_tray():
    def open_folder(icon, item):
        for f in active_folders:
            try:
                os.startfile(f)
            except Exception:
                pass

    def open_settings(icon, item):
        # 창은 메인 스레드에서 열어야 안전하므로 플래그만 세움
        state["open_settings"] = True

    def edit_rules(icon, item):
        try:
            os.startfile(RULES_FILE)
        except Exception:
            pass

    def reload_rules(icon, item):
        get_rules(force=True)
        notify("규칙 다시 읽기", "규칙을 다시 불러왔습니다.")

    def toggle_pause(icon, item):
        state["paused"] = not state["paused"]
        notify("상태", "일시정지됨" if state["paused"] else "정리 재개")

    def toggle_dry(icon, item):
        state["dry_run"] = not state["dry_run"]
        notify("연습 모드", "켜짐 (실제로 안 옮김)" if state["dry_run"] else "꺼짐")

    def toggle_autostart(icon, item):
        set_autostart(not autostart_enabled())

    def toggle_console(icon, item):
        set_console(not state["console_visible"])

    def undo(icon, item):
        do_undo()

    def quit_app(icon, item):
        state["running"] = False
        try:
            icon.stop()
        except Exception:
            pass

    menu = Menu(
        Item("설정 (폴더 고르기)", open_settings, default=True),
        Item("감시 폴더 열기", open_folder),
        Item("규칙 수정 (고급)", edit_rules),
        Menu.SEPARATOR,
        Item("일시정지", toggle_pause, checked=lambda i: state["paused"]),
        Item("연습 모드", toggle_dry, checked=lambda i: state["dry_run"]),
        Item("윈도우 시작 시 자동 실행", toggle_autostart, checked=lambda i: autostart_enabled()),
        Item("로그 창 보이기", toggle_console, checked=lambda i: state["console_visible"]),
        Menu.SEPARATOR,
        Item("방금 정리 되돌리기", undo),
        Menu.SEPARATOR,
        Item("종료", quit_app),
    )
    return pystray.Icon(APP_NAME, make_icon_image(), "파일 자동 정리", menu)


# ----------------------------- 감시 -----------------------------
class Handler(FileSystemEventHandler):
    def __init__(self, base_folder):
        self.base = base_folder

    def on_created(self, event):
        if not event.is_directory:
            file_queue.put((event.src_path, self.base))

    def on_moved(self, event):
        if not event.is_directory:
            file_queue.put((event.dest_path, self.base))


def folders_file_has_entries():
    """
    폴더목록.txt 에 (주석 '#'·빈 줄 말고) 실제 폴더 경로가 한 줄이라도 적혀 있는지 확인.
    - 이 파일은 설정을 '한 번 저장'해야 실제 폴더가 적힙니다.
    - 그래서 첫 실행(설정 전) 판단의 기준으로 씁니다.
      (보낼곳목록.txt 같은 '선택' 템플릿 파일이 있어도 첫 실행 안내는 떠야 하므로 여기선 안 봄)
    """
    if not os.path.exists(FOLDERS_FILE):
        return False
    try:
        with open(FOLDERS_FILE, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip().strip('"')
                if line and not line.startswith("#"):
                    return True
    except Exception:
        pass
    return False


def main():
    global active_folders, dest_roots, tk_root, tray_icon, observer

    load_app_settings()   # 저장된 설정(깊이/기존폴더/알람)이 있으면 먼저 반영

    # tk 루트를 먼저(숨겨서) 만들어 두면, 위치 경고·설정창·안내창을 바로 띄울 수 있음
    if HAS_TK:
        tk_root = tk.Tk()
        tk_root.withdraw()

    # 설정/기록을 저장할 수 없는 위치(압축 안 풂 / Program Files 등)면 먼저 크게 안내
    warn_if_readonly_location()

    # '첫 실행'은 정리할 폴더가 아직 설정되지 않은 상태로 판단합니다.
    #  보낼곳목록.txt 같은 '선택' 템플릿이 폴더에 있어도 안내창이 뜨도록,
    #  '폴더목록.txt 에 실제 폴더가 적혔는지' 만 봅니다. (설정을 한 번 저장하면 적힘)
    first_run = not (WATCH_FOLDERS or folders_file_has_entries())

    active_folders = load_watch_folders()
    dest_roots = load_dest_roots() if SEND_TO_EXISTING else []

    get_rules(force=True)
    log("=" * 50)
    log("파일 자동 정리 시작")
    log("감시 폴더:")
    for f in active_folders:
        log(f"   - {f}")
    if SEND_TO_EXISTING:
        log("기존 폴더를 찾을 곳:")
        for f in dest_roots:
            log(f"   - {f}")
    log(f"트레이 {HAS_TRAY} / 토스트 {HAS_TOAST} / 확인창 {HAS_TK}")
    log("=" * 50)

    observer = Observer()
    for base in active_folders:
        observer.schedule(Handler(base), base, recursive=False)
    observer.start()
    enqueue_existing()

    # 트레이가 있으면 별도 스레드로 띄우고 콘솔 숨김
    if HAS_TRAY:
        tray_icon = build_tray()
        threading.Thread(target=tray_icon.run, daemon=True).start()
        time.sleep(0.5)
        set_console(False)
        notify("파일 자동 정리", f"{len(active_folders)}개 폴더 감시 중입니다. (트레이 우클릭 → 설정)")
    else:
        log("트레이 라이브러리가 없어 콘솔 모드로 실행합니다. (끄려면 이 창 닫기)")

    # 처음 실행: 안전하게 '연습 모드'로 시작하고, 설정 창 → 안내 창을 이어서 띄웁니다.
    if first_run:
        state["dry_run"] = True
        log("첫 실행 감지 — 연습 모드로 시작 (실제 이동 안 함)")
        if HAS_TK:
            state["open_settings"] = True
            state["pending_onboarding"] = True

    try:
        while state["running"]:
            # 트레이에서 설정창 열기 요청이 오면 메인 스레드에서 처리
            if state["open_settings"]:
                state["open_settings"] = False
                try:
                    open_settings_window()
                    # 첫 실행일 때만: 설정 저장 직후 트레이 위치 + 연습/실제 안내를 한 번 띄움
                    if state.get("pending_onboarding"):
                        state["pending_onboarding"] = False
                        show_onboarding()
                except Exception as ex:
                    log(f"[경고] 설정창 오류: {ex}")
            if not state["paused"]:
                try:
                    fp, base = file_queue.get(timeout=0.3)
                    sort_file(fp, base)
                except queue.Empty:
                    pass
            else:
                time.sleep(0.3)
            if tk_root is not None:
                try:
                    tk_root.update()
                except Exception:
                    pass
    except KeyboardInterrupt:
        pass
    finally:
        log("종료합니다.")
        observer.stop()
        observer.join()


if __name__ == "__main__":
    main()
