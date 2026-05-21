#!/usr/bin/env python
# coding: utf-8

import os
import json
import random
import streamlit as st
from openai import OpenAI
import base64
from pathlib import Path
from datetime import datetime
import math
import re
import time
import csv
import queue
import threading
import streamlit.components.v1 as components
import pandas as pd
# 1) Import streamlit_analytics2
import streamlit_analytics2 as streamlit_analytics
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from streamlit_javascript import st_javascript
import json
import webbrowser


# if the user continue to interact, we remind them that they should continue to finish the study
# put the ads above
# instructions must stay at least 30 seconds
# ====== Completion link（可放到环境变量或 secrets）======
def get_completion_url():
    try:
        return st.secrets.get("COMPLETION_URL", None) or os.getenv(
            "COMPLETION_URL") or "https://app.prolific.com/submissions/complete?cc=CIR2NCAF"
    except Exception:
        return os.getenv("COMPLETION_URL") or "https://app.prolific.com/submissions/complete?cc=CIR2NCAF"


# ====== 实验阶段机位：'pid' -> 'instructions' -> 'experiment' -> 'survey' ======
st.session_state.setdefault("stage", "pid")  # 初始阶段：填写 Prolific ID


# 先不分配 variant，等点 Next 再分；如果你希望一进来就分配，移动到这里也行

def get_credentials_from_secrets():
    # 还原成 dict
    creds_dict = {key: value for key, value in st.secrets["GOOGLE_CREDENTIALS"].items()}
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    return creds_dict


DEFAULT_SPREADSHEET_AI_ADS = "Querya Earbuds AI Ads EXP8"
DEFAULT_SPREADSHEET_AI_ADS_FREE = "Querya Earbuds AI Ads Free EXP8"
GSHEET_ROW_FIELDS = ["id", "start", "variant", "timestamp", "type", "title", "url"]


def _resolve_spreadsheet_handle(client, *, variant=None):
    """Return a gspread Spreadsheet handle for the current earbuds AI condition."""
    v = variant if variant is not None else st.session_state.get("variant", None)
    v = str(v or "1")

    try:
        id_ads = st.secrets.get("GSHEET_ID_AI_ADS_EXP8", None)
        id_ads_free = st.secrets.get("GSHEET_ID_AI_ADS_FREE_EXP8", None)
        name_ads = st.secrets.get("GSHEET_NAME_AI_ADS_EXP8", None)
        name_ads_free = st.secrets.get("GSHEET_NAME_AI_ADS_FREE_EXP8", None)
    except Exception:
        id_ads = id_ads_free = None
        name_ads = name_ads_free = None

    id_ads = id_ads or os.getenv("GSHEET_ID_AI_ADS_EXP8")
    id_ads_free = id_ads_free or os.getenv("GSHEET_ID_AI_ADS_FREE_EXP8")

    name_ads = name_ads or os.getenv("GSHEET_NAME_AI_ADS_EXP8") or DEFAULT_SPREADSHEET_AI_ADS
    name_ads_free = name_ads_free or os.getenv("GSHEET_NAME_AI_ADS_FREE_EXP8") or DEFAULT_SPREADSHEET_AI_ADS_FREE

    ids = {"1": id_ads, "2": id_ads_free}
    names = {"1": name_ads, "2": name_ads_free}

    if ids.get(v):
        return client.open_by_key(ids[v])
    return client.open(names.get(v, name_ads))


def _gsheet_runtime_config() -> dict:
    """Collect Google Sheets routing while still on the Streamlit script thread."""
    try:
        id_ads = st.secrets.get("GSHEET_ID_AI_ADS_EXP8", None)
        id_ads_free = st.secrets.get("GSHEET_ID_AI_ADS_FREE_EXP8", None)
        name_ads = st.secrets.get("GSHEET_NAME_AI_ADS_EXP8", None)
        name_ads_free = st.secrets.get("GSHEET_NAME_AI_ADS_FREE_EXP8", None)
    except Exception:
        id_ads = id_ads_free = None
        name_ads = name_ads_free = None

    return {
        "ids": {
            "1": id_ads or os.getenv("GSHEET_ID_AI_ADS_EXP8"),
            "2": id_ads_free or os.getenv("GSHEET_ID_AI_ADS_FREE_EXP8"),
        },
        "names": {
            "1": name_ads or os.getenv("GSHEET_NAME_AI_ADS_EXP8") or DEFAULT_SPREADSHEET_AI_ADS,
            "2": name_ads_free or os.getenv("GSHEET_NAME_AI_ADS_FREE_EXP8") or DEFAULT_SPREADSHEET_AI_ADS_FREE,
        },
    }


def _normalize_gsheet_data(data: dict) -> dict:
    row = dict(data)
    row.setdefault("variant", st.session_state.get("variant", ""))
    row.setdefault("id", st.session_state.get("prolific_id", "unknown"))
    row.setdefault("start", st.session_state.get("start_time", datetime.now().isoformat()))
    row.setdefault("timestamp", datetime.now().isoformat())
    row.setdefault("url", " ")
    return row


class _GSheetWriter:
    def __init__(self, creds_dict: dict | None, sheet_config: dict, init_error: str = ""):
        self.creds_dict = creds_dict
        self.sheet_config = sheet_config
        self.init_error = init_error
        self._client = None
        self._sheets = {}
        self._cache_lock = threading.Lock()
        self._queue = queue.Queue(maxsize=1000)
        self._worker_lock = threading.Lock()
        self._worker_started = False
        self.last_error = ""

    def enqueue(self, row: dict) -> bool:
        self._ensure_worker()
        try:
            self._queue.put_nowait(dict(row))
            return True
        except queue.Full:
            self.last_error = "Google Sheets logging queue is full."
            return False

    def write_sync(self, row: dict, *, attempts: int = 3) -> bool:
        return self._write_with_retries(dict(row), attempts=attempts)

    def _ensure_worker(self):
        with self._worker_lock:
            if self._worker_started:
                return
            worker = threading.Thread(
                target=self._worker_loop,
                name="querya-gsheet-log-worker",
                daemon=True,
            )
            worker.start()
            self._worker_started = True

    def _worker_loop(self):
        while True:
            row = self._queue.get()
            try:
                self._write_with_retries(row, attempts=5)
            finally:
                self._queue.task_done()

    def _write_with_retries(self, row: dict, *, attempts: int) -> bool:
        for attempt in range(attempts):
            try:
                self._write_once(row)
                self.last_error = ""
                return True
            except Exception as e:
                self.last_error = str(e)
                if attempt < attempts - 1:
                    time.sleep(min(0.25 * (2 ** attempt), 2.0) + random.uniform(0, 0.15))
        return False

    def _write_once(self, row: dict):
        if self.init_error:
            raise RuntimeError(self.init_error)
        if not self.creds_dict:
            raise RuntimeError("Google credentials are not configured.")

        sheet = self._get_sheet(str(row.get("variant") or "1"))
        sheet.append_row(
            [row.get(k, "") for k in GSHEET_ROW_FIELDS],
            value_input_option="USER_ENTERED",
        )

    def _get_client(self):
        with self._cache_lock:
            if self._client is None:
                creds = ServiceAccountCredentials.from_json_keyfile_dict(
                    self.creds_dict,
                    scopes=[
                        "https://www.googleapis.com/auth/spreadsheets",
                        "https://www.googleapis.com/auth/drive",
                    ],
                )
                self._client = gspread.authorize(creds)
            return self._client

    def _get_sheet(self, variant: str):
        variant = variant if variant in ("1", "2") else "1"
        with self._cache_lock:
            if variant in self._sheets:
                return self._sheets[variant]

        client = self._get_client()
        sheet_id = self.sheet_config["ids"].get(variant)
        sheet_name = self.sheet_config["names"].get(variant) or DEFAULT_SPREADSHEET_AI_ADS
        spreadsheet = client.open_by_key(sheet_id) if sheet_id else client.open(sheet_name)
        sheet = spreadsheet.sheet1

        with self._cache_lock:
            self._sheets[variant] = sheet
        return sheet


@st.cache_resource(show_spinner=False)
def _get_gsheet_writer() -> _GSheetWriter:
    sheet_config = _gsheet_runtime_config()
    try:
        creds_dict = get_credentials_from_secrets()
        init_error = ""
    except Exception as e:
        creds_dict = None
        init_error = str(e)
    return _GSheetWriter(creds_dict, sheet_config, init_error=init_error)


def save_to_gsheet(data) -> bool:
    """Queue normal interaction logs without blocking the participant UI."""
    row = _normalize_gsheet_data(data)
    writer = _get_gsheet_writer()
    ok = writer.enqueue(row)
    if not ok:
        try:
            st.session_state["_gsheet_last_error"] = writer.last_error
        except Exception:
            pass
    return ok


def save_survey_to_gsheet(data) -> bool:
    """Synchronously save final survey rows; completion must wait for this."""
    row = _normalize_gsheet_data(data)
    writer = _get_gsheet_writer()
    ok = writer.write_sync(row, attempts=3)
    if not ok:
        try:
            st.session_state["_gsheet_last_error"] = writer.last_error
        except Exception:
            pass
    return ok


def log_event(event_type: str, title: str, url: str = " ") -> bool:
    return save_to_gsheet({
        "id": st.session_state.get("prolific_id", "unknown"),
        "start": st.session_state.get("start_time", datetime.now().isoformat()),
        "timestamp": datetime.now().isoformat(),
        "type": event_type,
        "title": title,
        "url": url,
    })


# def save_to_gsheet(data) -> bool:
#     # 自动注入 variant（如果还没分配，就留空字符串）
#     data = dict(data)
#     data.setdefault("variant", st.session_state.get("variant", ""))
#
#     creds = ServiceAccountCredentials.from_json_keyfile_dict(
#         get_credentials_from_secrets(),
#         scopes=[
#             "https://www.googleapis.com/auth/spreadsheets",
#             "https://www.googleapis.com/auth/drive"
#         ]
#     )
#     client = gspread.authorize(creds)
#     last_err = None
#     for i in range(3):
#         try:
#             sheet = client.open("Querya EXP4").sheet1
#             # 新顺序：id, start, variant, timestamp, type, title, url
#             sheet.append_row([data.get(k, "") for k in ["id", "start", "variant", "timestamp", "type", "title", "url"]])
#             return True
#         except Exception as e:
#             last_err = e
#             time.sleep(0.5)
#     # keep the latest error for debugging (optional)
#     try:
#         st.session_state["_gsheet_last_error"] = str(last_err) if last_err else ""
#     except Exception:
#         pass
#     return False


# simple in‑memory router
st.session_state.setdefault("page", "main")  # "main" | "product"
st.session_state.setdefault("current_product", {})  # dict of the product being viewed

st.session_state.setdefault("favorites", {})


# ===== Variant assignment (stable) =====
# We occasionally observed condition "flips" (AI <-> Search) if the Streamlit session refreshes
# or reconnects. To make the condition robust, we:
#   1) allow a URL query-param override (cond / variant / v),
#   2) freeze the first assigned variant in-session (_variant_fixed),
#   3) (best effort) persist it to the URL as ?cond=1/2 so a hard refresh keeps the same condition.

def _get_query_params_dict() -> dict:
    """Return query params as dict[str, list[str]] across Streamlit versions."""
    try:
        qp = st.query_params  # Streamlit >= 1.30
        d = {}
        for k, v in qp.items():
            if isinstance(v, list):
                d[k] = v
            else:
                d[k] = [v]
        return d
    except Exception:
        try:
            return st.experimental_get_query_params()
        except Exception:
            return {}


def _set_query_params_dict(d: dict):
    """Best-effort setter that preserves existing params."""
    try:
        # Legacy API (also works in many current versions)
        kwargs = {}
        for k, v in (d or {}).items():
            if isinstance(v, list):
                kwargs[k] = v if len(v) != 1 else v[0]
            else:
                kwargs[k] = v
        st.experimental_set_query_params(**kwargs)
        return
    except Exception:
        # New API fallback
        try:
            for k in list(st.query_params.keys()):
                del st.query_params[k]
            for k, v in (d or {}).items():
                if isinstance(v, list) and len(v) == 1:
                    st.query_params[k] = v[0]
                else:
                    st.query_params[k] = v
        except Exception:
            pass


def ensure_variant_stable():
    qp = _get_query_params_dict()

    # 1) Query-param override (or persistence across refresh)
    v_param = None
    for k in ("cond", "variant", "v"):
        if k in qp and qp[k]:
            v_param = str(qp[k][0]).strip()
            break
    desired = int(v_param) if v_param in ("1", "2") else None

    if desired is not None:
        st.session_state["variant"] = desired
        st.session_state["_variant_fixed"] = desired
        return

    # 2) Freeze within the session to prevent accidental flips
    if "_variant_fixed" in st.session_state:
        try:
            fixed = int(st.session_state["_variant_fixed"])
        except Exception:
            fixed = None
        if fixed in (1, 2):
            st.session_state["variant"] = fixed
            return
        st.session_state.pop("_variant_fixed", None)

    # 3) First time in this session: assign once
    try:
        current_variant = int(st.session_state.get("variant"))
    except Exception:
        current_variant = None
    if current_variant not in (1, 2):
        st.session_state["variant"] = random.randint(1, 2)

    try:
        st.session_state["_variant_fixed"] = int(st.session_state["variant"])
    except Exception:
        st.session_state["_variant_fixed"] = st.session_state["variant"]

    # 4) Best-effort persistence to URL (keeps condition stable across hard refresh/new session)
    if "cond" not in qp:
        qp["cond"] = [str(st.session_state["_variant_fixed"])]
        _set_query_params_dict(qp)


if "completed" not in st.session_state:
    st.session_state.completed = False
############################################
# Step 0: Page config & DeepSeek client
############################################
st.set_page_config(page_title="🛒 Querya", layout="wide")

API_KEY = os.getenv(
    "DEEPSEEK_API_KEY") or "sk-ce6eb3e9045c4110862945af28f4794e"  # st.secrets.get("DEEPSEEK_API_KEY", None) or os.getenv("DEEPSEEK_API_KEY")
client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com/v1")

# Record the app's start time if not set
if "start_time" not in st.session_state:
    st.session_state.start_time = datetime.now().isoformat()

############################################
# 1) Custom CSS to style all st.buttons like links
############################################
st.markdown(
    """
    <style>
      /* prominent Back button */
      div.stButton > button[title="back"] {
        background:  #ffb703 !important;   /* amber */
        color:       #000     !important;
        padding:     20px 50px !important; /* taller & wider */
        font-size:   30px      !important; /* BIGGER text   */
        font-weight: 900       !important;
        border:      none      !important;
        border-radius: 8px     !important;
        text-decoration: none  !important;
        width: 100%;                       /* full column width */
      }
      div.stButton > button[title="back"]:hover {
        background: #ffa400 !important;    /* darker on hover */
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- Hide Streamlit's default toolbar & icons (top-right corner) ---
HIDE_STREAMLIT_STYLE = """
<style>
/* Hide the hamburger menu, deploy/share/star buttons, fullscreen icon */
#MainMenu {visibility: hidden;}
header [data-testid="stToolbarActions"] {display: none !important;}
header [data-testid="stToolbar"] {display: none !important;}
footer {visibility: hidden;}
</style>
"""
st.markdown(HIDE_STREAMLIT_STYLE, unsafe_allow_html=True)

LINK_BUTTON_CSS = """
<style>
/* Turn all Streamlit buttons into link-style text */
div.stButton > button {
    background: none!important;
    color: #0645AD!important;
    border: none!important;
    padding: 0!important;
    font-size: 16px!important;
    text-decoration: underline!important;
    cursor: pointer!important;
}
div.stButton > button:hover {
    color: #0366d6!important;
}
</style>
"""
st.markdown(LINK_BUTTON_CSS, unsafe_allow_html=True)

# --- pill-like chip buttons for suggested prompts ---
SUGGESTION_CHIPS_CSS = """
<style>
div.stButton > button[title="chip"]{
    background:#f6f8fa !important;
    border:1px solid #d0d7de !important;
    border-radius:9999px !important;
    padding:6px 12px !important;
    margin:4px 6px 0 0 !important;
    font-size:14px !important;
    color:#111 !important;
    text-decoration:none !important;
    cursor:pointer !important;
}
div.stButton > button[title="chip"]:hover{
    background:#eef2f6 !important;
}
</style>
"""
st.markdown(SUGGESTION_CHIPS_CSS, unsafe_allow_html=True)

SURVEY_FONTS_CSS = """
<style>
/* Make radio/select labels & options match body size */
div[data-testid="stRadio"] label,
div[data-testid="stRadio"] div[role="radiogroup"] label span,
div[data-testid="stSelectbox"] label,
div[data-testid="stSelectbox"] div[role="combobox"],
div[data-testid="stSelectbox"] div[role="listbox"] * {
    font-size: 1rem !important;
    line-height: 1.35 !important;
}
</style>
"""
st.markdown(SURVEY_FONTS_CSS, unsafe_allow_html=True)

SPEC_TABLE_CSS = """
<style>
.table-specs { width:100%; border-collapse:collapse; }
.table-specs th, .table-specs td { padding:6px 8px; vertical-align:top; }
.table-specs th { width:38%; color:#555; font-weight:600; }
.table-specs tr { border-bottom:1px solid rgba(0,0,0,0.06); } /* faint lines */
</style>
"""
st.markdown(SPEC_TABLE_CSS, unsafe_allow_html=True)

st.markdown(
    """
    <style>
      /* 1️⃣  Peach border *and* a bit of breathing room */
      div:has(> #ad-box-anchor) {
        border: 1px solid #FEE9DF !important;   /* peach border        */
        border-radius: 6px;
        padding: 14px !important;               /* so the content
                                                  doesn’t cover border */
      }
      /* 1‑b  Make sure Streamlit columns inside are transparent */
      div:has(> #ad-box-anchor) [data-testid="column"] {
        background: transparent !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


############################################
# 2) Regex-based parser for [Title](URL) links in LLM text
############################################
# ===== Desktop-only gate (robust) =====
# ========= Desktop-only: detection + gating + debug =========

def enforce_desktop_only_frontend(*, strict_width: int | None = None,
                                  allow_param: str = "force_desktop",
                                  show_debug_probe: bool = False):
    """
    Blocks touch-first devices with a clean overlay (phones & tablets), without any JS bridge.
    - Uses input-modality media queries: (hover: none) and (pointer: coarse)
    - Also uses an iOS-only feature test to catch iPad that spoofs desktop UA
    - strict_width: optional extra rule (e.g., 820) if you want to also block very narrow viewports
    - allow_param: add ?force_desktop=1 to URL to bypass the overlay for debugging
    - show_debug_probe: show a tiny inline probe (UA + media queries) for quick verification
    """
    # Optional bypass via query param (for your own debugging)
    try:
        q = st.query_params  # Streamlit >= 1.30
    except Exception:
        q = st.experimental_get_query_params()
    bypass = False
    try:
        bypass = str(q.get(allow_param, ["0"])[0]) in ("1", "true", "True")
    except Exception:
        pass

    extra_width_rule = ""
    if strict_width:
        # Adds an extra guard based on viewport width if you *want* it
        extra_width_rule = f"""
        @media (max-width: {strict_width}px) {{
          #desktop_gate_overlay {{ display: flex !important; }}
        }}
        """

    # Core overlay (white background, high contrast; pinned on top)
    css = f"""
    <style>
    /* hidden by default; shown by modality queries below */
    #desktop_gate_overlay {{
      display: none;
      position: fixed; inset: 0; z-index: 2147483647;
      background: #fff; color: #111;
      align-items: center; justify-content: center;
      padding: 32px;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
    }}
    #desktop_gate_overlay .box {{ max-width: 760px; }}
    #desktop_gate_overlay h1 {{ margin: 0 0 12px 0; font-size: 1.6rem; }}
    #desktop_gate_overlay p  {{ margin: 0 0 8px 0; }}

    /* Touch-first devices: phones & tablets */
    @media (hover: none) and (pointer: coarse) {{
      #desktop_gate_overlay {{ display: flex; }}
    }}

    /* iOS only (iPhone/iPad Safari): feature combo nearly unique to iOS */
    @supports (-webkit-touch-callout: none) and (-webkit-overflow-scrolling: touch) {{
      #desktop_gate_overlay {{ display: flex !important; }}
    }}

    /* Optional extra: also block very narrow viewports if you choose */
    {extra_width_rule}

    /* If URL has ?{allow_param}=1, force-hide the overlay */
    {('#desktop_gate_overlay { display: none !important; }' if bypass else '')}
    </style>
    <div id="desktop_gate_overlay">
      <div class="box">
        <h1>Desktop/Laptop Required</h1>
        <p>Please use a <b>desktop or laptop</b> to access and complete this study.</p>
        <p>Now please open this link on a computer (Chrome / Edge / Firefox / Safari) and kindly return the study. Thank you!</p>
        <p><small>If you believe this is an error, add <code>?{allow_param}=1</code> to the URL to temporarily bypass for debugging.</small></p>
      </div>
    </div>
    """
    st.markdown(css, unsafe_allow_html=True)

    # Optional visual probe (doesn't return to Python; just shows what the browser reports)
    if show_debug_probe:
        import streamlit.components.v1 as components
        components.html("""
        <div style="font-family:system-ui,Arial; padding:8px; border:1px solid #ddd; margin-top:8px;">
          <div><b>UA</b>: <span id="ua"></span></div>
          <div><b>(hover: none)</b>: <span id="hov"></span></div>
          <div><b>(pointer: coarse)</b>: <span id="ptr"></span></div>
          <div><b>(any-pointer: coarse)</b>: <span id="aptr"></span></div>
          <div><b>iOS features</b>: <span id="ios"></span></div>
          <script>
            const mq = q => window.matchMedia ? window.matchMedia(q).matches : false;
            document.getElementById("ua").textContent  = navigator.userAgent;
            document.getElementById("hov").textContent = mq("(hover: none)");
            document.getElementById("ptr").textContent = mq("(pointer: coarse)");
            document.getElementById("aptr").textContent= mq("(any-pointer: coarse)");
            const ios = CSS && CSS.supports && CSS.supports("-webkit-touch-callout: none") && CSS.supports("-webkit-overflow-scrolling: touch");
            document.getElementById("ios").textContent = ios;
          </script>
        </div>
        """, height=150)


def _js_eval(expr: str, key: str):
    try:
        from streamlit_js_eval import streamlit_js_eval
    except Exception:
        return None
    try:
        # streamlit_js_eval caches by key; use stable keys for each expr
        return streamlit_js_eval(js_expressions=expr, key=key, timeout=0)
    except Exception:
        return None


def desktop_gate_via_js_eval(width_threshold: int = 900) -> tuple[bool, dict]:
    """
    Returns (block, info). Uses streamlit_js_eval to collect signals; no st_javascript needed.
    We DO NOT block a clear desktop OS only because the window is narrow.
    """
    ua = _js_eval("navigator.userAgent", "ua")
    w = _js_eval("Math.max(document.documentElement.clientWidth, window.innerWidth || 0)", "w")
    tp = _js_eval("navigator.maxTouchPoints || 0", "tp")
    any_coarse = _js_eval("window.matchMedia ? window.matchMedia('(any-pointer: coarse)').matches : false", "any")
    coarse = _js_eval("window.matchMedia ? window.matchMedia('(pointer: coarse)').matches : false", "coarse")
    hover_none = _js_eval("window.matchMedia ? window.matchMedia('(hover: none)').matches : false", "hovernone")
    ua_mobile = _js_eval("!!(navigator.userAgentData && navigator.userAgentData.mobile)", "uaDataMobile")

    info = {
        "ua": ua, "width": w, "touchPoints": tp,
        "anyCoarse": any_coarse, "pointerCoarse": coarse, "hoverNone": hover_none,
        "uaDataMobile": ua_mobile
    }

    if ua is None:
        # Bridge not available or blocked
        info["reasons"] = ["no-js-eval"]
        return (False, info)  # fall back to CSS method or let pass

    # Regexes evaluated in Python
    import re
    is_mobile_ua = bool(re.search(r"Mobile|Android|iP(hone|od)|Phone", ua or "", re.I))
    is_ipad_like = bool(re.search(r"iPad|Tablet", ua or "", re.I) or (
            re.search(r"Mac(Intel|intosh)", ua or "", re.I) and (tp or 0) > 0))
    desktop_os = bool(re.search(r"Windows NT|Macintosh|X11;|Linux x86_64|CrOS", ua or "", re.I))

    reasons = []
    if ua_mobile:  reasons.append("userAgentData.mobile")
    if is_mobile_ua: reasons.append("UA=mobile")
    if is_ipad_like: reasons.append("UA=tablet/iPad")
    if (not desktop_os) and (bool(any_coarse) or bool(hover_none) or bool(coarse)) and (
            w is not None and int(w) < width_threshold):
        reasons.append("touch+narrow")

    block = len(reasons) > 0
    info.update({
        "desktopOS": desktop_os,
        "isMobileUA": is_mobile_ua,
        "isIPadLike": is_ipad_like,
        "reasons": reasons,
        "provider": "streamlit_js_eval"
    })
    return (block, info)


def gate_desktop_only(width_threshold: int = 900):
    # Try JS-eval bridge first
    block, info = desktop_gate_via_js_eval(width_threshold=width_threshold)
    st.session_state["_device_info"] = info
    st.session_state["_is_mobile_like"] = block

    if block:
        # Log once
        if not st.session_state.get("_device_block_logged"):
            save_to_gsheet({
                "id": st.session_state.get("prolific_id", "unknown"),
                "start": st.session_state.get("start_time", datetime.now().isoformat()),
                "timestamp": datetime.now().isoformat(),
                "type": "device_block",
                "title": json.dumps(info, ensure_ascii=False),
                "url": " "
            })
            st.session_state["_device_block_logged"] = True

        st.title("Desktop/Laptop Required")
        st.error("For performance and consistency, this study must be completed on a **desktop or laptop**.")
        c1, c2 = st.columns([2, 1])
        with c1:
            st.markdown(
                "- Please open this link on a computer (Chrome / Edge / Firefox / Safari).\n"
                "- If you are on a phone/tablet, switch to a computer and re-open the same link.\n"
            )
            if st.button("Re-check"):
                # refresh the values
                st.session_state.pop("_device_info", None)
                st.session_state.pop("_is_mobile_like", None)
                st.rerun()
        with c2:
            st.caption("**Detected info (debug)**")
            st.json(info)
        st.stop()


def _js_device_gate_enabled() -> bool:
    """Keep the JS device probe opt-in; the CSS overlay handles the normal gate."""
    try:
        q = _get_query_params_dict()
        raw = q.get("js_device_gate", ["0"])[0]
        return str(raw).strip().lower() in ("1", "true", "yes")
    except Exception:
        return False


def get_variant_flags():
    """Return (variant, is_ai, with_ads, group_label) for the earbuds AI experiment."""
    v = st.session_state.get("variant", 1)
    try:
        v = int(v)
    except Exception:
        v = 1
    if v not in (1, 2):
        v = 1
    is_ai = True
    with_ads = True
    group_label = {
        1: "AI Assistant with Ads",
        2: "AI Assistant with Free-Service Ads Message",
    }.get(v, "AI Assistant")
    return v, is_ai, with_ads, group_label


def _build_instructions_md(is_ai: bool, with_ads: bool) -> str:
    if is_ai:
        body = (
            "Imagine you are shopping for a **fish oil supplement**. \n\n"
            "To help you decide which product to purchase, you will use an **AI chatbot** (“Querya”) to get some recommended products to consider. \n\n"
            " **Please follow these steps:**\n"
            "1. **Click the `Next / Start` button** below to open the AI chatbot.  \n"
            "2. **Ask for product recommendations.** For example, you might type:  \n"
            "   - “Can you recommend some fish oil supplements?”\n"
            "   - “Please recommend some fish oils.”\n"
            "You can also use any similar phrasing you would naturally use when chatting with an assistant.\n"
            "3. **Treat this task as if you were genuinely shopping for yourself.** \n "
            "Feel free to explore the recommended products by clicking their links and viewing them naturally, just as you would in real life.\n"
            "4. **If you’re interested in any product**, you may click the **`Add to Cart`** button at the top-right corner of its page.\n"
            "5. **When you’re done browsing**, close the AI chatbot by selecting **`Finish / End Session`** in the top-right corner of the conversation page.\n"
            "6. **Finally**, complete a short questionnaire about your experience."
        )
    else:
        body = (
            "Imagine you are shopping for a **fish oil supplement**. \n\n"
            "To help you decide which product to purchase, you will use a **search engine** (“Querya”) to find some recommended products.\n\n"
            " **Please follow these steps:**\n"
            "1. **Click the `Next / Start` button** below to open the search engine.  \n"
            "2. Enter keywords to get product recommendations. For example, you might type:  \n"
            "   - “Fish oil supplements”\n"
            "   - “Fish oils”\n"
            "Or use any other terms you would naturally type into a search engine.\n"
            "3. **Treat this task as if you were genuinely shopping for yourself.** \n "
            "Feel free to explore the recommended products by clicking their links and viewing them naturally, just as you would in real life.\n"
            "4. **If you’re interested in any product**, you may click the **`Add to Cart`** button at the top-right corner of its page.\n"
            "5. **When you’re done browsing**, close the search engine by selecting **`Finish / End Session`** in the top-right corner of the results page.\n"
            "6. **Finally**, complete a short questionnaire about your experience."
        )
    note = ""  # "\n\n> This condition may include **Sponsored** results." if with_ads else ""
    return f"### Instructions\n{body}{note}"


def instructions_button_inline():
    """Render an inline 'Instructions' button beside title."""
    _, is_ai, with_ads, _ = get_variant_flags()
    md = _build_instructions_md(is_ai, with_ads)

    # Prefer popover if available (Streamlit >= 1.31)
    if hasattr(st, "popover"):
        with st.popover("ℹ️ Instructions"):
            st.markdown(md)
    else:
        # Fallback: toggle an inline info box
        show = st.session_state.get("_show_instr_box", False)
        if st.button("ℹ️ Instructions"):
            st.session_state["_show_instr_box"] = not show
            st.rerun()
        if st.session_state.get("_show_instr_box", False):
            st.info(md)


def render_specs_table(specs: dict | None):
    if not specs:
        return
    rows = "\n".join(
        f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in specs.items()
    )
    st.markdown(f"<table class='table-specs'>{rows}</table>", unsafe_allow_html=True)


def parse_markdown_links(source):
    """
    Accepts either:
      • a raw markdown *string*      (LLM response, old behaviour), or
      • a *list of product dicts*    (new KEYWORD_RESPONSES format).

    Returns a flat list of segments:
       {"type": "text", "content": "..."}                # description paragraph
       {"type": "link", **product_dict}                  # product card
    """
    # ── Case A: list of product dicts ───────────────────────────
    if isinstance(source, list):
        segs = []
        for p in source:
            # 1) product‑link segment (keep all keys)
            seg = {"type": "link", **p}
            segs.append(seg)
            # 2) description as plain text segment
            if p.get("description"):
                segs.append({"type": "text", "content": p["description"]})
        return segs

    # ── Case B: regular markdown string ─────────────────────────
    text = str(source)
    pattern = r'\[([^\]]+)\]\(([^)]+)\)'
    segs, last_end = [], 0

    for m in re.finditer(pattern, text):
        start, end = m.span()
        if start > last_end:
            segs.append({"type": "text", "content": text[last_end:start]})

        label, url = m.group(1).strip(), m.group(2).strip()
        prod = PRODUCT_CATALOG.get(label)  # may be None
        seg = {"type": "link", "label": label, "url": url}
        if prod:
            seg.update(prod)  # enrich if in catalogue
            seg["product_url"] = url
        segs.append(seg)
        last_end = end

    if last_end < len(text):
        segs.append({"type": "text", "content": text[last_end:]})
    return segs


# Suggested prompts (you can edit/translate freely)
SUGGESTED_QUERIES_AI = [
    "Can you recommend some fish oil supplements?",
    "Please recommend some fish oils.",
    "Which fish oil do you recommend?",
    "Any fish oil recommendations?"
]

SUGGESTED_QUERIES_SEARCH = [
    "fish oils",
    "fish oil supplements",
    "Can you recommend some fish oil supplements?",
    "Please recommend some fish oils."
]


def render_suggestion_chips(queries: list[str], prefix: str) -> str | None:
    """Render chips in multiple columns; return the selected text or None."""
    if not queries:
        return None
    ncols = min(1, max(1, len(queries)))
    cols = st.columns(ncols)
    chosen = None
    for i, q in enumerate(queries):
        with cols[i % ncols]:
            if st.button(q, key=f"{prefix}_{i}", help="chip"):
                chosen = q
    return chosen


def display_parsed_markdown(source, link_type="organic"):
    """
    Splits 'text' into normal text vs. [Title](URL) links,
    then displays them with st.markdown for text,
    and record_link_click_and_open for links.
    """
    segments = parse_markdown_links(source)
    for seg in segments:
        if seg["type"] == "link":
            # show_product_item(seg, link_type="organic")

            show_product_item(seg, link_type=link_type, show_image=True, image_position='below')
        elif seg["type"] == "text":
            st.markdown(seg["content"])
        else:  # non‑product link
            st.markdown(f'[{seg["label"]}]({seg["url"]})')


def render_instructions_page():
    v, is_ai, with_ads, group_label = get_variant_flags()
    # st.title(f"Instructions — {group_label} condition")

    if is_ai:
        st.markdown("""
        ### 📝 Instructions

        Imagine you are shopping for a **fish oil supplement**.  
        To help you decide which product to purchase, you will use an **AI chatbot** (“Querya”) to get some recommended products to consider.

        ---

        **Please follow these steps:**

        1. **Click the `Next / Start` button** below to open the AI chatbot.  

        2. **Ask for product recommendations.** For example, you might type:  
           - “Can you recommend some fish oil supplements?”  
           - “Please recommend some fish oils.”  

           You can also use any similar phrasing you would naturally use when chatting with an assistant.

        3. **Treat this task as if you were genuinely shopping for yourself.**  
           Feel free to explore the recommended products by clicking their links and viewing them naturally, just as you would in real life.

        4. **If you’re interested in any product**, you may click the **`Add to Cart`** button at the top-right corner of its page.

        5. **When you’re done browsing**, close the AI chatbot by selecting **`Finish / End Session`** in the top-right corner of the conversation page.

        6. **Finally**, complete a short questionnaire about your experience.
        """)

    else:
        st.markdown("""
                ### 📝 Instructions

                Imagine you are shopping for a **fish oil supplement**.  
                To help you decide which product to purchase, you will use a **search engine** (“Querya”) to find some recommended products.
                **The Search Engine’s output will include advertisements (sponsored content).**

                ---

                **Please follow these steps:**

                1. **Click the `Next / Start` button** below to open the search engine.  

                2. Enter keywords to get product recommendations. For example, you might type:  
                   - “Fish oil supplements”  
                   - “Fish oils”  

                   Or use any other terms you would naturally type into a search engine.

                3. **Treat this task as if you were genuinely shopping for yourself.**  
                   Feel free to explore the recommended products by clicking the links and browsing naturally, just as you would in real life.

                4. **If you’re interested in a product**, you may click the **`Add to Cart`** button at the top-right corner of its page.

                5. **When you’re finished browsing**, close the search engine by selecting **`Finish / End Session`** in the top-right corner of the results page.

                6. **Finally**, complete a short questionnaire about your experience.
                """)

    # if with_ads:
    #     st.info("This condition **may include sponsored results** labeled “Sponsored”. Please browse naturally.")
    #
    # st.warning("Estimated time: about **2–3 minutes**. Please interact naturally as if you were shopping online.")
    # 30-second hold (auto-advance, no clicks)
    # ---- 30s 限制逻辑（不自动跳转；仅拦截 Next）----
    HOLD_SECONDS = 20
    if "instructions_start_ts" not in st.session_state:
        st.session_state.instructions_start_ts = time.time()

    elapsed = int(time.time() - st.session_state.instructions_start_ts)
    remaining = max(0, HOLD_SECONDS - elapsed)

    # 友好提示剩余时间（无需自动刷新）
    st.caption(f"Minimum reading time: {HOLD_SECONDS}s ")  # · Time elapsed: {elapsed}s · Remaining: {remaining}s

    # Next 按钮：30s 内点击 → 拦截并提示；30s 后点击 → 放行
    next_clicked = st.button("Next")
    if next_clicked:
        if remaining > 0:
            st.error(f"Please read the instructions for at least 20 seconds before proceeding. "
                     f"{remaining}s remaining.")
            # 记录过早点击
            save_to_gsheet({
                "id": st.session_state.get("prolific_id", "unknown"),
                "start": st.session_state.get("start_time", datetime.now().isoformat()),
                "timestamp": datetime.now().isoformat(),
                "type": "instructions_next_too_early",
                "title": f"{group_label} | ads={with_ads} | remaining={remaining}s",
                "url": " "
            })
            return  # 留在说明页
        else:
            # 通过，进入实验并记录
            save_to_gsheet({
                "id": st.session_state.get("prolific_id", "unknown"),
                "start": st.session_state.get("start_time", datetime.now().isoformat()),
                "timestamp": datetime.now().isoformat(),
                "type": "enter_experiment",
                "title": f"{group_label} | ads={with_ads}",
                "url": " "
            })
            st.session_state.stage = "experiment"
            st.rerun()


def render_final_survey_page():
    # ---- Already submitted? Show completed state and block all inputs ----
    if st.session_state.get("survey_locked"):
        st.title("Final Survey — Completed")
        st.success("Thanks! Your responses have already been submitted.")
        target = st.session_state.get("completion_url") or get_completion_url()
        try:
            st.link_button("Open the completion page", target)
        except Exception:
            st.markdown(f"[Open the completion page]({target})")
        st.caption("You can now close this tab.")
        st.stop()

    # ---- determine condition ----
    v, is_ai, with_ads, group_label = get_variant_flags()

    # Three-page survey state
    st.session_state.setdefault("survey_step", 1)  # 1, 2, or 3

    # Basic nouns
    PLATFORM_NOUN = "AI chatbot platform" if is_ai else "search engine platform"
    SYS_NOUN = "AI chatbot" if is_ai else "search engine"
    SYS_PLURAL = "AI chatbots" if is_ai else "search engines"

    st.title("Final Survey")

    # --- small CSS to keep radios compact ---
    st.markdown(
        """
        <style>
        div[data-testid="stRadio"] > div { gap: 0.5rem !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ---------- helpers ----------
    def is_blank(x) -> bool:
        # NOTE: An empty list (e.g., multiselect with no options chosen) is a valid answer.
        return x is None or (isinstance(x, str) and x.strip() == "")

    def likert7(question: str, key: str, left_anchor: str | None = None, right_anchor: str | None = None) -> int | None:
        """Single 7-point item. If anchors are provided, show them inline; otherwise show only the question."""
        if left_anchor is not None and right_anchor is not None:
            st.markdown(f"**{question} (1 = {left_anchor}, 7 = {right_anchor})**")
        else:
            st.markdown(f"**{question}**")
        val = st.radio(
            "",
            options=[1, 2, 3, 4, 5, 6, 7],
            horizontal=True,
            index=None,
            key=key,
            label_visibility="collapsed",
        )
        st.markdown("<div style='height:0.25rem;'></div>", unsafe_allow_html=True)
        return val

    def matrix_block(stem: str, items: list[tuple[str, str]], keyprefix: str,
                     *, left_anchor: str, right_anchor: str) -> dict:
        """Stem once, then each item as a row with a 1–7 radio."""
        st.markdown(f"**{stem}**")
        results = {}
        for k, q in items:
            st.markdown(f"**{q}**")
            results[k] = st.radio(
                "",
                options=[1, 2, 3, 4, 5, 6, 7],
                horizontal=True,
                index=None,
                key=f"{keyprefix}_{k}",
                label_visibility="collapsed",
            )
        st.markdown("---")
        return results

    def matrix_block_simple(stem_lines: list[str], items: list[tuple[str, str]], keyprefix: str,
                            *, left_anchor: str, right_anchor: str) -> dict:
        """Same as matrix_block but supports multiple stem lines (e.g., an extra 'I feel:' line)."""
        for line in stem_lines:
            st.markdown(f"**{line}**")
        results = {}
        for k, q in items:
            st.markdown(f"**{q}**")
            results[k] = st.radio(
                "",
                options=[1, 2, 3, 4, 5, 6, 7],
                horizontal=True,
                index=None,
                key=f"{keyprefix}_{k}",
                label_visibility="collapsed",
            )
        st.markdown("---")
        return results

    # =======================
    # Page 1 / 3
    # =======================
    if st.session_state.get("survey_step", 1) == 1:
        # Prominent instruction
        if is_ai:
            st.info(
                "First, we would like to know your perceptions of interacting with this AI chatbot platform. "
                "Please respond to the following questions."
            )
            # st.markdown("**The AI chatbot’s output will include advertisements (sponsored content).**")
        else:
            st.info(
                "First, we would like to know your perceptions of interacting with this search engine platform. "
                "Please respond to the following questions."
            )
            # st.markdown("**The Search Engine’s output will include advertisements (sponsored content).**")

        with st.form("final_survey_page1"):
            st.markdown("Please complete **all** questions on this page. There is no default selection.")

            # 1) Perceived Platform Objectivity
            obj_items = [
                ("obj1", "Objective"),
                ("obj2", "Neutral"),
                ("obj3", "Unbiased"),
                ("obj4", "Impartial"),
            ]
            obj = matrix_block(
                stem=f"How do you perceive this {PLATFORM_NOUN}, given that its responses include advertisements (sponsored content)? (1 = not at all, 7 = very much)",
                items=obj_items,
                keyprefix="p1_obj",
                left_anchor="not at all",
                right_anchor="very much",
            )

            # 2) Perceived Platform Credibility
            cred_items = [
                ("cred1", "Credible"),
                ("cred2", "Reliable"),
                ("cred3", "Believable"),
                ("cred4", "Well-intentioned"),
                ("cred5", "Having users’ best interests at heart"),
            ]
            cred = matrix_block(
                stem=f"How do you perceive this {PLATFORM_NOUN}, given that its responses include advertisements (sponsored content)? (1 = not at all, 7 = very much)",
                items=cred_items,
                keyprefix="p1_cred",
                left_anchor="not at all",
                right_anchor="very much",
            )

            # 3) Expectation Violation
            ev_items = [
                ("ev1",
                 f"The advertisements in this interaction with the {SYS_NOUN} did not fit what I expect from this kind of system."),
                ("ev2", f"The advertisements in this interaction with the {SYS_NOUN} felt inappropriate."),
                ("ev3",
                 f"The advertisements in this interaction with the {SYS_NOUN} violated my expectations for how this kind of interaction should go."),
            ]
            ev = matrix_block(
                stem=f"Thinking about how the {SYS_NOUN} behaved during this interaction, please indicate the extent to which you agree with the following statements: (1 = strongly disagree, 7 = strongly agree)",
                items=ev_items,
                keyprefix="p1_ev",
                left_anchor="strongly disagree",
                right_anchor="strongly agree",
            )

            # 4) Emotional Aversion Toward the Platform
            emo_items = [
                ("emo1", f"The advertisements in this interaction with the {SYS_NOUN} made me feel uncomfortable."),
                ("emo2", f"The advertisements in this interaction with the {SYS_NOUN} made me feel uneasy."),
                ("emo3", f"The advertisements in this interaction with the {SYS_NOUN} made me feel irritated."),
                ("emo4", f"The advertisements in this interaction with the {SYS_NOUN} made me feel disturbed."),
            ]
            emo = matrix_block_simple(
                stem_lines=[
                    f"Thinking about your interaction with this {PLATFORM_NOUN}, please indicate the extent to which you agree with the following statements: (1 = strongly disagree, 7 = strongly agree)",
                ],
                items=emo_items,
                keyprefix="p1_emo",
                left_anchor="strongly disagree",
                right_anchor="strongly agree",
            )

            # 5) Perceived Intrusiveness
            intr_items = [
                ("intr1", f"The advertisements in this interaction with the {SYS_NOUN} felt distracting."),
                ("intr2", f"The advertisements in this interaction with the {SYS_NOUN} felt intrusive."),
                ("intr3", f"The advertisements in this interaction with the {SYS_NOUN} felt invasive."),
            ]
            intr = matrix_block(
                stem=f"How do you perceive your interaction with this {SYS_NOUN}? Please indicate the extent to which you agree with the following statements: (1 = strongly disagree, 7 = strongly agree)",
                items=intr_items,
                keyprefix="p1_intr",
                left_anchor="strongly disagree",
                right_anchor="strongly agree",
            )

            # 6) Privacy Concern
            priv_items = [
                ("priv1", f"I am concerned that this {SYS_NOUN} collects too much personal information about me."),
                ("priv2",
                 f"I worry that this {SYS_NOUN} may use my personal information for purposes I have not authorized."),
                ("priv3",
                 f"I feel uneasy that this {SYS_NOUN} may share my personal information with others without my authorization."),
                ("priv4",
                 f"I am concerned that my personal information may not be securely protected from unauthorized access when using this {SYS_NOUN}."),
            ]
            priv = matrix_block(
                stem="Please indicate the extent to which you agree with the following statements: (1 = strongly disagree, 7 = strongly agree)",
                items=priv_items,
                keyprefix="p1_priv",
                left_anchor="strongly disagree",
                right_anchor="strongly agree",
            )

            next_clicked = st.form_submit_button("Next")

        if next_clicked:
            # Validate: all page-1 items must be answered
            all_vals = (
                    list(obj.values())
                    + list(cred.values())
                    + list(ev.values())
                    + list(emo.values())
                    + list(intr.values())
                    + list(priv.values())
            )
            if any(is_blank(v) for v in all_vals):
                st.error("Please complete all questions on this page before proceeding.")
                return

            # Store page 1 answers (for clean final export)
            st.session_state["survey_page1"] = {
                "platform_objectivity": obj,
                "platform_credibility": cred,
                "expectation_violation": ev,
                "emotional_aversion": emo,
                "perceived_intrusiveness": intr,
                "privacy_concern": priv,
            }

            st.session_state["survey_step"] = 2
            st.rerun()

        return

    # =======================
    # Page 2 / 3
    # =======================
    if st.session_state.get("survey_step", 1) == 2:
        # Safety: if someone lands here without Page 1 stored (e.g., refresh edge-case), send them back.
        if "survey_page1" not in st.session_state:
            st.session_state["survey_step"] = 1
            st.rerun()

        # Prominent instruction
        if is_ai:
            st.info(
                "Next, we would like to know your general perceptions of AI chatbots. "
                "Please answer the following questions."
            )
            # st.markdown("**The AI chatbot’s output will include advertisements (sponsored content).**")
        else:
            st.info(
                "Next, we would like to know your general perceptions of search engines. "
                "Please answer the following questions."
            )
            # st.markdown("**The Search Engine’s output will include advertisements (sponsored content).**")

        with st.form("final_survey_page2"):
            st.markdown("Please complete **all** questions on this page. There is no default selection.")

            # 1) Perceived Autonomous Agency
            agency_items = [
                ("aa1", f"{('AI chatbots' if is_ai else 'Search engines')} act autonomously."),
                ("aa2",
                 f"{('AI chatbots' if is_ai else 'Search engines')} make their own decisions when generating responses."),
                ("aa3", f"{('AI chatbots' if is_ai else 'Search engines')} learn from interactions with users."),
                ("aa4", f"{('AI chatbots' if is_ai else 'Search engines')} adapt their responses based on experience."),
            ]
            agency = matrix_block(
                stem=f"How do you perceive {('AI chatbots' if is_ai else 'search engines')} overall? (1 = strongly disagree, 7 = strongly agree)",
                items=agency_items,
                keyprefix="p2_agency",
                left_anchor="strongly disagree",
                right_anchor="strongly agree",
            )

            # 2) Perceived Personal Relationship
            rel_items = [
                ("pr1",
                 f"I feel a sense of personal connection with {('AI chatbots' if is_ai else 'search engines')}."),
                ("pr2",
                 f"{('AI chatbots' if is_ai else 'Search engines')} feel more like a personal assistant than an impersonal tool."),
                ("pr3", f"I feel emotionally connected to {('AI chatbots' if is_ai else 'search engines')}."),
            ]
            rel = matrix_block(
                stem=f"How do you perceive your relationship with {('AI chatbots' if is_ai else 'search engines')} overall? Please indicate the extent to which you agree with the following statements: (1 = strongly disagree, 7 = strongly agree)",
                items=rel_items,
                keyprefix="p2_rel",
                left_anchor="strongly disagree",
                right_anchor="strongly agree",
            )

            # 3) Perceived Communal–Exchange Orientation (semantic differential)
            ce_items = [
                ("ce1", "Communal ⟷ Commercial"),
                ("ce2", "Relationship-based ⟷ Transaction-based"),
                ("ce3", "Helping-oriented ⟷ Profit-oriented"),
                ("ce4", "Care-focused ⟷ Exchange-focused"),
            ]
            ce = matrix_block(
                stem=f"Thinking about {('AI chatbots' if is_ai else 'search engines')} overall, how would you characterize the nature of the relationship between users and {('AI chatbots' if is_ai else 'search engines')}? Please rate the relationship on the following scales: (1 = closer to the left description, 7 = closer to the right description)",
                items=ce_items,
                keyprefix="p2_ce",
                left_anchor="closer to the left description",
                right_anchor="closer to the right description",
            )

            next_clicked = st.form_submit_button("Next")

        if next_clicked:
            all_vals = list(agency.values()) + list(rel.values()) + list(ce.values())
            if any(is_blank(v) for v in all_vals):
                st.error("Please complete all questions on this page before proceeding.")
                return

            st.session_state["survey_page2"] = {
                "perceived_autonomous_agency": agency,
                "perceived_personal_relationship": rel,
                "perceived_communal_exchange_orientation": ce,
            }
            st.session_state["survey_step"] = 3
            st.rerun()

        return

    # =======================
    # Page 3 / 3
    # =======================
    # Safety: if someone lands here without Page 1/2 stored (e.g., refresh edge-case), send them back.
    if "survey_page1" not in st.session_state:
        st.session_state["survey_step"] = 1
        st.rerun()
    if "survey_page2" not in st.session_state:
        st.session_state["survey_step"] = 2
        st.rerun()

    # ------- form begins -------
    _form_holder = st.container()
    with _form_holder:
        with st.form("final_survey_page3"):
            st.markdown("Please complete **all** questions on this page. There is no default selection.")

            # ------ General Manipulation check ------
            st.markdown("**1. What did you use to seek recommended products in this study?**")
            mc_tool = st.radio(
                label="",
                options=["An AI chatbot", "A search engine"],
                index=None,
                key="p3_mc_tool",
                label_visibility="collapsed",
            )

            st.markdown(
                "**2. Did you see any “sponsored” products (i.e., advertisements) in the page presenting recommended products in this study?**"
            )
            mc_ads = st.radio(
                label="",
                options=["Yes", "No"],
                index=None,
                key="p3_mc_ads",
                label_visibility="collapsed",
            )
            st.markdown("---")

            # ------ Other checks (condition-specific wording) ------
            fish_fam = likert7(
                "How familiar are you with fish oil supplements overall?",
                key="p3_fish_fam",
                left_anchor="Not familiar at all",
                right_anchor="Very familiar",
            )

            sys_fam = likert7(
                f"How familiar are you with {('AI chatbots' if is_ai else 'search engines')} overall?",
                key="p3_sys_fam",
                left_anchor="Not familiar at all",
                right_anchor="Very familiar",
            )

            sys_att = likert7(
                f"What is your attitude toward {('AI chatbots' if is_ai else 'search engines')} overall?",
                key="p3_sys_att",
                left_anchor="Very negative",
                right_anchor="Very positive",
            )

            st.markdown(
                f"**In the past 7 days, on how many days did you use {('AI chatbots' if is_ai else 'search engines')}? 0 = 0 days; 1 = 1 day; 2 = 2 days; 3 = 3 days; 4 = 4 days; 5 = 5 days; 6 = 6 day; 7 = 7 days**"
            )
            days_used = st.radio(
                label="",
                options=[0, 1, 2, 3, 4, 5, 6, 7],
                index=None,
                horizontal=True,
                key="p3_days_used",
                label_visibility="collapsed",
            )
            st.markdown("<div style='height:0.25rem;'></div>", unsafe_allow_html=True)

            st.markdown(
                f"**In the past 30 days, which of the following ways have you used {('AI chatbots' if is_ai else 'search engines')}?**\n"
                "**Please check all that apply.**"
            )
            usage_options = [
                "Helping with work or school tasks",
                "Getting factual information or solving practical problems",
                "Drafting, editing, or summarizing written materials",
                "Planning travel, schedules, meals, or activities",
                "Comparing products or making purchase decisions",
                "Supporting hobbies or creative projects",
                "Thinking through personal situations or decisions",
                "Seeking comfort, advice, or encouragement",
                "Conversing for enjoyment or companionship",
            ]
            usage_30d = st.multiselect(
                label="",
                options=usage_options,
                default=[],
                key="p3_usage_30d",
                label_visibility="collapsed",
            )

            att_check = likert7(
                "Please select two",
                key="chk_att",
            )

            ads_exposure = likert7(
                f"How frequently have you been exposed to sponsored content (ads) in {('AI chatbot responses' if is_ai else 'search engine results')} in your daily life?",
                key="p3_ads_exposure",
                left_anchor="not at all frequently",
                right_anchor="very frequently",
            )

            st.markdown("---")

            # ------ Demographics ------
            st.markdown("**Your age:**")
            age_str = st.text_input(
                label="",
                value="",
                key="p3_demo_age",
                placeholder="Enter an integer between 18 and 99",
                label_visibility="collapsed",
            )

            st.markdown("**Your sex:**")
            sex = st.radio(
                label="",
                options=["Male", "Female"],
                index=None,
                key="p3_demo_sex",
                label_visibility="collapsed",
            )

            st.markdown("**Your educational background:**")
            edu = st.selectbox(
                label="",
                options=[
                    "Less than high school",
                    "High school graduate",
                    "Bachelor or equivalent",
                    "Master",
                    "Doctorate",
                ],
                index=None,
                placeholder="Select…",
                key="p3_demo_edu",
                label_visibility="collapsed",
            )

            st.markdown("**Your ethnicity:**")
            ethnicity = st.selectbox(
                label="",
                options=[
                    "White",
                    "Black or African American",
                    "American Indian or Alaska Native",
                    "Asian",
                    "Native Hawaiian or Pacific Islander",
                    "Other",
                ],
                index=None,
                placeholder="Select…",
                key="p3_demo_ethnicity",
                label_visibility="collapsed",
            )

            submitted = st.form_submit_button("Submit")

        # ---------- validation & submission ----------
        if submitted:
            # Extra safety: ensure Page 1 & 2 were fully completed
            p1 = st.session_state.get("survey_page1", {})
            p2 = st.session_state.get("survey_page2", {})

            def _vals_from_page(page_obj: dict) -> list:
                vals = []
                try:
                    for blk in (page_obj or {}).values():
                        if isinstance(blk, dict):
                            vals.extend(list(blk.values()))
                except Exception:
                    pass
                return vals

            p1_vals = _vals_from_page(p1)
            p2_vals = _vals_from_page(p2)

            if (not p1_vals) or any(is_blank(v) for v in p1_vals):
                st.error("It looks like some items on **Page 1** are missing. Please complete Page 1 first.")
                st.session_state["survey_step"] = 1
                st.rerun()

            if (not p2_vals) or any(is_blank(v) for v in p2_vals):
                st.error("It looks like some items on **Page 2** are missing. Please complete Page 2 first.")
                st.session_state["survey_step"] = 2
                st.rerun()

            # validate age
            age_val, age_err = None, None
            if is_blank(age_str):
                age_err = "Please enter your age."
            else:
                try:
                    age_val = int(str(age_str).strip())
                    if age_val < 18 or age_val > 99:
                        age_err = "Age must be between 18 and 99."
                except Exception:
                    age_err = "Age must be a whole number."

            required = {
                # Manipulation checks
                "mc_tool": mc_tool,
                "mc_ads": mc_ads,
                # Other checks
                "fish_familiarity": fish_fam,
                "system_familiarity": sys_fam,
                "system_attitude": sys_att,
                "days_used_past_7": days_used,
                "attention_check": att_check,
                "ads_exposure": ads_exposure,
                # Demographics
                "sex": sex,
                "education": edu,
                "ethnicity": ethnicity,
            }
            missing = [name for name, val in required.items() if is_blank(val)]

            if age_err or missing:
                if age_err:
                    st.error(age_err)
                if missing:
                    st.error("Please complete all required questions before submitting.")
                return

            # Assemble final answers
            answers = {
                "variant": st.session_state.get("variant"),
                "group": "AI" if is_ai else "Search",
                "with_ads": with_ads,
                "page1": st.session_state.get("survey_page1", {}),
                "page2": st.session_state.get("survey_page2", {}),
                "page3": {
                    "manipulation_check": {
                        "tool_used": mc_tool,
                        "saw_sponsored": mc_ads,
                    },
                    "other_checks": {
                        "fish_oil_familiarity": fish_fam,
                        "system_familiarity": sys_fam,
                        "system_attitude": sys_att,
                        "days_used_past_7": days_used,
                        "usage_30d": usage_30d,
                        "attention_check": att_check,
                        "ads_exposure_daily_life": ads_exposure,
                    },
                    "demographics": {
                        "age": age_val,
                        "sex": sex,
                        "education": edu,
                        "ethnicity": ethnicity,
                    },
                },
            }

            # ---- Save only once; then lock the survey ----
            if not st.session_state.get("survey_locked"):
                ok = save_to_gsheet({
                    "id": st.session_state.prolific_id,
                    "start": st.session_state.start_time,
                    "timestamp": datetime.now().isoformat(),
                    "type": "survey",
                    "title": "final_survey",
                    "url": json.dumps(answers, ensure_ascii=False),
                })
                if not ok:
                    st.error(
                        "We could not record your responses due to a temporary server/network error. "
                        "Please click **Submit** again. (Do not close this tab yet.)"
                    )
                    err_txt = st.session_state.get("_gsheet_last_error", "")
                    if err_txt:
                        st.caption(f"Debug info: {err_txt}")
                    return

            # Remember completion URL & lock the UI
            target = get_completion_url()
            st.session_state["survey_locked"] = True
            st.session_state["completion_url"] = target

            # Immediately remove the form from the page so nothing is clickable
            _form_holder.empty()

            st.success("Submitted. Please click below to complete:")

            try:
                if st.link_button("Please click here to complete", target):
                    st.session_state.completed = True
            except Exception:
                st.markdown(f"[Please click here to complete]({target})")

            st.stop()


def render_predefined_products(prod_list, heading, link_type="organic"):
    """Print heading once, then for each product: title ★ + description."""
    st.markdown(heading)
    for p in prod_list:
        show_product_item(p, link_type=link_type, show_image=False)
        if p.get("image_url"):
            st.markdown(
                f"<img src='{p['image_url']}' "
                f"style='display:block; margin:6px auto 0 auto; "
                f"width:120px; height:120px; object-fit:contain;'>",
                unsafe_allow_html=True,
            )
        if p.get("description"):
            st.markdown(p["description"])


############################################
# 3) Predefined replies
############################################


# ─── 🗂  Central catalogue (20 items) ─────────────────────────────
PRODUCT_CATALOG = {
    # ── Fish-oil group ──
    "Nordic Naturals Ultimate Omega": {
        "id": "fish_01",
        "title": "Nordic Naturals Ultimate Omega",
        "product_url": "https://www.amazon.com/Nordic-Naturals-Ultimate-Support-Healthy/dp/B002CQU564",
        "image_url": "https://m.media-amazon.com/images/I/61x5u8LMFWL._AC_SL1000_.jpg",
        "price": "$41.33",
        "specs": {
            "Brand": "Nordic Naturals",
            "Flavor": "Lemon",
            "Primary supplement type": "Omega-3",
            "Unit Count": "180 Count",
            "Item Form": "Softgel",
            "Item Weight": "0.69 lb"
        },
        "description": "- Features: High-concentration EPA/DHA (650 mg Omega-3 per soft-gel); IFOS 5-star certified; triglyceride (TG) form for superior absorption.\n- Ideal for: Cardiovascular health, anti-inflammatory needs, or anyone seeking a highly purified fish oil.",
        "page_description": "**About this item**\n- WHY OMEGA-3s – EPA & DHA support heart, brain, eye and immune health, and help maintain a healthy mood.\n- DOCTOR-RECOMMENDED dose meets American Heart Association guidelines for cardiovascular support.\n- BETTER ABSORPTION & TASTE – Triglyceride form with pleasant lemon flavor and zero fishy burps.\n- PURITY GUARANTEED – Wild-caught fish, non-GMO, gluten- & dairy-free with no artificial additives."
    },

    "WHC UnoCardio 1000": {
        "id": "fish_02",
        "title": "WHC UnoCardio 1000",
        "price": "$40.45",
        "specs": {
            "Brand": "WHC",
            "Flavor": "Natrual Orange",
            "Primary supplement type": "Omega-3",
            "Unit Count": "180 Count",
            "Item Form": "Softgel",
            "Item Weight": "16.8 ounces"
        },
        "product_url": "https://www.amazon.com/WHC-UnoCardio-Softgels-Triglyceride-concentration/dp/B00QFTGSK6",
        "image_url": "https://m.media-amazon.com/images/I/71htaA+bT9L._AC_SL1500_.jpg",
        "description": "- Features: Ranked No. 1 globally by IFOS; 1 000 mg Omega-3 (EPA + DHA) per soft-gel; enriched with vitamin D3; individually blister-packed to prevent oxidation.\n- Ideal for: Middle-aged and older adults who demand top purity and a premium formulation.",
        "page_description": "**About this item**\n- 1 180 mg total Omega-3 (EPA 665 mg / DHA 445 mg) per soft-gel for heart, brain and vision.\n- Provides 1 000 IU vitamin D3 to support bones, muscles and immunity.\n- r-Triglyceride form for superior absorption; lactose- & gluten-free, burp-free orange flavor.\n- Ultra-pure, Friend-of-the-Sea-certified fish oil in beef-gelatin-free blister packs."
    },

    "Now Foods Ultra Omega-3": {
        "id": "fish_03",
        "title": "Now Foods Ultra Omega-3",
        "price": "$41.51",
        "specs": {
            "Brand": "Now Foods",
            "Flavor": "Unflavoured",
            "Primary supplement type": "Omega-3",
            "Unit Count": "180 Count",
            "Item Form": "Softgel",
            "Item Weight": "375 g"
        },
        "product_url": "https://www.amazon.sg/Supplements-Neptune-Strength-Phospholipid-Bound-Softgels/dp/B06XDNT7TQ/",
        "image_url": "https://m.media-amazon.com/images/I/71auVVCYKnL._AC_SX679_.jpg",
        "description": "- Features: Great value (EPA 500 mg + DHA 250 mg per soft-gel); IFOS certified; suitable for long-term, everyday supplementation.\n- Ideal for: General health maintenance, budget-conscious consumers, and daily nutritional support.",
        "page_description": "**About this item**\n- CARDIOVASCULAR SUPPORT – 600 mg EPA & 300 mg DHA per enteric-coated soft-gel.\n- MOLECULARLY DISTILLED for purity; tested free of PCBs, dioxins & heavy metals.\n- ENTERIC COATING reduces nausea and fishy aftertaste.\n- NON-GMO, Kosher and GMP-quality assured by the family-owned NOW® brand since 1968."
    },

    "Blackmores OMEGA BRAIN Caps 60s": {
        "id": "fish_04",
        "title": "Blackmores OMEGA BRAIN Caps 60s",
        "price": "$40.9",
        "specs": {
            "Brand": "Blackmores",
            "Flavor": "Lutein",
            "Primary supplement type": "Omega-3",
            "Unit Count": "180 Count",
            "Item Form": "Tablet",
            "Item Weight": "0.39 Kilograms"
        },
        "product_url": "https://www.amazon.com/Blackmores-OMEGA-BRAIN-Caps-60s/dp/B00AQ7T7UQ",
        "image_url": "https://m.media-amazon.com/images/I/71UhUKoWbnL._AC_SL1500_.jpg",
        "description": "- Features: Blackmores Omega Brain Capsules provide concentrated omega-3 fatty acids, particularly high DHA levels to support brain structure and enhance cognitive function.\n- Ideal for: Intensive cardiovascular support, joint health, and individuals seeking a high-dose omega-3 supplement.",
        "page_description": "**About this item**\n- One-a-day capsule delivers 500 mg DHA to maintain brain health and mental performance.\n- Provides four-times more DHA than standard fish oil—ideal if you eat little fish.\n- 100 % wild-caught small-fish oil rigorously tested for mercury, dioxins & PCBs.\n- Supports healthy growth in children and overall wellbeing for all ages."
    },

    "Möller’s Norwegian Cod-Liver Oil": {
        "id": "fish_05",
        "title": "Möller’s Norwegian Cod-Liver Oil",
        "price": "$40.63",
        "specs": {
            "Brand": "Möller’s",
            "Flavor": "Lofoten",
            "Primary supplement type": "Fish Oil",
            "Unit Count": "8.4 Fluid Ounces",
            "Item Form": "Liquid",
            "Item Weight": "1.1 Pounds"
        },
        "product_url": "https://www.amazon.com/M%C3%B8llers-Cod-Liver-Oil-Lemon-Flavor/dp/B084LYXCL1",
        "image_url": "https://m.media-amazon.com/images/I/61eg-Vgm97L._AC_SL1500_.jpg",
        "description": "- Features: Liquid fish oil enriched with natural vitamins A and D; trusted Nordic brand with over 100 years of history; suitable for children and pregnant women.\n- Ideal for: Family supplementation, children’s health, pregnancy nutritional support, and enhancing immune function.",
        "page_description": "**About this item**\n- Natural source of EPA & DHA to support heart, brain and vision.\n- Supplies vitamins A & D for immune function and normal bone growth.\n- Sustainably sourced Arctic cod and bottled under Norway’s century-old Möller’s quality standards.\n- Refreshing lemon flavor with no fishy aftertaste; kid- and pregnancy-friendly."
    },

    # ── Liver-support group ──
    "Thorne Liver Cleanse": {
        "id": "liver_01",
        "title": "Thorne Liver Cleanse",
        "product_url": "https://www.amazon.com/Thorne-Research-Cleanse-Detoxification-Capsules/dp/B07978NYC5",
        "image_url": "https://m.media-amazon.com/images/I/71eMoaqvJyL._AC_SL1500_.jpg",
        "description": "- Features: Professional-grade formula that combines milk thistle (125 mg silymarin), burdock, chicory, berberine, and other botanicals; NSF-Certified for Sport®; produced in a GMP-compliant U.S. facility.\n- Ideal for: Individuals looking for a broad-spectrum botanical detox blend—especially those who value third-party testing and athlete-friendly certifications.",
        "page_description": "**About this item**\n- Synergistic botanical blend enhances detoxification and bile flow.*\n- Supports both Phase I and Phase II liver detox pathways.*\n- Also provides kidney-supportive herbs for comprehensive clearance.*\n- NSF Certified for Sport® and third-party tested for contaminants."
    },

    "Himalaya LiverCare (Liv 52 DS)": {
        "id": "liver_02",
        "title": "Himalaya LiverCare (Liv 52 DS)",
        "product_url": "https://www.amazon.com.be/-/en/Himalaya-Liv-52-DS-3-Pack/dp/B09MF88N71",
        "image_url": "https://m.media-amazon.com/images/I/61VEN7Bl8wL._AC_SL1500_.jpg",
        "description": "- Features: Clinically studied Ayurvedic blend (capers, chicory, black nightshade, arjuna, yarrow, etc.) shown to improve Child-Pugh scores and reduce ALT/AST in liver-compromised patients.\n- Ideal for: Those seeking a time-tested herbal formula with human-trial evidence, including individuals with mild enzyme elevations or high environmental/toxic exposure.",
        "page_description": "**About this item**\n- Herbal liver-cleanse formula that helps detoxify and protect liver cells.*\n- Boosts metabolic capacity and promotes healthy bile production for digestion.*\n- Vegan caplets free of gluten, dairy, soy, corn, nuts and animal gelatin; non-GMO.\n- Trusted Ayurvedic brand since 1930 with decades of clinical research."
    },

    "Jarrow Formulas Milk Thistle (150 mg)": {
        "id": "liver_03",
        "title": "Jarrow Formulas Milk Thistle (150 mg)",
        "product_url": "https://www.amazon.com/Jarrow-Formulas-Silymarin-Marianum-Promotes/dp/B0013OULVA",
        "image_url": "https://m.media-amazon.com/images/I/71G03a0TYUL._AC_SL1500_.jpg",
        "description": "- Features: 30:1 standardized silymarin phytosome bonded to phosphatidylcholine for up-to-30× higher bioavailability than conventional milk thistle; vegetarian capsules; gluten-, soy-, and dairy-free.\n- Ideal for: People who need a concentrated, highly absorbable milk-thistle extract—e.g., those on multiple medications or with occasional alcohol use.",
        "page_description": "**About this item**\n- 150 mg 30:1 milk-thistle extract standardized to 80 % silymarin flavonoids.\n- Helps raise glutathione levels for healthy liver detoxification.*\n- Provides antioxidant protection against free-radical damage.*\n- Easy-to-swallow veggie capsules; adults take 1–3 daily as directed."
    },

    "NOW Foods Liver Refresh™": {
        "id": "liver_04",
        "title": "NOW Foods Liver Refresh™",
        "product_url": "https://www.amazon.com/Liver-Refresh-Capsules-NOW-Foods/dp/B001EQ92VW",
        "image_url": "https://m.media-amazon.com/images/I/71fW7Z6vFAL._AC_SL1500_.jpg",
        "description": "- Features: Synergistic blend of milk thistle, N-acetyl cysteine (NAC), methionine, and herbal antioxidants; non-GMO Project Verified and GMP-qualified.\n- Ideal for: Individuals wanting comprehensive antioxidant support—such as frequent travelers, people with high oxidative stress, or those following high-protein diets.",
        "page_description": "**About this item**\n- Promotes optimal liver health with milk thistle plus herbal-enzyme blend.*\n- Supports healthy detoxification processes and normal liver enzyme levels.*\n- Non-GMO, vegetarian capsules produced in a GMP-certified facility.\n- Amazon’s Choice pick with thousands of 4-plus-star reviews."
    },

    "Nutricost TUDCA 250 mg": {
        "id": "liver_05",
        "title": "Nutricost TUDCA 250 mg",
        "product_url": "https://www.amazon.com/Nutricost-Tudca-250mg-Capsules-Tauroursodeoxycholic/dp/B01A68H2BA",
        "image_url": "https://m.media-amazon.com/images/I/61EJx7JnxfL._AC_SL1500_.jpg",
        "description": "- Features: Pure tauroursodeoxycholic acid (TUDCA) at 250 mg per veggie capsule; non-GMO, soy- and gluten-free; 3rd-party ISO-accredited lab tested; made in an FDA-registered, GMP facility.\n- Ideal for: Advanced users seeking bile-acid–based cellular protection—popular among those with cholestatic or high-fat-diet concerns.",
        "page_description": "**About this item**\n- 250 mg TUDCA per capsule—research-backed bile acid for liver & cellular health.*\n- Convenient one-capsule daily serving; 60-count bottle is a two-month supply.\n- Non-GMO, soy- and gluten-free formula; ISO-accredited third-party tested.\n- Made in a GMP-compliant, FDA-registered U.S. facility."
    }
}

KEYWORD_RESPONSES = {
    "fish oil": [PRODUCT_CATALOG[k] for k in (
        "Nordic Naturals Ultimate Omega",
        "WHC UnoCardio 1000",
        "Now Foods Ultra Omega-3",
        "Blackmores OMEGA BRAIN Caps 60s",
        "Möller’s Norwegian Cod-Liver Oil"
        # ... eight more keys in display order
    )],
    "liver": [PRODUCT_CATALOG[k] for k in (
        "Thorne Liver Cleanse",
        "Himalaya LiverCare (Liv 52 DS)",
        "Jarrow Formulas Milk Thistle (150 mg)",
        "NOW Foods Liver Refresh™",
        "Nutricost TUDCA 250 mg"
        # ... eight more
    )],
    "优惠码": "🎁 **本月通用优惠码：DS-MAY25**\n下单立减 25 元（限时 5 月 31 日前，秒杀品除外）。",
}

PREDEFINED_HEADINGS = {
    "fish oil": (
        "Certainly! Here are some well‑regarded fish‑oil supplements that"
        " are commonly recommended based on quality, purity, and "
        "third‑party testing."
    ),
    "liver": (
        "Certainly! Here are some well‑regarded liver‑support supplements"
        " that are commonly recommended based on quality, purity, and "
        "third‑party testing."
    ),
}


def get_predefined_response(user_text: str):
    lower = user_text.lower()
    if 'fish' in lower:
        lower = 'fish oil'
    for kw, reply in KEYWORD_RESPONSES.items():
        if kw.lower() in lower:
            return reply
    return None


############################################
# 4) Sponsored Product Data + Layout
############################################
PRODUCTS_DATA = {
    "liver": [
        {
            "id": "liver_06",
            "title": "Gaia Herbs Liver Cleanse",
            "price": "¥215",
            "image_url": "https://m.media-amazon.com/images/I/710RG7jzTqL._AC_SL1500_.jpg",
            "product_url": "https://www.amazon.com/dp/B00BSU2HFW",
            "sponsored": True,
            "page_description": "**About this item**\n- Liver support – helps the liver remove wastes and process nutrients.\n- Herbal helping hand – plant-based backup when your liver needs it most.\n- Premium ingredients – traditional botanicals chosen specifically for liver health.\n- Quality commitment – Gaia sources top-grade herbs and has linked people, plants & planet since 1987."
        },
        {
            "id": "liver_07",
            "title": "Pure Encapsulations Liver-GI Detox",
            "price": "¥430",
            "image_url": "https://m.media-amazon.com/images/I/71KCict6JDL.__AC_SX300_SY300_QL70_ML2_.jpg",
            "product_url": "https://www.amazon.com/dp/B0016L2XT8",
            "sponsored": True,
            "page_description": "**About this item**\n- Liver & GI detox – supports natural detox pathways with NAC and L-methionine.\n- Nutrient-rich blend – vitamins, minerals, ALA, turmeric & milk thistle for liver health.\n- GI support – helps maintain intestinal integrity and proper nutrient use.\n- Suggested use – 2 capsules daily with a meal."
        },
        {
            "id": "liver_08",
            "title": "Life Extension NAC 600 mg",
            "price": "¥110",
            "image_url": "https://m.media-amazon.com/images/I/61yHnalNZSL.__AC_SX300_SY300_QL70_ML2_.jpg",
            "product_url": "https://www.amazon.com/dp/B07KR3LZNJ",
            "sponsored": True,
            "page_description": "**About this item**\n- Whole-body health – 600 mg NAC supports liver, respiratory & immune function.\n- Antioxidant protection – replenishes glutathione to combat oxidative stress.\n- Flexible supply – 150 capsules last 50–150 days at 1–3 caps/day.\n- Clean formula – non-GMO, gluten-free, made in the USA for 40+ years."
        },
        {
            "id": "liver_09",
            "title": "Swisse Ultiboost Liver Detox",
            "price": "¥150",
            "image_url": "https://m.media-amazon.com/images/I/61irB7SYZJL._AC_SL1500_.jpg",
            "product_url": "https://www.amazon.com/Swisse-Ultiboost-Traditional-Supplement-Supports/dp/B06Y59V34H",
            "sponsored": True,
            "page_description": "**About this item**\n- Liver cleanse, detox & repair with milk-thistle extract.\n- Multi-herb blend – milk thistle, turmeric & artichoke for antioxidant support.\n- Digestive relief – helps ease indigestion, bloating & flatulence.\n- GMP-made: 2 tablets daily, crafted in FDA-registered facilities."
        },
        {
            "id": "liver_10",
            "title": "Solaray Liver Blend SP-13",
            "price": "¥200",
            "image_url": "https://m.media-amazon.com/images/I/619Fhmmu5bL.__AC_SX300_SY300_QL70_FMwebp_.jpg",
            "product_url": "https://www.amazon.com/Solaray-Healthy-Dandelion-Artichoke-Peppermint/dp/B00014D9VC",
            "sponsored": True,
            "page_description": "**About this item**\n- Herbal liver blend – milk thistle, dandelion, burdock & more for liver tone.\n- Synergistic formula – combo yields stronger benefits than single herbs.\n- Eco bottle – post-consumer recycled resin reduces plastic waste.\n- Utah-made – GMP facility & in-house lab testing ensure purity."
        }
    ],

    "fish oil": [
        {
            "id": "fish_06",
            "title": "omega3 Fish Oil",
            "price": "$41.95",
            "specs": {
                "Brand": "MAV NUTRITION",
                "Flavor": "Lemon",
                "Primary supplement type": "DHA",
                "Unit Count": "180 Count",
                "Item Form": "Softgel",
                "Item Weight": "0.37 Kilograms"
            },
            "image_url": "https://m.media-amazon.com/images/I/71ZBnxvlvCL._AC_SL1500_.jpg",
            "product_url": "https://www.amazon.com/Strength-Support-Non-GMO-Burpless-Softgels/dp/B01NBTJFJB/",
            "sponsored": True,
            "page_description": "**About this item**\n- Triple-strength 2 500 mg fish oil with 1 500 mg EPA & 570 mg DHA per serving.*\n- The fatty acids in fish oil support healthy eyes, brain, immune system, and so much more.*\n- IFOS & Labdoor-certified; wild-caught, purified to minimize contaminants.\n- Easy-swallow, burp-less softgels in re-esterified triglyceride form for absorption."
        },
        {
            "id": "fish_07",
            "title": "Swisse Fish Oil Soft Capsules",
            "price": "$40.13",
            "specs": {
                "Brand": "Swisse",
                "Flavor": "Unflavored",
                "Primary supplement type": "Omega 3 Fish Oil",
                "Unit Count": "400 Count",
                "Item Form": "Softgel",
                "Item Weight": "1.34 Pounds"
            },
            "image_url": "https://m.media-amazon.com/images/I/61AF1Mw+RkL._AC_SL1500_.jpg",
            "product_url": "https://www.amazon.com/Swisse-Supplement-Sustainably-Essential-Promotes/dp/B0D45ZYSWZ?th=1",
            "sponsored": True,
            "page_description": "**About this item**\n- Premium 1 000 mg odorless wild-fish oil for heart, brain & eye support.\n- Sustainably sourced & heavy-metal tested (mercury, lead, etc.).\n- 400-softgel value size delivers DHA + EPA to aid mood & nervous-system balance.\n- Crafted by Swisse with strict purity & potency standards."
        },
        {
            "id": "fish_08",
            "title": "GNC Fish Oil",
            "price": "$40.82",
            "specs": {
                "Brand": "GNC",
                "Flavor": "Unflavored",
                "Primary supplement type": "Omega-3",
                "Unit Count": "120 Count",
                "Item Form": "Softgel",
                "Item Weight": "3.48 Grams"
            },
            "image_url": "https://m.media-amazon.com/images/I/61gW5yxTCgL._AC_SX679_.jpg",
            "product_url": "https://www.amazon.com/GNC-Strength-Potency-Quality-Supplement/dp/B01NCSCP1Y",
            "sponsored": True,
            "page_description": "**About this item**\n- Delivers 1 000 mg EPA/DHA to support cardiovascular wellness.\n- Also aids brain, eye, skin & joint health; may benefit muscle function.\n- Enteric-coated, burp-less softgels with balanced-mood support.\n- Wild-caught deep-ocean fish, purified & gluten-free—no sugars or dyes."
        },
        {
            "id": "fish_09",
            "title": "Viva Naturals Fish Oil",
            "price": "$41.75",
            "specs": {
                "Brand": "Viva Naturals",
                "Flavor": "Lemon",
                "Primary supplement type": "Omega-3 fatty acids, Total Omega-3 fatty acids, DHA, EPA",
                "Unit Count": "180 Count",
                "Item Form": "Softgel",
                "Item Weight": "7.4 Ounces"
            },
            "image_url": "https://m.media-amazon.com/images/I/61C6MAD6f1L._AC_SL1000_.jpg",
            "product_url": "https://www.amazon.com/Viva-Naturals-Triple-Strength-Supplement/dp/B0CB4QHF3N",
            "sponsored": True,
            "page_description": "**About this item**\n- Omega-3s for heart, brain, skin & eye health.\n- Purified to reduce mercury, PCBs & dioxins below IFOS limits.\n- Re-esterified triglyceride form for superior absorption.\n- IFOS & Labdoor-certified; wild-caught and sustainably sourced."
        },
        {
            "id": "fish_10",
            "title": "Nature's Bounty Fish Oil",
            "price": "$41.5",
            "specs": {
                "Brand": "Nature's Bounty",
                "Flavor": "fish oil,fish",
                "Primary supplement type": "Fish Oil",
                "Unit Count": "200 Count",
                "Item Form": "Softgel",
                "Item Weight": "11.2 ounces"
            },
            "image_url": "https://m.media-amazon.com/images/I/61DfA7Q2L1L.__AC_SX300_SY300_QL70_FMwebp_.jpg",
            "product_url": "https://www.amazon.com/Natures-Bounty-Fish-1200mg-Softgels/dp/B0061GLLZU",
            "sponsored": True,
            "page_description": "**About this item**\n- Helps maintain triglyceride levels that are already within the normal range.\n- Omega-3s support metabolic and immune health.\n- Rapid-release 1 200 mg softgels for quick dispersion.\n- From a Nature’s Bounty brand trusted for nearly 50 years."
        }
    ]
}


############################################
# 5) Two-phase approach for links
############################################
def open_pending_link():
    """If st.session_state.pending_link is set, open it in a new tab, then clear."""
    if "pending_link" in st.session_state and st.session_state["pending_link"]:
        target_url = st.session_state["pending_link"]
        st.session_state["pending_link"] = None

        # Possibly blocked if user hasn't allowed popups:
        js_code = f"""
        <script>
            window.open("{target_url}", "_blank");
        </script>
        """
        st.markdown(js_code, unsafe_allow_html=True)


def back_to_main():
    """Return from product page and log the click."""
    # 1) write click to Google Sheet
    log_event("back", "Back to main")
    time.sleep(0.5)
    # 2) navigate
    st.session_state.update({"page": "main", "current_product": {}})


def render_product_page():
    """Single‑product landing page."""
    p = st.session_state.current_product

    # b) UI
    st.button("← Back", key="back_to_main", help="back", on_click=back_to_main)

    # 3 columns: image | info/specs | buy box
    col_img, col_info, col_buy = st.columns([4, 5, 3])

    # Left: product image
    with col_img:
        if p.get("image_url"):
            st.image(p["image_url"], use_container_width=True)
            st.markdown(
                """
                <style>
                  img:nth-last-of-type(1) { max-height: 360px; object-fit: contain; }
                </style>
                """,
                unsafe_allow_html=True,
            )

    # Middle: description + specs table (if provided)
    with col_info:
        # short description first
        # if p.get("description"):
        #     st.write(p["description"])
        # longer “About this item”
        if p.get("page_description"):
            with st.expander("About this item", expanded=True):
                st.markdown(p["page_description"])
        # Optional specs (per‑product; see Section 4)
        specs = p.get("specs")  # or p.get("attributes") or {}
        if specs:
            st.markdown("#### Product details")
            render_specs_table(specs)

    # Right: buy box (demo only)
    with col_buy:
        with st.container(border=True):
            # price if available
            if p.get("price"):
                st.markdown(f"**Price**: {p['price']}")
            # quantity (optional)
            qty = st.number_input("Quantity", min_value=1, max_value=99, value=1,
                                  key=f"qty_demo_{p.get('id', '')}")
            # demo button that only logs to Google Sheet
            if st.button("Add to Cart", key=f"add_demo_{p.get('id', '')}"):
                log_event("add_to_cart_demo", p.get("title", ""), p.get("product_url", " "))
                st.success("Added to cart")
                # no real cart; do nothing else

            # optional external link
            # if p.get("product_url"):
            #     st.markdown(f"[View on site]({p['product_url']})")


def record_link_click_and_open(label, url, link_type):
    click_log_file = "click_history.csv"
    # current favourite state
    fav_dict = st.session_state.favorites
    is_fav = url in fav_dict
    star = "★" if is_fav else "☆"

    # compose single label
    btn_label = f"{label} {star}"
    btn_key = f"{label}"  # make key unique per URL

    if label == 'end':
        if st.sidebar.button("Finish / End Session"):
            st.success("Session ended. Thank you!")

            click_data = {
                "id": st.session_state.prolific_id,
                "start": st.session_state.start_time,
                "timestamp": datetime.now().isoformat(),
                "type": link_type,
                "title": label,
                "url": url
            }
            save_to_gsheet(click_data)
            st.stop()
    else:
        if st.button(btn_label, key=btn_key):
            # 新点击记录
            click_data = {
                "id": st.session_state.prolific_id,
                "start": st.session_state.start_time,
                "timestamp": datetime.now().isoformat(),
                "type": link_type,
                "title": label,
                "url": url
            }
            save_to_gsheet(click_data)
            js = f'window.open("{url}", "_blank").then(r => window.parent.location.href);'
            st_javascript(js)
            # ---------- 2) toggle favourite & log ---------------
            if is_fav:
                del fav_dict[url]
            else:
                fav_dict[url] = label

            time.sleep(3)
            st.rerun()


def show_product_item(p: dict, *, link_type="organic",
                      show_image=False, orientation="horizontal", image_position="none"):
    """
    Minimal list item:
      - optional image (top or below)
      - clickable title that navigates to the product page and logs the click
    """
    if orientation == "vertical" and show_image and p.get("image_url"):
        st.markdown(
            f"<img src='{p['image_url']}' "
            f"style='display:block; margin:0 auto; "
            f"width:120px; height:120px; object-fit:contain;'>",
            unsafe_allow_html=True,
        )

    label_text = f"Sponsored · {p['title']}" if link_type == "ad" else p["title"]
    if st.button(label_text, key=f"prod_{p['id']}"):
        log_event(link_type, p["title"], p.get("product_url", " "))
        st.session_state.update({"page": "product", "current_product": p})
        st.rerun()

    if show_image and image_position == "below" and p.get("image_url"):
        st.markdown(
            f"<img src='{p['image_url']}' "
            f"style='display:block; margin:6px auto 0 auto; "
            f"width:120px; height:120px; object-fit:contain;'>",
            unsafe_allow_html=True,
        )


############################################
# 6) Ads in a 5-column grid
############################################
def show_advertisements(relevant_products):
    # ➊ keep the border=True container
    with st.container(border=True):
        # invisible anchor so we can target the container via CSS
        st.markdown("<div id='ad-box-anchor'></div>", unsafe_allow_html=True)

        # red badge (unchanged)
        st.markdown(
            "<div style='position:relative;'>"
            "<span style='position:absolute; top:-12px; left:-12px; "
            "background:#e53935; color:#fff; font-size:13px; "
            "padding:4px 10px; border-radius:4px;'>Querya Advertising</span>"
            "</div>",
            unsafe_allow_html=True,
        )

        # grid – unchanged
        n, col_count = len(relevant_products), 5
        rows = math.ceil(n / col_count)
        for r in range(rows):
            cols = st.columns(col_count, gap="small")
            for c in range(col_count):
                idx = r * col_count + c
                if idx < n:
                    with cols[c]:
                        show_product_item(
                            relevant_products[idx],
                            link_type="ad",
                            show_image=True,
                            orientation="vertical",
                        )


############################################
# 7) Query -> relevant products
############################################
def get_products_by_query(query: str):
    lower_q = query.lower()
    if ("肝" in lower_q) or ("护肝" in lower_q) or ("liver" in lower_q):
        return PRODUCTS_DATA["liver"]
    elif ("鱼油" in lower_q) or ("fish" in lower_q):
        return PRODUCTS_DATA["fish oil"]
    else:
        return []


############################################
# Step 2: random "variant"
############################################
# if "variant" not in st.session_state:
#     st.session_state.variant = random.randint(1, 4)
# variant = 3#st.session_state.variant


############################################
# 8) DeepSeek Recommendation Flow
############################################
# def show_deepseek_recommendation(with_ads: bool):
#     col1, col2 = st.columns([6, 1])
#     with col1:
#         st.title("Querya Rec")
#     with col2:
#         end_clicked = st.button("Finish / End Session", key=f"end_button_{st.session_state.get('variant', '')}")
#
#     if end_clicked:
#         # Full-screen centered message (clears interface)
#         # st.session_state["end_clicked"] = True
#         click_data = {
#             "id": st.session_state.get("prolific_id", "unknown"),
#             "start": st.session_state.get("start_time", datetime.now().isoformat()),
#             "timestamp": datetime.now().isoformat(),
#             "type": "end",
#             "title": "Finish / End Session",
#             "url": " "
#         }
#         save_to_gsheet(click_data)
#         st.session_state.stage = "survey"
#         st.rerun()  # Re-run to show the message cleanly in next render
#
#     # After rerun
#     if st.session_state.get("end_clicked", False):
#         st.markdown("<br><br><br>", unsafe_allow_html=True)
#         st.markdown(
#             "<h1 style='text-align:center;'>✅ Session ended. Thank you!</h1>",
#             unsafe_allow_html=True
#         )
#         st.stop()
#
#     if "history" not in st.session_state:
#         st.session_state.history = [
#             ("system", "You are an e-commerce chat assistant who recommends products based on user needs.")
#         ]
#     if "first_message_submitted" not in st.session_state:
#         st.session_state.first_message_submitted = False
#     if "pending_first_message" not in st.session_state:
#         st.session_state.pending_first_message = None
#     if "current_ads" not in st.session_state:
#         st.session_state.current_ads = []
#
#     # Display conversation so far
#     for role, content in st.session_state.history:
#         if role == "system":
#             continue
#         if role == "assistant":
#             with st.chat_message("assistant"):
#                 display_parsed_markdown(content, link_type="deepseek")
#         else:
#             st.chat_message(role).write(content)
#
#     # If we have a pending first message
#     if st.session_state.first_message_submitted and st.session_state.pending_first_message:
#         user_first_input = st.session_state.pending_first_message
#         st.session_state.pending_first_message = None
#
#         if with_ads:
#             prods = get_products_by_query(user_first_input)
#             st.session_state.current_ads = prods
#
#             # Show current ads
#             if st.session_state.current_ads:
#                 show_advertisements(st.session_state.current_ads)
#
#         predefined = get_predefined_response(user_first_input)
#         if predefined:
#             assistant_text = predefined
#             if isinstance(predefined, list):  # fish‑oil / liver list
#                 # detect which keyword we hit (fish oil vs liver)
#                 kw = "fish oil" if "fish" in user_first_input.lower() else "liver"
#                 heading = PREDEFINED_HEADINGS[kw]
#                 with st.chat_message("assistant"):
#                     render_predefined_products(predefined, heading, link_type="organic")
#             else:  # a plain string reply
#                 with st.chat_message("assistant"):
#                     display_parsed_markdown(predefined, link_type="organic")
#         else:
#             resp = client.chat.completions.create(
#                 model="deepseek-chat",
#                 messages=[{"role": r, "content": c} for r, c in st.session_state.history],
#                 temperature=1,
#                 stream=False,
#             )
#             assistant_text = resp.choices[0].message.content
#             with st.chat_message("assistant"):
#                 display_parsed_markdown(assistant_text, link_type="deepseek")
#
#         st.session_state.history.append(("assistant", assistant_text))
#
#
#
#
#
#     # If first message not yet
#     def to_base64(path: str) -> str:
#         return base64.b64encode(Path(path).read_bytes()).decode()
#
#     if not st.session_state.first_message_submitted:
#         # col1, col2, col3 = st.columns([1, 2, 1])
#         # with col2:
#         try:
#             logo_b64 = to_base64("querya.png")
#             st.markdown(
#                 f"""
#                 <div style="text-align:center; margin-top:20px;">
#                     <img src="data:image/png;base64,{logo_b64}" style="height:80px;" />
#                 </div>
#                 """,
#                 unsafe_allow_html=True
#             )
#         except:
#             st.write("Querya Rec")
#
#         # query = st.text_input("", placeholder="Input Key Words for Search Here")
#         user_first_input = st.text_input("", placeholder="Please enter your message:")
#
#         if user_first_input:
#             st.session_state.history.append(("user", user_first_input))
#             st.chat_message("user").write(user_first_input)
#             st.session_state.first_message_submitted = True
#             st.session_state.pending_first_message = user_first_input
#             st.rerun()
#         return
#
#     # Subsequent messages
#     user_input = ...
#     if not user_input:
#         return
#
#     st.session_state.history.append(("user", user_input))
#     st.chat_message("user").write(user_input)
#     if with_ads:
#         prods = get_products_by_query(user_input)
#         st.session_state.current_ads = prods
#         if prods:
#             show_advertisements(prods)
#
#     predefined = get_predefined_response(user_input)
#     if predefined:
#         assistant_text = predefined
#         if isinstance(predefined, list):  # fish‑oil / liver list
#             # detect which keyword we hit (fish oil vs liver)
#             kw = "fish oil" if "fish" in user_input.lower() else "liver"
#             heading = PREDEFINED_HEADINGS[kw]
#             with st.chat_message("assistant"):
#                 render_predefined_products(predefined, heading, link_type="organic")
#         else:  # a plain string reply
#             with st.chat_message("assistant"):
#                 display_parsed_markdown(predefined, link_type="organic")
#     else:
#         resp = client.chat.completions.create(
#             model="deepseek-chat",
#             messages=[{"role": r, "content": c} for r, c in st.session_state.history],
#             temperature=1,
#             stream=False,
#         )
#         assistant_text = resp.choices[0].message.content
#         with st.chat_message("assistant"):
#             display_parsed_markdown(assistant_text, link_type="deepseek")
#
#     st.session_state.history.append(("assistant", assistant_text))

def show_deepseek_recommendation(with_ads: bool):
    """AI-chat condition: one-shot query with organic-first rendering and suggested prompts."""
    # -------- Header --------
    col1, col_mid, col2 = st.columns([5.6, 1.6, 1])
    with col1:
        st.title("Querya Rec")
    with col_mid:
        instructions_button_inline()
    with col2:
        end_clicked = st.button("Finish / End Session", key=f"end_button_{st.session_state.get('variant', '')}")

    if end_clicked:
        save_to_gsheet({
            "id": st.session_state.get("prolific_id", "unknown"),
            "start": st.session_state.get("start_time", datetime.now().isoformat()),
            "timestamp": datetime.now().isoformat(),
            "type": "end",
            "title": "Finish / End Session",
            "url": " "
        })
        st.session_state.stage = "survey"
        st.rerun()

    # -------- State scaffolding --------
    st.session_state.setdefault("history", [
        ("system", "You are an e-commerce chat assistant who recommends products based on user needs.")
    ])
    st.session_state.setdefault("first_message_submitted", False)
    st.session_state.setdefault("pending_first_message", None)
    st.session_state.setdefault("current_ads", [])
    ads_shown_this_render = False  # to avoid double rendering in a single run

    # -------- Render past turns --------
    ads_inserted = False
    for role, content in st.session_state.history:
        if role == "system":
            continue
        if role == "assistant":
            # Place sponsored products ABOVE the organic assistant output (more visible)
            if with_ads and (not ads_inserted) and st.session_state.get("current_ads"):
                show_advertisements(st.session_state.current_ads)
                ads_inserted = True
            with st.chat_message("assistant"):
                display_parsed_markdown(content, link_type="deepseek")
        else:
            st.chat_message(role).write(content)

    # -------- (optional) Persistent ADS box (now rendered below) --------
    # if with_ads and st.session_state.get("current_ads"):
    #     show_advertisements(st.session_state.current_ads)
    #     ads_shown_this_render = True

    # -------- If we have a pending first message, process it once --------
    if st.session_state.first_message_submitted and st.session_state.pending_first_message:
        user_first_input = st.session_state.pending_first_message
        st.session_state.pending_first_message = None

        # Log first query
        save_to_gsheet({
            "id": st.session_state.prolific_id,
            "start": st.session_state.start_time,
            "timestamp": datetime.now().isoformat(),
            "type": "first_query",
            "title": user_first_input,
            "url": " "
        })

        # 1) ADS (compute + render ABOVE organic output)
        prods = []
        if with_ads:
            prods = get_products_by_query(user_first_input)
            st.session_state.current_ads = prods

        if with_ads and prods:
            show_advertisements(prods)
            ads_shown_this_render = True

        # 2) Then organic response
        predefined = get_predefined_response(user_first_input)
        if predefined:
            assistant_text = predefined
            if isinstance(predefined, list):
                # choose heading based on detected keyword
                kw = "fish oil" if "fish" in user_first_input.lower() else "liver"
                heading = PREDEFINED_HEADINGS.get(kw, "Recommended items")
                with st.chat_message("assistant"):
                    render_predefined_products(predefined, heading, link_type="organic")
            else:
                with st.chat_message("assistant"):
                    display_parsed_markdown(predefined, link_type="organic")
        else:
            resp = client.chat_completions.create(  # if your client is OpenAI, keep .chat.completions.create
                model="deepseek-chat",
                messages=[{"role": r, "content": c} for r, c in st.session_state.history],
                temperature=1,
                stream=False,
            )
            assistant_text = resp.choices[0].message.content
            with st.chat_message("assistant"):
                display_parsed_markdown(assistant_text, link_type="deepseek")

        st.session_state.history.append(("assistant", assistant_text))

    # -------- First message UI (shows only before first submission) --------
    if not st.session_state.first_message_submitted:
        # optional logo
        try:
            b64 = base64.b64encode(Path("querya.png").read_bytes()).decode()
            st.markdown(f"<div style='text-align:center; margin-top:12px;'>"
                        f"<img src='data:image/png;base64,{b64}' style='height:80px;' /></div>",
                        unsafe_allow_html=True)
        except Exception:
            pass

        # input + suggested prompts
        st.markdown("**Please enter ONE query to start:**")
        user_first_input = st.text_input("", placeholder="e.g., Can you recommend some fish oil supplements?")

        SUGGESTED_QUERIES_AI = [
            "Can you recommend some fish oil supplements?",
            "Please recommend some fish oils.",
            "Which fish oils are good?",
            "Any fish oil recommendations?"
        ]
        # st.caption("Or pick a suggested prompt:")
        # cols = st.columns(3)
        # chosen = None
        # for i, q in enumerate(SUGGESTED_QUERIES_AI):
        #     if cols[i % 3].button(q, key=f"sug_ai_{i}"):
        #         chosen = q
        chosen = render_suggestion_chips(SUGGESTED_QUERIES_AI, "sug_search")
        if chosen:
            user_first_input = chosen

        if user_first_input:
            st.session_state.history.append(("user", user_first_input))
            st.chat_message("user").write(user_first_input)
            st.session_state.first_message_submitted = True
            st.session_state.pending_first_message = user_first_input
            st.rerun()
        return

    # Do not render a bottom chat box after the first query; it steals focus and scrolls down.
    st.markdown("<div style='height:0.5rem;'></div>", unsafe_allow_html=True)
    msg_cols = st.columns([8, 1])
    with msg_cols[0]:
        extra_input = st.text_input(
            "",
            placeholder="Type a message...",
            key="ai_extra_message",
            label_visibility="collapsed",
        )
    with msg_cols[1]:
        send_clicked = st.button("Send", key="btn_ai_extra_message")

    if send_clicked and extra_input.strip():
        save_to_gsheet({
            "id": st.session_state.prolific_id,
            "start": st.session_state.start_time,
            "timestamp": datetime.now().isoformat(),
            "type": "extra_query_attempt",
            "title": extra_input.strip()[:200],
            "url": " ",
        })
        st.info("Thanks! For this study, you only need to enter **one** query. Please click **Finish / End Session** (top right) to proceed to the survey.")
    return


############################################
# 9) Google-like Search Flow
############################################
def do_fake_google_search(query):
    lower_q = query.lower()

    # 这里仅做示例返回几条伪搜索结果，可根据关键词控制输出

    if ("鱼油" in lower_q) or ("fish" in lower_q):
        return [
            {
                "id": "fish_01",
                "title": "Nordic Naturals Ultimate Omega  ",
                "product_url": "https://www.amazon.com/Nordic-Naturals-Ultimate-Support-Healthy/dp/B002CQU564/ref=sr_1_1?content-id=amzn1.sym.c9738cef-0b5a-4096-ab1b-6af7c45832cd%3Aamzn1.sym.c9738cef-0b5a-4096-ab1b-6af7c45832cd&dib=eyJ2IjoiMSJ9.EmMg0Sjrk3Up1-B8Uq6XmXPfqBR6LsN4xh_xk9FkohcxjUGjjtl8VDmFPAv02s7DdvP4IMVJlYCiu4xLS3tkFzqAjY8zzLpTcrQiGDBHfSlCICd1rxDQrjuX09VNQDqQLzn3cHDWmdL3cWFyPa6GoFGZn3Y4_gA0M70XM89DcYOwpBeQlrC5yad9lab17AwZgciNRLxb8byU-LfuW17zz3q-IozuDG-egQAIeXgugVoJ8WRIvJz3NkILl22JMYtajLueBHt6DzsSWXw0pyyU1wzGr_pw1-I-LzakONQMKjk.5XQSZpgWB9fgxSBUCDKvd3csceCcXwJ8hgXGTLOIUrg&dib_tag=se&keywords=Nordic%2BNaturals%2BUltimate%2BOmega%2BCognition&pd_rd_r=dbeef994-8b31-4a6a-965d-1774b9bbb5c4&pd_rd_w=oTInk&pd_rd_wg=3hsHS&qid=1747570281&sr=8-1&th=1",
                "site": "www.iherb.com",
                "price": "$41.33",
                "specs": {
                    "Brand": "Nordic Naturals",
                    "Flavor": "Lemon",
                    "Primary supplement type": "Omega-3",
                    "Unit Count": "180 Count",
                    "Item Form": "Softgel",
                    "Item Weight": "0.69 lb"
                },
                "image_url": "https://m.media-amazon.com/images/I/61x5u8LMFWL._AC_SL1000_.jpg",
                "desc": "High-concentration EPA/DHA (650 mg Omega-3 per soft-gel); IFOS 5-star certified; triglyceride (TG) form for superior absorption. Ideal for cardiovascular health, anti-inflammatory needs, or anyone seeking a highly purified fish oil.",
                "page_description": "**About this item**\n- WHY OMEGA-3s – EPA & DHA support heart, brain, eye and immune health, and help maintain a healthy mood.\n- DOCTOR-RECOMMENDED dose meets American Heart Association guidelines for cardiovascular support.\n- BETTER ABSORPTION & TASTE – Triglyceride form with pleasant lemon flavor and zero fishy burps.\n- PURITY GUARANTEED – Wild-caught fish, non-GMO, gluten- & dairy-free with no artificial additives."
            },
            {
                "id": "fish_02",
                "title": "WHC UnoCardio 1000 ",
                "product_url": "https://www.amazon.com/stores/page/29B9D3D0-5A5E-4EEA-A0A2-D812CA2F8559/?_encoding=UTF8&store_ref=SB_A076637421Z7I7ERZ0TXQ-A03352931L0DK4Z7CLDKO&pd_rd_plhdr=t&aaxitk=49fae88956cfec31cfd29cac8b8abde1&hsa_cr_id=0&lp_asins=B00QFTGSK6%2CB01MQJZI9D%2CB07NLCBPGN&lp_query=WHC%20UnoCardio%201000&lp_slot=desktop-hsa-3psl&ref_=sbx_be_s_3psl_mbd_mb0_logo&pd_rd_w=kHhnR&content-id=amzn1.sym.5594c86b-e694-4e3e-9301-a074f0faf98a%3Aamzn1.sym.5594c86b-e694-4e3e-9301-a074f0faf98a&pf_rd_p=5594c86b-e694-4e3e-9301-a074f0faf98a&pf_rd_r=J95ESAZ01FFJGKDH15S5&pd_rd_wg=udhtB&pd_rd_r=1ca75ded-9d8a-4db4-9e02-4051fdc574f2",
                "site": "www.whc.clinic",
                "price": "$40.45",
                "specs": {
                    "Brand": "WHC",
                    "Flavor": "Natrual Orange",
                    "Primary supplement type": "Omega-3",
                    "Unit Count": "180 Count",
                    "Item Form": "Softgel",
                    "Item Weight": "16.8 ounces"
                },
                "image_url": "https://m.media-amazon.com/images/I/71htaA+bT9L._AC_SL1500_.jpg",
                "desc": "Ranked No. 1 globally by IFOS; Contains 1,000 mg Omega-3 (EPA + DHA) per soft-gel; enriched with vitamin D3; individually blister-packed to prevent oxidation. Ideal for middle-aged and older adults who demand top purity and a premium formulation.",
                "page_description": "**About this item**\n- 1 180 mg total Omega-3 (EPA 665 mg / DHA 445 mg) per soft-gel for heart, brain and vision.\n- Provides 1 000 IU vitamin D3 to support bones, muscles and immunity.\n- r-Triglyceride form for superior absorption; lactose- & gluten-free, burp-free orange flavor.\n- Ultra-pure, Friend-of-the-Sea-certified fish oil in beef-gelatin-free blister packs."
            },
            {
                "id": "fish_03",
                "title": "Now Foods Ultra Omega-3",
                "product_url": "https://www.amazon.com/NOW-Supplements-Molecularly-Distilled-Softgels/dp/B0BGQR8KSG/ref=sr_1_1?crid=1WK5FQS4N6VT9&dib=eyJ2IjoiMSJ9.sczFj7G5tzaluW3utIDJFvN3vRVXIKN8OW6iAI1rL8RiGXrbNcV75KmT0QHEw_-mrjN9Y2Z_QXZcyi9A3KwDB5TpToVICSiFPa7RnnItgqpDWW7DzU2ECbX73MLiBO0nOBcQe4If9EV_QeFtgmERZF360mEcTJ3ZfaxrOKNzI8A.dUyPZz9HZwZJIqkDLMtL5snAfj0y8Ayu3PNq8Ugt-WU&dib_tag=se&keywords=Now%2BFoods%2BUltra%2BOmega-3&qid=1747669011&sprefix=now%2Bfoods%2Bultra%2Bomega-3%2Caps%2C677&sr=8-1&th=1",
                "site": "www.iherb.com",
                "price": "$41.51",
                "specs": {
                    "Brand": "Now Foods",
                    "Flavor": "Unflavoured",
                    "Primary supplement type": "Omega-3",
                    "Unit Count": "180 Count",
                    "Item Form": "Softgel",
                    "Item Weight": "375 g"
                },
                "image_url": "https://m.media-amazon.com/images/I/71auVVCYKnL._AC_SX679_.jpg",
                "desc": "Great value (EPA 500 mg + DHA 250 mg per soft-gel); IFOS certified; suitable for long-term, everyday supplementation. This is ideal for general health maintenance, budget-conscious consumers, and daily nutritional support.",
                "page_description": "**About this item**\n- CARDIOVASCULAR SUPPORT – 600 mg EPA & 300 mg DHA per enteric-coated soft-gel.\n- MOLECULARLY DISTILLED for purity; tested free of PCBs, dioxins & heavy metals.\n- ENTERIC COATING reduces nausea and fishy aftertaste.\n- NON-GMO, Kosher and GMP-quality assured by the family-owned NOW® brand since 1968."
            },
            {
                "id": "fish_04",
                "title": "Blackmores OMEGA BRAIN Caps 60s",
                "product_url": "https://www.amazon.com.au/Blackmores-Omega-Triple-Concentrated-Capsules/dp/B0773JF7JX?th=1",
                "site": "vivanaturals.com",
                "price": "$40.9",
                "specs": {
                    "Brand": "Blackmores",
                    "Flavor": "Lutein",
                    "Primary supplement type": "Omega-3",
                    "Unit Count": "180 Count",
                    "Item Form": "Tablet",
                    "Item Weight": "0.39 Kilograms"
                },
                "image_url": "https://m.media-amazon.com/images/I/71UhUKoWbnL._AC_SL1500_.jpg",
                "desc": "Best-selling Australian pharmacy product; 900 mg Omega-3 per soft-gel; supports cardiovascular health. This is ideal for intensive cardiovascular support, joint health, and individuals seeking a high-dose omega-3 supplement.",
                "page_description": "**About this item**\n- One-a-day capsule delivers 500 mg DHA to maintain brain health and mental performance.\n- Provides four-times more DHA than standard fish oil—ideal if you eat little fish.\n- 100 % wild-caught small-fish oil rigorously tested for mercury, dioxins & PCBs.\n- Supports healthy growth in children and overall wellbeing for all ages."
            },
            {
                "id": "fish_05",
                "title": "Möller’s Norwegian Cod-Liver Oil",
                "product_url": "https://www.amazon.com.be/-/en/Mollers-Omega-Norwegian-Cod-Liver-Pruners/dp/B074XB9RNH?language=en_GB",
                "site": "www.mollers.no",
                "price": "$40.63",
                "specs": {
                    "Brand": "Möller’s",
                    "Flavor": "Lofoten",
                    "Primary supplement type": "Fish Oil",
                    "Unit Count": "8.4 Fluid Ounces",
                    "Item Form": "Liquid",
                    "Item Weight": "1.1 Pounds"
                },
                "image_url": "https://m.media-amazon.com/images/I/61eg-Vgm97L._AC_SL1500_.jpg",
                "desc": "Liquid fish oil enriched with natural vitamins A and D; trusted Nordic brand with over 100 years of history; suitable for children and pregnant women. This is ideal for family supplementation, children’s health, pregnancy nutritional support, and enhancing immune function.",
                "page_description": "**About this item**\n- Natural source of EPA & DHA to support heart, brain and vision.\n- Supplies vitamins A & D for immune function and normal bone growth.\n- Sustainably sourced Arctic cod and bottled under Norway’s century-old Möller’s quality standards.\n- Refreshing lemon flavor with no fishy aftertaste; kid- and pregnancy-friendly."
            },
        ]
    # 如果搜索里包含'liver'
    elif ("liver" in lower_q):
        return [
            {
                "id": "liver_01",
                "title": "Thorne Liver Cleanse",
                "product_url": "https://www.amazon.com/Thorne-Research-Cleanse-Detoxification-Capsules/dp/B07978NYC5",
                "site": "https://www.amazon.com/Thorne-Research-Cleanse-Detoxification-Capsules/dp/B07978NYC5",
                "image_url": "https://m.media-amazon.com/images/I/71eMoaqvJyL._AC_SL1500_.jpg",
                "desc": "Professional-grade formula that combines milk thistle (125 mg silymarin), burdock, chicory, berberine, and other botanicals; NSF-Certified for Sport®; produced in a GMP-compliant U.S. facility. This is ideal for individuals looking for a broad-spectrum botanical detox blend—especially those who value third-party testing and athlete-friendly certifications.",
                "page_description": "**About this item**\n- Synergistic botanical blend enhances detoxification and bile flow.*\n- Supports both Phase I and Phase II liver detox pathways.*\n- Also provides kidney-supportive herbs for comprehensive clearance.*\n- NSF Certified for Sport® and third-party tested for contaminants."
            },
            {
                "id": "liver_02",
                "title": "Himalaya LiverCare (Liv 52 DS)",
                "product_url": "https://www.amazon.com.be/-/en/Himalaya-Liv-52-DS-3-Pack/dp/B09MF88N71",
                "site": "www.whc.clinic",
                "image_url": "https://m.media-amazon.com/images/I/61VEN7Bl8wL._AC_SL1500_.jpg",
                "desc": "Clinically studied Ayurvedic blend (capers, chicory, black nightshade, arjuna, yarrow, etc.) shown to improve Child-Pugh scores and reduce ALT/AST in liver-compromised patients. This is ideal for those seeking a time-tested herbal formula with human-trial evidence, including individuals with mild enzyme elevations or high environmental/toxic exposure.",
                "page_description": "**About this item**\n- Herbal liver-cleanse formula that helps detoxify and protect liver cells.*\n- Boosts metabolic capacity and promotes healthy bile production for digestion.*\n- Vegan caplets free of gluten, dairy, soy, corn, nuts and animal gelatin; non-GMO.\n- Trusted Ayurvedic brand since 1930 with decades of clinical research."
            },
            {
                "id": "liver_03",
                "title": "Jarrow Formulas Milk Thistle (150 mg)",
                "product_url": "https://www.amazon.com/Jarrow-Formulas-Silymarin-Marianum-Promotes/dp/B0013OULVA?th=1",
                "site": "https://www.amazon.com/Jarrow-Formulas-Silymarin-Marianum-Promotes/dp/B0013OULVA?th=1",
                "image_url": "https://m.media-amazon.com/images/I/71G03a0TYUL._AC_SL1500_.jpg",
                "desc": "It contains 30:1 standardized silymarin phytosome bonded to phosphatidylcholine for up-to-30× higher bioavailability than conventional milk thistle; vegetarian capsules; gluten-, soy-, and dairy-free. This is ideal for people who need a concentrated, highly absorbable milk-thistle extract—e.g., those on multiple medications or with occasional alcohol use.",
                "page_description": "**About this item**\n- 150 mg 30:1 milk-thistle extract standardized to 80 % silymarin flavonoids.\n- Helps raise glutathione levels for healthy liver detoxification.*\n- Provides antioxidant protection against free-radical damage.*\n- Easy-to-swallow veggie capsules; adults take 1–3 daily as directed."
            },
            {
                "id": "liver_04",
                "title": "NOW Foods Liver Refresh™",
                "product_url": "https://www.amazon.com/Liver-Refresh-Capsules-NOW-Foods/dp/B001EQ92VW?th=1",
                "site": "vivanaturals.com",
                "image_url": "https://m.media-amazon.com/images/I/71fW7Z6vFAL._AC_SL1500_.jpg",
                "desc": "Synergistic blend of milk thistle, N-acetyl cysteine (NAC), methionine, and herbal antioxidants; non-GMO Project Verified and GMP-qualified. This is ideal for individuals wanting comprehensive antioxidant support—such as frequent travelers, people with high oxidative stress, or those following high-protein diets.",
                "page_description": "**About this item**\n- Promotes optimal liver health with milk thistle plus herbal-enzyme blend.*\n- Supports healthy detoxification processes and normal liver enzyme levels.*\n- Non-GMO, vegetarian capsules produced in a GMP-certified facility.\n- Amazon’s Choice pick with thousands of 4-plus-star reviews."
            },
            {
                "id": "liver_05",
                "title": "Nutricost TUDCA 250 mg",
                "product_url": "https://www.amazon.com/Nutricost-Tudca-250mg-Capsules-Tauroursodeoxycholic/dp/B01A68H2BA?th=1",
                "site": "www.mollers.no",
                "image_url": "https://m.media-amazon.com/images/I/61EJx7JnxfL._AC_SL1500_.jpg",
                "desc": "Pure tauroursodeoxycholic acid (TUDCA) at 250 mg per veggie capsule; non-GMO, soy- and gluten-free; 3rd-party ISO-accredited lab tested; made in an FDA-registered, GMP facility. This is ideal for advanced users seeking bile-acid–based cellular protection—popular among those with cholestatic or high-fat-diet concerns.",
                "page_description": "**About this item**\n- 250 mg TUDCA per capsule—research-backed bile acid for liver & cellular health.*\n- Convenient one-capsule daily serving; 60-count bottle is a two-month supply.\n- Non-GMO, soy- and gluten-free formula; ISO-accredited third-party tested.\n- Made in a GMP-compliant, FDA-registered U.S. facility."
            },
        ]
    else:
        # 默认结果
        return [
            {"title": "通用搜索结果1", "url": "https://example.com/result1"},
            {"title": "通用搜索结果2", "url": "https://example.com/result2"}
        ]


# def show_google_search(with_ads: bool):
#     col1, col2 = st.columns([6, 1])
#     with col1:
#         st.title("Querya search")
#     with col2:
#         end_clicked = st.button("Finish / End Session", key=f"end_button_{st.session_state.get('variant', '')}")
#
#     if end_clicked:
#         # Full-screen centered message (clears interface)
#         # st.session_state["end_clicked"] = True
#         click_data = {
#             "id": st.session_state.get("prolific_id", "unknown"),
#             "start": st.session_state.get("start_time", datetime.now().isoformat()),
#             "timestamp": datetime.now().isoformat(),
#             "type": "end",
#             "title": "Finish / End Session",
#             "url": " "
#         }
#         save_to_gsheet(click_data)
#         st.session_state.stage = "survey"
#         st.rerun()  # Re-run to show the message cleanly in next render
#
#     # After rerun
#     if st.session_state.get("end_clicked", False):
#         st.markdown("<br><br><br>", unsafe_allow_html=True)
#         st.markdown(
#             "<h1 style='text-align:center;'>✅ Session ended. Thank you!</h1>",
#             unsafe_allow_html=True
#         )
#         st.stop()
#
#     if "search_results" not in st.session_state:
#         st.session_state.search_results = []
#
#
#
#     def to_base64(path: str) -> str:
#         return base64.b64encode(Path(path).read_bytes()).decode()
#
#     try:
#         logo_b64 = to_base64("querya.png")
#         st.markdown(
#             f"""
#             <div style="text-align:center; margin-top:20px;">
#                 <img src="data:image/png;base64,{logo_b64}" style="height:80px;" />
#             </div>
#             """,
#             unsafe_allow_html=True
#         )
#     except:
#         st.write("Querya Search")
#
#     # Query box
#     query = st.text_input("", placeholder="Input Key Words for Search Here (e.g., best fish oil supplements)")
#     st.caption("Or pick one of the suggested queries:")
#     chosen = render_suggestion_chips(SUGGESTED_QUERIES_SEARCH, "sug_search")
#
#     # If a chip is chosen, execute search immediately (acts like pressing Search)
#     if chosen:
#         results = do_fake_google_search(chosen)
#         st.session_state.search_results = results
#         if with_ads:
#             st.session_state.current_ads = get_products_by_query(chosen)
#         save_to_gsheet({
#             "id": st.session_state.prolific_id,
#             "start": st.session_state.start_time,
#             "timestamp": datetime.now().isoformat(),
#             "type": "search_submit",
#             "title": chosen,
#             "url": " "
#         })
#         st.rerun()
#
#     if st.button("Search"):
#         results = do_fake_google_search(query)
#         st.session_state.search_results = results
#         if with_ads:
#             st.session_state.current_ads = get_products_by_query(query)
#         save_to_gsheet({
#             "id": st.session_state.prolific_id,
#             "start": st.session_state.start_time,
#             "timestamp": datetime.now().isoformat(),
#             "type": "search_submit",
#             "title": query,
#             "url": " "
#         })
#
#     # Show stored search results
#     if st.session_state.search_results:
#         st.write("---")
#         if with_ads:
#             if "current_ads" not in st.session_state:
#                 st.session_state.current_ads = []
#             if st.session_state.current_ads:
#                 show_advertisements(st.session_state.current_ads)
#         st.write("**Search Results:**")
#
#         for item in st.session_state.search_results:
#             show_product_item(item, link_type="organic", show_image=True, image_position="below")
#
#             if item["desc"]:
#                 st.write(item["desc"])
#             st.write("---")
#
#     # Show ads if any
def show_google_search(with_ads: bool):
    # ===== Header =====
    col1, col_mid, col2 = st.columns([5.6, 1.6, 1])
    with col1:
        st.title("Querya search")
    with col_mid:
        instructions_button_inline()
    with col2:
        end_clicked = st.button("Finish / End Session", key="end_button_inline")

    if end_clicked:
        save_to_gsheet({
            "id": st.session_state.get("prolific_id", "unknown"),
            "start": st.session_state.get("start_time", datetime.now().isoformat()),
            "timestamp": datetime.now().isoformat(),
            "type": "finish_click",
            "title": "Finish / End Session",
            "url": " "
        })
        st.session_state.stage = "survey"
        st.rerun()

    # ===== State =====
    st.session_state.setdefault("search_results", [])
    st.session_state.setdefault("current_ads", [])
    st.session_state.setdefault("search_started", False)  # 控制是否隐藏建议

    # ===== (可选) Logo =====
    def to_base64(path: str) -> str:
        return base64.b64encode(Path(path).read_bytes()).decode()

    try:
        logo_b64 = to_base64("querya.png")
        st.markdown(
            f"<div style='text-align:center; margin-top:20px;'><img src='data:image/png;base64,{logo_b64}' style='height:80px;' /></div>",
            unsafe_allow_html=True
        )
    except Exception:
        st.write("Querya Search")

    # ===== 搜索执行辅助：统一结果、广告、日志 =====
    def run_search(q: str):
        q = (q or "").strip()
        if not q:
            return
        # 1) 获取结果：优先用你原来的 do_fake_google_search；如果不存在，就用 fallback
        results = None
        try:
            # 如果你把 do_fake_google_search 定义在本函数里，保留原实现即可
            results = do_fake_google_search(q)  # noqa: F821  # 由你现有代码提供
        except Exception:
            # fallback：用广告产品生成简单“自然结果”，保证不报错
            simple = []
            for p in get_products_by_query(q):
                simple.append({
                    "id": p.get("id", ""),
                    "title": p.get("title", ""),
                    "product_url": p.get("product_url", " "),
                    "site": "",
                    "image_url": p.get("image_url", ""),
                    "desc": p.get("description", ""),
                    "page_description": p.get("page_description", "")
                })
            results = simple

        st.session_state.search_results = results or []

        # 2) 写入广告（如果有广告条件）
        st.session_state.current_ads = get_products_by_query(q) if with_ads else []

        # 3) 日志
        save_to_gsheet({
            "id": st.session_state.prolific_id,
            "start": st.session_state.start_time,
            "timestamp": datetime.now().isoformat(),
            "type": "search_submit",
            "title": q,
            "url": " "
        })

    # ===== 建议查询（chips）——仅在首次搜索前显示 =====
    # SUGGESTED_QUERIES_SEARCH = [
    #     "best fish oil supplements",
    #     "top omega‑3 fish oils",
    #     "fish oil for heart health",
    #     "high EPA DHA fish oil",
    #     "omega‑3 for brain function"
    # ]

    if not st.session_state.search_started:
        # —— 首搜前：输入框 + 建议 chips ——
        query = st.text_input(
            "",
            placeholder="Input Key Words for Search Here (e.g., best fish oil supplements)",
            key="first_search_query"
        )
        st.caption("Or pick one of the suggested queries:")

        # 简单 3 列 chips；若你已实现 render_suggestion_chips(...)，也可改用那个
        chosen = render_suggestion_chips(SUGGESTED_QUERIES_SEARCH, "sug_search")

        # —— 选择了建议：立即搜索 + 隐藏建议 ——
        if chosen:
            st.session_state.search_started = True
            run_search(chosen)
            st.rerun()

        # —— 点击 Search：立即搜索 + 隐藏建议 ——
        if st.button("Search", key="btn_search_first"):
            st.session_state.search_started = True
            run_search(query)
            st.rerun()

        # 首搜前不渲染结果
        return

    else:
        # —— 首搜之后：不再显示 chips（可保留一个再次搜索输入框；不要求可删除） ——
        query2 = st.text_input("", placeholder="Search again (optional)", key="search_again")
        if st.button("Search", key="btn_search_again"):
            run_search(query2)
            st.rerun()

    # ===== Render results (Organic first → Ads below) =====
    if st.session_state.search_results:
        st.write("---")

        # Ads box on top (more visible)
        if with_ads and st.session_state.current_ads:
            show_advertisements(st.session_state.current_ads)
            st.write("---")

        st.write("**Search Results:**")
        for item in st.session_state.search_results:
            show_product_item(item, link_type="organic", show_image=True, image_position="below")
            if item.get("desc"):
                st.write(item["desc"])
            st.write("---")


############################################
# Earbuds AI-only experiment overrides
############################################

EARBUD_KEYWORDS = (
    "earbud", "earbuds", "earphone", "earphones", "headphone", "headphones",
    "wireless", "bluetooth", "tws", "buds", "ear buds",
)

ORGANIC_EARBUD_PRODUCTS = [
    {
        "id": "earbuds_org_01",
        "title": "TOZO A1 Mini Wireless Earbuds",
        "product_url": "https://www.amazon.com/dp/B09FT58QQP",
        "image_url": "https://m.media-amazon.com/images/I/41766A8gWtL._SL500_.jpg",
        "price": "$19.99",
        "specs": {
            "Brand": "TOZO",
            "Model Name": "A1 Mini",
            "Form Factor": "In Ear",
            "Connectivity": "Wireless Bluetooth",
            "Bluetooth Version": "5.3",
            "Battery Life": "Up to 32 hours with charging case",
            "Water Resistance": "IPX5",
        },
        "description": "- Features: Ultra-light mini earbuds with app-based EQ presets, clear call microphones, and a compact charging case.\n- Ideal for: Everyday listening, small ears, workouts, and shoppers who want a low-cost portable pair.",
        "page_description": "**About this item**\n- Lightweight in-ear design made for comfortable daily wear.\n- Bluetooth 5.3 connection supports quick pairing and stable listening.\n- App EQ presets let users adjust the sound profile for music, podcasts, or calls.\n- IPX5 water resistance helps with sweat and light rain during workouts.",
    },
    {
        "id": "earbuds_org_02",
        "title": "SOUNDPEATS Clear Wireless Earbuds",
        "product_url": "https://www.amazon.com/dp/B0CJV9ZDLK",
        "image_url": "https://goodio.be/media/cache/sylius_shop_product_original/55/8d/61eacea39d6fdf3753efd72c5ce2.webp",
        "price": "$29.99",
        "specs": {
            "Brand": "SOUNDPEATS",
            "Model Name": "Clear",
            "Form Factor": "In Ear",
            "Connectivity": "Wireless Bluetooth",
            "Bluetooth Version": "5.3",
            "Battery Life": "Up to 40 hours with charging case",
            "Driver": "12 mm dynamic driver",
        },
        "description": "- Features: Transparent case design, 12 mm drivers, dual microphones, game mode, and app control.\n- Ideal for: Budget-conscious users who want a distinctive look and long battery life.",
        "page_description": "**About this item**\n- 12 mm dynamic drivers deliver a full casual-listening sound.\n- Up to 40 hours total playtime with the charging case.\n- Dual microphones support clearer everyday calls.\n- Game mode and app controls help customize the listening experience.",
    },
    {
        "id": "earbuds_org_03",
        "title": "EarFun Free 2S Wireless Earbuds",
        "product_url": "https://www.amazon.com/dp/B0BF4XGC1K",
        "image_url": "https://m.media-amazon.com/images/I/419f26NHa0L._SL500_.jpg",
        "price": "$39.99",
        "specs": {
            "Brand": "EarFun",
            "Model Name": "Free 2S",
            "Form Factor": "In Ear",
            "Connectivity": "Wireless Bluetooth",
            "Bluetooth Version": "5.2",
            "Codec Support": "aptX, SBC, AAC",
            "Water Resistance": "IPX7",
        },
        "description": "- Features: Qualcomm chip, aptX audio support, customizable EQ, low-latency mode, and IPX7 waterproofing.\n- Ideal for: Users who want stronger codec support and a balanced everyday earbud.",
        "page_description": "**About this item**\n- Qualcomm Bluetooth chipset supports aptX audio and stable wireless playback.\n- Low-latency mode helps reduce delay for videos and casual gaming.\n- Customizable EQ allows tuning through the companion app.\n- IPX7 waterproof rating supports workout and commute use.",
    },
    {
        "id": "earbuds_org_04",
        "title": "JLab Go Air Pop True Wireless Earbuds",
        "product_url": "https://www.amazon.com/dp/B09HN594TL",
        "image_url": "https://www.jlab.com/cdn/shop/files/JLab-GO-Air-Pop-True-Wireless-Earbuds-Black-Front_3ce6e2a3-5174-4bad-a377-4fae954af28a.jpg?v=1762446369",
        "price": "$24.99",
        "specs": {
            "Brand": "JLab",
            "Model Name": "Go Air Pop",
            "Form Factor": "In Ear",
            "Connectivity": "Wireless Bluetooth",
            "Bluetooth Version": "5.1",
            "Battery Life": "Up to 32 hours total",
            "Water Resistance": "IPX4",
        },
        "description": "- Features: Compact case, dual-connect earbuds, built-in EQ modes, and an integrated charging cable.\n- Ideal for: Backup earbuds, commuting, gym bags, and shoppers seeking a simple low-cost option.",
        "page_description": "**About this item**\n- Up to 8 hours per earbud and up to 32 hours with the charging case.\n- Dual Connect lets either earbud be used independently.\n- Three built-in EQ sound settings support different listening preferences.\n- Compact case includes an integrated charging cable for convenience.",
    },
    {
        "id": "earbuds_org_05",
        "title": "Baseus Bowie MA10 Wireless Earbuds",
        "product_url": "https://www.amazon.com/s?k=Baseus+Bowie+MA10+Wireless+Earbuds",
        "image_url": "https://baseus.com.au/cdn/shop/files/Baseus_Bowie_MA10_True_Wireless_Earphones_Cluster_Black_10.jpg?v=1736399643",
        "price": "$29.99",
        "specs": {
            "Brand": "Baseus",
            "Model Name": "Bowie MA10",
            "Form Factor": "In Ear",
            "Connectivity": "Wireless Bluetooth",
            "Bluetooth Version": "5.3",
            "Noise Control": "Hybrid ANC",
            "Battery Life": "Up to 140 hours with charging case",
        },
        "description": "- Features: Hybrid active noise cancellation, large charging case capacity, IPX6 waterproofing, and low-latency mode.\n- Ideal for: Long trips, office use, and buyers prioritizing battery life and ANC at a budget price.",
        "page_description": "**About this item**\n- Hybrid ANC reduces background noise for commuting and work sessions.\n- Large-capacity charging case supports up to 140 hours of total playtime.\n- Bluetooth 5.3 supports quick connection and low-latency listening.\n- IPX6 water resistance helps protect against sweat and splashes.",
    },
]

SPONSORED_EARBUD_PRODUCTS = [
    {
        "id": "earbuds_ad_01",
        "title": "TAGRY X08 True Wireless Earbuds",
        "product_url": "https://www.amazon.com/dp/B09DT48V16",
        "image_url": "https://tagrystore.com/cdn/shop/files/8_41ffd5b9-7fa2-4695-8f10-f646d338363b.png?v=1776242235",
        "price": "$35.99",
        "specs": {
            "Brand": "TAGRY",
            "Model Name": "X08",
            "Form Factor": "In Ear",
            "Connectivity": "Wireless Bluetooth",
            "Bluetooth Version": "5.3",
            "Battery Life": "Up to 60 hours with charging case",
            "Water Resistance": "IPX5",
        },
        "description": "- Sponsored features: LED power display, wireless charging case, 60-hour total playback, and IPX5 waterproofing.\n- Ideal for: Users who want visible battery status and long playback time.",
        "page_description": "**About this item**\n- Dual LED display shows battery level for the charging case and earbuds.\n- Charging case supports wireless charging and USB-C charging.\n- Up to 60 hours total playtime with the charging case.\n- Bluetooth 5.3 and built-in microphone support daily calls and listening.",
        "sponsored": True,
    },
    {
        "id": "earbuds_ad_02",
        "title": "PocBuds 80H Bluetooth Headphones",
        "product_url": "https://www.amazon.com/dp/B0C3W4MNN1",
        "image_url": "https://m.media-amazon.com/images/I/41a13oczERL._AC_.jpg",
        "price": "$49.99",
        "specs": {
            "Brand": "PocBuds",
            "Model Name": "80H Sports Earbuds",
            "Form Factor": "Over Ear",
            "Connectivity": "Wireless Bluetooth",
            "Bluetooth Version": "5.3",
            "Battery Life": "Up to 80 hours with charging case",
            "Water Resistance": "IPX7",
        },
        "description": "- Sponsored features: Earhook fit, 80-hour total playback, dual digital display, wireless charging, and IPX7 waterproofing.\n- Ideal for: Running, gym use, and buyers who prefer over-ear hooks.",
        "page_description": "**About this item**\n- Earhook design helps keep earbuds stable during workouts.\n- Dual LED display shows remaining charging-case and earbud power.\n- Up to 80 hours total playback with the charging case.\n- IPX7 waterproof rating supports sports and outdoor use.",
        "sponsored": True,
    },
    {
        "id": "earbuds_ad_03",
        "title": "BMANI T16 Wireless Earbuds",
        "product_url": "https://www.amazon.com/dp/B09FLNSYDZ",
        "image_url": "https://m.media-amazon.com/images/I/41kYmsfm90L._SL500_.jpg",
        "price": "$25.98",
        "specs": {
            "Brand": "BMANI",
            "Model Name": "T16",
            "Form Factor": "Over Ear",
            "Connectivity": "Wireless Bluetooth",
            "Bluetooth Version": "5.0",
            "Battery Life": "Up to 48 hours with charging case",
            "Control Type": "Button control",
        },
        "description": "- Sponsored features: Sports earhooks, LED charging display, button controls, and water-resistant design.\n- Ideal for: Workouts, running, and users who prefer physical buttons over touch controls.",
        "page_description": "**About this item**\n- Over-ear hooks provide a secure fit for exercise.\n- LED charging display makes remaining battery easy to check.\n- Button controls reduce accidental touch inputs during activity.\n- Built-in microphone supports calls from phones, tablets, and laptops.",
        "sponsored": True,
    },
    {
        "id": "earbuds_ad_04",
        "title": "CAPOXO 120H Wireless Earbuds",
        "product_url": "https://www.amazon.com/dp/B0C6TTG88V",
        "image_url": "https://m.media-amazon.com/images/I/41MQ94XYlML._AC_SL1500_.jpg",
        "price": "$39.99",
        "specs": {
            "Brand": "CAPOXO",
            "Model Name": "D8",
            "Form Factor": "Over Ear",
            "Connectivity": "Wireless Bluetooth",
            "Bluetooth Version": "5.3",
            "Battery Life": "Up to 120 hours with charging case",
            "Water Resistance": "IPX7",
        },
        "description": "- Sponsored features: 2600 mAh power-display charging case, over-ear hooks, 120-hour total playback, and IPX7 waterproofing.\n- Ideal for: Heavy listeners and sports users who want a high-capacity case.",
        "page_description": "**About this item**\n- High-capacity charging case supports extended use between charges.\n- Power display helps track the charging case battery level.\n- Over-ear hooks improve stability for running and workouts.\n- IPX7 waterproof design helps protect against sweat and rain.",
        "sponsored": True,
    },
    {
        "id": "earbuds_ad_05",
        "title": "Kurdene Wireless Earbuds Bluetooth 5.3",
        "product_url": "https://www.amazon.com/dp/B0D635YLCT",
        "image_url": "https://m.media-amazon.com/images/I/715fNrGN%2BML._AC_SL1500_.jpg",
        "price": "$19.99",
        "specs": {
            "Brand": "Kurdene",
            "Model Name": "P3",
            "Form Factor": "In Ear",
            "Connectivity": "Wireless Bluetooth",
            "Bluetooth Version": "5.3",
            "Battery Life": "Up to 48 hours with charging case",
            "Microphones": "Built-in clear-call mics",
        },
        "description": "- Sponsored features: Lightweight fit, deep bass tuning, Bluetooth 5.3, clear-call microphones, and long battery life.\n- Ideal for: Budget shoppers seeking simple earbuds for music, calls, and workouts.",
        "page_description": "**About this item**\n- 8 mm drivers are tuned for enhanced bass in a compact earbud body.\n- Bluetooth 5.3 supports fast pairing and stable daily use.\n- Built-in microphones support clearer hands-free calls.\n- Lightweight ergonomic design is intended for extended wear.",
        "sponsored": True,
    },
]


def _earbud_product_slot(product: dict, slot_id: str, *, sponsored: bool) -> dict:
    """Copy a product into its current experimental slot without mutating the source stimulus."""
    copied = dict(product)
    copied["specs"] = dict(product.get("specs", {}))
    copied["id"] = slot_id
    if sponsored:
        copied["sponsored"] = True
        if copied.get("description", "").startswith("- Features:"):
            copied["description"] = copied["description"].replace("- Features:", "- Sponsored features:", 1)
    else:
        copied.pop("sponsored", None)
        if copied.get("description", "").startswith("- Sponsored features:"):
            copied["description"] = copied["description"].replace("- Sponsored features:", "- Features:", 1)
    return copied


_ORIGINAL_ORGANIC_EARBUD_PRODUCTS = ORGANIC_EARBUD_PRODUCTS
_ORIGINAL_SPONSORED_EARBUD_PRODUCTS = SPONSORED_EARBUD_PRODUCTS

ORGANIC_EARBUD_PRODUCTS = [
    _earbud_product_slot(_ORIGINAL_SPONSORED_EARBUD_PRODUCTS[1], "earbuds_org_01", sponsored=False),
    _earbud_product_slot(_ORIGINAL_ORGANIC_EARBUD_PRODUCTS[1], "earbuds_org_02", sponsored=False),
    _earbud_product_slot(_ORIGINAL_ORGANIC_EARBUD_PRODUCTS[2], "earbuds_org_03", sponsored=False),
    _earbud_product_slot(_ORIGINAL_ORGANIC_EARBUD_PRODUCTS[3], "earbuds_org_04", sponsored=False),
    _earbud_product_slot(_ORIGINAL_SPONSORED_EARBUD_PRODUCTS[2], "earbuds_org_05", sponsored=False),
]

SPONSORED_EARBUD_PRODUCTS = [
    _earbud_product_slot(_ORIGINAL_SPONSORED_EARBUD_PRODUCTS[0], "earbuds_ad_01", sponsored=True),
    _earbud_product_slot(_ORIGINAL_ORGANIC_EARBUD_PRODUCTS[0], "earbuds_ad_02", sponsored=True),
    _earbud_product_slot(_ORIGINAL_ORGANIC_EARBUD_PRODUCTS[4], "earbuds_ad_03", sponsored=True),
    _earbud_product_slot(_ORIGINAL_SPONSORED_EARBUD_PRODUCTS[3], "earbuds_ad_04", sponsored=True),
    _earbud_product_slot(_ORIGINAL_SPONSORED_EARBUD_PRODUCTS[4], "earbuds_ad_05", sponsored=True),
]

PRODUCT_CATALOG = {p["title"]: p for p in ORGANIC_EARBUD_PRODUCTS}
PRODUCT_CATALOG.update({p["title"]: p for p in SPONSORED_EARBUD_PRODUCTS})

KEYWORD_RESPONSES = {
    "wireless earbuds": ORGANIC_EARBUD_PRODUCTS,
    "bluetooth earbuds": ORGANIC_EARBUD_PRODUCTS,
    "earbuds": ORGANIC_EARBUD_PRODUCTS,
    "earphones": ORGANIC_EARBUD_PRODUCTS,
    "headphones": ORGANIC_EARBUD_PRODUCTS,
}

PREDEFINED_HEADINGS = {
    "wireless earbuds": (
        "Certainly! Here are some wireless Bluetooth earbuds to consider, "
        "selected for everyday listening, portability, battery life, and value."
    ),
}

SUGGESTED_QUERIES_AI = [
    "Can you recommend some wireless Bluetooth earbuds?",
    "Please recommend some budget wireless earbuds.",
    "Which Bluetooth earbuds are good for everyday use?",
    "Any wireless earbud recommendations?",
]
SUGGESTED_QUERIES_SEARCH = SUGGESTED_QUERIES_AI


def _is_earbuds_query(user_text: str) -> bool:
    lower = (user_text or "").lower()
    return any(keyword in lower for keyword in EARBUD_KEYWORDS)


def _condition_label_for_variant(v: int) -> str:
    return {
        1: "AI Assistant with Ads",
        2: "AI Assistant with Free-Service Ads Message",
    }.get(v, "AI Assistant")


def _build_instructions_md(is_ai: bool, with_ads: bool) -> str:
    v = st.session_state.get("variant", 1)
    try:
        v = int(v)
    except Exception:
        v = 1
    ads_sentence = ""
    body = (
        "Imagine you are shopping for **wireless Bluetooth earbuds**.\n\n"
        "To help you decide which product to purchase, you will use an **AI chatbot** (\"Querya\") "
        "to get some recommended products to consider."
        f"{ads_sentence}\n\n"
        "**Please follow these steps:**\n"
        "1. **Click the `Next / Start` button** below to open the AI chatbot.\n"
        "2. **Ask for product recommendations.** For example, you might type:\n"
        "   - \"Can you recommend some wireless Bluetooth earbuds?\"\n"
        "   - \"Please recommend some budget wireless earbuds.\"\n"
        "3. **Treat this task as if you were genuinely shopping for yourself.** "
        "Feel free to explore the recommended products by clicking their links and viewing them naturally.\n"
        "4. **If you're interested in any product**, you may click the **`Add to Cart`** button at the top-right corner of its page.\n"
        "5. **When you're done browsing**, close the AI chatbot by selecting **`Finish / End Session`** in the top-right corner of the conversation page.\n"
        "6. **Finally**, complete a short questionnaire about your experience."
    )
    return f"### Instructions\n{body}"


def render_instructions_page():
    v, is_ai, with_ads, group_label = get_variant_flags()
    st.markdown(_build_instructions_md(is_ai, with_ads))

    HOLD_SECONDS = 20
    timer_key = f"instructions_start_ts_v{v}"
    if timer_key not in st.session_state:
        st.session_state[timer_key] = time.time()

    instructions_start_ts = st.session_state[timer_key]
    elapsed = int(time.time() - instructions_start_ts)
    remaining = max(0, HOLD_SECONDS - elapsed)
    components.html(
        f"""
        <div style="font-family:system-ui, -apple-system, Segoe UI, sans-serif; font-size:14px; color:#475569;">
          Minimum reading time: <strong>{HOLD_SECONDS}s</strong>
          <span style="margin-left:10px;">Remaining: <strong id="instruction-countdown">{remaining}</strong>s</span>
        </div>
        <script>
        const initialRemaining = {remaining};
        const startedAtPerf = performance.now();
        const el = document.getElementById("instruction-countdown");
        let timer = null;
        function tick() {{
          const elapsed = Math.floor((performance.now() - startedAtPerf) / 1000);
          const remaining = Math.max(0, initialRemaining - elapsed);
          if (el) {{
            el.textContent = remaining;
          }}
          if (remaining <= 0 && timer !== null) {{
            clearInterval(timer);
          }}
        }}
        tick();
        timer = setInterval(tick, 250);
        </script>
        """,
        height=36,
    )

    next_clicked = st.button("Next")
    if next_clicked:
        if remaining > 0:
            st.error(f"Please read the instructions for at least 20 seconds before proceeding. {remaining}s remaining.")
            log_event("instructions_next_too_early", f"{group_label} | ads={with_ads} | remaining={remaining}s")
            return

        log_event("enter_experiment", f"{group_label} | ads={with_ads}")
        st.session_state.stage = "experiment"
        st.rerun()


def get_predefined_response(user_text: str):
    if _is_earbuds_query(user_text):
        return ORGANIC_EARBUD_PRODUCTS
    return None


def get_products_by_query(query: str):
    return SPONSORED_EARBUD_PRODUCTS if _is_earbuds_query(query) else []


def show_advertisements(relevant_products):
    v, _, _, _ = get_variant_flags()

    with st.container(border=True):
        st.markdown("<div id='ad-box-anchor'></div>", unsafe_allow_html=True)
        free_service_message = (
            "<span style='display:inline-flex; align-items:center; background:#f1f1f1; "
            "color:#111; font-size:16px; line-height:1; padding:8px 16px; "
            "border-radius:4px; min-height:29px;'>"
            "Advertising helps keep this AI service free for users.</span>"
            if v == 2
            else ""
        )
        st.markdown(
            "<div style='display:flex; align-items:center; gap:10px; flex-wrap:nowrap; "
            "margin:0 0 12px 0; min-height:32px;'>"
            "<span style='display:inline-flex; align-items:center; background:#e53935; "
            "color:#fff; font-size:13px; font-weight:600; line-height:1; "
            "padding:4px 10px; border-radius:4px; white-space:nowrap;'>"
            "Querya Advertising</span>"
            f"{free_service_message}"
            "</div>",
            unsafe_allow_html=True,
        )

        n, col_count = len(relevant_products), 5
        rows = math.ceil(n / col_count)
        for r in range(rows):
            cols = st.columns(col_count, gap="small")
            for c in range(col_count):
                idx = r * col_count + c
                if idx < n:
                    with cols[c]:
                        show_product_item(
                            relevant_products[idx],
                            link_type="ad",
                            show_image=True,
                            orientation="vertical",
                        )


def display_earbud_assistant_reply(content, link_type="organic"):
    if isinstance(content, list):
        render_predefined_products(
            content,
            PREDEFINED_HEADINGS["wireless earbuds"],
            link_type=link_type,
        )
    else:
        display_parsed_markdown(content, link_type=link_type)


def show_deepseek_recommendation(with_ads: bool):
    """AI-only earbuds condition with optional fixed sponsored products."""
    col1, col_mid, col2 = st.columns([5.6, 1.6, 1])
    with col1:
        st.title("Querya Rec")
    with col_mid:
        instructions_button_inline()
    with col2:
        end_clicked = st.button("Finish / End Session", key=f"end_button_{st.session_state.get('variant', '')}")

    if end_clicked:
        log_event("end", "Finish / End Session")
        st.session_state.stage = "survey"
        st.rerun()

    st.session_state.setdefault("history", [
        ("system", "You are an e-commerce chat assistant who recommends wireless Bluetooth earbuds based on user needs.")
    ])
    st.session_state.setdefault("first_message_submitted", False)
    st.session_state.setdefault("pending_first_message", None)
    st.session_state.setdefault("current_ads", [])

    ads_inserted = False
    for role, content in st.session_state.history:
        if role == "system":
            continue
        if role == "assistant":
            if with_ads and (not ads_inserted) and st.session_state.get("current_ads"):
                show_advertisements(st.session_state.current_ads)
                ads_inserted = True
            with st.chat_message("assistant"):
                display_earbud_assistant_reply(content, link_type="deepseek")
        else:
            st.chat_message(role).write(content)

    if st.session_state.first_message_submitted and st.session_state.pending_first_message:
        user_first_input = st.session_state.pending_first_message
        st.session_state.pending_first_message = None

        log_event("first_query", user_first_input)

        prods = get_products_by_query(user_first_input) if with_ads else []
        st.session_state.current_ads = prods
        if with_ads and prods:
            show_advertisements(prods)

        predefined = get_predefined_response(user_first_input)
        if predefined:
            assistant_text = predefined
            with st.chat_message("assistant"):
                render_predefined_products(
                    predefined,
                    PREDEFINED_HEADINGS["wireless earbuds"],
                    link_type="organic",
                )
        else:
            resp = client.chat_completions.create(
                model="deepseek-chat",
                messages=[{"role": r, "content": c} for r, c in st.session_state.history],
                temperature=1,
                stream=False,
            )
            assistant_text = resp.choices[0].message.content
            with st.chat_message("assistant"):
                display_parsed_markdown(assistant_text, link_type="deepseek")

        st.session_state.history.append(("assistant", assistant_text))

    if not st.session_state.first_message_submitted:
        try:
            b64 = base64.b64encode(Path("querya.png").read_bytes()).decode()
            st.markdown(
                f"<div style='text-align:center; margin-top:12px;'>"
                f"<img src='data:image/png;base64,{b64}' style='height:80px;' /></div>",
                unsafe_allow_html=True,
            )
        except Exception:
            pass

        st.markdown("**Please enter ONE query to start:**")
        user_first_input = st.text_input(
            "Initial product recommendation query",
            placeholder="e.g., Can you recommend some wireless Bluetooth earbuds?",
            label_visibility="collapsed",
        )
        chosen = render_suggestion_chips(SUGGESTED_QUERIES_AI, "sug_ai")
        if chosen:
            user_first_input = chosen

        if user_first_input:
            st.session_state.history.append(("user", user_first_input))
            st.chat_message("user").write(user_first_input)
            st.session_state.first_message_submitted = True
            st.session_state.pending_first_message = user_first_input
            st.rerun()
        return

    st.markdown("<div style='height:0.5rem;'></div>", unsafe_allow_html=True)
    msg_cols = st.columns([8, 1])
    with msg_cols[0]:
        extra_input = st.text_input(
            "Additional message",
            placeholder="Type a message...",
            key="ai_extra_message",
            label_visibility="collapsed",
        )
    with msg_cols[1]:
        send_clicked = st.button("Send", key="btn_ai_extra_message")

    if send_clicked and extra_input.strip():
        log_event("extra_query_attempt", extra_input.strip()[:200])
        st.info("Thanks! For this study, you only need to enter **one** query. Please click **Finish / End Session** (top right) to proceed to the survey.")
    return


def render_final_survey_page():
    """Final survey for the earbuds experiment: manipulation, attention, demographics."""
    if st.session_state.get("survey_locked"):
        st.title("Final Survey - Completed")
        st.success("Thanks! Your responses have already been submitted.")
        target = st.session_state.get("completion_url") or get_completion_url()
        try:
            st.link_button("Open the completion page", target)
        except Exception:
            st.markdown(f"[Open the completion page]({target})")
        st.caption("You can now close this tab.")
        st.stop()

    v, is_ai, with_ads, group_label = get_variant_flags()
    st.title("Final Survey")
    st.markdown(
        """
        <style>
        div[data-testid="stRadio"] > div { gap: 0.5rem !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    def is_blank(x) -> bool:
        return x is None or (isinstance(x, str) and x.strip() == "")

    with st.form("final_survey_earbuds_compact"):
        st.markdown("Please complete **all** questions. There is no default selection.")

        mc_ads_label = "Did you see any sponsored products (i.e., advertisements) on the page presenting recommended products in this study?"
        st.markdown(f"**1. {mc_ads_label}**")
        mc_ads = st.radio(
            mc_ads_label,
            options=["Yes", "No"],
            index=None,
            key="p3_mc_ads",
            label_visibility="collapsed",
        )

        mc_free_service_label = (
            "To what extent do you agree with the following statement?\n\n"
            "1 = Strongly disagree, 7 = Strongly agree\n\n"
            "The advertising shown in the AI service appeared to support keeping the AI service free for users."
        )
        st.markdown("**2. To what extent do you agree with the following statement?**")
        st.markdown("**1 = Strongly disagree, 7 = Strongly agree**")
        st.markdown(
            "**The advertising shown in the AI service appeared to support keeping the AI service free for users.**"
        )
        mc_free_service = st.radio(
            mc_free_service_label,
            options=[1, 2, 3, 4, 5, 6, 7],
            horizontal=True,
            index=None,
            key="p3_mc_ads_support_free_service",
            label_visibility="collapsed",
        )
        st.markdown("---")

        st.markdown("**Please select two.**")
        att_check = st.radio(
            "Please select two.",
            options=[1, 2, 3, 4, 5, 6, 7],
            horizontal=True,
            index=None,
            key="chk_att",
            label_visibility="collapsed",
        )
        st.markdown("---")

        st.markdown("**Your age:**")
        age_str = st.text_input(
            "Your age",
            value="",
            key="p3_demo_age",
            placeholder="Enter an integer between 18 and 99",
            label_visibility="collapsed",
        )

        st.markdown("**Your sex:**")
        sex = st.radio(
            "Your sex",
            options=["Male", "Female"],
            index=None,
            key="p3_demo_sex",
            label_visibility="collapsed",
        )

        st.markdown("**Your educational background:**")
        edu = st.selectbox(
            "Your educational background",
            options=[
                "Less than high school",
                "High school graduate",
                "Bachelor or equivalent",
                "Master",
                "Doctorate",
            ],
            index=None,
            placeholder="Select",
            key="p3_demo_edu",
            label_visibility="collapsed",
        )

        st.markdown("**Your ethnicity:**")
        ethnicity = st.selectbox(
            "Your ethnicity",
            options=[
                "White",
                "Black or African American",
                "American Indian or Alaska Native",
                "Asian",
                "Native Hawaiian or Pacific Islander",
                "Other",
            ],
            index=None,
            placeholder="Select",
            key="p3_demo_ethnicity",
            label_visibility="collapsed",
        )

        submitted = st.form_submit_button("Submit")

    if not submitted:
        return

    age_val, age_err = None, None
    if is_blank(age_str):
        age_err = "Please enter your age."
    else:
        try:
            age_val = int(str(age_str).strip())
            if age_val < 18 or age_val > 99:
                age_err = "Age must be between 18 and 99."
        except Exception:
            age_err = "Age must be a whole number."

    required = {
        "mc_ads": mc_ads,
        "ads_support_free_service": mc_free_service,
        "attention_check": att_check,
        "sex": sex,
        "education": edu,
        "ethnicity": ethnicity,
    }
    missing = [name for name, val in required.items() if is_blank(val)]

    if age_err or missing:
        if age_err:
            st.error(age_err)
        if missing:
            st.error("Please complete all required questions before submitting.")
        return

    answers = {
        "variant": st.session_state.get("variant"),
        "group": "AI",
        "with_ads": with_ads,
        "condition_label": group_label,
        "manipulation_check": {
            "saw_sponsored_products": mc_ads,
            "ads_support_free_service": mc_free_service,
        },
        "attention_check": att_check,
        "attention_check_passed": att_check == 2,
        "demographics": {
            "age": age_val,
            "sex": sex,
            "education": edu,
            "ethnicity": ethnicity,
        },
    }

    if not st.session_state.get("survey_locked"):
        log_event("survey", "final_survey", json.dumps(answers, ensure_ascii=False))

    target = get_completion_url()
    st.session_state["survey_locked"] = True
    st.session_state["completion_url"] = target
    st.success("Submitted. Please click below to complete:")
    try:
        if st.link_button("Please click here to complete", target):
            st.session_state.completed = True
    except Exception:
        st.markdown(f"[Please click here to complete]({target})")
    st.stop()


############################################
# Main App Flow
############################################
def main():
    # Ensure the condition (AI vs Search) is stable for this session (and across refresh, if possible)
    ensure_variant_stable()
    enforce_desktop_only_frontend(strict_width=None)  # visual block, no logging
    # The JS bridge can wait on the browser component and make the page feel stuck.
    # Keep it available for debugging only; the CSS overlay is the participant-facing gate.
    if _js_device_gate_enabled():
        try:
            gate_desktop_only(width_threshold=900)
        except Exception:
            pass
    if st.session_state.stage == "pid":
        st.title("Welcome!")
        pid = st.text_input("Please enter your Prolific ID:")
        if st.button("Confirm"):
            if pid.strip():
                st.session_state.prolific_id = pid.strip()
                # 记录
                log_event("pid_entered", "pid_ok")
                log_event("variant_assigned", f"variant={st.session_state.variant}")
                st.session_state.stage = "instructions"
                st.rerun()
        st.stop()

    # B) 说明页阶段
    if st.session_state.stage == "instructions":
        render_instructions_page()
        st.stop()

    # C) 问卷阶段
    if st.session_state.stage == "survey":
        render_final_survey_page()
        st.stop()

    # D) 实验阶段（四个 condition）
    # 如果此时用户点进了单品页
    if st.session_state.page == "product" and st.session_state.current_product:
        render_product_page()
        return

    # 其余正常路由
    # All earbuds experiment variants use the AI chatbot.
    _, _, with_ads, _ = get_variant_flags()
    show_deepseek_recommendation(with_ads=with_ads)


if __name__ == "__main__":
    main()
