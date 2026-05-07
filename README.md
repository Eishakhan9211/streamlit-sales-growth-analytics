# Sales Growth Analytics

A simple web dashboard built with **Streamlit**. You open it in your browser, upload a sales file, and see your numbers as charts and tables—no coding needed to use it.

**What it does in plain terms:**  
Put in a **CSV** or **Excel** spreadsheet. The app can help fix messy data (like duplicate rows or empty cells) and figure out which column is revenue, dates, product names, and so on. Then you get summaries, how products are doing, trends over time, stock-style views, and charts you can explore.

## Features

- **Upload** a file: `.csv`, `.xlsx`, or `.xls`
- **Sidebar tools** (optional): remove duplicates, drop blank rows, tell the app which columns mean money, date, product, and stock
- **Filters:** narrow down by product and date range when those columns are set
- **Four screens (tabs):** Overview, Sales, Stock, Charts
- **Look and feel:** colors and sections are controlled in `app_styles.css` (soft blush-style background)

## Requirements

- **Python 3.10 or newer** (3.11+ is fine)
- Python packages are listed in `requirements.txt`

## Quick start

### 1. Install dependencies

From this folder:

```bash
pip install -r requirements.txt
```

### 2. Run the app

**Option A — batch file (Windows)**  
Double-click `run_dashboard.bat`, or run it from a terminal.

**Option B — command line**

```bash
streamlit run app.py
```

Then open **http://localhost:8501** in your browser.

## Deploy on Vercel

Vercel’s normal serverless setup is built for short HTTP requests, not a classic **Streamlit server** (which stays running and uses WebSockets). This repo is set up to still work on **Vercel** by serving a static page (`index.html`) that runs the same app in the browser with **[stlite](https://github.com/whitphx/stlite)** (Streamlit + Pyodide). Your data stays in the visitor’s browser.

1. Push this project to GitHub (or GitLab / Bitbucket).
2. In [Vercel](https://vercel.com), create a project and import that repo.
3. Under **Settings → General → Build & Development**, set **Framework Preset** to **Other** and leave **Build Command** and **Output Directory** empty unless Vercel fills them in—there is no build step; the site is static files plus `app.py`.
4. Deploy. Open the production URL; the first load may take a while while scientific libraries download in the browser.

If Vercel picks “Python” on its own because of `requirements.txt`, switch the preset to **Other** so it does not try to run `streamlit` on the server.

### Full server Streamlit (Docker)

For the usual `streamlit run` experience (often faster and better for very large Excel files), use the included **`Dockerfile`** on a platform that runs containers (for example Railway, Render, Fly.io, or your own host), not Vercel’s serverless functions.

## Project layout

| File                | What it’s for                                                  |
| ------------------- | -------------------------------------------------------------- |
| `app.py`            | Main app (the dashboard)                                       |
| `app_styles.css`    | Styling (colors, layout)                                       |
| `index.html`        | Static shell for Vercel (stlite loads `app.py` in the browser) |
| `vercel.json`       | Tells Vercel this is not a Node/React framework project        |
| `Dockerfile`        | Optional: run Streamlit as a normal web server in Docker       |
| `requirements.txt`  | List of Python libraries to install                            |
| `run_dashboard.bat` | Windows shortcut to start the app                              |

## Tips

- **Spreadsheet columns:** works best when you have things like product name, date, and sales or revenue. The app tries to pick the right columns automatically; if it’s wrong, fix them under **Optional — column names, stock & cleaning** in the sidebar.
- **Change the design:** edit `app_styles.css`, save, and refresh the page in your browser.

## License

Use and modify freely for your own projects. Add a license file here if you need one for sharing publicly.
