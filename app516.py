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
        return st.secrets.get("COMPLETION_URL", None) or os.getenv("COMPLETION_URL") or "https://www.prolific.com/"
    except Exception:
        return os.getenv("COMPLETION_URL") or "https://www.prolific.com/"


# ====== 实验阶段机位：'pid' -> 'instructions' -> 'experiment' -> 'survey' ======
st.session_state.setdefault("stage", "pid")  # 初始阶段：填写 Prolific ID


# 先不分配 variant，等点 Next 再分；如果你希望一进来就分配，移动到这里也行

def get_credentials_from_secrets():
    # 还原成 dict
    creds_dict = {key: value for key, value in st.secrets["GOOGLE_CREDENTIALS"].items()}
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    
    return creds_dict

    return creds_dict


# def save_to_gsheet(data: dict):
#     scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
#     creds = ServiceAccountCredentials.from_json_keyfile_name("streamlit_app.json", scope)
#     client = gspread.authorize(creds)
#     sheet = client.open("Click History").sheet1
#     sheet.append_row([data[k] for k in ["id", "timestamp", "type", "title", "url"]])

def save_to_gsheet(data):
    # 自动注入 variant（如果还没分配，就留空字符串）
    data = dict(data)
    data.setdefault("variant", st.session_state.get("variant", ""))

    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        get_credentials_from_secrets(),
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
    )
    client = gspread.authorize(creds)
    for i in range(3):
        try:
            sheet = client.open("SeEn Ads").sheet1
            # 新顺序：id, start, variant, timestamp, type, title, url
            sheet.append_row([data.get(k, "") for k in ["id", "start", "variant", "timestamp", "type", "title", "url"]])
            return ''
        except Exception as e:
            time.sleep(0.5)
    return ''


# simple in‑memory router
st.session_state.setdefault("page", "main")  # "main" | "product"
st.session_state.setdefault("current_product", {})  # dict of the product being viewed

st.session_state.setdefault("favorites", {})

# ===== Variant assignment happens immediately (once per session) =====
if "variant" not in st.session_state:
    # 1: AI w/o ads, 2: AI + ads, 3: Search w/o ads, 4: Search + ads
    st.session_state.variant = random.randint(1, 4)

############################################
# Step 0: Page config & DeepSeek client
############################################
st.set_page_config(page_title="🛒 Querya", layout="wide")

API_KEY = st.secrets.get("DEEPSEEK_API_KEY", None) or os.getenv("DEEPSEEK_API_KEY")
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
def get_variant_flags():
    """Return (variant, is_ai, with_ads, group_label)."""
    v = st.session_state.get("variant", 4)
    is_ai = v in (1, 2)
    with_ads = v in (2, 4)
    group_label = "AI Assistant" if is_ai else "Search Engine"
    return v, is_ai, with_ads, group_label

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
        To help you decide which product to purchase, you will use an AI chatbot (“**Querya**”) to get some recommended products to consider.

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
                To help you decide which product to purchase, you will use a search engine (“**Querya**”) to find some recommended products.

                ---

                **Please follow these steps:**

                1. **Click the `Next / Start` button** below to open the AI chatbot.  

                2. **Ask for product recommendations.** For example, you might type:  
                   - “Fish oil supplements”  
                   - “Fish oils”  
                    
                   Or use any other terms you would naturally type into a search engine.

                3. **Treat this task as if you were genuinely shopping for yourself.**  
                   Feel free to explore the recommended products by clicking the links and browsing naturally, just as you would in real life.

                4. **If you’re interested in a product**, you may click the **`Add to Cart`** button at the top-right corner of its page.

                5. **When you’re finished browsing**, close the AI chatbot by selecting **`Finish / End Session`** in the top-right corner of the results page.

                6. **Finally**, complete a short questionnaire about your experience.
                """)

    # if with_ads:
    #     st.info("This condition **may include sponsored results** labeled “Sponsored”. Please browse naturally.")
    #
    # st.warning("Estimated time: about **2–3 minutes**. Please interact naturally as if you were shopping online.")

    if st.button("Start the task"):
        # Optional: log variant explicitly once PID is known
        save_to_gsheet({
            "id":        st.session_state.get("prolific_id", "unknown"),
            "start":     st.session_state.get("start_time", datetime.now().isoformat()),
            "timestamp": datetime.now().isoformat(),
            "type":      "enter_experiment",
            "title":     f"{group_label} | ads={with_ads}",
            "url":       " "
        })
        st.session_state.stage = "experiment"
        st.rerun()



# def render_final_survey_page():
#     st.title("Final Survey")
#
#     # Legend
#     st.caption("Scale anchor: 1 = Strongly disagree … 7 = Strongly agree")
#
#     # 7-point horizontal Likert with question ABOVE
#     def likert7(question: str, key: str) -> int | None:
#         return st.radio(
#             question,
#             options=[1, 2, 3, 4, 5, 6, 7],
#             index=None,  # <- no default
#             horizontal=True,
#             key=key
#         )
#
#     def is_blank(x) -> bool:
#         return x is None or (isinstance(x, str) and x.strip() == "")
#
#     with st.form("final_survey"):
#         st.markdown(
#             "Please complete all questions below. "
#             "**All items are required.**"
#         )
#
#         # ---------------- Demographics ----------------
#         st.markdown("### Demographics")
#         age_str = st.text_input("Age (18–99)", value="", key="demo_age_text")
#         gender = st.radio("Gender", ["Male", "Female", "Other / Prefer not to say"],
#                           index=None, key="demo_gender")
#         edu = st.selectbox("Highest Education",
#                            ["High school or below", "Bachelor", "Master", "Doctorate"],
#                            index=None, placeholder="Select…", key="demo_edu")
#         online_freq = st.selectbox("Online Shopping Frequency",
#                                    ["Rarely", "Occasionally", "Several times a month", "Several times a week or more"],
#                                    index=None, placeholder="Select…", key="demo_online_freq")
#         ai_exp = st.selectbox("Familiarity with Generative AI / AI Assistants",
#                               ["Not familiar", "Somewhat familiar", "Familiar", "Very familiar"],
#                               index=None, placeholder="Select…", key="demo_ai_exp")
#
#         st.markdown("---")
#
#         # ---------------- Scales (7-point Likert; all required) ----------------
#         st.markdown("### Scales (7-point Likert)")
#
#         # Satisfaction (3)
#         st.markdown("**Satisfaction**")
#         sat1 = likert7("I am satisfied with the overall experience of using this system.", "sat1")
#         sat2 = likert7("The results met my expectations.", "sat2")
#         sat3 = likert7("If I could choose again, I would still use this system.", "sat3")
#
#         # Trust (3)
#         st.markdown("**Trust**")
#         tr1 = likert7("I trust the results provided by this system.", "tr1")
#         tr2 = likert7("I believe the system acts in the interest of the user.", "tr2")
#         tr3 = likert7("I believe the system would not intentionally mislead me.", "tr3")
#
#         # Relevance (3)
#         st.markdown("**Relevance**")
#         rel1 = likert7("The returned products were highly relevant to my needs.", "rel1")
#         rel2 = likert7("The results accurately reflected my query intention.", "rel2")
#         rel3 = likert7("Irrelevant or noisy results were minimal.", "rel3")
#
#         # Ease of Use (3)
#         st.markdown("**Ease of Use**")
#         ease1 = likert7("The interface was easy to use overall.", "ease1")
#         ease2 = likert7("Learning to operate this system was easy for me.", "ease2")
#         ease3 = likert7("Completing the task required little effort.", "ease3")
#
#         # Ad perception (3) + noticed_ads
#         st.markdown("**Ad Perception**")
#         ad1 = likert7("I clearly recognized which items were sponsored content/ads.", "ad1")
#         ad2 = likert7("Ads did not interfere with my browsing experience.", "ad2")
#         ad3 = likert7("The ads shown were relevant to my needs.", "ad3")
#         noticed_ads = st.radio("Did you notice sponsored content/ads during this task?",
#                                ["Yes", "No", "Not sure"], index=None, key="noticed_ads")
#
#         # Intention (2)
#         st.markdown("**Intention**")
#         inten1 = likert7("I would like to use this system again in the future.", "inten1")
#         inten2 = likert7("I would consider purchasing products shown in the results.", "inten2")
#
#         comments = st.text_area("Other comments or suggestions (optional)", key="open_comments")
#
#         submitted = st.form_submit_button("Submit & Redirect")
#
#     # ---------------- Validation & submit ----------------
#     if submitted:
#         # Validate age input
#         age_val = None
#         age_err = None
#         if is_blank(age_str):
#             age_err = "Please enter your age."
#         else:
#             try:
#                 age_val = int(age_str.strip())
#                 if age_val < 18 or age_val > 99:
#                     age_err = "Age must be between 18 and 99."
#             except Exception:
#                 age_err = "Age must be a whole number."
#
#         # Required fields map
#         required_map = {
#             "Gender": gender,
#             "Highest Education": edu,
#             "Online Shopping Frequency": online_freq,
#             "Familiarity with Generative AI": ai_exp,
#             # Likert items
#             "Satisfaction Q1": sat1, "Satisfaction Q2": sat2, "Satisfaction Q3": sat3,
#             "Trust Q1": tr1, "Trust Q2": tr2, "Trust Q3": tr3,
#             "Relevance Q1": rel1, "Relevance Q2": rel2, "Relevance Q3": rel3,
#             "Ease of Use Q1": ease1, "Ease of Use Q2": ease2, "Ease of Use Q3": ease3,
#             "Ad Perception Q1": ad1, "Ad Perception Q2": ad2, "Ad Perception Q3": ad3,
#             "Noticed Ads": noticed_ads,
#             "Intention Q1": inten1, "Intention Q2": inten2,
#         }
#         missing = [label for label, val in required_map.items() if is_blank(val)]
#
#         if age_err or missing:
#             if age_err:
#                 st.error(age_err)
#             if missing:
#                 st.error("Please complete all required questions: " + ", ".join(missing))
#                 st.warning("Your responses have not been submitted. Please answer the missing items above.")
#             return  # keep the form for corrections
#
#         # Compute means
#         def mean(vals):
#             return round(sum(vals) / len(vals), 3)
#
#         scores = {
#             "satisfaction_mean": mean([sat1, sat2, sat3]),
#             "trust_mean": mean([tr1, tr2, tr3]),
#             "relevance_mean": mean([rel1, rel2, rel3]),
#             "ease_mean": mean([ease1, ease2, ease3]),
#             "ad_perception_mean": mean([ad1, ad2, ad3]),
#             "intention_mean": mean([inten1, inten2]),
#         }
#
#         demographics = {
#             "age": age_val,
#             "gender": gender,
#             "education": edu,
#             "online_freq": online_freq,
#             "ai_exp": ai_exp,
#             "noticed_ads": noticed_ads,
#         }
#
#         answers = {
#             "variant": st.session_state.get("variant"),
#             "demographics": demographics,
#             "scores": scores,
#             "comments": comments,
#         }
#
#         # Log & redirect
#         save_to_gsheet({
#             "id": st.session_state.prolific_id,
#             "start": st.session_state.start_time,
#             "timestamp": datetime.now().isoformat(),
#             "type": "survey",
#             "title": "final_survey",
#             "url": json.dumps(answers, ensure_ascii=False)
#         })
#
#         target = get_completion_url()
#         st.success("Submitted. Please click the below button to redirect to the completion page…")
#         if (st.link_button("If you are not redirected automatically, click here to finish.", target)):
#             st.success("Session ended. Thank you!")
#             st.stop()

def render_final_survey_page():
    # ---- determine condition ----
    def get_variant_flags():
        v = st.session_state.get("variant", 4)
        is_ai = v in (1, 2)
        with_ads = v in (2, 4)
        group_label = "AI Assistant" if is_ai else "Search Engine"
        return v, is_ai, with_ads, group_label

    v, is_ai, with_ads, group_label = get_variant_flags()
    SYS_NOUN = "AI chatbot" if is_ai else "search engine"   # used in stems
    SYS_NOUN_PLURAL = "AI chatbots" if is_ai else "search engines"

    st.title("Final Survey")
    st.caption("Unless otherwise stated, use a 7‑point scale where "
               "1 = Strongly disagree and 7 = Strongly agree.")

    # --- small CSS to keep radios compact; anchors close to the scale ---
    st.markdown("""
        <style>
        div[data-testid="stRadio"] > div { gap: 0.5rem !important; }
        .anchorrow div { text-align:center; white-space:nowrap; font-size:0.85rem; color:#666; }
        </style>
    """, unsafe_allow_html=True)

    # ---------- helpers ----------
    def is_blank(x) -> bool:
        return x is None or (isinstance(x, str) and x.strip() == "")

    def render_anchor_row(left: str, right: str):
        cols = st.columns(7)
        with cols[0]:
            st.markdown(f"<div class='anchorrow'>{left}</div>", unsafe_allow_html=True)
        for i in range(1, 6):
            with cols[i]:
                st.markdown("<div class='anchorrow'>&nbsp;</div>", unsafe_allow_html=True)
        with cols[6]:
            st.markdown(f"<div class='anchorrow'>{right}</div>", unsafe_allow_html=True)

    def likert7(question: str, key: str,
                left_anchor="Strongly disagree", right_anchor="Strongly agree") -> int | None:
        """Question text above, custom anchors above 1 & 7, then 1–7 horizontally (no default)."""

        st.markdown(f"**{question}** (1={left_anchor}, 7={right_anchor})")
        # render_anchor_row(left_anchor, right_anchor)
        sel = st.radio("", options=[1,2,3,4,5,6,7], horizontal=True, index=None,
                       key=key, label_visibility="collapsed")
        st.markdown("<div style='height:0.25rem;'></div>", unsafe_allow_html=True)
        return sel

    def matrix_block(title: str, items: list[tuple[str, str]],
                     keyprefix: str, left_anchor="Strongly disagree", right_anchor="Strongly agree"):
        """Show anchor row once for a set; return dict {key:score}."""
        # st.markdown(f"### {title}")
        st.markdown(f"1={left_anchor},7={right_anchor}")
        # render_anchor_row(left_anchor, right_anchor)
        results = {}
        for k, q in items:
            # keep each question visible above its row (Qualtrics-style matrix)
            st.markdown(f"**{q}**")
            results[k] = st.radio("", options=[1,2,3,4,5,6,7],
                                  horizontal=True, index=None,
                                  key=f"{keyprefix}_{k}", label_visibility="collapsed")
        st.markdown("---")
        return results

    def ios_image():
        # Try a few likely paths; ignore if missing
        possible = [
            "/mnt/data/2e1e965d-f6e5-49da-9166-2e2576a413ea.png",
            "ios_overlapping_circles.png", "ios.jpg", "ioss.png"
        ]
        for p in possible:
            try:
                if os.path.exists(p):
                    st.image(p, caption="Choose the pair that best represents your feelings.")
                    return
            except Exception:
                pass
        st.caption("Circle diagram: (image unavailable). Please still select 1–7 below.")

    # ------- form begins -------
    with st.form("final_survey"):
        st.markdown("Please complete **all** questions. There is no default selection.")

        # ============= CONDITION-SPECIFIC BLOCKS =============

        # 1) Trust (5 items)
        trust_items_ai = [
            ("trust1", f"I believe that this {SYS_NOUN} would act in my best interest."),
            ("trust2", f"This {SYS_NOUN} is truthful and honest in its responses."),
            ("trust3", f"This {SYS_NOUN} is competent and effective in providing information."),
            ("trust4", f"This {SYS_NOUN} is sincere and genuine."),
            ("trust5", f"I feel that I can rely on this {SYS_NOUN} when I need important information.")
        ]
        trust_items_search = [
            ("trust1", f"I believe that this {SYS_NOUN} would act in my best interest."),
            ("trust2", f"This {SYS_NOUN} is truthful and honest in its responses."),
            ("trust3", f"This {SYS_NOUN} is competent and effective in providing information."),
            ("trust4", f"This {SYS_NOUN} is sincere and genuine."),
            ("trust5", f"I feel that I can rely on this {SYS_NOUN} when I need important information.")
        ]
        trust = matrix_block("Trust", trust_items_ai if is_ai else trust_items_search,
                             keyprefix="trust")

        # 2) Privacy Concern (4 items)
        privacy_items = [
            ("priv1", f"I am concerned that this {SYS_NOUN} collects too much personal information about me."),
            ("priv2", f"I worry that this {SYS_NOUN} may use my personal information for purposes I have not authorized."),
            ("priv3", f"I feel uneasy that this {SYS_NOUN} may share my personal information with others without my authorization."),
            ("priv4", f"I am concerned that my personal information may not be securely protected from unauthorized access when using this {SYS_NOUN}."),
        ]
        privacy = matrix_block("Privacy Concern", privacy_items, keyprefix="privacy")

        # 3) Sense of Exploitation (2 items)
        exploit_items = [
            ("exp1", f"I believe this {SYS_NOUN} would be exploitative in its use of my personal information."),
            ("exp2", f"I believe this {SYS_NOUN} would take advantage of my personal information.")
        ]
        exploitation = matrix_block("Sense of Exploitation", exploit_items, keyprefix="exploit")

        # 4) Relationship (IOS + 4 items)
        # st.markdown("### Relationship Closeness (IOS)")
        st.markdown(
            f"In the pairs of circles below, one circle represents **you**, and the other represents **{SYS_NOUN_PLURAL}**. "
            "The amount of overlap indicates closeness. Please select the pair that best represents your feelings."
        )
        ios_image()
        ios_choice = st.radio(
            "Please select the pair (1–7).",
            options=[1,2,3,4,5,6,7], index=None, horizontal=True, key="ios_choice"
        )
        st.markdown("---")

        rel_items = [
            ("rel1", f"Overall, I have a warm and comfortable relationship with {SYS_NOUN_PLURAL}."),
            ("rel2", f"Overall, I experience intimate communication with {SYS_NOUN_PLURAL}."),
            ("rel3", f"Overall, I have a relationship of mutual understanding with {SYS_NOUN_PLURAL}."),
            ("rel4", f"Overall, I feel emotionally close to {SYS_NOUN_PLURAL}."),
        ]
        # relationship = matrix_block("Relationship (statements)", rel_items, keyprefix="relationship")

        # 5) Familiarity with the just-used system (4 items; disagree/agree anchors)
        fam_items = [
            ("fam1", f"The {SYS_NOUN}’s response felt unfamiliar to me."),
            # ("fam2", f"The interaction did not align with how I usually experience similar systems."),
            ("fam3", f"This experience did not feel typical of how platforms usually respond."),
            # ("fam4", f"Something about the interaction felt unfamiliar."),
        ]
        familiarity = matrix_block("Familiarity with the just-used system", fam_items, keyprefix="familiarity")

        # ============= GENERAL / MANIPULATION CHECKS =============

        # st.markdown("### Manipulation Check")
        mc_tool = st.radio(
            "What did you use to seek recommended products in this study?",
            ["An AI chatbot", "A search engine"], index=None, key="mc_tool"
        )
        mc_ads = st.radio(
            "Did you see any “sponsored” products (i.e., advertisements) on the recommendation page?",
            ["Yes", "No"], index=None, key="mc_ads"
        )
        st.markdown("---")

        # ============= OTHER CHECKS (group-specific anchors where needed) =============

        # st.markdown("### Other Checks")

        fish_fam = likert7(
            "How familiar are you with fish oil supplements?",
            key="chk_fish_familiar",
            left_anchor="Not familiar at all", right_anchor="Very familiar"
        )

        # attitude / experience / frequency / familiarity about the system
        attitude = likert7(
            f"What is your attitude toward {SYS_NOUN_PLURAL}?",
            key="chk_attitude",
            left_anchor="Very negative", right_anchor="Very positive"
        )
        experience = likert7(
            f"How much experience do you have using {SYS_NOUN_PLURAL}?",
            key="chk_experience",
            left_anchor="Very little", right_anchor="Very much"
        )
        # frequency = likert7(
        #     f"How often do you use {SYS_NOUN_PLURAL}?",
        #     key="chk_frequency",
        #     left_anchor="Not often at all", right_anchor="Very often"
        # )
        # sys_familiar = likert7(
        #     f"How familiar are you with {SYS_NOUN_PLURAL}?",
        #     key="chk_sys_familiar",
        #     left_anchor="Not familiar at all", right_anchor="Very familiar"
        # )

        # commonness / habituation to sponsored content in this ecosystem
        # common_ads = likert7(
        #     f"It is very common to see sponsored content in "
        #     f"{'responses provided by AI chatbots' if is_ai else 'search engine results'}.",
        #     key="chk_common_ads"
        # )
        att_check = likert7(
            f"Please select 2",
            key="chk_att"
        )
        used_to_ads = likert7(
            f"I am used to seeing sponsored content in "
            f"{'responses provided by AI chatbots' if is_ai else 'search engine results'}.",
            key="chk_used_to_ads"
        )

        st.markdown("---")

        # ============= DEMOGRAPHICS =============
        # st.markdown("### Demographics (all required)")
        age_str = st.text_input("Your age", value="", key="demo_age_text")

        sex = st.radio("Your sex", ["Male", "Female"], index=None, key="demo_sex")

        edu = st.selectbox(
            "Your educational background",
            ["Less than high school", "High school graduate", "Bachelor or equivalent", "Master", "Doctorate"],
            index=None, placeholder="Select…", key="demo_edu"
        )

        ethnicity = st.selectbox(
            "Your ethnicity",
            ["White", "Black or African American", "American Indian or Alaska Native",
             "Asian", "Native Hawaiian or Pacific Islander", "Other"],
            index=None, placeholder="Select…", key="demo_ethnicity"
        )

        comments = st.text_area("Other comments (optional)", key="open_comments")

        # submit
        submitted = st.form_submit_button("Submit & Redirect")

    # ---------- validation & submission ----------
    if submitted:
        # validate age
        age_val, age_err = None, None
        if is_blank(age_str):
            age_err = "Please enter your age."
        else:
            try:
                age_val = int(age_str.strip())
                if age_val < 18 or age_val > 99:
                    age_err = "Age must be between 18 and 99."
            except Exception:
                age_err = "Age must be a whole number."

        # collect required fields dynamically
        required = {
            # condition-specific blocks
            **{f"trust_{k}": v for k,v in trust.items()},
            **{f"privacy_{k}": v for k,v in privacy.items()},
            **{f"exploit_{k}": v for k,v in exploitation.items()},
            "ios_choice": ios_choice,
            **{f"relationship_{k}": v for k,v in relationship.items()},
            **{f"familiarity_{k}": v for k,v in familiarity.items()},
            # general checks
            "mc_tool": mc_tool,
            "mc_ads": mc_ads,
            "fish_familiar": fish_fam,
            "attitude": attitude,
            "experience": experience,
            "frequency": frequency,
            "sys_familiar": sys_familiar,
            "common_ads": common_ads,
            "used_to_ads": used_to_ads,
            # demographics
            "sex": sex,
            "education": edu,
            "ethnicity": ethnicity,
        }
        missing = [name for name, val in required.items() if is_blank(val)]

        if age_err or missing:
            if age_err:
                st.error(age_err)
            if missing:
                st.error("Please complete all required questions: " + ", ".join(missing))
                st.warning("Your responses have not been submitted. Please answer the missing items above.")
            return

        # assemble raw (item-level) answers
        answers = {
            "variant": st.session_state.get("variant"),
            "group": "AI" if is_ai else "Search",
            "with_ads": with_ads,
            "trust": trust,                      # 5 items (1..7)
            "privacy_concern": privacy,          # 4 items
            "exploitation": exploitation,        # 2 items
            "relationship_ios_choice": ios_choice,        # 1..7
            "relationship_statements": relationship,      # 4 items
            "familiarity_block": familiarity,    # 4 items (about the just-used system)
            "manipulation_check": {
                "tool_used": mc_tool,
                "saw_sponsored": mc_ads
            },
            "other_checks": {
                "fish_oil_familiarity": fish_fam,
                "attitude_toward_system": attitude,
                "experience_with_system": experience,
                "frequency_of_use": frequency,
                "system_familiarity_general": sys_familiar,
                "commonness_of_ads": common_ads,
                "habituation_to_ads": used_to_ads
            },
            "demographics": {
                "age": age_val,
                "sex": sex,
                "education": edu,
                "ethnicity": ethnicity
            },
            "comments": comments,
        }

        # log & redirect
        save_to_gsheet({
            "id":        st.session_state.prolific_id,
            "start":     st.session_state.start_time,
            "timestamp": datetime.now().isoformat(),
            "type":      "survey",
            "title":     "final_survey",
            "url":       json.dumps(answers, ensure_ascii=False)
        })

        target = get_completion_url()
        st.success("Submitted. Redirecting to the completion page…")
        st_javascript(f'window.location.href = "{target}";')
        try:
            st.link_button("If not redirected, click here to complete", target)
        except Exception:
            st.markdown(f"[If not redirected, click here to complete]({target})")
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
    save_to_gsheet({
        "id": st.session_state.prolific_id,
        "start": st.session_state.start_time,
        "timestamp": datetime.now().isoformat(),
        "type": "back",
        "title": "Back to main",
        "url": " ",  # no external URL
    })
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
                save_to_gsheet({
                    "id": st.session_state.prolific_id,
                    "start": st.session_state.start_time,
                    "timestamp": datetime.now().isoformat(),
                    "type": "add_to_cart_demo",  # <- easy to filter later
                    "title": p.get("title", ""),
                    "url": p.get("product_url", " ")
                })
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


# def show_product_item(p: dict, link_type: str = "ad"):
#     """
#     Shows one product line with:
#       [Title]   [☆/★]
#     """
#     favs = st.session_state.favorites
#     is_fav = p["product_url"] in favs
#
#     # layout: 10:1 ratio
#     title_col, star_col = st.columns([10, 1], gap="small")
#
#     with title_col:
#         if st.button(p["title"], key=f"prod_{p['id']}"):
#             # 1) log the click
#             save_to_gsheet({
#                 "id": st.session_state.prolific_id,
#                 "start": st.session_state.start_time,
#                 "timestamp": datetime.now().isoformat(),
#                 "type": link_type,   # "ad" or "organic"
#                 "title": p["title"],
#                 "url": p["product_url"],
#             })
#             # 2) open internal page
#             st.session_state.page = "product"
#             st.session_state.current_product = p
#             st.rerun()
#
#     with star_col:
#         star_lbl = "★" if is_fav else "☆"
#         if st.button(star_lbl, key=f"fav_{p['id']}"):
#             if is_fav:
#                 del favs[p["product_url"]]
#             else:
#                 favs[p["product_url"]] = p["title"]
#             st.rerun()

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
        save_to_gsheet({
            "id": st.session_state.prolific_id,
            "start": st.session_state.start_time,
            "timestamp": datetime.now().isoformat(),
            "type": link_type,  # "ad", "organic", "deepseek"
            "title": p["title"],
            "url": p.get("product_url", " ")
        })
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
def show_deepseek_recommendation(with_ads: bool):
    col1, col2 = st.columns([6, 1])
    with col1:
        st.title("Querya Rec")
    with col2:
        end_clicked = st.button("Finish / End Session", key=f"end_button_{st.session_state.get('variant', '')}")

    if end_clicked:
        # Full-screen centered message (clears interface)
        # st.session_state["end_clicked"] = True
        click_data = {
            "id": st.session_state.get("prolific_id", "unknown"),
            "start": st.session_state.get("start_time", datetime.now().isoformat()),
            "timestamp": datetime.now().isoformat(),
            "type": "end",
            "title": "Finish / End Session",
            "url": " "
        }
        save_to_gsheet(click_data)
        st.session_state.stage = "survey"
        st.rerun()  # Re-run to show the message cleanly in next render

    # After rerun
    if st.session_state.get("end_clicked", False):
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        st.markdown(
            "<h1 style='text-align:center;'>✅ Session ended. Thank you!</h1>",
            unsafe_allow_html=True
        )
        st.stop()

    if "history" not in st.session_state:
        st.session_state.history = [
            ("system", "You are an e-commerce chat assistant who recommends products based on user needs.")
        ]
    if "first_message_submitted" not in st.session_state:
        st.session_state.first_message_submitted = False
    if "pending_first_message" not in st.session_state:
        st.session_state.pending_first_message = None
    if "current_ads" not in st.session_state:
        st.session_state.current_ads = []

    # Display conversation so far
    for role, content in st.session_state.history:
        if role == "system":
            continue
        if role == "assistant":
            with st.chat_message("assistant"):
                display_parsed_markdown(content, link_type="deepseek")
        else:
            st.chat_message(role).write(content)

    # If we have a pending first message
    if st.session_state.first_message_submitted and st.session_state.pending_first_message:
        user_first_input = st.session_state.pending_first_message
        st.session_state.pending_first_message = None

        predefined = get_predefined_response(user_first_input)
        if predefined:
            assistant_text = predefined
            if isinstance(predefined, list):  # fish‑oil / liver list
                # detect which keyword we hit (fish oil vs liver)
                kw = "fish oil" if "fish" in user_first_input.lower() else "liver"
                heading = PREDEFINED_HEADINGS[kw]
                with st.chat_message("assistant"):
                    render_predefined_products(predefined, heading, link_type="organic")
            else:  # a plain string reply
                with st.chat_message("assistant"):
                    display_parsed_markdown(predefined, link_type="organic")
        else:
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": r, "content": c} for r, c in st.session_state.history],
                temperature=1,
                stream=False,
            )
            assistant_text = resp.choices[0].message.content
            with st.chat_message("assistant"):
                display_parsed_markdown(assistant_text, link_type="deepseek")

        st.session_state.history.append(("assistant", assistant_text))

        if with_ads:
            prods = get_products_by_query(user_first_input)
            st.session_state.current_ads = prods

    # Show current ads
    if st.session_state.current_ads:
        show_advertisements(st.session_state.current_ads)

    # If first message not yet
    def to_base64(path: str) -> str:
        return base64.b64encode(Path(path).read_bytes()).decode()

    if not st.session_state.first_message_submitted:
        # col1, col2, col3 = st.columns([1, 2, 1])
        # with col2:
        try:
            logo_b64 = to_base64("querya.png")
            st.markdown(
                f"""
                <div style="text-align:center; margin-top:20px;">
                    <img src="data:image/png;base64,{logo_b64}" style="height:80px;" />
                </div>
                """,
                unsafe_allow_html=True
            )
        except:
            st.write("Querya Rec")

        # query = st.text_input("", placeholder="Input Key Words for Search Here")
        user_first_input = st.text_input("", placeholder="Please enter your message:")

        if user_first_input:
            st.session_state.history.append(("user", user_first_input))
            st.chat_message("user").write(user_first_input)
            st.session_state.first_message_submitted = True
            st.session_state.pending_first_message = user_first_input
            st.rerun()
        return

    # Subsequent messages
    user_input = st.chat_input("Input message and press enter…")
    if not user_input:
        return

    st.session_state.history.append(("user", user_input))
    st.chat_message("user").write(user_input)

    predefined = get_predefined_response(user_input)
    if predefined:
        assistant_text = predefined
        if isinstance(predefined, list):  # fish‑oil / liver list
            # detect which keyword we hit (fish oil vs liver)
            kw = "fish oil" if "fish" in user_input.lower() else "liver"
            heading = PREDEFINED_HEADINGS[kw]
            with st.chat_message("assistant"):
                render_predefined_products(predefined, heading, link_type="organic")
        else:  # a plain string reply
            with st.chat_message("assistant"):
                display_parsed_markdown(predefined, link_type="organic")
    else:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": r, "content": c} for r, c in st.session_state.history],
            temperature=1,
            stream=False,
        )
        assistant_text = resp.choices[0].message.content
        with st.chat_message("assistant"):
            display_parsed_markdown(assistant_text, link_type="deepseek")

    st.session_state.history.append(("assistant", assistant_text))

    if with_ads:
        prods = get_products_by_query(user_input)
        st.session_state.current_ads = prods
        if prods:
            show_advertisements(prods)


############################################
# 9) Google-like Search Flow
############################################
def show_google_search(with_ads: bool):
    col1, col2 = st.columns([6, 1])
    with col1:
        st.title("Querya search")
    with col2:
        end_clicked = st.button("Finish / End Session", key=f"end_button_{st.session_state.get('variant', '')}")

    if end_clicked:
        # Full-screen centered message (clears interface)
        # st.session_state["end_clicked"] = True
        click_data = {
            "id": st.session_state.get("prolific_id", "unknown"),
            "start": st.session_state.get("start_time", datetime.now().isoformat()),
            "timestamp": datetime.now().isoformat(),
            "type": "end",
            "title": "Finish / End Session",
            "url": " "
        }
        save_to_gsheet(click_data)
        st.session_state.stage = "survey"
        st.rerun()  # Re-run to show the message cleanly in next render

    # After rerun
    if st.session_state.get("end_clicked", False):
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        st.markdown(
            "<h1 style='text-align:center;'>✅ Session ended. Thank you!</h1>",
            unsafe_allow_html=True
        )
        st.stop()

    if "search_results" not in st.session_state:
        st.session_state.search_results = []

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

    def to_base64(path: str) -> str:
        return base64.b64encode(Path(path).read_bytes()).decode()

    try:
        logo_b64 = to_base64("querya.png")
        st.markdown(
            f"""
            <div style="text-align:center; margin-top:20px;">
                <img src="data:image/png;base64,{logo_b64}" style="height:80px;" />
            </div>
            """,
            unsafe_allow_html=True
        )
    except:
        st.write("Querya Search")

    query = st.text_input("", placeholder="Input Key Words for Search Here")
    if st.button("Search"):
        results = do_fake_google_search(query)
        st.session_state.search_results = results
        if with_ads:
            prods = get_products_by_query(query)
            st.session_state.current_ads = prods

    # Show stored search results
    if st.session_state.search_results:
        st.write("---")
        st.write("**Search Results:**")

        for item in st.session_state.search_results:
            show_product_item(item, link_type="organic", show_image=True, image_position="below")

            if item["desc"]:
                st.write(item["desc"])
            st.write("---")

    # Show ads if any
    if with_ads:
        if "current_ads" not in st.session_state:
            st.session_state.current_ads = []
        if st.session_state.current_ads:
            show_advertisements(st.session_state.current_ads)


############################################
# Main App Flow
############################################
def main():
    if st.session_state.stage == "pid":
        st.title("Welcome!")
        pid = st.text_input("Please enter your Prolific ID:")
        if st.button("Confirm"):
            if pid.strip():
                st.session_state.prolific_id = pid.strip()
                # 记录
                save_to_gsheet({
                    "id": st.session_state.prolific_id,
                    "start": st.session_state.start_time,
                    "timestamp": datetime.now().isoformat(),
                    "type": "pid_entered",
                    "title": "pid_ok",
                    "url": " "
                })
                save_to_gsheet({
                    "id": st.session_state.prolific_id,
                    "start": st.session_state.start_time,
                    "timestamp": datetime.now().isoformat(),
                    "type": "variant_assigned",
                    "title": f"variant={st.session_state.variant}",
                    "url": " "
                })
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
    variant = st.session_state.get("variant", 1)  # 容错：若未分配就临时给个值
    if variant == 1:
        show_deepseek_recommendation(with_ads=False)
    elif variant == 2:
        show_deepseek_recommendation(with_ads=True)
    elif variant == 3:
        show_google_search(with_ads=False)
    elif variant == 4:
        show_google_search(with_ads=True)


if __name__ == "__main__":
    main()
