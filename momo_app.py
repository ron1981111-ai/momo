# 執行方式：streamlit run momo_app.py
import re
import time

import pandas as pd
import plotly.express as px
import streamlit as st
from curl_cffi import requests

API_URL = "https://apisearch.momoshop.com.tw/momoSearchCloud/moec/textSearch"
HOME_URL = "https://www.momoshop.com.tw/"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.momoshop.com.tw",
    "Referer": "https://www.momoshop.com.tw/",
}


# ---------------------------------------------------------------- 爬蟲 (CODE01)
def build_payload(keyword: str, page: int) -> dict:
    return {
        "host": "momoshop",
        "flag": "searchEngine",
        "data": {
            "searchValue": keyword,
            "searchType": "1",
            "cateLevel": "-1",
            "curPage": str(page),
            "priceS": "0",
            "priceE": "9999999",
            "showType": "chessboardType",
            "isFuzzy": "0",
            "rtnCateDatainfo": {
                "cateCode": "",
                "cateLv": "-1",
                "keyword": keyword,
                "curPage": str(page),
                "historyDoPush": "false",
                "timestamp": int(time.time() * 1000),
            },
            "flag": 2018,
            "serviceCode": "MT01",
            "addressSearchData": {},
        },
    }


@st.cache_data(ttl=600, show_spinner=False)
def crawl(keyword: str, pages: int, delay: float) -> pd.DataFrame:
    """爬取 1~pages 頁，回傳 DataFrame（品名、價格、頁數、連結）。"""
    session = requests.Session(impersonate="chrome")  # 模擬 Chrome TLS 指紋
    session.get(HOME_URL, headers=HEADERS)            # 先取得 cookie

    rows = []
    for page in range(1, pages + 1):
        resp = session.post(API_URL, headers=HEADERS, json=build_payload(keyword, page))
        if resp.status_code != 200:
            raise RuntimeError(f"第 {page} 頁請求失敗（HTTP {resp.status_code}）：{resp.text[:200]}")
        goods = resp.json().get("rtnSearchData", {}).get("goodsInfoList", [])
        if not goods:  # 已經沒有更多資料
            break
        for p in goods:
            code = p.get("goodsCode", "")
            rows.append({
                "品名": p.get("goodsName", ""),
                "價格": p.get("goodsPrice", ""),
                "頁數": page,
                "連結": f"https://www.momoshop.com.tw/goods/GoodsDetail.jsp?i_code={code}" if code else "",
            })
        time.sleep(delay)  # 禮貌性延遲，避免被擋
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 清理 (CODE02)
def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["價格"] = pd.to_numeric(df["價格"].astype(str).str.replace(r"[^\d]", "", regex=True), errors="coerce")
    df = df.dropna(subset=["價格"]).drop_duplicates(subset=["品名", "價格"]).reset_index(drop=True)
    df["價格"] = df["價格"].astype(int)
    df.index = df.index + 1
    df.index.name = "編號"

    def brand(name: str) -> str:
        m = re.search(r"【(.+?)】", name)
        return m.group(1).strip() if m else "其他"

    df["品牌"] = df["品名"].map(brand)
    return df


def nice_step(span: int, bins: int = 6) -> int:
    raw = max(span / bins, 1)
    magnitude = 10 ** (len(str(int(raw))) - 1)
    return int(round(raw / magnitude) * magnitude) or magnitude


def add_price_range(df: pd.DataFrame, step: int) -> pd.DataFrame:
    df = df.copy()
    lo = (df["價格"].min() // step) * step
    hi = (df["價格"].max() // step + 1) * step
    edges = list(range(lo, hi + step, step))
    labels = [f"{a:,}–{b - 1:,}" for a, b in zip(edges[:-1], edges[1:])]
    df["價格區間"] = pd.cut(df["價格"], bins=edges, labels=labels, right=False)
    df["價格區間"] = df["價格區間"].astype(str)
    return df, labels


# ---------------------------------------------------------------- 介面
st.set_page_config(page_title="MOMO 商品價格分析", page_icon="🛒", layout="wide")
st.title("🛒 MOMO 商品價格查詢與視覺化")

with st.sidebar:
    st.header("查詢條件")
    keyword = st.text_input("商品關鍵字", value="筆電")
    pages = st.number_input("爬取頁數", min_value=1, max_value=20, value=2, step=1)
    delay = st.slider("每頁間隔（秒）", 0.5, 5.0, 1.0, 0.5)
    chart_type = st.radio("圖表類型", ["圓餅圖", "折線圖", "旭日圖"])
    run = st.button("開始查詢", type="primary", use_container_width=True)

if run:
    if not keyword.strip():
        st.warning("請輸入商品關鍵字")
        st.stop()
    try:
        with st.spinner(f"正在爬取「{keyword}」前 {pages} 頁…"):
            raw = crawl(keyword.strip(), int(pages), float(delay))
    except Exception as e:
        st.error(f"爬取失敗：{e}")
        st.stop()
    if raw.empty:
        st.warning("查無資料，請換個關鍵字或稍後再試。")
        st.stop()
    st.session_state["df"] = clean(raw)
    st.session_state["keyword"] = keyword.strip()

if "df" not in st.session_state:
    st.info("請在左側輸入商品與頁數，然後按「開始查詢」。")
    st.stop()

df: pd.DataFrame = st.session_state["df"]
kw = st.session_state["keyword"]
if df.empty:
    st.warning("沒有可用的價格資料。")
    st.stop()

# 統計
c1, c2, c3, c4 = st.columns(4)
c1.metric("商品數", f"{len(df):,}")
c2.metric("平均價格", f"${df['價格'].mean():,.0f}")
c3.metric("最高價格", f"${df['價格'].max():,}")
c4.metric("最低價格", f"${df['價格'].min():,}")

# 圖表
st.subheader(f"「{kw}」價格分析 — {chart_type}")
mean_price = df["價格"].mean()

if chart_type == "折線圖":
    n = st.slider("顯示前幾筆商品", 10, len(df), min(70, len(df))) if len(df) > 10 else len(df)
    sub = df.head(n).reset_index()
    fig = px.line(sub, x="編號", y="價格", hover_name="品名", markers=True)
    fig.add_hline(y=mean_price, line_dash="dash", line_color="red",
                  annotation_text=f"平均 {mean_price:,.0f}")
    fig.update_layout(xaxis_title="商品編號", yaxis_title="價格 (NT$)", height=550)
else:
    default_step = nice_step(int(df["價格"].max() - df["價格"].min()))
    step = st.number_input("價格區間寬度", min_value=1, value=default_step, step=max(default_step // 5, 1))
    ranged, labels = add_price_range(df, int(step))
    if chart_type == "圓餅圖":
        counts = ranged["價格區間"].value_counts().reindex(labels).dropna().reset_index()
        counts.columns = ["價格區間", "商品數"]
        fig = px.pie(counts, names="價格區間", values="商品數", hole=0.3)
        fig.update_traces(textinfo="label+percent", sort=False)
    else:  # 旭日圖：價格區間 → 品牌
        top = ranged["品牌"].value_counts().head(8).index
        ranged["品牌"] = ranged["品牌"].where(ranged["品牌"].isin(top), "其他")
        fig = px.sunburst(ranged, path=["價格區間", "品牌"])
        fig.update_traces(textinfo="label+value", insidetextorientation="radial")
    fig.update_layout(height=650)

st.plotly_chart(fig, use_container_width=True)

# 資料表與下載
with st.expander("查看原始資料", expanded=False):
    st.dataframe(
        df, use_container_width=True,
        column_config={"連結": st.column_config.LinkColumn("連結", display_text="前往商品")},
    )
st.download_button(
    "⬇️ 下載 CSV",
    df.to_csv(encoding="utf-8-sig").encode("utf-8-sig"),
    file_name=f"MOMO_{kw}_{time.strftime('%Y%m%d')}.csv",
    mime="text/csv",
)
