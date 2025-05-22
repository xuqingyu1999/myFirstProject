#!/usr/bin/env python
# coding: utf-8

# In[ ]:


# app.py
import os
import json
import random
import streamlit as st
from openai import OpenAI
import base64
from pathlib import Path

############################################
# step 0: 页面 & DeepSeek 客户端初始化
############################################
st.set_page_config(page_title="🛒 DeepSeek 实验", layout="wide")

API_KEY = os.getenv("DEEPSEEK_API_KEY") or "sk-ce6eb3e9045c4110862945af28f4794e"
client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com/v1")

############################################
# 新增：关键词触发的「预设答复」字典，
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
    """命中关键词就返回预设答复，否则返回 None"""
    lower = user_text.lower()
    for kw, reply in KEYWORD_RESPONSES.items():
        if kw.lower() in lower:
            return reply
    return None

############################################
# 商品/广告数据
############################################
# 这里可以继续添加更多商品类型
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

def show_advertisements(relevant_products):
    # 构建广告 HTML（每行最多5列，图片居中，去掉价格）
    ad_html = """
<div style="padding:16px; border:2px solid #ddd; border-radius:10px; background:#f9f9f9; margin-top:24px;">
  <div style="position:relative; margin-bottom:12px;">
    <div style="position:absolute; top:-10px; left:-10px; background-color:#e53935; color:white; font-size:14px; padding:6px 12px; border-radius:4px;">sponsored</div>
  </div>
  <div style="display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px;">
"""

    for product in relevant_products:
        ad_html += f"""
   <div style="flex: 1 1 calc(20% - 12px); max-width: calc(20% - 12px); border: 1px solid #ccc; border-radius: 8px; padding: 10px; box-sizing: border-box; text-align: center; background: white;">
       <img src="{product['image_url']}" alt="{product['title']}" style="width:100%; max-height:120px; object-fit: contain; margin-bottom: 8px;" />
       <a href="{product['product_url']}" target="_blank" style="font-weight:600; text-decoration:none; color:#0366d6; font-size:14px; display:block;">{product['title']}</a>
    </div>
"""

    ad_html += """
  </div>
</div>
"""

    # 正确渲染广告区域
    st.markdown(ad_html, unsafe_allow_html=True)


def get_products_by_query(query: str):
    """
    根据用户输入的query，判断关键词并返回对应的商品列表。
    例如包含'花'/'鲜花'就返回flowers，包含'鱼油'返回fishoil，否则返回空或默认。
    """
    lower_q = query.lower()  # 转小写，方便关键词匹配

    # 判断逻辑可根据需求自由扩展
    if ("肝" in lower_q) or ("护肝" in lower_q) or ("liver" in lower_q):
        return PRODUCTS_DATA["liver"]
    elif ("鱼油" in lower_q) or ("fish oil" in lower_q):
        return PRODUCTS_DATA["fish oil"]
    else:
        # 如果没有匹配到，可以返回空或默认商品
        return []


############################################
# step 2: 随机分流 variant=1..4
############################################
if "variant" not in st.session_state:
    st.session_state.variant = random.randint(1, 4)
variant = st.session_state.variant

############################################
# step 3: DeepSeek 推荐场景（改）
############################################
def show_deepseek_recommendation(with_ads: bool):
    st.title("Querya Rec")
    st.write(f"Current version：{'with ads' if with_ads else 'without ads'}")

    if "history" not in st.session_state:
        st.session_state.history = [("system", "You are an e-commerce chat assistant who recommends products based on user needs.")]

    for role, content in st.session_state.history:
        if role == "system":
            continue
        st.chat_message(role).write(content)

    user_input = st.chat_input("Input message and press enter…")
    if not user_input:
        return

    # -- 用户消息入历史 --
    st.session_state.history.append(("user", user_input))
    st.chat_message("user").write(user_input)

    # ★ 先尝试关键词预设答复
    predefined = get_predefined_response(user_input)
    if predefined is not None:
        assistant_text = predefined
         # 输出 & 写历史
        st.session_state.history.append(("assistant", assistant_text))
        st.chat_message("assistant").write(assistant_text)

        # 广告
        if with_ads:
            prods = get_products_by_query(user_input)
            if prods:
                show_advertisements(prods)
    else:
        # 调用 DeepSeek
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": r, "content": c} for r, c in st.session_state.history],
            temperature=1,
            stream=False,
        )
        assistant_text = resp.choices[0].message.content
        # 输出 & 写历史
        st.session_state.history.append(("assistant", assistant_text))
        st.chat_message("assistant").write(assistant_text)
   
    

############################################
# step 4: 仿 Google 场景（
############################################

def show_google_search(with_ads: bool):
    """
    当 with_ads=False 时，结果无广告
    当 with_ads=True 时，往搜索结果里插入 sponsor 或标记 sponsored
    """

    st.title("Querya search")
    st.write(f"Current Version：{'with ads' if with_ads else 'without ads'}")

    # 演示：模拟的搜索结果(伪)函数
    def do_fake_google_search(query):
        lower_q = query.lower()
        
        #这里仅做示例返回几条伪搜索结果，可根据关键词控制输出
       
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

    # -- 搜索框（仿Google的Logo & 布局） --
    # st.markdown("""
    # <div style="text-align:center; margin-top:20px;">
    #   <img src="https://www.google.com/images/branding/googlelogo/2x/googlelogo_color_92x30dp.png"
    #        style="height:40px;" />
    # </div>
    # """, unsafe_allow_html=True)

    def to_base64(path: str) -> str:
        return base64.b64encode(Path(path).read_bytes()).decode()

    logo_b64 = to_base64("querya.png")  # adjust filename / path

    st.markdown(
        f"""
        <div style="text-align:center; margin-top:20px;">
            <img src="data:image/png;base64,{logo_b64}" style="height:80px;" />
        </div>
        """,
        unsafe_allow_html=True
    )

    query = st.text_input("", placeholder="Input Key Words for Search Here")
    if st.button("Search"):
        results = do_fake_google_search(query)
        st.write("---")
        st.write("**Search Results: **")
        for i, item in enumerate(results):
            st.markdown(f"""
        <div style="margin-bottom:30px;">
          <div style="font-size:22px; line-height:1.4;">
            <a href="{item['url']}" target="_blank" style=" text-decoration:none;">
              {item['title']}
            </a>
          </div>
          <div style="font-size:16px; margin-top:4px;">
            {item.get('desc', '')}
          </div>
        </div>
        """, unsafe_allow_html=True)
        # 如果带广告，就额外插入广告商品
        if with_ads:
            relevant_products = get_products_by_query(query)
            if relevant_products:
                show_advertisements(relevant_products)

############################################
# step 5: 主逻辑
############################################
def main():
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

