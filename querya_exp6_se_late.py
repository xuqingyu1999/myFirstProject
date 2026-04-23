#!/usr/bin/env python
# coding: utf-8

import base64
import json
import math
import os
import random
import time
from datetime import datetime
from pathlib import Path

import gspread
import streamlit as st
from oauth2client.service_account import ServiceAccountCredentials


CONDITION_CODE = 'se_late'
CONDITION_LABEL = 'SE Late'
SYSTEM_TYPE = 'search'
STAGE_TYPE = 'late'
GSHEET_NAME = 'Querya EXP6 SE Late'
PAGE_TITLE = 'Querya search'

INSTRUCTIONS_MD = """
### 📝 Instructions

Imagine that you have already decided to purchase a **fish oil supplement** and are now comparing available options before making your final selection.

At this stage, your goal is to **evaluate specific products, compare their features, and decide which one to buy**.

To help you with this, you will use a **search engine** (?Querya?) to look up information.

---

**Please follow these steps:**

1. **Click the `Next / Start` button** below to open the search engine.

2. **You enter a search like the following:**
   - ?fish oil supplement recommendations?
   - ?best fish oil supplements?

   You can also use similar phrasing you would naturally use when searching online, as long as your search focuses on identifying and comparing specific fish oil supplement options to decide which one to choose.

3. **Treat this task as if you were genuinely exploring this question for yourself.**
   Feel free to review the responses, just as you would in real life.

4. When you?re done browsing, close the search page by selecting **`Finish / End Session`**.

5. **Finally**, complete a short questionnaire about your experience.
"""

SUGGESTED_QUERIES = ['fish oil supplement recommendations',
 'best fish oil supplements',
 'which fish oil supplements are best',
 'top rated fish oil supplements']

RESPONSE_HEADING = 'Top results for fish oil supplements'

ORGANIC_PRODUCTS = [
    {
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
            "Item Weight": "0.69 lb",
        },
        "description": "- Features: High-concentration EPA/DHA (650 mg Omega-3 per soft-gel); IFOS 5-star certified; triglyceride (TG) form for superior absorption.\n- Ideal for: Cardiovascular health, anti-inflammatory needs, or anyone seeking a highly purified fish oil.",
        "page_description": "**About this item**\n- WHY OMEGA-3s – EPA & DHA support heart, brain, eye and immune health, and help maintain a healthy mood.\n- DOCTOR-RECOMMENDED dose meets American Heart Association guidelines for cardiovascular support.\n- BETTER ABSORPTION & TASTE – Triglyceride form with pleasant lemon flavor and zero fishy burps.\n- PURITY GUARANTEED – Wild-caught fish, non-GMO, gluten- & dairy-free with no artificial additives.",
    },
    {
        "id": "fish_02",
        "title": "WHC UnoCardio 1000",
        "price": "$40.45",
        "specs": {
            "Brand": "WHC",
            "Flavor": "Natrual Orange",
            "Primary supplement type": "Omega-3",
            "Unit Count": "180 Count",
            "Item Form": "Softgel",
            "Item Weight": "16.8 ounces",
        },
        "product_url": "https://www.amazon.com/WHC-UnoCardio-Softgels-Triglyceride-concentration/dp/B00QFTGSK6",
        "image_url": "https://m.media-amazon.com/images/I/71htaA+bT9L._AC_SL1500_.jpg",
        "description": "- Features: Ranked No. 1 globally by IFOS; 1 000 mg Omega-3 (EPA + DHA) per soft-gel; enriched with vitamin D3; individually blister-packed to prevent oxidation.\n- Ideal for: Middle-aged and older adults who demand top purity and a premium formulation.",
        "page_description": "**About this item**\n- 1 180 mg total Omega-3 (EPA 665 mg / DHA 445 mg) per soft-gel for heart, brain and vision.\n- Provides 1 000 IU vitamin D3 to support bones, muscles and immunity.\n- r-Triglyceride form for superior absorption; lactose- & gluten-free, burp-free orange flavor.\n- Ultra-pure, Friend-of-the-Sea-certified fish oil in beef-gelatin-free blister packs.",
    },
    {
        "id": "fish_03",
        "title": "Now Foods Ultra Omega-3",
        "price": "$41.51",
        "specs": {
            "Brand": "Now Foods",
            "Flavor": "Unflavoured",
            "Primary supplement type": "Omega-3",
            "Unit Count": "180 Count",
            "Item Form": "Softgel",
            "Item Weight": "375 g",
        },
        "product_url": "https://www.amazon.sg/Supplements-Neptune-Strength-Phospholipid-Bound-Softgels/dp/B06XDNT7TQ/",
        "image_url": "https://m.media-amazon.com/images/I/71auVVCYKnL._AC_SX679_.jpg",
        "description": "- Features: Great value (EPA 500 mg + DHA 250 mg per soft-gel); IFOS certified; suitable for long-term, everyday supplementation.\n- Ideal for: General health maintenance, budget-conscious consumers, and daily nutritional support.",
        "page_description": "**About this item**\n- CARDIOVASCULAR SUPPORT – 600 mg EPA & 300 mg DHA per enteric-coated soft-gel.\n- MOLECULARLY DISTILLED for purity; tested free of PCBs, dioxins & heavy metals.\n- ENTERIC COATING reduces nausea and fishy aftertaste.\n- NON-GMO, Kosher and GMP-quality assured by the family-owned NOW® brand since 1968.",
    },
    {
        "id": "fish_04",
        "title": "Blackmores OMEGA BRAIN Caps 60s",
        "price": "$40.9",
        "specs": {
            "Brand": "Blackmores",
            "Flavor": "Lutein",
            "Primary supplement type": "Omega-3",
            "Unit Count": "180 Count",
            "Item Form": "Tablet",
            "Item Weight": "0.39 Kilograms",
        },
        "product_url": "https://www.amazon.com/Blackmores-OMEGA-BRAIN-Caps-60s/dp/B00AQ7T7UQ",
        "image_url": "https://m.media-amazon.com/images/I/71UhUKoWbnL._AC_SL1500_.jpg",
        "description": "- Features: Blackmores Omega Brain Capsules provide concentrated omega-3 fatty acids, particularly high DHA levels to support brain structure and enhance cognitive function.\n- Ideal for: Intensive cardiovascular support, joint health, and individuals seeking a high-dose omega-3 supplement.",
        "page_description": "**About this item**\n- One-a-day capsule delivers 500 mg DHA to maintain brain health and mental performance.\n- Provides four-times more DHA than standard fish oil—ideal if you eat little fish.\n- 100 % wild-caught small-fish oil rigorously tested for mercury, dioxins & PCBs.\n- Supports healthy growth in children and overall wellbeing for all ages.",
    },
    {
        "id": "fish_05",
        "title": "Möller’s Norwegian Cod-Liver Oil",
        "price": "$40.63",
        "specs": {
            "Brand": "Möller’s",
            "Flavor": "Lofoten",
            "Primary supplement type": "Fish Oil",
            "Unit Count": "8.4 Fluid Ounces",
            "Item Form": "Liquid",
            "Item Weight": "1.1 Pounds",
        },
        "product_url": "https://www.amazon.com/M%C3%B8llers-Cod-Liver-Oil-Lemon-Flavor/dp/B084LYXCL1",
        "image_url": "https://m.media-amazon.com/images/I/61eg-Vgm97L._AC_SL1500_.jpg",
        "description": "- Features: Liquid fish oil enriched with natural vitamins A and D; trusted Nordic brand with over 100 years of history; suitable for children and pregnant women.\n- Ideal for: Family supplementation, children’s health, pregnancy nutritional support, and enhancing immune function.",
        "page_description": "**About this item**\n- Natural source of EPA & DHA to support heart, brain and vision.\n- Supplies vitamins A & D for immune function and normal bone growth.\n- Sustainably sourced Arctic cod and bottled under Norway’s century-old Möller’s quality standards.\n- Refreshing lemon flavor with no fishy aftertaste; kid- and pregnancy-friendly.",
    },
]

SPONSORED_PRODUCTS = [
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
            "Item Weight": "0.37 Kilograms",
        },
        "image_url": "https://m.media-amazon.com/images/I/71ZBnxvlvCL._AC_SL1500_.jpg",
        "product_url": "https://www.amazon.com/Strength-Support-Non-GMO-Burpless-Softgels/dp/B01NBTJFJB/",
        "sponsored": True,
        "page_description": "**About this item**\n- Triple-strength 2 500 mg fish oil with 1 500 mg EPA & 570 mg DHA per serving.*\n- The fatty acids in fish oil support healthy eyes, brain, immune system, and so much more.*\n- IFOS & Labdoor-certified; wild-caught, purified to minimize contaminants.\n- Easy-swallow, burp-less softgels in re-esterified triglyceride form for absorption.",
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
            "Item Weight": "1.34 Pounds",
        },
        "image_url": "https://m.media-amazon.com/images/I/61AF1Mw+RkL._AC_SL1500_.jpg",
        "product_url": "https://www.amazon.com/Swisse-Supplement-Sustainably-Essential-Promotes/dp/B0D45ZYSWZ?th=1",
        "sponsored": True,
        "page_description": "**About this item**\n- Premium 1 000 mg odorless wild-fish oil for heart, brain & eye support.\n- Sustainably sourced & heavy-metal tested (mercury, lead, etc.).\n- 400-softgel value size delivers DHA + EPA to aid mood & nervous-system balance.\n- Crafted by Swisse with strict purity & potency standards.",
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
            "Item Weight": "3.48 Grams",
        },
        "image_url": "https://m.media-amazon.com/images/I/61gW5yxTCgL._AC_SX679_.jpg",
        "product_url": "https://www.amazon.com/GNC-Strength-Potency-Quality-Supplement/dp/B01NCSCP1Y",
        "sponsored": True,
        "page_description": "**About this item**\n- Delivers 1 000 mg EPA/DHA to support cardiovascular wellness.\n- Also aids brain, eye, skin & joint health; may benefit muscle function.\n- Enteric-coated, burp-less softgels with balanced-mood support.\n- Wild-caught deep-ocean fish, purified & gluten-free—no sugars or dyes.",
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
            "Item Weight": "7.4 Ounces",
        },
        "image_url": "https://m.media-amazon.com/images/I/61C6MAD6f1L._AC_SL1000_.jpg",
        "product_url": "https://www.amazon.com/Viva-Naturals-Triple-Strength-Supplement/dp/B0CB4QHF3N",
        "sponsored": True,
        "page_description": "**About this item**\n- Omega-3s for heart, brain, skin & eye health.\n- Purified to reduce mercury, PCBs & dioxins below IFOS limits.\n- Re-esterified triglyceride form for superior absorption.\n- IFOS & Labdoor-certified; wild-caught and sustainably sourced.",
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
            "Item Weight": "11.2 ounces",
        },
        "image_url": "https://m.media-amazon.com/images/I/61DfA7Q2L1L.__AC_SX300_SY300_QL70_FMwebp_.jpg",
        "product_url": "https://www.amazon.com/Natures-Bounty-Fish-1200mg-Softgels/dp/B0061GLLZU",
        "sponsored": True,
        "page_description": "**About this item**\n- Helps maintain triglyceride levels that are already within the normal range.\n- Omega-3s support metabolic and immune health.\n- Rapid-release 1 200 mg softgels for quick dispersion.\n- From a Nature’s Bounty brand trusted for nearly 50 years.",
    },
]


def get_completion_url():
    try:
        return st.secrets.get("COMPLETION_URL", None) or os.getenv(
            "COMPLETION_URL"
        ) or "https://app.prolific.com/submissions/complete?cc=CIR2NCAF"
    except Exception:
        return os.getenv("COMPLETION_URL") or "https://app.prolific.com/submissions/complete?cc=CIR2NCAF"


def get_credentials_from_secrets():
    creds_dict = {key: value for key, value in st.secrets["GOOGLE_CREDENTIALS"].items()}
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    return creds_dict


def save_to_gsheet(data) -> bool:
    data = dict(data)
    data.setdefault("variant", CONDITION_CODE)
    last_err = None
    for attempt in range(5):
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(
                get_credentials_from_secrets(),
                scopes=[
                    "https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive",
                ],
            )
            client = gspread.authorize(creds)
            sheet = client.open(GSHEET_NAME).sheet1
            sheet.append_row(
                [data.get(k, "") for k in ["id", "start", "variant", "timestamp", "type", "title", "url"]],
                value_input_option="USER_ENTERED",
            )
            return True
        except Exception as e:
            last_err = e
            if attempt < 4:
                time.sleep(min(0.25 * (2**attempt), 4.0) + random.uniform(0, 0.2))
    try:
        st.session_state["_gsheet_last_error"] = str(last_err) if last_err else ""
    except Exception:
        pass
    return False


def log_event(event_type, title, url=" "):
    return save_to_gsheet(
        {
            "id": st.session_state.get("prolific_id", "unknown"),
            "start": st.session_state.get("start_time", datetime.now().isoformat()),
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "title": title,
            "url": url,
        }
    )


st.set_page_config(page_title="Querya", layout="wide")

if "start_time" not in st.session_state:
    st.session_state.start_time = datetime.now().isoformat()
st.session_state.setdefault("stage", "pid")
st.session_state.setdefault("page", "main")
st.session_state.setdefault("current_product", {})
st.session_state.setdefault("current_product_type", "")
st.session_state.setdefault("completed", False)
st.session_state["variant"] = CONDITION_CODE

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
      /* Peach border *and* a bit of breathing room */
      div:has(> #ad-box-anchor) {
        border: 1px solid #FEE9DF !important;   /* peach border        */
        border-radius: 6px;
        padding: 14px !important;               /* so the content
                                                  doesn't cover border */
      }
      /* Make sure Streamlit columns inside are transparent */
      div:has(> #ad-box-anchor) [data-testid="column"] {
        background: transparent !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


def render_specs_table(specs):
    if not specs:
        return
    rows = "\n".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in specs.items())
    st.markdown(f"<table class='table-specs'>{rows}</table>", unsafe_allow_html=True)


def render_suggestion_chips(queries, prefix):
    chosen = None
    for i, query in enumerate(queries):
        if st.button(query, key=f"{prefix}_{i}", help="chip"):
            chosen = query
    return chosen


def render_logo():
    try:
        logo_b64 = base64.b64encode(Path("querya.png").read_bytes()).decode()
        st.markdown(
            f"<div style='text-align:center; margin-top:20px;'><img src='data:image/png;base64,{logo_b64}' style='height:80px;' /></div>",
            unsafe_allow_html=True,
        )
    except Exception:
        pass


def show_product_item(p, *, link_type="organic", show_image=False, orientation="horizontal", image_position="none"):
    if orientation == "vertical" and show_image and p.get("image_url"):
        st.markdown(
            f"<img src='{p['image_url']}' "
            f"style='display:block; margin:0 auto; "
            f"width:120px; height:120px; object-fit:contain;'>",
            unsafe_allow_html=True,
        )

    label_text = f"Sponsored · {p['title']}" if link_type == "ad" else p["title"]
    if st.button(label_text, key=f"prod_{p['id']}"):
        save_to_gsheet(
            {
                "id": st.session_state.prolific_id,
                "start": st.session_state.start_time,
                "timestamp": datetime.now().isoformat(),
                "type": link_type,
                "title": p["title"],
                "url": p.get("product_url", " "),
            }
        )
        st.session_state.update({"page": "product", "current_product": p, "current_product_type": link_type})
        st.rerun()

    if show_image and image_position == "below" and p.get("image_url"):
        st.markdown(
            f"<img src='{p['image_url']}' "
            f"style='display:block; margin:6px auto 0 auto; "
            f"width:120px; height:120px; object-fit:contain;'>",
            unsafe_allow_html=True,
        )


def show_advertisements(relevant_products):
    with st.container(border=True):
        st.markdown("<div id='ad-box-anchor'></div>", unsafe_allow_html=True)
        st.markdown(
            "<div style='position:relative;'>"
            "<span style='position:absolute; top:-12px; left:-12px; "
            "background:#e53935; color:#fff; font-size:13px; "
            "padding:4px 10px; border-radius:4px;'>Querya Advertising</span>"
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


def render_product_results():
    st.markdown(RESPONSE_HEADING)
    st.markdown("<div style='height:0.5rem;'></div>", unsafe_allow_html=True)
    show_advertisements(SPONSORED_PRODUCTS)
    st.write("---")
    for item in ORGANIC_PRODUCTS:
        show_product_item(item, link_type="organic", show_image=True, image_position="below")
        if item.get("description"):
            st.markdown(item["description"])
        st.write("---")


def back_to_main():
    save_to_gsheet(
        {
            "id": st.session_state.prolific_id,
            "start": st.session_state.start_time,
            "timestamp": datetime.now().isoformat(),
            "type": "back",
            "title": "Back to main",
            "url": " ",
        }
    )
    time.sleep(0.5)
    st.session_state.update({"page": "main", "current_product": {}, "current_product_type": ""})


def render_product_page():
    p = st.session_state.current_product
    st.button("← Back", key="back_to_main", help="back", on_click=back_to_main)

    col_img, col_info, col_buy = st.columns([4, 5, 3])
    with col_img:
        if p.get("image_url"):
            st.image(p["image_url"], use_container_width=True)
    with col_info:
        if p.get("page_description"):
            with st.expander("About this item", expanded=True):
                st.markdown(p["page_description"])
        if p.get("specs"):
            st.markdown("#### Product details")
            render_specs_table(p.get("specs"))
    with col_buy:
        with st.container(border=True):
            if p.get("price"):
                st.markdown(f"**Price**: {p['price']}")
            if st.session_state.get("current_product_type") == "ad":
                st.caption("Sponsored product")


def instructions_button_inline():
    if hasattr(st, "popover"):
        with st.popover("Instructions"):
            st.markdown(INSTRUCTIONS_MD)
    else:
        show = st.session_state.get("_show_instr_box", False)
        if st.button("Instructions"):
            st.session_state["_show_instr_box"] = not show
            st.rerun()
        if st.session_state.get("_show_instr_box", False):
            st.info(INSTRUCTIONS_MD)


def render_header():
    col1, col_mid, col2 = st.columns([5.6, 1.6, 1])
    with col1:
        st.title(PAGE_TITLE)
    with col_mid:
        instructions_button_inline()
    with col2:
        if st.button("Finish / End Session", key="finish_button_inline"):
            log_event("finish_click", "Finish / End Session")
            st.session_state.stage = "survey"
            st.rerun()


def render_instructions_page():
    st.markdown(INSTRUCTIONS_MD)
    hold_seconds = 20
    if "instructions_start_ts" not in st.session_state:
        st.session_state.instructions_start_ts = time.time()
    elapsed = int(time.time() - st.session_state.instructions_start_ts)
    remaining = max(0, hold_seconds - elapsed)
    st.caption(f"Minimum reading time: {hold_seconds}s ")
    if st.button("Next / Start"):
        if remaining > 0:
            st.error(f"Please read the instructions for at least {hold_seconds} seconds before proceeding. {remaining}s remaining.")
            log_event("instructions_next_too_early", f"{CONDITION_LABEL} | remaining={remaining}s")
            return
        log_event("enter_experiment", CONDITION_LABEL)
        st.session_state.stage = "experiment"
        st.rerun()


def submit_first_query(query):
    query = (query or "").strip()
    if not query:
        st.error("Please enter or select one question to start.")
        return
    st.session_state.first_message_submitted = True
    st.session_state.first_query_text = query
    log_event("first_query", query)
    st.rerun()


def render_ai_experiment():
    render_header()
    st.session_state.setdefault("first_message_submitted", False)
    st.session_state.setdefault("first_query_text", "")
    if st.session_state.first_message_submitted:
        st.chat_message("user").write(st.session_state.first_query_text)
        with st.chat_message("assistant"):
            render_product_results()
        user_input = st.chat_input("Only one query is needed for this study. Click 'Finish / End Session' when ready.")
        if user_input:
            st.chat_message("user").write(user_input)
            log_event("extra_query_attempt", user_input[:200])
            with st.chat_message("assistant"):
                st.info("Thanks! For this study, you only need to enter one query. Please click Finish / End Session in the top-right corner to proceed to the survey.")
        return

    render_logo()
    st.markdown("**Choose or enter one question to start:**")
    query = st.text_input("", placeholder=SUGGESTED_QUERIES[0], key="first_query_input")
    chosen = render_suggestion_chips(SUGGESTED_QUERIES, "sug_ai")
    if chosen:
        submit_first_query(chosen)
    if st.button("Start", key="start_ai_query"):
        submit_first_query(query)


def run_search(query):
    query = (query or "").strip()
    if not query:
        st.error("Please enter or select one search to start.")
        return
    st.session_state.search_started = True
    st.session_state.search_query_text = query
    log_event("search_submit", query)
    st.rerun()


def render_search_experiment():
    render_header()
    st.session_state.setdefault("search_started", False)
    st.session_state.setdefault("search_query_text", "")
    render_logo()

    if not st.session_state.search_started:
        st.markdown("**Choose or enter one question to start:**")
        query = st.text_input("", placeholder=SUGGESTED_QUERIES[0], key="first_search_query")
        chosen = render_suggestion_chips(SUGGESTED_QUERIES, "sug_search")
        if chosen:
            run_search(chosen)
        if st.button("Search", key="btn_search_first"):
            run_search(query)
        return

    query2 = st.text_input("", placeholder="Search again (optional)", key="search_again")
    if st.button("Search", key="btn_search_again"):
        run_search(query2)
    st.write("---")
    render_product_results()


def is_blank(x) -> bool:
    return x is None or (isinstance(x, str) and x.strip() == "")


def render_final_survey_page():
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

    st.title("Final Survey")
    with st.form("final_survey"):
        st.markdown("Please complete **all** questions on this page. There is no default selection.")
        st.markdown("**1. Which of the following best describes your goal in this task scenario?**")
        mc_goal = st.radio(
            "",
            options=[
                "To better understand whether fish oil supplements would be suitable for me",
                "To compare fish oil supplement options and decide which one to buy",
            ],
            index=None,
            key="mc_goal",
            label_visibility="collapsed",
        )
        st.markdown("**2. Which type of system did you use to complete the task in this study?**")
        mc_system = st.radio(
            "",
            options=["An AI chatbot", "A search engine"],
            index=None,
            key="mc_system",
            label_visibility="collapsed",
        )
        st.markdown('**3. Did you notice any “sponsored” products (i.e., advertisements) on the page you viewed?**')
        mc_ads = st.radio(
            "",
            options=["Yes", "No"],
            index=None,
            key="mc_ads",
            label_visibility="collapsed",
        )
        st.markdown("---")
        st.markdown("**Your age:**")
        age_str = st.text_input("", value="", key="demo_age", placeholder="Enter an integer between 18 and 99", label_visibility="collapsed")
        st.markdown("**Your sex:**")
        sex = st.radio("", options=["Male", "Female"], index=None, key="demo_sex", label_visibility="collapsed")
        st.markdown("**Your educational background:**")
        edu = st.selectbox(
            "",
            options=["Less than high school", "High school graduate", "Bachelor or equivalent", "Master", "Doctorate"],
            index=None,
            placeholder="Select",
            key="demo_edu",
            label_visibility="collapsed",
        )
        st.markdown("**Your ethnicity:**")
        ethnicity = st.selectbox(
            "",
            options=["White", "Black or African American", "American Indian or Alaska Native", "Asian", "Native Hawaiian or Pacific Islander", "Other"],
            index=None,
            placeholder="Select",
            key="demo_ethnicity",
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
        "goal": mc_goal,
        "system": mc_system,
        "ads": mc_ads,
        "sex": sex,
        "education": edu,
        "ethnicity": ethnicity,
    }
    if age_err or any(is_blank(v) for v in required.values()):
        if age_err:
            st.error(age_err)
        st.error("Please complete all required questions before submitting.")
        return

    answers = {
        "condition": {
            "code": CONDITION_CODE,
            "label": CONDITION_LABEL,
            "system_type": SYSTEM_TYPE,
            "stage_type": STAGE_TYPE,
        },
        "manipulation_checks": {
            "goal": mc_goal,
            "system_used": mc_system,
            "noticed_sponsored": mc_ads,
        },
        "demographics": {
            "age": age_val,
            "sex": sex,
            "education": edu,
            "ethnicity": ethnicity,
        },
    }
    ok = save_to_gsheet(
        {
            "id": st.session_state.get("prolific_id", "unknown"),
            "start": st.session_state.get("start_time", datetime.now().isoformat()),
            "timestamp": datetime.now().isoformat(),
            "type": "survey",
            "title": "final_survey",
            "url": json.dumps(answers, ensure_ascii=False),
        }
    )
    if not ok:
        st.error("We could not record your responses due to a temporary server/network error. Please click Submit again. Do not close this tab yet.")
        err_txt = st.session_state.get("_gsheet_last_error", "")
        if err_txt:
            st.caption(f"Debug info: {err_txt}")
        return
    target = get_completion_url()
    st.session_state["survey_locked"] = True
    st.session_state["completion_url"] = target
    st.success("Submitted. Please click below to complete:")
    try:
        st.link_button("Please click here to complete", target)
    except Exception:
        st.markdown(f"[Please click here to complete]({target})")
    st.stop()


def render_pid_page():
    st.title("Welcome!")
    pid = st.text_input("Please enter your Prolific ID:")
    if st.button("Confirm"):
        if not pid.strip():
            st.error("Please enter your Prolific ID.")
            return
        st.session_state.prolific_id = pid.strip()
        log_event("pid_entered", "pid_ok")
        log_event("condition_assigned", CONDITION_LABEL)
        st.session_state.stage = "instructions"
        st.rerun()


def main():
    if st.session_state.stage == "pid":
        render_pid_page()
        st.stop()
    if st.session_state.stage == "instructions":
        render_instructions_page()
        st.stop()
    if st.session_state.stage == "survey":
        render_final_survey_page()
        st.stop()
    if st.session_state.page == "product" and st.session_state.current_product:
        render_product_page()
        return
    if SYSTEM_TYPE == "ai":
        render_ai_experiment()
    else:
        render_search_experiment()


if __name__ == "__main__":
    main()
