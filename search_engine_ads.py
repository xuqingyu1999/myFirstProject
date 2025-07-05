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


def get_credentials_from_secrets():
    # 还原成 dict
    creds_dict = {key: value for key, value in st.secrets["GOOGLE_CREDENTIALS"].items()}
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    
    return creds_dict


# def save_to_gsheet(data: dict):
#     scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
#     creds = ServiceAccountCredentials.from_json_keyfile_name("streamlit_app.json", scope)
#     client = gspread.authorize(creds)
#     sheet = client.open("Click History").sheet1
#     sheet.append_row([data[k] for k in ["id", "timestamp", "type", "title", "url"]])

def save_to_gsheet(data):
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
            sheet.append_row([data[k] for k in ["id", "timestamp", "type", "title", "url"]])
            return ''
        except Exception as e:
            time.sleep(0.5)

    return ''
# simple in‑memory router
st.session_state.setdefault("page", "main")         # "main" | "product"
st.session_state.setdefault("current_product", {})  # dict of the product being viewed

st.session_state.setdefault("favorites", {})
############################################
# Step 0: Page config & DeepSeek client
############################################
st.set_page_config(page_title="🛒 DeepSeek 实验", layout="wide")

API_KEY = os.getenv("DEEPSEEK_API_KEY") or "sk-ce6eb3e9045c4110862945af28f4794e"
client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com/v1")

# Record the app's start time if not set
if "start_time" not in st.session_state:
    st.session_state.start_time = datetime.now().isoformat()

############################################
# 1) Custom CSS to style all st.buttons like links
############################################
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

st.markdown(
    """
    <style>
      /* tighten ONLY the star buttons (title="star")  */
      div.stButton > button[title="collect"] {
        display: inline-block !important;
        background: none       !important;
        border: none           !important;
        padding: 0             !important;
        margin: 0 0 0 4px      !important;   /* 4‑px gap from the title */
        font-size: 20px        !important;
        line-height: 1         !important;
        width: auto            !important;
        color: #008080         !important;   /* teal; pick any colour   */
      }
      div.stButton > button[title="collect"]:hover {
        color: #000;                           /* darker on hover        */
      }
    </style>
    """,
    unsafe_allow_html=True,
)


############################################
# 2) Regex-based parser for [Title](URL) links in LLM text
############################################
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
        prod = PRODUCT_CATALOG.get(label)           # may be None
        seg = {"type": "link", "label": label, "url": url}
        if prod:
            seg.update(prod)                        # enrich if in catalogue
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
            show_product_item(seg, link_type=link_type, show_image=False)
        elif seg["type"] == "text":
            st.markdown(seg["content"])
        else:  # non‑product link
            st.markdown(f'[{seg["label"]}]({seg["url"]})')

def render_predefined_products(prod_list, heading, link_type="organic"):
    """Print heading once, then for each product: title ★ + description."""
    st.markdown(heading)
    for p in prod_list:
        show_product_item(p, link_type=link_type, show_image=False)
        if p.get("description"):
            st.markdown(p["description"])

############################################
# 3) Predefined replies
############################################
# KEYWORD_RESPONSES = {
#     # 键写关键词，值写你想直接返回的内容
#     # 命中逻辑 = “用户输入里包含该关键词（不区分大小写）”
#     "fish oil": """
#     Certainly! Here are some well-regarded fish oil supplements that are commonly recommended based on quality, purity, and third-party testing
# ### **I. Recommended High-Reputation Fish-Oil Brands**
# [**Nordic Naturals Ultimate Omega**](https://www.amazon.com/Nordic-Naturals-Ultimate-Support-Healthy/dp/B002CQU564/ref=sr_1_1?content-id=amzn1.sym.c9738cef-0b5a-4096-ab1b-6af7c45832cd%3Aamzn1.sym.c9738cef-0b5a-4096-ab1b-6af7c45832cd&dib=eyJ2IjoiMSJ9.EmMg0Sjrk3Up1-B8Uq6XmXPfqBR6LsN4xh_xk9FkohcxjUGjjtl8VDmFPAv02s7DdvP4IMVJlYCiu4xLS3tkFzqAjY8zzLpTcrQiGDBHfSlCICd1rxDQrjuX09VNQDqQLzn3cHDWmdL3cWFyPa6GoFGZn3Y4_gA0M70XM89DcYOwpBeQlrC5yad9lab17AwZgciNRLxb8byU-LfuW17zz3q-IozuDG-egQAIeXgugVoJ8WRIvJz3NkILl22JMYtajLueBHt6DzsSWXw0pyyU1wzGr_pw1-I-LzakONQMKjk.5XQSZpgWB9fgxSBUCDKvd3csceCcXwJ8hgXGTLOIUrg&dib_tag=se&keywords=Nordic%2BNaturals%2BUltimate%2BOmega%2BCognition&pd_rd_r=dbeef994-8b31-4a6a-965d-1774b9bbb5c4&pd_rd_w=oTInk&pd_rd_wg=3hsHS&qid=1747570281&sr=8-1&th=1)
#    - Features: High-concentration EPA/DHA (650 mg Omega-3 per soft-gel); IFOS 5-star certified; triglyceride (TG) form for superior absorption.
#    - Ideal for: Cardiovascular health, anti-inflammatory needs, or anyone seeking a highly purified fish oil.
#
# [**WHC UnoCardio 1000** ](https://www.amazon.com/stores/page/29B9D3D0-5A5E-4EEA-A0A2-D812CA2F8559/?_encoding=UTF8&store_ref=SB_A076637421Z7I7ERZ0TXQ-A03352931L0DK4Z7CLDKO&pd_rd_plhdr=t&aaxitk=49fae88956cfec31cfd29cac8b8abde1&hsa_cr_id=0&lp_asins=B00QFTGSK6%2CB01MQJZI9D%2CB07NLCBPGN&lp_query=WHC%20UnoCardio%201000&lp_slot=desktop-hsa-3psl&ref_=sbx_be_s_3psl_mbd_mb0_logo&pd_rd_w=kHhnR&content-id=amzn1.sym.5594c86b-e694-4e3e-9301-a074f0faf98a%3Aamzn1.sym.5594c86b-e694-4e3e-9301-a074f0faf98a&pf_rd_p=5594c86b-e694-4e3e-9301-a074f0faf98a&pf_rd_r=J95ESAZ01FFJGKDH15S5&pd_rd_wg=udhtB&pd_rd_r=1ca75ded-9d8a-4db4-9e02-4051fdc574f2)
#    - Features: Ranked No. 1 globally by IFOS; 1,000 mg Omega-3 (EPA + DHA) per soft-gel; enriched with vitamin D3; individually blister-packed to prevent oxidation.
#    - Ideal for: Middle-aged and older adults who demand top purity and a premium formulation.
#
# [**Now Foods Ultra Omega-3** ](https://www.amazon.com/NOW-Supplements-Molecularly-Distilled-Softgels/dp/B0BGQR8KSG/ref=sr_1_1?crid=1WK5FQS4N6VT9&dib=eyJ2IjoiMSJ9.sczFj7G5tzaluW3utIDJFvN3vRVXIKN8OW6iAI1rL8RiGXrbNcV75KmT0QHEw_-mrjN9Y2Z_QXZcyi9A3KwDB5TpToVICSiFPa7RnnItgqpDWW7DzU2ECbX73MLiBO0nOBcQe4If9EV_QeFtgmERZF360mEcTJ3ZfaxrOKNzI8A.dUyPZz9HZwZJIqkDLMtL5snAfj0y8Ayu3PNq8Ugt-WU&dib_tag=se&keywords=Now%2BFoods%2BUltra%2BOmega-3&qid=1747669011&sprefix=now%2Bfoods%2Bultra%2Bomega-3%2Caps%2C677&sr=8-1&th=1)
#    - Features: Great value (EPA 500 mg + DHA 250 mg per soft-gel); IFOS certified; suitable for long-term, everyday supplementation.
#    - Ideal for: General health maintenance, budget-conscious consumers, and daily nutritional support.
#
# [**Blackmores OMEGA BRAIN Caps 60s** ](https://www.amazon.com.au/Blackmores-Omega-Triple-Concentrated-Capsules/dp/B0773JF7JX?th=1)
#    - Features: Best-selling Australian pharmacy product; 900 mg Omega-3 per soft-gel; supports cardiovascular health.
#    - Ideal for: Intensive cardiovascular support, joint health, and individuals seeking a high-dose omega-3 supplement.
#
# [**Möller’s Norwegian Cod-Liver Oil**](https://www.amazon.com.be/-/en/Mollers-Omega-Norwegian-Cod-Liver-Pruners/dp/B074XB9RNH?language=en_GB)
#    - Features: Liquid fish oil enriched with natural vitamins A and D; trusted Nordic brand with over 100 years of history; suitable for children and pregnant women.
#    - Ideal for: Family supplementation, children’s health, pregnancy nutritional support, and enhancing immune function.
#
# """
#     ,
#     "liver":
#         """
#         Certainly! Here are some well-regarded liver-support supplements that are commonly recommended based on quality, purity, and third-party testing.
#         ### **I. Recommended High-Quality Liver-Support Brands**
#         [**Thorne Liver Cleanse**](https://www.amazon.com/Thorne-Research-Cleanse-Detoxification-Capsules/dp/B07978NYC5)
#            - Features: Professional-grade formula that combines milk thistle (125 mg silymarin), burdock, chicory, berberine, and other botanicals; NSF-Certified for Sport®; produced in a GMP-compliant U.S. facility.
#            - Ideal for: Individuals looking for a broad-spectrum botanical detox blend—especially those who value third-party testing and athlete-friendly certifications.
#
#         [**Himalaya LiverCare (Liv 52 DS)**](https://www.amazon.com.be/-/en/Himalaya-Liv-52-DS-3-Pack/dp/B09MF88N71)
#            - Features: Clinically studied Ayurvedic blend (capers, chicory, black nightshade, arjuna, yarrow, etc.) shown to improve Child-Pugh scores and reduce ALT/AST in liver-compromised patients.
#            - Ideal for: Those seeking a time-tested herbal formula with human-trial evidence, including individuals with mild enzyme elevations or high environmental/toxic exposure.
#
#         [**Jarrow Formulas Milk Thistle (150 mg)**](https://www.amazon.com/Jarrow-Formulas-Silymarin-Marianum-Promotes/dp/B0013OULVA?th=1)
#            - Features: 30:1 standardized silymarin phytosome bonded to phosphatidylcholine for up-to-30× higher bioavailability than conventional milk thistle; vegetarian capsules; gluten-, soy-, and dairy-free.
#            - Ideal for: People who need a concentrated, highly absorbable milk-thistle extract—e.g., those on multiple medications or with occasional alcohol use.
#
#         [**NOW Foods Liver Refresh™**](https://www.amazon.com/Liver-Refresh-Capsules-NOW-Foods/dp/B001EQ92VW?th=1)
#            - Features: Synergistic blend of milk thistle, N-acetyl cysteine (NAC), methionine, and herbal antioxidants; non-GMO Project Verified and GMP-qualified.
#            - Ideal for: Individuals wanting comprehensive antioxidant support—such as frequent travelers, people with high oxidative stress, or those following high-protein diets.
#
#         [**Nutricost TUDCA 250 mg**](https://www.amazon.com/Nutricost-Tudca-250mg-Capsules-Tauroursodeoxycholic/dp/B01A68H2BA?th=1)
#            - Features: Pure tauroursodeoxycholic acid (TUDCA) at 250 mg per veggie capsule; non-GMO, soy- and gluten-free; 3rd-party ISO-accredited lab tested; made in an FDA-registered, GMP facility.
#            - Ideal for: Advanced users seeking bile-acid–based cellular protection—popular among those with cholestatic or high-fat-diet concerns.
#         """,
#     "优惠码": "🎁 **本月通用优惠码：DS-MAY25**\n下单立减 25 元（限时 5 月 31 日前，秒杀品除外）。",
#     # 继续添加更多：
#     # "shipping": "标准配送 48 h 内发货，全国包邮。",
# }


# ─── 🗂  Central catalogue (20 items) ─────────────────────────────
PRODUCT_CATALOG = {
    # ── Fish-oil group ──
    "Nordic Naturals Ultimate Omega": {
        "id": "fish_01",
        "title": "Nordic Naturals Ultimate Omega",
        "product_url": "https://www.amazon.com/Nordic-Naturals-Ultimate-Support-Healthy/dp/B002CQU564",
        "image_url": "https://m.media-amazon.com/images/I/61x5u8LMFWL._AC_SL1000_.jpg",
        "description": "- Features: High-concentration EPA/DHA (650 mg Omega-3 per soft-gel); IFOS 5-star certified; triglyceride (TG) form for superior absorption.\n- Ideal for: Cardiovascular health, anti-inflammatory needs, or anyone seeking a highly purified fish oil.",
        "page_description": "[**About this item**]\n- WHY OMEGA-3s – EPA & DHA support heart, brain, eye and immune health, and help maintain a healthy mood.\n- DOCTOR-RECOMMENDED dose meets American Heart Association guidelines for cardiovascular support.\n- BETTER ABSORPTION & TASTE – Triglyceride form with pleasant lemon flavor and zero fishy burps.\n- PURITY GUARANTEED – Wild-caught fish, non-GMO, gluten- & dairy-free with no artificial additives."
    },

    "WHC UnoCardio 1000": {
        "id": "fish_02",
        "title": "WHC UnoCardio 1000",
        "product_url": "https://www.amazon.com/WHC-UnoCardio-Softgels-Triglyceride-concentration/dp/B00QFTGSK6",
        "image_url": "https://m.media-amazon.com/images/I/71htaA+bT9L._AC_SL1500_.jpg",
        "description": "- Features: Ranked No. 1 globally by IFOS; 1 000 mg Omega-3 (EPA + DHA) per soft-gel; enriched with vitamin D3; individually blister-packed to prevent oxidation.\n- Ideal for: Middle-aged and older adults who demand top purity and a premium formulation.",
        "page_description": "[**About this item**]\n- 1 180 mg total Omega-3 (EPA 665 mg / DHA 445 mg) per soft-gel for heart, brain and vision.\n- Provides 1 000 IU vitamin D3 to support bones, muscles and immunity.\n- r-Triglyceride form for superior absorption; lactose- & gluten-free, burp-free orange flavor.\n- Ultra-pure, Friend-of-the-Sea-certified fish oil in beef-gelatin-free blister packs."
    },

    "Now Foods Ultra Omega-3": {
        "id": "fish_03",
        "title": "Now Foods Ultra Omega-3",
        "product_url": "https://www.amazon.com/NOW-Ultra-Omega-Fish-Softgels/dp/B000SE5SY6",
        "image_url": "https://m.media-amazon.com/images/I/51xrY5WFFIL._AC_.jpg",
        "description": "- Features: Great value (EPA 500 mg + DHA 250 mg per soft-gel); IFOS certified; suitable for long-term, everyday supplementation.\n- Ideal for: General health maintenance, budget-conscious consumers, and daily nutritional support.",
        "page_description": "[**About this item**]\n- CARDIOVASCULAR SUPPORT – 600 mg EPA & 300 mg DHA per enteric-coated soft-gel.\n- MOLECULARLY DISTILLED for purity; tested free of PCBs, dioxins & heavy metals.\n- ENTERIC COATING reduces nausea and fishy aftertaste.\n- NON-GMO, Kosher and GMP-quality assured by the family-owned NOW® brand since 1968."
    },

    "Blackmores OMEGA BRAIN Caps 60s": {
        "id": "fish_04",
        "title": "Blackmores OMEGA BRAIN Caps 60s",
        "product_url": "https://www.amazon.com/Blackmores-OMEGA-BRAIN-Caps-60s/dp/B00AQ7T7UQ",
        "image_url": "https://m.media-amazon.com/images/I/71UhUKoWbnL._AC_SL1500_.jpg",
        "description": "- Features: Blackmores Omega Brain Capsules provide concentrated omega-3 fatty acids, particularly high DHA levels to support brain structure and enhance cognitive function.\n- Ideal for: Intensive cardiovascular support, joint health, and individuals seeking a high-dose omega-3 supplement.",
        "page_description": "[**About this item**]\n- One-a-day capsule delivers 500 mg DHA to maintain brain health and mental performance.\n- Provides four-times more DHA than standard fish oil—ideal if you eat little fish.\n- 100 % wild-caught small-fish oil rigorously tested for mercury, dioxins & PCBs.\n- Supports healthy growth in children and overall wellbeing for all ages."
    },

    "Möller’s Norwegian Cod-Liver Oil": {
        "id": "fish_05",
        "title": "Möller’s Norwegian Cod-Liver Oil",
        "product_url": "https://www.amazon.com/M%C3%B8llers-Cod-Liver-Oil-Lemon-Flavor/dp/B084LYXCL1",
        "image_url": "https://m.media-amazon.com/images/I/61eg-Vgm97L._AC_SL1500_.jpg",
        "description": "- Features: Liquid fish oil enriched with natural vitamins A and D; trusted Nordic brand with over 100 years of history; suitable for children and pregnant women.\n- Ideal for: Family supplementation, children’s health, pregnancy nutritional support, and enhancing immune function.",
        "page_description": "[**About this item**]\n- Natural source of EPA & DHA to support heart, brain and vision.\n- Supplies vitamins A & D for immune function and normal bone growth.\n- Sustainably sourced Arctic cod and bottled under Norway’s century-old Möller’s quality standards.\n- Refreshing lemon flavor with no fishy aftertaste; kid- and pregnancy-friendly."
    },

    # ── Liver-support group ──
    "Thorne Liver Cleanse": {
        "id": "liver_01",
        "title": "Thorne Liver Cleanse",
        "product_url": "https://www.amazon.com/Thorne-Research-Cleanse-Detoxification-Capsules/dp/B07978NYC5",
        "image_url": "https://m.media-amazon.com/images/I/71eMoaqvJyL._AC_SL1500_.jpg",
        "description": "- Features: Professional-grade formula that combines milk thistle (125 mg silymarin), burdock, chicory, berberine, and other botanicals; NSF-Certified for Sport®; produced in a GMP-compliant U.S. facility.\n- Ideal for: Individuals looking for a broad-spectrum botanical detox blend—especially those who value third-party testing and athlete-friendly certifications.",
        "page_description": "[**About this item**]\n- Synergistic botanical blend enhances detoxification and bile flow.*\n- Supports both Phase I and Phase II liver detox pathways.*\n- Also provides kidney-supportive herbs for comprehensive clearance.*\n- NSF Certified for Sport® and third-party tested for contaminants."
    },

    "Himalaya LiverCare (Liv 52 DS)": {
        "id": "liver_02",
        "title": "Himalaya LiverCare (Liv 52 DS)",
        "product_url": "https://www.amazon.com.be/-/en/Himalaya-Liv-52-DS-3-Pack/dp/B09MF88N71",
        "image_url": "https://m.media-amazon.com/images/I/61VEN7Bl8wL._AC_SL1500_.jpg",
        "description": "- Features: Clinically studied Ayurvedic blend (capers, chicory, black nightshade, arjuna, yarrow, etc.) shown to improve Child-Pugh scores and reduce ALT/AST in liver-compromised patients.\n- Ideal for: Those seeking a time-tested herbal formula with human-trial evidence, including individuals with mild enzyme elevations or high environmental/toxic exposure.",
        "page_description": "[**About this item**]\n- Herbal liver-cleanse formula that helps detoxify and protect liver cells.*\n- Boosts metabolic capacity and promotes healthy bile production for digestion.*\n- Vegan caplets free of gluten, dairy, soy, corn, nuts and animal gelatin; non-GMO.\n- Trusted Ayurvedic brand since 1930 with decades of clinical research."
    },

    "Jarrow Formulas Milk Thistle (150 mg)": {
        "id": "liver_03",
        "title": "Jarrow Formulas Milk Thistle (150 mg)",
        "product_url": "https://www.amazon.com/Jarrow-Formulas-Silymarin-Marianum-Promotes/dp/B0013OULVA",
        "image_url": "https://m.media-amazon.com/images/I/71G03a0TYUL._AC_SL1500_.jpg",
        "description": "- Features: 30:1 standardized silymarin phytosome bonded to phosphatidylcholine for up-to-30× higher bioavailability than conventional milk thistle; vegetarian capsules; gluten-, soy-, and dairy-free.\n- Ideal for: People who need a concentrated, highly absorbable milk-thistle extract—e.g., those on multiple medications or with occasional alcohol use.",
        "page_description": "[**About this item**]\n- 150 mg 30:1 milk-thistle extract standardized to 80 % silymarin flavonoids.\n- Helps raise glutathione levels for healthy liver detoxification.*\n- Provides antioxidant protection against free-radical damage.*\n- Easy-to-swallow veggie capsules; adults take 1–3 daily as directed."
    },

    "NOW Foods Liver Refresh™": {
        "id": "liver_04",
        "title": "NOW Foods Liver Refresh™",
        "product_url": "https://www.amazon.com/Liver-Refresh-Capsules-NOW-Foods/dp/B001EQ92VW",
        "image_url": "https://m.media-amazon.com/images/I/71fW7Z6vFAL._AC_SL1500_.jpg",
        "description": "- Features: Synergistic blend of milk thistle, N-acetyl cysteine (NAC), methionine, and herbal antioxidants; non-GMO Project Verified and GMP-qualified.\n- Ideal for: Individuals wanting comprehensive antioxidant support—such as frequent travelers, people with high oxidative stress, or those following high-protein diets.",
        "page_description": "[**About this item**]\n- Promotes optimal liver health with milk thistle plus herbal-enzyme blend.*\n- Supports healthy detoxification processes and normal liver enzyme levels.*\n- Non-GMO, vegetarian capsules produced in a GMP-certified facility.\n- Amazon’s Choice pick with thousands of 4-plus-star reviews."
    },

    "Nutricost TUDCA 250 mg": {
        "id": "liver_05",
        "title": "Nutricost TUDCA 250 mg",
        "product_url": "https://www.amazon.com/Nutricost-Tudca-250mg-Capsules-Tauroursodeoxycholic/dp/B01A68H2BA",
        "image_url": "https://m.media-amazon.com/images/I/61EJx7JnxfL._AC_SL1500_.jpg",
        "description": "- Features: Pure tauroursodeoxycholic acid (TUDCA) at 250 mg per veggie capsule; non-GMO, soy- and gluten-free; 3rd-party ISO-accredited lab tested; made in an FDA-registered, GMP facility.\n- Ideal for: Advanced users seeking bile-acid–based cellular protection—popular among those with cholestatic or high-fat-diet concerns.",
        "page_description": "[**About this item**]\n- 250 mg TUDCA per capsule—research-backed bile acid for liver & cellular health.*\n- Convenient one-capsule daily serving; 60-count bottle is a two-month supply.\n- Non-GMO, soy- and gluten-free formula; ISO-accredited third-party tested.\n- Made in a GMP-compliant, FDA-registered U.S. facility."
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
            "price": "¥280",
            "image_url": "https://m.media-amazon.com/images/I/81yjLlHfB3L._AC_SX679_.jpg",
            "product_url": "https://www.amazon.com/fish-oil-omega-3-supplements/dp/B014LDT0ZM",
            "sponsored": True,
            "page_description": "**About this item**\n- Triple-strength 2 500 mg fish oil with 1 500 mg EPA & 570 mg DHA per serving.*\n- Supports heart, brain, skin & eye health for men and women.*\n- IFOS & Labdoor-certified; wild-caught, purified to minimize contaminants.\n- Easy-swallow, burp-less softgels in re-esterified triglyceride form for absorption."
        },
        {
            "id": "fish_07",
            "title": "Swisse Fish Oil Soft Capsules",
            "price": "¥148",
            "image_url": "https://m.media-amazon.com/images/I/61AF1Mw+RkL._AC_SL1500_.jpg",
            "product_url": "https://www.amazon.com/Swisse-Supplement-Sustainably-Essential-Promotes/dp/B0D45ZYSWZ?th=1",
            "sponsored": True,
            "page_description": "**About this item**\n- Premium 1 000 mg odorless wild-fish oil for heart, brain & eye support.\n- Sustainably sourced & heavy-metal tested (mercury, lead, etc.).\n- 400-softgel value size delivers DHA + EPA to aid mood & nervous-system balance.\n- Crafted by Swisse with strict purity & potency standards."
        },
        {
            "id": "fish_08",
            "title": "GNC Fish Oil",
            "price": "¥80",
            "image_url": "https://m.media-amazon.com/images/I/61gW5yxTCgL._AC_SX679_.jpg",
            "product_url": "https://www.amazon.com/GNC-Strength-Potency-Quality-Supplement/dp/B01NCSCP1Y",
            "sponsored": True,
            "page_description": "**About this item**\n- Delivers 1 000 mg EPA/DHA to support cardiovascular wellness.\n- Also aids brain, eye, skin & joint health; may benefit muscle function.\n- Enteric-coated, burp-less softgels with balanced-mood support.\n- Wild-caught deep-ocean fish, purified & gluten-free—no sugars or dyes."
        },
        {
            "id": "fish_09",
            "title": "Viva Naturals Fish Oil",
            "price": "¥148",
            "image_url": "https://m.media-amazon.com/images/I/61C6MAD6f1L._AC_SL1000_.jpg",
            "product_url": "https://www.amazon.com/Viva-Naturals-Triple-Strength-Supplement/dp/B0CB4QHF3N",
            "sponsored": True,
            "page_description": "**About this item**\n- Omega-3s for heart, brain, skin & eye health.\n- Purified to reduce mercury, PCBs & dioxins below IFOS limits.\n- Re-esterified triglyceride form for superior absorption.\n- IFOS & Labdoor-certified; wild-caught and sustainably sourced."
        },
        {
            "id": "fish_10",
            "title": "Nature's Bounty Fish Oil",
            "price": "¥148",
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

def render_product_page():
    """Single‑product landing page."""
    p = st.session_state.current_product

    # a) record that the page was opened
    # save_to_gsheet({
    #     "id": st.session_state.prolific_id,
    #     "start": st.session_state.start_time,
    #     "timestamp": datetime.now().isoformat(),
    #     "type": "product_page",
    #     "title": p["title"],
    #     "url": p["product_url"],
    # })

    # b) UI
    st.button("← Back", key="back_to_main", on_click=lambda: st.session_state.update({"page": "main"}))
    st.subheader(p["title"])
    # st.image(p["image_url"], use_column_width=True)
    st.image(p["image_url"], use_container_width=True)
    st.markdown(
        """
        <style>
          /* constrain the last image rendered (Streamlit wraps it in <img>) */
          img:nth-last-of-type(1) {
            max-height: 300px;               /* pick any height */
            object-fit: contain;             /* keep aspect ratio */
          }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(p["page_description"])
    # st.markdown(f"**Price:** {p['price']}")
    st.markdown("---")

    # optional external link
    # if st.button("🔗 Buy on site", key="buy_button"):
    #     open_button_link(p["product_url"])


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
                      show_image=False, orientation="horizontal"):
    """
    Render one product line.
      orientation = "horizontal" → TITLE ★        (no image)
      orientation = "vertical"   → [img]
                                      TITLE ★    (used for ads)
    """
    favs = st.session_state.favorites
    is_fav = p["product_url"] in favs
    star = "★" if is_fav else "☆"

    if orientation == "vertical" and show_image:
        # st.image(p["image_url"], width=90)               # picture on top
        st.markdown(
            f"<img src='{p['image_url']}' "
            f"style='display:block; margin:0 auto; "
            f"width:120px; height:120px; object-fit:contain;'>",
            unsafe_allow_html=True,
        )

    # title + star on same row
    if link_type=='ad':
        title_col, star_col = st.columns([2, 1], gap="small")
    else:
        title_col, star_col = st.columns([9, 1], gap="small")
    with title_col:
        if link_type=='ad':
            st.markdown("<div style='text-align:right;'>", unsafe_allow_html=True)
        else:
            st.markdown("<div style='text-align:left;'>", unsafe_allow_html=True)
        if st.button(p["title"], key=f"prod_{p['id']}"):
            save_to_gsheet({
                "id": st.session_state.prolific_id,
                "start": st.session_state.start_time,
                "timestamp": datetime.now().isoformat(),
                "type": link_type,
                "title": p["title"],
                "url": p["product_url"],
            })
            st.session_state.update({"page": "product", "current_product": p})
            st.rerun()

    with star_col:
        if link_type == 'ad':
            st.markdown("<div style='text-align:left;'>", unsafe_allow_html=True)
        else:
            st.markdown("<div style='text-align:right;'>", unsafe_allow_html=True)
        if st.button(star, key=f"fav_{p['id']}", help="collect"):
            if is_fav:
                del favs[p["product_url"]]
                save_to_gsheet({
                    "id": st.session_state.prolific_id,
                    "start": st.session_state.start_time,
                    "timestamp": datetime.now().isoformat(),
                    "type": 'uncollect',
                    "title": p["title"],
                    "url": p["product_url"],
                })
            else:
                favs[p["product_url"]] = p["title"]
                save_to_gsheet({
                    "id": st.session_state.prolific_id,
                    "start": st.session_state.start_time,
                    "timestamp": datetime.now().isoformat(),
                    "type": 'collect',
                    "title": p["title"],
                    "url": p["product_url"],
                })
            st.rerun()

############################################
# 6) Ads in a 5-column grid
############################################
def show_advertisements(relevant_products):
    with st.container(border=True):
        st.markdown("<div style='text-align: center;'></div>", unsafe_allow_html=True)

        # st.markdown(
        #     """
        #       <div style="position:absolute; top:-14px; left:-14px; background-color:#e53935; color:white; font-size:14px; padding:6px 12px; border-radius:4px;">
        #         sponsored
        #       </div>
        #     """,
        #     unsafe_allow_html=True
        # )
        # st.markdown("<div style='text-align: center;'></div>", unsafe_allow_html=True)
        st.markdown(
            "<div style='position:relative;'>"
            "<span style='position:absolute; top:-12px; left:-12px; "
            "background:#e53935; color:#fff; font-size:13px; "
            "padding:4px 10px; border-radius:4px;'>sponsored</span></div>",
            unsafe_allow_html=True,
        )
        n = len(relevant_products)
        col_count = 5
        rows = math.ceil(n / col_count)

        for r in range(rows):
            row_cols = st.columns(col_count, gap="small")
            for c in range(col_count):
                idx = r * col_count + c
                if idx >= n:
                    break
                product = relevant_products[idx]
                with row_cols[c]:
                    show_product_item(
                        product,
                        link_type="ad",
                        show_image=True,
                        orientation="vertical",  # picture on top
                    )
                    # st.markdown(f"""
                    # <div style="flex-shrink:0; margin-right:8px;">
                    #   <img src="{product['image_url']}"
                    #        style="width:80px; height:80px; object-fit:contain;" />
                    # </div>
                    # <div style="display:flex; flex-direction:column; justify-content:center;">
                    # """, unsafe_allow_html=True)
                    #
                    # record_link_click_and_open(
                    #     label=product["title"],
                    #     url=product["product_url"],
                    #     link_type="ad"
                    # )
                    # st.markdown("</div></div>", unsafe_allow_html=True)


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
if "variant" not in st.session_state:
    st.session_state.variant = random.randint(1, 4)
variant = 4#st.session_state.variant


############################################
# 8) DeepSeek Recommendation Flow
############################################
def show_deepseek_recommendation(with_ads: bool):
    col1, col2 = st.columns([6, 1])
    with col1:
        st.title("Querya Rec")
    with col2:
        end_clicked = st.button("Finish / End Session", key="end_button_inline")

    if end_clicked:
        # Full-screen centered message (clears interface)
        st.session_state["end_clicked"] = True
        click_data = {
            "id": st.session_state.get("prolific_id", "unknown"),
            "start": st.session_state.get("start_time", datetime.now().isoformat()),
            "timestamp": datetime.now().isoformat(),
            "type": "end",
            "title": "Finish / End Session",
            "url": " "
        }
        save_to_gsheet(click_data)
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
    if not st.session_state.first_message_submitted:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            user_first_input = st.text_input("**Please enter your message:**")

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
        end_clicked = st.button("Finish / End Session", key="end_button_inline")

    if end_clicked:
        # Full-screen centered message (clears interface)
        st.session_state["end_clicked"] = True
        click_data = {
            "id": st.session_state.get("prolific_id", "unknown"),
            "start": st.session_state.get("start_time", datetime.now().isoformat()),
            "timestamp": datetime.now().isoformat(),
            "type": "end",
            "title": "Finish / End Session",
            "url": " "
        }
        save_to_gsheet(click_data)
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
                    "image_url": "https://m.media-amazon.com/images/I/61x5u8LMFWL._AC_SL1000_.jpg",
                    "desc": "High-concentration EPA/DHA (650 mg Omega-3 per soft-gel); IFOS 5-star certified; triglyceride (TG) form for superior absorption. Ideal for cardiovascular health, anti-inflammatory needs, or anyone seeking a highly purified fish oil.",
                    "page_description": "**About this item**\n- WHY OMEGA-3s – EPA & DHA support heart, brain, eye and immune health, and help maintain a healthy mood.\n- DOCTOR-RECOMMENDED dose meets American Heart Association guidelines for cardiovascular support.\n- BETTER ABSORPTION & TASTE – Triglyceride form with pleasant lemon flavor and zero fishy burps.\n- PURITY GUARANTEED – Wild-caught fish, non-GMO, gluten- & dairy-free with no artificial additives."
                },
                {
                    "id": "fish_02",
                    "title": "WHC UnoCardio 1000 ",
                    "product_url": "https://www.amazon.com/stores/page/29B9D3D0-5A5E-4EEA-A0A2-D812CA2F8559/?_encoding=UTF8&store_ref=SB_A076637421Z7I7ERZ0TXQ-A03352931L0DK4Z7CLDKO&pd_rd_plhdr=t&aaxitk=49fae88956cfec31cfd29cac8b8abde1&hsa_cr_id=0&lp_asins=B00QFTGSK6%2CB01MQJZI9D%2CB07NLCBPGN&lp_query=WHC%20UnoCardio%201000&lp_slot=desktop-hsa-3psl&ref_=sbx_be_s_3psl_mbd_mb0_logo&pd_rd_w=kHhnR&content-id=amzn1.sym.5594c86b-e694-4e3e-9301-a074f0faf98a%3Aamzn1.sym.5594c86b-e694-4e3e-9301-a074f0faf98a&pf_rd_p=5594c86b-e694-4e3e-9301-a074f0faf98a&pf_rd_r=J95ESAZ01FFJGKDH15S5&pd_rd_wg=udhtB&pd_rd_r=1ca75ded-9d8a-4db4-9e02-4051fdc574f2",
                    "site": "www.whc.clinic",
                    "image_url": "https://m.media-amazon.com/images/I/71htaA+bT9L._AC_SL1500_.jpg",
                    "desc": "Ranked No. 1 globally by IFOS; Contains 1,000 mg Omega-3 (EPA + DHA) per soft-gel; enriched with vitamin D3; individually blister-packed to prevent oxidation. Ideal for middle-aged and older adults who demand top purity and a premium formulation.",
                    "page_description": "**About this item**\n- 1 180 mg total Omega-3 (EPA 665 mg / DHA 445 mg) per soft-gel for heart, brain and vision.\n- Provides 1 000 IU vitamin D3 to support bones, muscles and immunity.\n- r-Triglyceride form for superior absorption; lactose- & gluten-free, burp-free orange flavor.\n- Ultra-pure, Friend-of-the-Sea-certified fish oil in beef-gelatin-free blister packs."
                },
                {
                    "id": "fish_03",
                    "title": "Now Foods Ultra Omega-3",
                    "product_url": "https://www.amazon.com/NOW-Supplements-Molecularly-Distilled-Softgels/dp/B0BGQR8KSG/ref=sr_1_1?crid=1WK5FQS4N6VT9&dib=eyJ2IjoiMSJ9.sczFj7G5tzaluW3utIDJFvN3vRVXIKN8OW6iAI1rL8RiGXrbNcV75KmT0QHEw_-mrjN9Y2Z_QXZcyi9A3KwDB5TpToVICSiFPa7RnnItgqpDWW7DzU2ECbX73MLiBO0nOBcQe4If9EV_QeFtgmERZF360mEcTJ3ZfaxrOKNzI8A.dUyPZz9HZwZJIqkDLMtL5snAfj0y8Ayu3PNq8Ugt-WU&dib_tag=se&keywords=Now%2BFoods%2BUltra%2BOmega-3&qid=1747669011&sprefix=now%2Bfoods%2Bultra%2Bomega-3%2Caps%2C677&sr=8-1&th=1",
                    "site": "www.iherb.com",
                    "image_url": "https://m.media-amazon.com/images/I/51xrY5WFFIL._AC_.jpg",
                    "desc": "Great value (EPA 500 mg + DHA 250 mg per soft-gel); IFOS certified; suitable for long-term, everyday supplementation. This is ideal for general health maintenance, budget-conscious consumers, and daily nutritional support.",
                    "page_description": "**About this item**\n- CARDIOVASCULAR SUPPORT – 600 mg EPA & 300 mg DHA per enteric-coated soft-gel.\n- MOLECULARLY DISTILLED for purity; tested free of PCBs, dioxins & heavy metals.\n- ENTERIC COATING reduces nausea and fishy aftertaste.\n- NON-GMO, Kosher and GMP-quality assured by the family-owned NOW® brand since 1968."
                },
                {
                    "id": "fish_04",
                    "title": "Blackmores Triple-Strength Fish Oil",
                    "product_url": "https://www.amazon.com.au/Blackmores-Omega-Triple-Concentrated-Capsules/dp/B0773JF7JX?th=1",
                    "site": "vivanaturals.com",
                    "image_url": "https://m.media-amazon.com/images/I/71UhUKoWbnL._AC_SL1500_.jpg",
                    "desc": "Best-selling Australian pharmacy product; 900 mg Omega-3 per soft-gel; supports cardiovascular health. This is ideal for intensive cardiovascular support, joint health, and individuals seeking a high-dose omega-3 supplement.",
                    "page_description": "**About this item**\n- One-a-day capsule delivers 500 mg DHA to maintain brain health and mental performance.\n- Provides four-times more DHA than standard fish oil—ideal if you eat little fish.\n- 100 % wild-caught small-fish oil rigorously tested for mercury, dioxins & PCBs.\n- Supports healthy growth in children and overall wellbeing for all ages."
                },
                {
                    "id": "fish_05",
                    "title": "Möller’s Norwegian Cod-Liver Oil",
                    "product_url": "https://www.amazon.com.be/-/en/Mollers-Omega-Norwegian-Cod-Liver-Pruners/dp/B074XB9RNH?language=en_GB",
                    "site": "www.mollers.no",
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
            show_product_item(item, link_type="organic")

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
    # 1) Start logging with streamlit_analytics2
    #    Here we use default settings, so logs go in `./streamlit_analytics/`
    with streamlit_analytics.track():
        # 0️⃣  If the user is looking at an item page, short‑circuit the normal flow.
        if st.session_state.page == "product" and st.session_state.current_product:
            render_product_page()  # <-- new helper (see §4)
            return

        # (A) If we have a pending link from a previous run, open it now
        open_pending_link()

        # (B) Ask for Prolific ID if not set
        if "prolific_id" not in st.session_state:
            st.session_state.prolific_id = None

        if st.session_state.prolific_id is None:
            st.title("Welcome!")
            pid = st.text_input("Please enter your Prolific ID:")
            if pid:
                st.session_state.prolific_id = pid
                st.rerun()
            st.stop()

        # (C) Initialize click_history if not present
        if "click_history" not in st.session_state:
            st.session_state.click_history = []

        # (D) Provide an "End Session" button in the sidebar
        # st.sidebar.title("Menu")
        # record_link_click_and_open(label='end', url=' ', link_type='end')
        with st.sidebar.expander("★ My favourites", expanded=False):
            favs = st.session_state.favorites
            if favs:
                for link, title in favs.items():
                    st.markdown(f"- [{title}]")
            else:
                st.write("Nothing yet – click ☆ to add.")

        # (E) Show whichever scenario is chosen
        if variant == 1:
            show_deepseek_recommendation(with_ads=False)
        elif variant == 2:
            show_deepseek_recommendation(with_ads=True)
        elif variant == 3:
            show_google_search(with_ads=False)
        elif variant == 4:
            show_google_search(with_ads=True)

        # (F) Debug click history
        # st.write("Debug Click History:", st.session_state.click_history)


if __name__ == "__main__":
    main()
