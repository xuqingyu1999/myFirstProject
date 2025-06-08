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
import json

# 1) Must be your first Streamlit call
st.set_page_config(
    page_title="My App",
    layout="wide",
    # you can also prune the hamburger menu this way
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": None
    }
)

# hide header, footer, main menu, share/more, and “Manage app” button
st.markdown(
    """
    <style>
      header {visibility: hidden;}
      #MainMenu {visibility: hidden;}
      footer {visibility: hidden;}
      /* hide the “Share” and “More” icons (if still present) */
      [data-testid="share-button"], [data-testid="more-actions-button"] {
        visibility: hidden;
      }
      /* hide the “Manage app” button in the bottom-right */
      button[title="Manage app"] {
        display: none !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

def get_credentials_from_secrets():
    # 还原成 dict
    creds_dict = {key: value for key, value in st.secrets["GOOGLE_CREDENTIALS"].items()}
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    return creds_dict

def save_to_gsheet(data):
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        get_credentials_from_secrets(),
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
    )
    client = gspread.authorize(creds)
    sheet = client.open("QRec").sheet1
    sheet.append_row([data[k] for k in ["id", "start", "timestamp", "type", "title", "url"]])


############################################
# Step 0: Page config & DeepSeek client
############################################
# st.set_page_config(page_title="🛒 DeepSeek 实验", layout="wide")

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


############################################
# 2) Regex-based parser for [Title](URL) links in LLM text
############################################
def parse_markdown_links(text: str):
    """
    Finds all [Label](URL) patterns in 'text'.
    Returns a list of segments, e.g.:
      [{"type": "text", "content": "some text"},
       {"type": "link", "label": "Nordic Naturals", "url": "..."},
       ...]
    """
    pattern = r'\[([^\]]+)\]\(([^)]+)\)'
    segments = []
    last_end = 0

    for match in re.finditer(pattern, text):
        start, end = match.span()
        if start > last_end:
            # text before this link
            segments.append({
                "type": "text",
                "content": text[last_end:start]
            })
        link_label = match.group(1)
        link_url = match.group(2)
        segments.append({
            "type": "link",
            "label": link_label,
            "url": link_url
        })
        last_end = end

    if last_end < len(text):
        # leftover text after last link
        segments.append({
            "type": "text",
            "content": text[last_end:]
        })

    return segments


def display_parsed_markdown(text: str, link_type="deepseek"):
    """
    Splits 'text' into normal text vs. [Title](URL) links,
    then displays them with st.markdown for text,
    and record_link_click_and_open for links.
    """
    segments = parse_markdown_links(text)
    for seg in segments:
        if seg["type"] == "text":
            st.markdown(seg["content"])
        elif seg["type"] == "link":
            record_link_click_and_open(seg["label"], seg["url"], link_type)


############################################
# 3) Predefined replies
############################################
KEYWORD_RESPONSES = {
    # 键写关键词，值写你想直接返回的内容
    # 命中逻辑 = “用户输入里包含该关键词（不区分大小写）”
    "fish oil": """
### **I. Recommended High-Reputation Fish-Oil Brands**
1. [**Nordic Naturals Ultimate Omega**](https://www.amazon.com/Nordic-Naturals-Ultimate-Support-Healthy/dp/B002CQU564/ref=sr_1_1?content-id=amzn1.sym.c9738cef-0b5a-4096-ab1b-6af7c45832cd%3Aamzn1.sym.c9738cef-0b5a-4096-ab1b-6af7c45832cd&dib=eyJ2IjoiMSJ9.EmMg0Sjrk3Up1-B8Uq6XmXPfqBR6LsN4xh_xk9FkohcxjUGjjtl8VDmFPAv02s7DdvP4IMVJlYCiu4xLS3tkFzqAjY8zzLpTcrQiGDBHfSlCICd1rxDQrjuX09VNQDqQLzn3cHDWmdL3cWFyPa6GoFGZn3Y4_gA0M70XM89DcYOwpBeQlrC5yad9lab17AwZgciNRLxb8byU-LfuW17zz3q-IozuDG-egQAIeXgugVoJ8WRIvJz3NkILl22JMYtajLueBHt6DzsSWXw0pyyU1wzGr_pw1-I-LzakONQMKjk.5XQSZpgWB9fgxSBUCDKvd3csceCcXwJ8hgXGTLOIUrg&dib_tag=se&keywords=Nordic%2BNaturals%2BUltimate%2BOmega%2BCognition&pd_rd_r=dbeef994-8b31-4a6a-965d-1774b9bbb5c4&pd_rd_w=oTInk&pd_rd_wg=3hsHS&qid=1747570281&sr=8-1&th=1) 
   - Features: High-concentration EPA/DHA (650 mg Omega-3 per soft-gel); IFOS 5-star certified; triglyceride (TG) form for superior absorption.
   - Ideal for: Cardiovascular health, anti-inflammatory needs, or anyone seeking a highly purified fish oil. 
   - Where to buy: iHerb, Amazon Global.

2. [**WHC UnoCardio 1000** ](https://www.amazon.com/stores/page/29B9D3D0-5A5E-4EEA-A0A2-D812CA2F8559/?_encoding=UTF8&store_ref=SB_A076637421Z7I7ERZ0TXQ-A03352931L0DK4Z7CLDKO&pd_rd_plhdr=t&aaxitk=49fae88956cfec31cfd29cac8b8abde1&hsa_cr_id=0&lp_asins=B00QFTGSK6%2CB01MQJZI9D%2CB07NLCBPGN&lp_query=WHC%20UnoCardio%201000&lp_slot=desktop-hsa-3psl&ref_=sbx_be_s_3psl_mbd_mb0_logo&pd_rd_w=kHhnR&content-id=amzn1.sym.5594c86b-e694-4e3e-9301-a074f0faf98a%3Aamzn1.sym.5594c86b-e694-4e3e-9301-a074f0faf98a&pf_rd_p=5594c86b-e694-4e3e-9301-a074f0faf98a&pf_rd_r=J95ESAZ01FFJGKDH15S5&pd_rd_wg=udhtB&pd_rd_r=1ca75ded-9d8a-4db4-9e02-4051fdc574f2) 
   - Features: Ranked No. 1 globally by IFOS; 1,000 mg Omega-3 (EPA + DHA) per soft-gel; enriched with vitamin D3; individually blister-packed to prevent oxidation.  
   - Ideal for: Middle-aged and older adults who demand top purity and a premium formulation.
   - Price: Relatively high, but excellent value for money.  

3. [**Now Foods Ultra Omega-3** ](https://www.amazon.com/NOW-Supplements-Molecularly-Distilled-Softgels/dp/B0BGQR8KSG/ref=sr_1_1?crid=1WK5FQS4N6VT9&dib=eyJ2IjoiMSJ9.sczFj7G5tzaluW3utIDJFvN3vRVXIKN8OW6iAI1rL8RiGXrbNcV75KmT0QHEw_-mrjN9Y2Z_QXZcyi9A3KwDB5TpToVICSiFPa7RnnItgqpDWW7DzU2ECbX73MLiBO0nOBcQe4If9EV_QeFtgmERZF360mEcTJ3ZfaxrOKNzI8A.dUyPZz9HZwZJIqkDLMtL5snAfj0y8Ayu3PNq8Ugt-WU&dib_tag=se&keywords=Now%2BFoods%2BUltra%2BOmega-3&qid=1747669011&sprefix=now%2Bfoods%2Bultra%2Bomega-3%2Caps%2C677&sr=8-1&th=1)
   - Features: Great value (EPA 500 mg + DHA 250 mg per soft-gel); IFOS certified; suitable for long-term, everyday supplementation. 
   - Where to buy: iHerb, Tmall Global.

4. [**Blackmores Triple-Strength Fish Oil** ](https://www.amazon.com.au/Blackmores-Omega-Triple-Concentrated-Capsules/dp/B0773JF7JX?th=1)
   - Features: Best-selling Australian pharmacy product; 900 mg Omega-3 per soft-gel; supports cardiovascular health.  
   - Note: Check the IFOS certification status for each production batch.

5. [**Möller’s Norwegian Cod-Liver Oil**](https://www.amazon.com.be/-/en/Mollers-Omega-Norwegian-Cod-Liver-Pruners/dp/B074XB9RNH?language=en_GB)
   - Features: Liquid fish oil enriched with natural vitamins A and D; trusted Nordic brand with over 100 years of history; suitable for children and pregnant women.
   - How to take: Consume directly or mix with food.

"""
    ,
    "liver":
        """
        ### **I. Recommended High-Quality Liver-Support Brands**
        1. [**Thorne Liver Cleanse**](https://www.amazon.com/Thorne-Research-Cleanse-Detoxification-Capsules/dp/B07978NYC5) 
           - Features: Professional-grade formula that combines milk thistle (125 mg silymarin), burdock, chicory, berberine, and other botanicals; NSF-Certified for Sport®; produced in a GMP-compliant U.S. facility. 
           - Ideal for: Individuals looking for a broad-spectrum botanical detox blend—especially those who value third-party testing and athlete-friendly certifications.
           - Where to buy: Thorne.com, iHerb, Amazon Global.

        2. [**Himalaya LiverCare (Liv 52 DS)**](https://www.amazon.com.be/-/en/Himalaya-Liv-52-DS-3-Pack/dp/B09MF88N71) 
           - Features: Clinically studied Ayurvedic blend (capers, chicory, black nightshade, arjuna, yarrow, etc.) shown to improve Child-Pugh scores and reduce ALT/AST in liver-compromised patients. 
           - Ideal for: Those seeking a time-tested herbal formula with human-trial evidence, including individuals with mild enzyme elevations or high environmental/toxic exposure.
           - Where to buy: Himalaya-USA site, Amazon, local natural-health stores.

        3. [**Jarrow Formulas Milk Thistle (150 mg)**](https://www.amazon.com/Jarrow-Formulas-Silymarin-Marianum-Promotes/dp/B0013OULVA?th=1) 
           - Features: 30:1 standardized silymarin phytosome bonded to phosphatidylcholine for up-to-30× higher bioavailability than conventional milk thistle; vegetarian capsules; gluten-, soy-, and dairy-free. 
           - Ideal for: People who need a concentrated, highly absorbable milk-thistle extract—e.g., those on multiple medications or with occasional alcohol use.
           - Where to buy: iHerb, Amazon, VitaCost, brick-and-mortar vitamin shops.

        4. [**NOW Foods Liver Refresh™**](https://www.amazon.com/Liver-Refresh-Capsules-NOW-Foods/dp/B001EQ92VW?th=1) 
           - Features: Synergistic blend of milk thistle, N-acetyl cysteine (NAC), methionine, and herbal antioxidants; non-GMO Project Verified and GMP-qualified. 
           - Ideal for: Individuals wanting comprehensive antioxidant support—such as frequent travelers, people with high oxidative stress, or those following high-protein diets.
           - Where to buy: NOWFoods.com, Amazon, iHerb, Whole Foods Market.

        5. [**Nutricost TUDCA 250 mg**](https://www.amazon.com/Nutricost-Tudca-250mg-Capsules-Tauroursodeoxycholic/dp/B01A68H2BA?th=1) 
           - Features: Pure tauroursodeoxycholic acid (TUDCA) at 250 mg per veggie capsule; non-GMO, soy- and gluten-free; 3rd-party ISO-accredited lab tested; made in an FDA-registered, GMP facility. 
           - Ideal for: Advanced users seeking bile-acid–based cellular protection—popular among those with cholestatic or high-fat-diet concerns.
           - Where to buy: Amazon, Nutricost.com, Walmart.com.
        """,
    "优惠码": "🎁 **本月通用优惠码：DS-MAY25**\n下单立减 25 元（限时 5 月 31 日前，秒杀品除外）。",
    # 继续添加更多：
    # "shipping": "标准配送 48 h 内发货，全国包邮。",
}


def get_predefined_response(user_text: str):
    lower = user_text.lower()
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
            "title": "Gaia Herbs Liver Cleanse",
            "price": "¥215",
            "image_url": "https://m.media-amazon.com/images/I/710RG7jzTqL._AC_SL1500_.jpg",
            "product_url": "https://www.amazon.com/dp/B00BSU2HFW",
            "sponsored": True
        },
        {
            "title": "Pure Encapsulations Liver-GI Detox",
            "price": "¥430",
            "image_url": "https://m.media-amazon.com/images/I/71KCict6JDL.__AC_SX300_SY300_QL70_ML2_.jpg",
            "product_url": "https://www.amazon.com/dp/B0016L2XT8",
            "sponsored": True
        },
        {
            "title": "Life Extension NAC 600 mg",
            "price": "¥110",
            "image_url": "https://m.media-amazon.com/images/I/61yHnalNZSL.__AC_SX300_SY300_QL70_ML2_.jpg",
            "product_url": "https://www.amazon.com/dp/B07KR3LZNJ",
            "sponsored": True
        },
        {
            "title": "Swisse Ultiboost Liver Detox",
            "price": "¥150",
            "image_url": "https://m.media-amazon.com/images/I/61irB7SYZJL._AC_SL1500_.jpg",
            "product_url": "https://www.amazon.com/Swisse-Ultiboost-Traditional-Supplement-Supports/dp/B06Y59V34H",
            "sponsored": True
        },
        {
            "title": "Solaray Liver Blend SP-13",
            "price": "¥200",
            "image_url": "https://m.media-amazon.com/images/I/619Fhmmu5bL.__AC_SX300_SY300_QL70_FMwebp_.jpg",
            "product_url": "https://www.amazon.com/Solaray-Healthy-Dandelion-Artichoke-Peppermint/dp/B00014D9VC",
            "sponsored": True
        }
    ]
    ,
    "fish oil": [
        {
            "title": "omega3 Fish Oil",
            "price": "¥280",
            "image_url": "https://m.media-amazon.com/images/I/81yjLlHfB3L._AC_SX679_.jpg",
            "product_url": "https://www.amazon.com/fish-oil-omega-3-supplements/dp/B014LDT0ZM/ref=zg_bs_g_10728601_d_sccl_7/145-4892816-1278847?th=1",
            "sponsored": True
        },
        {
            "title": "Swisse Fish Oil Soft Capsules",
            "price": "¥148",
            "image_url": "https://m.media-amazon.com/images/I/61AF1Mw+RkL._AC_SL1500_.jpg",
            "product_url": "https://www.amazon.com/Swisse-Supplement-Sustainably-Essential-Promotes/dp/B0D45ZYSWZ?th=1",
            "sponsored": True
        },
        {
            "title": "GNC Fish Oil",
            "price": "¥80",
            "image_url": "https://m.media-amazon.com/images/I/61gW5yxTCgL._AC_SX679_.jpg",
            "product_url": "https://www.amazon.com/GNC-Strength-Potency-Quality-Supplement/dp/B01NCSCP1Y",
            "sponsored": True
        },
        {
            "title": "Viva Naturals Fish Oil",
            "price": "¥148",
            "image_url": "https://m.media-amazon.com/images/I/61C6MAD6f1L._AC_SL1000_.jpg",
            "product_url": "https://www.amazon.com/Viva-Naturals-Triple-Strength-Supplement/dp/B0CB4QHF3N",
            "sponsored": True
        },
        {
            "title": "Nature's Bounty Fish Oil",
            "price": "¥148",
            "image_url": "https://m.media-amazon.com/images/I/61DfA7Q2L1L.__AC_SX300_SY300_QL70_FMwebp_.jpg",
            "product_url": "https://www.amazon.com/Natures-Bounty-Fish-1200mg-Softgels/dp/B0061GLLZU/ref=sr_1_13?crid=2LKKOIQSFYS6S&dib=eyJ2IjoiMSJ9.8YqelzrxWTEtpFDV7_gTMiPQAt5OIYhBGkWbpttvAWpIvlJRJOUoxxp7IMXmJlY57c9lfT_luHCybc1LKbEJMTwwhcDZDUoeVgwcNLO5l_dwXu5c-1Ez7i5UfKmzH4EOJv2zV8VSBDMBJXCFdD_rjvwshCy5ME-g2v0Xbs4ZGD3I-i_M4tw0c0gNrYF-xwkBeyrduPmxrdQEkbIzftr_TGCq2DjeL1ufFCEdm_6mHMzPamqBh5oSS9JGcii9g_-GfO5TfsR69plRTAIe4cpr7iDgjqQdytvYbw8oupa53Cw.WR8rDyjDlym7-4N1ufSr7JPlqdZ2D2g32m2iEm64hlk&dib_tag=se&keywords=fish+oil&qid=1747492409&sprefix=fish+oi%2Caps%2C620&sr=8-13",
            "sponsored": True
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


def open_button_link(link):
    js_code = f"""
            <script>
                window.open("{link}", "_blank");
            </script>
            """
    st.markdown(js_code, unsafe_allow_html=True)


def record_link_click_and_open(label, url, link_type):
    click_log_file = "click_history.csv"
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
        if st.button(label, key=label):
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

            # 打开链接
            components.html(f"""
            <script>
            window.open("{url}", "_blank");
            </script>
            """, height=0)


############################################
# 6) Ads in a 5-column grid
############################################
def show_advertisements(relevant_products):
    with st.container(border=True):
        st.markdown("<div style='text-align: center;'></div>", unsafe_allow_html=True)

        st.markdown(
            """
              <div style="position:absolute; top:-14px; left:-14px; background-color:#e53935; color:white; font-size:14px; padding:6px 12px; border-radius:4px;">
                sponsored
              </div>
            """,
            unsafe_allow_html=True
        )
        st.markdown("<div style='text-align: center;'></div>", unsafe_allow_html=True)
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

                    st.markdown(f"""
                    <div style="flex-shrink:0; margin-right:8px;">
                      <img src="{product['image_url']}" 
                           style="width:80px; height:80px; object-fit:contain;" />
                    </div>
                    <div style="display:flex; flex-direction:column; justify-content:center;">
                    """, unsafe_allow_html=True)

                    record_link_click_and_open(
                        label=product["title"],
                        url=product["product_url"],
                        link_type="ad"
                    )
                    st.markdown("</div></div>", unsafe_allow_html=True)

        # st.markdown("</div>", unsafe_allow_html=True)


############################################
# 7) Query -> relevant products
############################################
def get_products_by_query(query: str):
    lower_q = query.lower()
    if ("肝" in lower_q) or ("护肝" in lower_q) or ("liver" in lower_q):
        return PRODUCTS_DATA["liver"]
    elif ("鱼油" in lower_q) or ("fish oil" in lower_q):
        return PRODUCTS_DATA["fish oil"]
    else:
        return []


############################################
# Step 2: random "variant"
############################################
if "variant" not in st.session_state:
    st.session_state.variant = random.randint(1, 4)
variant = 1  # st.session_state.variant


############################################
# 8) DeepSeek Recommendation Flow
############################################
def show_deepseek_recommendation(with_ads: bool):
    st.title("Querya Rec")
    # st.write(f"Current version: {'with ads' if with_ads else 'without ads'}")

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
        else:
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": r, "content": c} for r, c in st.session_state.history],
                temperature=1,
                stream=False,
            )
            assistant_text = resp.choices[0].message.content

        st.session_state.history.append(("assistant", assistant_text))

        with st.chat_message("assistant"):
            display_parsed_markdown(assistant_text, link_type="deepseek")

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
            user_first_input = st.text_input("**Ask anything:**")

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
    else:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": r, "content": c} for r, c in st.session_state.history],
            temperature=1,
            stream=False,
        )
        assistant_text = resp.choices[0].message.content

    st.session_state.history.append(("assistant", assistant_text))

    with st.chat_message("assistant"):
        display_parsed_markdown(assistant_text, link_type="deepseek")

    if with_ads:
        prods = get_products_by_query(user_input)
        st.session_state.current_ads = prods
        if prods:
            show_advertisements(prods)


############################################
# 9) Google-like Search Flow
############################################
def show_google_search(with_ads: bool):
    st.title("Querya search")

    if "search_results" not in st.session_state:
        st.session_state.search_results = []

    def do_fake_google_search(query):
        lower_q = query.lower()

        # 这里仅做示例返回几条伪搜索结果，可根据关键词控制输出

        if ("鱼油" in lower_q) or ("fish oil" in lower_q):
            return [
                {
                    "title": "Nordic Naturals Ultimate Omega  ",
                    "url": "https://www.amazon.com/Nordic-Naturals-Ultimate-Support-Healthy/dp/B002CQU564/ref=sr_1_1?content-id=amzn1.sym.c9738cef-0b5a-4096-ab1b-6af7c45832cd%3Aamzn1.sym.c9738cef-0b5a-4096-ab1b-6af7c45832cd&dib=eyJ2IjoiMSJ9.EmMg0Sjrk3Up1-B8Uq6XmXPfqBR6LsN4xh_xk9FkohcxjUGjjtl8VDmFPAv02s7DdvP4IMVJlYCiu4xLS3tkFzqAjY8zzLpTcrQiGDBHfSlCICd1rxDQrjuX09VNQDqQLzn3cHDWmdL3cWFyPa6GoFGZn3Y4_gA0M70XM89DcYOwpBeQlrC5yad9lab17AwZgciNRLxb8byU-LfuW17zz3q-IozuDG-egQAIeXgugVoJ8WRIvJz3NkILl22JMYtajLueBHt6DzsSWXw0pyyU1wzGr_pw1-I-LzakONQMKjk.5XQSZpgWB9fgxSBUCDKvd3csceCcXwJ8hgXGTLOIUrg&dib_tag=se&keywords=Nordic%2BNaturals%2BUltimate%2BOmega%2BCognition&pd_rd_r=dbeef994-8b31-4a6a-965d-1774b9bbb5c4&pd_rd_w=oTInk&pd_rd_wg=3hsHS&qid=1747570281&sr=8-1&th=1",
                    "site": "www.iherb.com",
                    "desc": "High-concentration EPA/DHA in triglyceride form; 650 mg Omega-3 per soft-gel; IFOS 5-star certified—ideal for cardiovascular support and anti-inflammatory needs."
                },
                {
                    "title": "WHC UnoCardio 1000 ",
                    "url": "https://www.amazon.com/stores/page/29B9D3D0-5A5E-4EEA-A0A2-D812CA2F8559/?_encoding=UTF8&store_ref=SB_A076637421Z7I7ERZ0TXQ-A03352931L0DK4Z7CLDKO&pd_rd_plhdr=t&aaxitk=49fae88956cfec31cfd29cac8b8abde1&hsa_cr_id=0&lp_asins=B00QFTGSK6%2CB01MQJZI9D%2CB07NLCBPGN&lp_query=WHC%20UnoCardio%201000&lp_slot=desktop-hsa-3psl&ref_=sbx_be_s_3psl_mbd_mb0_logo&pd_rd_w=kHhnR&content-id=amzn1.sym.5594c86b-e694-4e3e-9301-a074f0faf98a%3Aamzn1.sym.5594c86b-e694-4e3e-9301-a074f0faf98a&pf_rd_p=5594c86b-e694-4e3e-9301-a074f0faf98a&pf_rd_r=J95ESAZ01FFJGKDH15S5&pd_rd_wg=udhtB&pd_rd_r=1ca75ded-9d8a-4db4-9e02-4051fdc574f2",
                    "site": "www.whc.clinic",
                    "desc": "IFOS global No. 1 rating; 1,000 mg Omega-3 plus vitamin D3 per capsule; aluminum-blister packaging to prevent oxidation—well suited to middle-aged and older adults."
                },
                {
                    "title": "Now Foods Ultra Omega-3",
                    "url": "https://www.amazon.com/NOW-Supplements-Molecularly-Distilled-Softgels/dp/B0BGQR8KSG/ref=sr_1_1?crid=1WK5FQS4N6VT9&dib=eyJ2IjoiMSJ9.sczFj7G5tzaluW3utIDJFvN3vRVXIKN8OW6iAI1rL8RiGXrbNcV75KmT0QHEw_-mrjN9Y2Z_QXZcyi9A3KwDB5TpToVICSiFPa7RnnItgqpDWW7DzU2ECbX73MLiBO0nOBcQe4If9EV_QeFtgmERZF360mEcTJ3ZfaxrOKNzI8A.dUyPZz9HZwZJIqkDLMtL5snAfj0y8Ayu3PNq8Ugt-WU&dib_tag=se&keywords=Now%2BFoods%2BUltra%2BOmega-3&qid=1747669011&sprefix=now%2Bfoods%2Bultra%2Bomega-3%2Caps%2C677&sr=8-1&th=1",
                    "site": "www.iherb.com",
                    "desc": "Cost-effective daily formula with 500 mg EPA + 250 mg DHA; IFOS certified—designed for long-term, everyday supplementation."
                },
                {
                    "title": "Blackmores Triple-Strength Fish Oil",
                    "url": "https://www.amazon.com.au/Blackmores-Omega-Triple-Concentrated-Capsules/dp/B0773JF7JX?th=1",
                    "site": "vivanaturals.com",
                    "desc": "Premium concentrated rTG version delivering 700 mg EPA and 240 mg DHA—ideal for people focused on cardiovascular management."
                },
                {
                    "title": "Möller’s Norwegian Cod-Liver Oil",
                    "url": "https://www.amazon.com.be/-/en/Mollers-Omega-Norwegian-Cod-Liver-Pruners/dp/B074XB9RNH?language=en_GB",
                    "site": "www.mollers.no",
                    "desc": "Century-old Nordic brand containing natural vitamins A and D; gentle liquid format suitable for children and pregnant women."
                },
            ]
        # 如果搜索里包含'liver'
        elif ("liver" in lower_q):
            return [
                {
                    "title": "Thorne Liver Cleanse",
                    "url": "https://www.amazon.com/Thorne-Research-Cleanse-Detoxification-Capsules/dp/B07978NYC5",
                    "site": "https://www.amazon.com/Thorne-Research-Cleanse-Detoxification-Capsules/dp/B07978NYC5",
                    "desc": "Professional-grade formula that combines milk thistle (125 mg silymarin), burdock, chicory, berberine, and other botanicals; NSF-Certified for Sport®; produced in a GMP-compliant U.S. facility. This is ideal for ndividuals looking for a broad-spectrum botanical detox blend—especially those who value third-party testing and athlete-friendly certifications."
                },
                {
                    "title": "Himalaya LiverCare (Liv 52 DS)",
                    "url": "https://www.amazon.com.be/-/en/Himalaya-Liv-52-DS-3-Pack/dp/B09MF88N71",
                    "site": "www.whc.clinic",
                    "desc": "- Features: Clinically studied Ayurvedic blend (capers, chicory, black nightshade, arjuna, yarrow, etc.) shown to improve Child-Pugh scores and reduce ALT/AST in liver-compromised patients. This is ideal for those seeking a time-tested herbal formula with human-trial evidence, including individuals with mild enzyme elevations or high environmental/toxic exposure."
                },
                {
                    "title": "Jarrow Formulas Milk Thistle (150 mg)",
                    "url": "https://www.amazon.com/Jarrow-Formulas-Silymarin-Marianum-Promotes/dp/B0013OULVA?th=1",
                    "site": "https://www.amazon.com/Jarrow-Formulas-Silymarin-Marianum-Promotes/dp/B0013OULVA?th=1",
                    "desc": "It contains 30:1 standardized silymarin phytosome bonded to phosphatidylcholine for up-to-30× higher bioavailability than conventional milk thistle; vegetarian capsules; gluten-, soy-, and dairy-free. This is ideal for people who need a concentrated, highly absorbable milk-thistle extract—e.g., those on multiple medications or with occasional alcohol use."
                },
                {
                    "title": "NOW Foods Liver Refresh™",
                    "url": "https://www.amazon.com/Liver-Refresh-Capsules-NOW-Foods/dp/B001EQ92VW?th=1",
                    "site": "vivanaturals.com",
                    "desc": "Synergistic blend of milk thistle, N-acetyl cysteine (NAC), methionine, and herbal antioxidants; non-GMO Project Verified and GMP-qualified. This is ideal for individuals wanting comprehensive antioxidant support—such as frequent travelers, people with high oxidative stress, or those following high-protein diets."
                },
                {
                    "title": "Nutricost TUDCA 250 mg",
                    "url": "https://www.amazon.com/Nutricost-Tudca-250mg-Capsules-Tauroursodeoxycholic/dp/B01A68H2BA?th=1",
                    "site": "www.mollers.no",
                    "desc": "- Features: Pure tauroursodeoxycholic acid (TUDCA) at 250 mg per veggie capsule; non-GMO, soy- and gluten-free; 3rd-party ISO-accredited lab tested; made in an FDA-registered, GMP facility. This is ideal for advanced users seeking bile-acid–based cellular protection—popular among those with cholestatic or high-fat-diet concerns."
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
            record_link_click_and_open(item["title"], item["url"], link_type="organic")
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
        # (A) If we have a pending link from a previous run, open it now
        # open_pending_link()

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
        st.sidebar.title("Menu")
        record_link_click_and_open(label='end', url=' ', link_type='end')
        # if st.sidebar.button("Finish / End Session"):
        #     # Gather data
        #     data_to_save = {
        #         "prolific_id": st.session_state.prolific_id,
        #         "variant": variant,
        #         "start_time": st.session_state.start_time,
        #         "ended_at": datetime.now().isoformat(),
        #         "conversation_history": st.session_state.get("history", []),
        #         "click_history": st.session_state.click_history,
        #     }
        #     with open("session_data.json", "w", encoding="utf-8") as f:
        #         json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        #
        #     st.success("Session data saved to session_data.json. Thank you!")
        #     st.stop()

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
