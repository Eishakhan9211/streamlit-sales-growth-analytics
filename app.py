"""
Sales analytics dashboard: upload CSV/Excel, clean data, explore insights and custom charts.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st


def unique_column_names(cols: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for c in cols:
        base = str(c).strip() or "column"
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.append(base if n == 0 else f"{base}_{n + 1}")
    return out


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    flat = (
        pd.Index(out.columns)
        .astype(str)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )
    out.columns = unique_column_names(flat.tolist())
    return out


def drop_fully_blank(df: pd.DataFrame) -> pd.DataFrame:
    return df.dropna(how="all").dropna(axis=1, how="all")


def apply_missing_strategy(
    df: pd.DataFrame,
    *,
    numeric_fill: str,
    text_fill: str,
    subset_key_cols: list[str] | None = None,
) -> pd.DataFrame:
    """numeric_fill: median | mean | zero | skip; text_fill: mode | unknown | skip"""
    out = df.copy()
    nums = out.select_dtypes(include=[np.number]).columns
    cats = out.select_dtypes(exclude=[np.number]).columns

    for c in nums:
        if out[c].isna().any():
            if numeric_fill == "median":
                out[c] = out[c].fillna(out[c].median())
            elif numeric_fill == "mean":
                out[c] = out[c].fillna(out[c].mean())
            elif numeric_fill == "zero":
                out[c] = out[c].fillna(0)

    for c in cats:
        if out[c].isna().any():
            if text_fill == "mode":
                m = out[c].mode(dropna=True)
                fill = m.iloc[0] if len(m) else ""
                out[c] = out[c].fillna(fill)
            elif text_fill == "unknown":
                out[c] = out[c].fillna("(missing)")

    if subset_key_cols:
        cols = [c for c in subset_key_cols if c in out.columns]
        if cols:
            out = out.dropna(subset=cols)

    return out


def guess_sales_columns(df: pd.DataFrame) -> dict[str, str | None]:
    cols = list(df.columns)
    lower_map = {c: str(c).lower() for c in cols}

    def pick(keywords: list[str], excludes: tuple[str, ...] = ()) -> str | None:
        for c in cols:
            lc = lower_map[c]
            if any(x in lc for x in excludes):
                continue
            if any(k in lc for k in keywords):
                return c
        return None

    revenue = pick(
        ["revenue", "sales", "amount", "total", "value", "price", "inr", "usd", "gmv"],
        ("quantity", "qty", "count", "units"),
    )
    dt = pick(
        ["date", "time", "month", "order_date", "invoice", "day"],
        (),
    )
    product = pick(
        ["product", "item", "sku", "name", "goods", "article"],
        ("customer", "client", "region"),
    )

    if revenue is None:
        nums = df.select_dtypes(include=[np.number]).columns
        revenue = nums[0] if len(nums) else None

    return {"revenue": revenue, "date": dt, "product": product}


def guess_stock_column(df: pd.DataFrame) -> str | None:
    """Guess a column that holds on-hand stock or remaining quantity."""
    cols = list(df.columns)
    lower_map = {c: str(c).lower() for c in cols}
    keywords = [
        "stock",
        "inventory",
        "on hand",
        "onhand",
        "available",
        "balance",
        "remaining",
        "qty left",
        "quantity left",
        "units left",
        "in stock",
        "on_hand",
    ]
    for c in cols:
        lc = lower_map[c]
        if any(k in lc for k in keywords):
            return c
    return None


def coerce_date_series(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce")


def filtered_frame(
    df: pd.DataFrame,
    *,
    product_col: str | None,
    date_col: str | None,
    products_sel: list[str] | None,
    date_range: tuple[Any, Any] | None,
) -> pd.DataFrame:
    out = df
    if product_col and product_col in out.columns and products_sel is not None:
        out = out[out[product_col].astype(str).isin(products_sel)]
    if (
        date_col
        and date_col in out.columns
        and date_range is not None
        and len(date_range) == 2
    ):
        s = coerce_date_series(out[date_col])
        start, end = date_range
        out = out[(s >= pd.Timestamp(start)) & (s <= pd.Timestamp(end))]
    return out


def load_uploaded(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    bio = BytesIO(uploaded_file.getvalue())
    if name.endswith(".csv"):
        try:
            return pd.read_csv(bio)
        except UnicodeDecodeError:
            bio.seek(0)
            return pd.read_csv(bio, encoding="latin-1")
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(bio)
    raise ValueError("Upload a CSV or Excel file (.csv, .xlsx, .xls).")


def sum_by_group(df: pd.DataFrame, x: str, y: str) -> pd.DataFrame:
    v = pd.to_numeric(df[y], errors="coerce")
    return (
        df.assign(__y=v)
        .groupby(x, dropna=False)["__y"]
        .sum()
        .reset_index()
        .rename(columns={"__y": y})
    )


def latest_stock_by_product(
    df: pd.DataFrame,
    product_col: str,
    stock_col: str,
    date_col: str | None,
) -> pd.DataFrame:
    """
    One current quantity per product: last row by date if a date column exists,
    otherwise last row in file order within each product group.
    """
    # Avoid df[[col, col]] which creates duplicate columns and breaks pd.to_numeric
    use_ordered: list[str] = []
    for c in (product_col, stock_col):
        if c in df.columns and c not in use_ordered:
            use_ordered.append(c)
    if date_col and date_col in df.columns and date_col not in use_ordered:
        use_ordered.append(date_col)
    w = df.loc[:, use_ordered].copy()
    raw = w[stock_col]
    if isinstance(raw, pd.DataFrame):
        raw = raw.iloc[:, 0]
    elif not isinstance(raw, pd.Series):
        raw = pd.Series(raw, index=w.index)

    if str(product_col) == str(stock_col):
        w["__q"] = np.nan
    else:
        w["__q"] = pd.to_numeric(raw, errors="coerce")

    w = w.dropna(subset=[product_col])
    w = w[w[product_col].astype(str).str.strip().ne("")]
    if w.empty:
        return pd.DataFrame(columns=[product_col, "Current quantity"])
    if date_col and date_col in w.columns:
        w["__d"] = coerce_date_series(w[date_col])
        w = w.sort_values("__d", kind="mergesort", na_position="last")
    qty = w.groupby(product_col, dropna=False)["__q"].last()
    out = qty.reset_index()
    out.columns = [product_col, "Current quantity"]
    return out


def inject_app_styles() -> None:
    css_path = Path(__file__).resolve().parent / "app_styles.css"
    st.markdown(
        f"<style>{css_path.read_text(encoding='utf-8')}</style>",
        unsafe_allow_html=True,
    )


st.set_page_config(
    page_title="Sales Growth Analytics",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_app_styles()

st.markdown(
    """
    <div class="page-hero">
      <h1 class="page-hero-title">Sales Growth Analytics</h1>
      <p class="page-hero-caption">Turn a spreadsheet into simple sales charts.</p>
    </div>
    """,
    unsafe_allow_html=True,
)
with st.expander("How to use this (read me first)", expanded=False):
    st.markdown(
        """
1. **Upload** your Excel or CSV file below.  
2. Use **Focus your report** in the sidebar to limit dates or products *only if you want to* — you can skip it.  
3. Open the tabs: **Sales**, **Stock** (only if you track inventory numbers), **Charts**.  
4. Only open **Optional — column names, stock & cleaning** in the sidebar if something looks wrong (wrong money column, messy blanks, etc.).
        """
    )

if "df_raw" not in st.session_state:
    st.session_state.df_raw = None
if "df_clean" not in st.session_state:
    st.session_state.df_clean = None
if "file_name" not in st.session_state:
    st.session_state.file_name = None

upload = st.file_uploader(
    "1. Upload your Excel or CSV file",
    type=["csv", "xlsx", "xls"],
    help="Excel (.xlsx, .xls) or CSV (.csv)",
)

if upload is not None:
    try:
        st.session_state.df_raw = load_uploaded(upload)
        st.session_state.file_name = upload.name
        st.session_state.df_clean = None
    except Exception as e:
        st.error(f"Could not read file: {e}")
        st.session_state.df_raw = None

df_raw = st.session_state.df_raw

if df_raw is None:
    st.info(
        "Upload your file above to begin. Typical columns include product name, date, and how much was sold."
    )
    st.stop()

norm_preview = normalize_columns(df_raw.copy())
guesses = guess_sales_columns(norm_preview)
all_cols = list(norm_preview.columns)

with st.sidebar.expander(
    "Optional — column names, stock & cleaning",
    expanded=False,
):
    st.caption(
        "You usually **don’t need** this. Use it only if totals look wrong, dates don’t chart, "
        "or your file has blanks and duplicates."
    )
    mapped_rev = st.sidebar.selectbox(
        "Which column is **sales / revenue (money)**?",
        options=[None] + all_cols,
        format_func=lambda x: "— not set —" if x is None else str(x),
        index=(1 + all_cols.index(guesses["revenue"])) if guesses["revenue"] in all_cols else 0,
        key="map_rev",
    )
    mapped_dt = st.sidebar.selectbox(
        "Which column is the **date**?",
        options=[None] + all_cols,
        format_func=lambda x: "— not set —" if x is None else str(x),
        index=(1 + all_cols.index(guesses["date"])) if guesses["date"] in all_cols else 0,
        key="map_dt",
    )
    mapped_prod = st.sidebar.selectbox(
        "Which column is **product name**?",
        options=[None] + all_cols,
        format_func=lambda x: "— not set —" if x is None else str(x),
        index=(1 + all_cols.index(guesses["product"])) if guesses["product"] in all_cols else 0,
        key="map_prod",
    )
    guess_st = guess_stock_column(norm_preview)
    st.sidebar.divider()
    st.sidebar.markdown("**Inventory (only if you track stock)**")
    mapped_stock = st.sidebar.selectbox(
        "**How many units are left / in stock** (numbers only)",
        options=[None] + all_cols,
        format_func=lambda x: "— skip — I don’t have this" if x is None else str(x),
        index=(1 + all_cols.index(guess_st)) if guess_st in all_cols else 0,
        key="map_stock",
    )

    st.sidebar.divider()
    st.sidebar.markdown("**Tidy messy data**")
    remove_dup_rows = st.sidebar.checkbox("Remove duplicate rows", value=True, key="opt_dup_rows")
    drop_if_key_na = st.sidebar.checkbox(
        "Remove rows missing money, date, or product (when those are set above)",
        value=False,
        key="opt_drop_na_keys",
    )
    numeric_fill = st.sidebar.selectbox(
        "Blank numbers → fill with",
        ["median", "mean", "zero", "skip (leave blank)"],
        format_func=lambda x: {
            "median": "Typical middle value",
            "mean": "Average",
            "zero": "Zero",
            "skip (leave blank)": "Leave blank",
        }.get(str(x), str(x)),
        index=3,
        key="num_fill",
    )
    text_fill_label = {
        "mode": "Most common text",
        "unknown": 'Label blanks as "(missing)"',
        "skip": "Leave blanks as they are",
    }
    raw_text_opts = ["mode", "unknown", "skip"]
    text_fill = st.sidebar.selectbox(
        "Blank text cells → fill with",
        raw_text_opts,
        format_func=lambda x: text_fill_label.get(str(x), str(x)),
        index=2,
        key="text_fill",
    )


def compute_clean(raw: pd.DataFrame) -> pd.DataFrame:
    d = normalize_columns(raw.copy())
    d = drop_fully_blank(d)
    if remove_dup_rows:
        d = d.drop_duplicates()
    key_cols = []
    if mapped_rev is not None and mapped_rev in d.columns:
        key_cols.append(str(mapped_rev))
    if mapped_dt is not None and mapped_dt in d.columns:
        key_cols.append(str(mapped_dt))
    if mapped_prod is not None and mapped_prod in d.columns:
        key_cols.append(str(mapped_prod))
    nf = numeric_fill if isinstance(numeric_fill, str) else "skip"
    if nf == "skip (leave blank)":
        nf = "skip"
    return apply_missing_strategy(
        d,
        numeric_fill=nf,
        text_fill=text_fill,
        subset_key_cols=key_cols if drop_if_key_na else None,
    )


if st.sidebar.button("Apply fixes & refresh data", type="secondary", key="clean_apply"):
    try:
        st.session_state.df_clean = compute_clean(df_raw)
        st.sidebar.success("Data refreshed.")
    except Exception as e:
        st.sidebar.error(str(e))

st.sidebar.divider()

st.sidebar.markdown("### Focus your report")
st.sidebar.caption("Optional. Leave as-is to see **everything**.")

if st.session_state.df_clean is None:
    st.session_state.df_clean = compute_clean(df_raw)

df = st.session_state.df_clean

before_norm = normalize_columns(df_raw.copy())
before_norm = drop_fully_blank(before_norm)
row_before_dedup = len(before_norm)
row_after_dedup = len(before_norm.drop_duplicates()) if remove_dup_rows else row_before_dedup
duplicate_rows_removed = max(0, row_before_dedup - row_after_dedup)

prod_opts_sidebar: list[str] | None = None
dr_sidebar: tuple[Any, ...] | None = None

if mapped_prod and str(mapped_prod) in df.columns:
    products_all = sorted(df[str(mapped_prod)].dropna().astype(str).unique().tolist())
    prod_opts_sidebar = st.sidebar.multiselect(
        "Pick products (or leave all ticked)",
        options=products_all,
        default=products_all,
        help="Shows only these products in charts. Uncheck ones you want to hide.",
        key="filter_products",
    )
else:
    st.sidebar.caption(
        'No product list yet — open **Optional — column names** and choose the **product name** column if you want this filter.'
    )

if mapped_dt and str(mapped_dt) in df.columns:
    parsed = coerce_date_series(df[str(mapped_dt)])
    vmin = parsed.min()
    vmax = parsed.max()
    if pd.notna(vmin) and pd.notna(vmax):
        dmin, dmax = vmin.date(), vmax.date()
        dr_sidebar = st.sidebar.date_input(
            "Pick dates (or leave full range)",
            value=(dmin, dmax),
            min_value=dmin,
            max_value=dmax,
            key="filter_dates",
        )
else:
    st.sidebar.caption(
        'No date filter yet — open **Optional** and set your **date** column if you want to filter by time.'
    )

filt_df = filtered_frame(
    df,
    product_col=str(mapped_prod) if mapped_prod else None,
    date_col=str(mapped_dt) if mapped_dt else None,
    products_sel=prod_opts_sidebar if prod_opts_sidebar else None,
    date_range=(
        (dr_sidebar[0], dr_sidebar[1])
        if dr_sidebar is not None and isinstance(dr_sidebar, tuple) and len(dr_sidebar) == 2
        else None
    ),
)

st.divider()

tab_intro, tab_insights, tab_inventory, tab_explorer = st.tabs(
    ["Overview", "Sales", "Stock", "Charts"],
)

with tab_intro:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows (after cleaning)", f"{len(df):,}")
    c2.metric("Columns", len(df.columns))
    if remove_dup_rows:
        c3.metric("Duplicate rows removed", f"{duplicate_rows_removed:,}")
    else:
        c3.metric("Duplicate rows removed", "Not applied")
    null_pct = (
        round(100 * float(df.isna().sum().sum()) / float(max(df.shape[0] * df.shape[1], 1)), 2)
        if df.size
        else 0.0
    )
    c4.metric("Missing cells (overall %)", f"{null_pct}%")

    preview_n = st.slider("Preview rows", 5, 200, 15)
    st.subheader("Column summary")
    st.dataframe(df.dtypes.astype(str).rename("dtype").to_frame(), use_container_width=True)
    with st.expander("Summary statistics (numeric columns)", expanded=False):
        st.dataframe(df.describe(include=[np.number]).T, use_container_width=True)

    st.subheader("Preview (cleaned data)")
    st.dataframe(df.head(preview_n), use_container_width=True)

with tab_insights:
    st.caption(f"Using **{len(filt_df):,}** rows after **Focus your report** choices in the sidebar.")

    key_metrics = st.columns(4)
    rev_series = filt_df[str(mapped_rev)] if mapped_rev and str(mapped_rev) in filt_df.columns else None
    total_rev = pd.to_numeric(rev_series, errors="coerce").sum() if rev_series is not None else None
    n_rows = len(filt_df)

    num_rev_clean = pd.to_numeric(rev_series, errors="coerce") if rev_series is not None else None

    key_metrics[0].metric("Filtered rows", f"{n_rows:,}")
    key_metrics[1].metric(
        "Total revenue (sum)",
        f"{total_rev:,.2f}" if total_rev is not None and pd.notna(total_rev) else "—",
    )
    avg_rev = num_rev_clean.mean() if num_rev_clean is not None and n_rows else None
    key_metrics[2].metric(
        "Average row revenue",
        f"{avg_rev:,.4f}" if avg_rev is not None and pd.notna(avg_rev) else "—",
    )
    if mapped_prod and str(mapped_prod) in filt_df.columns and mapped_rev:
        uniq = filt_df[str(mapped_prod)].nunique(dropna=True)
        key_metrics[3].metric("Distinct products", f"{uniq:,}")
    else:
        key_metrics[3].metric("Distinct products", "—")

    st.subheader("Product performance")
    if mapped_prod and mapped_rev and str(mapped_prod) in filt_df.columns and str(mapped_rev) in filt_df.columns:
        gdf = sum_by_group(filt_df, str(mapped_prod), str(mapped_rev))
        prod_label = str(mapped_prod)
        gdf.columns = [prod_label, "Total sales"]

        lc, rc = st.columns((1, 1))
        with lc:
            st.markdown("**Highest-selling products**")
            st.dataframe(gdf.sort_values("Total sales", ascending=False).head(20), use_container_width=True)
        with rc:
            st.markdown("**Lowest-selling products** (bottom 20)")
            st.dataframe(gdf.sort_values("Total sales").head(20), use_container_width=True)

        chart_df = gdf.sort_values("Total sales", ascending=False).head(25)
        fig = px.bar(
            chart_df,
            x=str(mapped_prod),
            y="Total sales",
            title="Top 25 products by total sales",
        )
        fig.update_layout(xaxis_title="Product", yaxis_title="Sales", xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)
    elif mapped_prod:
        st.warning("Map a numeric **sales / revenue** column for product totals.")
    else:
        st.warning("Map a **product** column for product-level insights.")

    st.subheader("Sales over time (by calendar month)")
    if mapped_dt and mapped_rev and str(mapped_dt) in filt_df.columns and str(mapped_rev) in filt_df.columns:
        tdf = filt_df[[str(mapped_dt), str(mapped_rev)]].copy()
        tdf["_d"] = coerce_date_series(tdf[str(mapped_dt)])
        tdf = tdf.dropna(subset=["_d"])
        tdf["_v"] = pd.to_numeric(tdf[str(mapped_rev)], errors="coerce")
        tdf = tdf.dropna(subset=["_v"])
        tdf["_ym"] = tdf["_d"].dt.to_period("M").dt.to_timestamp()
        agg = tdf.groupby("_ym", dropna=False)["_v"].sum().reset_index(name="Monthly sales")

        tbl, ch = st.columns((1, 1))
        with tbl:
            st.dataframe(
                agg.sort_values("_ym", ascending=False).rename(columns={"_ym": "Month start"}),
                use_container_width=True,
            )
        with ch:
            fig2 = px.line(agg, x="_ym", y="Monthly sales", markers=True, title="Monthly revenue trend")
            fig2.update_layout(xaxis_title="Month", yaxis_title="Sales")
            st.plotly_chart(fig2, use_container_width=True)

        fig3 = px.bar(agg, x="_ym", y="Monthly sales", title="Monthly sales (bars)")
        fig3.update_layout(xaxis_title="Month", yaxis_title="Sales")
        st.plotly_chart(fig3, use_container_width=True)
    else:
        st.info("Map both **date** and **sales / revenue** for monthly aggregates.")

with tab_inventory:
    st.subheader("Current quantity by product")
    st.caption(
        "Uses your **Stock / quantity on hand** column. If a **date** is mapped and the file has several "
        "rows per product, the **most recent** row (by date) is treated as the current quantity."
    )

    if mapped_stock is None:
        st.info(
            "If your spreadsheet includes stock or inventory levels, open **Inventory (optional)** in the "
            "sidebar and choose the right column."
        )
        if st.button("Check quantity for a product", key="inventory_btn_no_column"):
            st.warning(
                "No data available. You have not mapped a **Stock / quantity on hand** column. "
                "Add that column to your data or map it in the sidebar, then try again."
            )
    elif not mapped_prod:
        st.info("Map a **product** column in the sidebar to see quantity per product.")
        if st.button("Check quantity for a product", key="inventory_btn_no_product_col"):
            st.warning(
                "No data available. Map a **product** column under **Column mapping (sales)** first."
            )
    elif str(mapped_stock) not in filt_df.columns or str(mapped_prod) not in filt_df.columns:
        st.error("Mapped columns are missing from the cleaned data. Re-upload or adjust column mapping.")
    elif str(mapped_stock) == str(mapped_prod):
        st.error(
            "**Product** and **Stock / quantity on hand** cannot be the same column. "
            "Pick a column that contains **numbers** for how many units are left (for example *Qty on hand*, *Stock*, *Inventory*)."
        )
    else:
        inv_df = latest_stock_by_product(
            filt_df,
            str(mapped_prod),
            str(mapped_stock),
            str(mapped_dt) if mapped_dt else None,
        )
        has_any = inv_df["Current quantity"].notna().any()

        if filt_df.empty:
            st.warning("No data available for the current filters. Widen the product or date filters in the sidebar.")
        elif inv_df.empty or not has_any:
            st.warning(
                "No quantity data available. All stock values are missing or empty for the rows you filtered. "
                "Check the **Stock / quantity on hand** column in your source file."
            )
        else:
            show_df = inv_df.sort_values("Current quantity", ascending=False, na_position="last")
            left, right = st.columns(2)
            with left:
                st.dataframe(show_df, use_container_width=True)
            with right:
                chart_inv = show_df.dropna(subset=["Current quantity"])
                if not chart_inv.empty:
                    fig_inv = px.bar(
                        chart_inv.head(40),
                        x=str(mapped_prod),
                        y="Current quantity",
                        title="Current quantity by product (up to 40)",
                    )
                    fig_inv.update_layout(xaxis_title="Product", yaxis_title="Quantity", xaxis_tickangle=-45)
                    st.plotly_chart(fig_inv, use_container_width=True)
            csv_inv = show_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download inventory table (CSV)",
                csv_inv,
                file_name="inventory_by_product.csv",
                mime="text/csv",
                key="inventory_csv_dl",
            )

        with st.expander("Look up one product"):
            choices = sorted(filt_df[str(mapped_prod)].dropna().astype(str).unique().tolist())
            pick = st.selectbox("Product", options=choices or ["(no products)"], key="inventory_pick_one")
            if st.button("Show current quantity", key="inventory_lookup_btn"):
                if mapped_stock is None:
                    st.warning(
                        "No data available. Map **Stock / quantity on hand** in the sidebar under **Inventory (optional)**."
                    )
                elif not choices or pick == "(no products)":
                    st.warning("No data available. There are no products in the current filtered data.")
                else:
                    row = inv_df[inv_df[str(mapped_prod)].astype(str) == pick]
                    if row.empty or pd.isna(row["Current quantity"].iloc[0]):
                        st.warning(f'No quantity data available for **{pick}** in the current selection.')
                    else:
                        q = float(row["Current quantity"].iloc[0])
                        st.metric("Current quantity", f"{q:,.2f}")

with tab_explorer:
    st.subheader("Build your own chart and matching table")

    use_same_filters = st.checkbox(
        "Use the same product & date limits as the **Sales** tab",
        value=True,
        key="explorer_use_filters",
    )
    base = filt_df if use_same_filters else df

    viz_type = st.selectbox(
        "Chart type",
        ["Bar", "Line", "Scatter", "Histogram", "Box", "Pie", "Area"],
        key="explorer_viz",
    )
    xc = st.selectbox("X-axis / category column", options=list(df.columns), key="explorer_x")
    numeric_cols = base.select_dtypes(include=[np.number]).columns.tolist()
    y_candidates = numeric_cols + [c for c in base.columns if c not in numeric_cols]
    pref_y = str(mapped_rev) if mapped_rev else None
    y_index = (
        y_candidates.index(pref_y)
        if pref_y and pref_y in y_candidates
        else (0 if y_candidates else 0)
    )
    yc = st.selectbox(
        "Y-axis / values column (numeric preferred)",
        options=y_candidates if y_candidates else list(base.columns),
        index=min(max(y_index, 0), len(y_candidates) - 1 if y_candidates else 0),
        key="explorer_y",
    )

    color_opts = [None] + [c for c in base.columns if c not in {str(xc), str(yc)}]
    color_col = st.selectbox(
        "Color / grouping (optional)",
        options=color_opts,
        format_func=lambda x: "(none)" if x is None else str(x),
        key="explorer_color",
    )

    ok_color = color_col is not None and str(color_col) in base.columns
    color_kw = {"color": str(color_col)} if ok_color else {}

    fig = None

    try:
        dplot = base.copy()

        numeric_y = pd.to_numeric(dplot[str(yc)], errors="coerce")

        if viz_type == "Bar":
            g = sum_by_group(dplot, str(xc), str(yc))
            fig = px.bar(g, x=str(xc), y=str(yc), **color_kw)
            fig.update_layout(xaxis_title=str(xc), yaxis_title=str(yc))
        elif viz_type == "Pie":
            g = sum_by_group(dplot, str(xc), str(yc))
            fig = px.pie(g, names=str(xc), values=str(yc))
        elif viz_type == "Line":
            gx = coerce_date_series(dplot[str(xc)]) if xc in dplot.columns else None
            if gx is not None and gx.notna().sum() >= 2:
                agg_line = (
                    dplot.assign(__gx=gx, __yv=numeric_y)
                    .dropna(subset=["__gx", "__yv"])
                    .groupby("__gx")["__yv"]
                    .sum()
                    .reset_index()
                    .rename(columns={"__gx": str(xc), "__yv": str(yc)})
                    .sort_values(str(xc))
                )
                fig = px.line(agg_line, x=str(xc), y=str(yc), markers=True, **{})
            else:
                g = (
                    dplot.assign(__x=str(dplot[str(xc)].astype(str)), __yv=numeric_y)
                    .groupby("__x", dropna=False)["__yv"]
                    .sum()
                    .reset_index()
                    .rename(columns={"__x": str(xc)})
                )
                fig = px.line(g.sort_values(str(xc)), x=str(xc), y="__yv")
                fig.update_layout(yaxis_title=str(yc))
        elif viz_type == "Scatter":
            sx = pd.to_numeric(dplot[str(xc)], errors="coerce")
            sdf = pd.DataFrame({str(xc): sx, str(yc): numeric_y})
            if ok_color:
                sdf[str(color_col)] = dplot[str(color_col)].values
            sdf = sdf.dropna(subset=[str(xc), str(yc)])
            fig = px.scatter(sdf, x=str(xc), y=str(yc), color=str(color_col) if ok_color else None)
        elif viz_type == "Histogram":
            fig = px.histogram(dplot, x=str(xc), nbins=40, **color_kw)
        elif viz_type == "Box":
            fig = px.box(dplot.assign(__y=numeric_y), x=str(xc), y="__y", **color_kw)
            fig.update_layout(yaxis_title=str(yc))
        elif viz_type == "Area":
            gx = coerce_date_series(dplot[str(xc)]) if xc in dplot.columns else None
            if gx is not None and gx.notna().any():
                agg_a = (
                    dplot.assign(__gx=gx, __yv=numeric_y)
                    .dropna(subset=["__gx", "__yv"])
                    .groupby("__gx")["__yv"]
                    .sum()
                    .reset_index()
                    .rename(columns={"__gx": str(xc)})
                )
                fig = px.area(agg_a, x=str(xc), y="__yv", **{})
                fig.update_layout(yaxis_title=str(yc))
            else:
                g = sum_by_group(dplot, str(xc), str(yc)).sort_values(str(xc))
                fig = px.area(g, x=str(xc), y=str(yc))

        if fig is not None:
            fig.update_layout(title=f"{viz_type}: {xc} × {yc}")
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("**Table aligned with chart logic**")

        tbl_out: pd.DataFrame | None = None
        if viz_type in ("Bar", "Pie"):
            tbl_out = sum_by_group(dplot, str(xc), str(yc)).rename(
                columns={str(yc): f"Sum of {yc}"}
            )
            tbl_out = tbl_out.sort_values(f"Sum of {yc}", ascending=False).reset_index(drop=True)
        elif viz_type == "Line":
            gx = coerce_date_series(dplot[str(xc)]) if xc in dplot.columns else None
            if gx is not None and gx.notna().sum() >= 2:
                tbl_out = (
                    dplot.assign(__gx=gx, __yv=numeric_y)
                    .dropna(subset=["__gx", "__yv"])
                    .groupby("__gx")["__yv"]
                    .sum()
                    .reset_index()
                    .rename(columns={"__gx": str(xc), "__yv": f"Sum of {yc}"})
                    .sort_values(str(xc))
                )
            else:
                tbl_out = (
                    dplot.assign(__x=str(dplot[str(xc)].astype(str)), __yv=numeric_y)
                    .groupby("__x", dropna=False)["__yv"]
                    .sum()
                    .reset_index()
                    .rename(columns={"__x": str(xc), "__yv": f"Sum of {yc}"})
                )
        elif viz_type == "Area":
            gx = coerce_date_series(dplot[str(xc)]) if xc in dplot.columns else None
            if gx is not None and gx.notna().any():
                tbl_out = (
                    dplot.assign(__gx=gx, __yv=numeric_y)
                    .dropna(subset=["__gx", "__yv"])
                    .groupby("__gx")["__yv"]
                    .sum()
                    .reset_index()
                    .rename(columns={"__gx": str(xc), "__yv": f"Sum of {yc}"})
                )
            else:
                tbl_out = sum_by_group(dplot, str(xc), str(yc)).rename(
                    columns={str(yc): f"Sum of {yc}"}
                )
        elif viz_type == "Histogram":
            vc = pd.to_numeric(dplot[str(xc)], errors="coerce").dropna()
            if len(vc):
                bins = pd.cut(vc, bins=min(40, max(10, len(vc) // 5)))
                tmp = pd.DataFrame({str(xc): vc.values, "bin": bins.astype(str)})
                tbl_out = (
                    tmp.groupby("bin", dropna=False)[str(xc)]
                    .agg(count="count", min="min", max="max")
                    .reset_index()
                )
            else:
                tbl_out = None
        elif viz_type == "Box":
            tbl_out = dplot[[str(xc), str(yc)]].assign(__yv=numeric_y)
            tbl_out = (
                tbl_out.dropna(subset=["__yv"])
                .groupby(str(xc), dropna=False)["__yv"]
                .agg(["count", "mean", "median", "std", "min", "max"])
                .reset_index()
            )
        elif viz_type == "Scatter":
            cols = [str(xc), str(yc)]
            if ok_color:
                cols.append(str(color_col))
            tbl_out = dplot.loc[:, cols].copy()
            tbl_out[str(yc)] = numeric_y
            if str(xc) != str(yc):
                tbl_out[str(xc)] = pd.to_numeric(dplot[str(xc)], errors="coerce")
            tbl_out = tbl_out.drop_duplicates()

        if tbl_out is not None and not tbl_out.empty:
            st.dataframe(tbl_out, use_container_width=True)
            csv_bytes = tbl_out.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download table as CSV",
                csv_bytes,
                file_name="explorer_export.csv",
                mime="text/csv",
                key="explorer_csv_dl",
            )
        else:
            st.caption("No rows available for this table after filters.")

    except Exception as e:
        st.error(f"Could not build chart or table: {e}")

st.sidebar.markdown("---")
st.sidebar.caption(f"Loaded: **{st.session_state.file_name}**")
