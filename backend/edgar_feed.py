"""
SEC EDGAR real-time feed.
Polls EDGAR RSS for 8-K (material events) and Form 4 (insider transactions).
Both are public, no API key required.
"""

import asyncio
import time
import re
import json
import hashlib
from datetime import datetime, timedelta
from typing import Optional
import httpx
import xml.etree.ElementTree as ET

# ─── EDGAR endpoints ─────────────────────────────────────────────────────────

EDGAR_RSS = "https://www.sec.gov/cgi-bin/browse-edgar"
EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"
EDGAR_VIEWER = "https://www.sec.gov"

HEADERS = {
    "User-Agent": "TradeDesk/1.0 contact@tradedesk.app",
    "Accept-Encoding": "gzip",
}

# ─── State ────────────────────────────────────────────────────────────────────

_seen: set = set()
_subscribers: list = []
_recent: list = []          # keep last 50 events for replay on new connections
_MAX_RECENT = 50
_running = False
_poll_task = None

# Insider-cluster tracking: ticker -> list of recent BUY records (insider, value, ts)
# A "cluster" = ≥2 distinct insiders buying the same ticker within the window.
_insider_buys: dict = {}
CLUSTER_WINDOW_DAYS = 14
CLUSTER_MIN_INSIDERS = 2
_clusters_fired: set = set()   # ticker+date keys already alerted

# ─── RSS helpers ─────────────────────────────────────────────────────────────

async def fetch_rss(form_type: str, count: int = 40) -> list:
    """Fetch EDGAR RSS feed for a given form type."""
    params = {
        "action": "getcurrent",
        "type": form_type,
        "dateb": "",
        "owner": "include",
        "count": count,
        "search_text": "",
        "output": "atom",
    }
    async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
        try:
            r = await client.get(EDGAR_RSS, params=params)
            r.raise_for_status()
            return parse_atom(r.text, form_type)
        except Exception as e:
            print(f"[EDGAR] RSS error ({form_type}): {e}")
            return []


def parse_atom(xml_text: str, form_type: str) -> list:
    """Parse EDGAR Atom feed into list of filings."""
    try:
        root = ET.fromstring(xml_text.encode("utf-8", errors="replace"))
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)
        filings = []
        for entry in entries:
            def t(tag):
                el = entry.find(f"atom:{tag}", ns)
                return el.text.strip() if el is not None and el.text else ""

            # Link → filing index URL
            filing_url = ""
            for link in entry.findall("atom:link", ns):
                href = link.get("href", "")
                if href and "index.htm" in href:
                    filing_url = href
                    break
            if not filing_url:
                for link in entry.findall("atom:link", ns):
                    filing_url = link.get("href", "")
                    if filing_url: break

            # Title format: "8-K - COMPANY NAME (CIK) (Filer)"
            raw_title = t("title")
            company = raw_title
            filing_items = ""
            if " - " in raw_title:
                after_dash = raw_title.split(" - ", 1)[1]
                # Remove "(CIK) (Filer)" or "(CIK) (Reporting)" suffix
                company = re.sub(r'\s*\(\d+\)\s*\([^)]+\)\s*$', '', after_dash).strip()

            # Summary contains items like "Item 1.01: ..."
            raw_summary = t("summary")
            # Strip HTML entities
            clean_summary = re.sub(r'<[^>]+>', ' ', raw_summary)
            clean_summary = clean_summary.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
            items = re.findall(r'Item\s+[\d.]+:\s*([^\n<]+)', clean_summary)
            filing_items = "; ".join(items[:3])

            # Extract CIK from URL: /Archives/edgar/data/{CIK}/
            cik_m = re.search(r'/Archives/edgar/data/(\d+)/', filing_url)
            cik_no = cik_m.group(1) if cik_m else ""

            # Extract accession number from URL or id
            acc_m = re.search(r'(\d{10}-\d{2}-\d{6})', filing_url)
            acc_no = acc_m.group(1) if acc_m else ""
            if not acc_no:
                id_text = t("id")
                acc_m2 = re.search(r'accession-number=([0-9-]+)', id_text)
                acc_no = acc_m2.group(1) if acc_m2 else ""

            # Category term = actual form type (e.g. "8-K", "4")
            category = entry.find("atom:category", ns)
            actual_form = category.get("term", form_type) if category is not None else form_type

            filing_id = hashlib.md5((acc_no or t("id")).encode()).hexdigest()[:12]

            filings.append({
                "id": filing_id,
                "form_type": actual_form,
                "company": company,
                "title": filing_items or company,   # show items in title
                "raw_title": raw_title,
                "summary": clean_summary.strip()[:300],
                "url": filing_url,
                "acc_no": acc_no,
                "cik": cik_no,
                "published": t("updated") or t("published"),
            })
        return filings
    except Exception as e:
        print(f"[EDGAR] Parse error: {e}")
        return []


# ─── Form 4 parser ────────────────────────────────────────────────────────────

async def fetch_form4_detail(acc_no: str, cik: str) -> dict:
    """Fetch and parse Form 4 XML for insider transaction details."""
    if not acc_no or not cik:
        return {}
    try:
        # Construct filing index URL
        acc_clean = acc_no.replace("-", "")
        index_url = f"{EDGAR_VIEWER}/Archives/edgar/data/{cik}/{acc_clean}/{acc_no}-index.htm"
        async with httpx.AsyncClient(timeout=10, headers=HEADERS) as client:
            r = await client.get(index_url)
            # Find the .xml form4 file
            xml_match = re.search(r'href="([^"]+\.xml)"', r.text)
            if not xml_match:
                return {}
            xml_path = xml_match.group(1)
            xml_url = f"{EDGAR_VIEWER}{xml_path}" if xml_path.startswith("/") else xml_path
            rx = await client.get(xml_url)
            return parse_form4_xml(rx.text)
    except Exception:
        return {}


def parse_form4_xml(xml_text: str) -> dict:
    try:
        # SEC Form 4 XML sometimes has encoding issues — clean it up
        xml_clean = re.sub(r'&(?!(?:amp|lt|gt|apos|quot);)', '&amp;', xml_text)
        root = ET.fromstring(xml_clean)

        def find(tag):
            el = root.find(f".//{tag}")
            return el.text.strip() if el is not None and el.text else ""

        issuer = find("issuerName")
        ticker = find("issuerTradingSymbol")
        owner = find("rptOwnerName")
        is_director = find("isDirector") == "1"
        is_officer = find("isOfficer") == "1"
        officer_title = find("officerTitle")
        role = officer_title if is_officer else ("Director" if is_director else "Owner")

        transactions = []
        for tx in root.findall(".//nonDerivativeTransaction"):
            def txf(tag):
                el = tx.find(f".//{tag}")
                return el.text.strip() if el is not None and el.text else ""

            tx_type = txf("transactionCode")  # P=purchase, S=sale
            shares = txf("transactionShares")
            price = txf("transactionPricePerShare")
            date = txf("transactionDate")
            shares_after = txf("sharesOwnedFollowingTransaction")

            label = "BUY" if tx_type == "P" else "SELL" if tx_type == "S" else tx_type
            try:
                value = float(shares or 0) * float(price or 0)
            except Exception:
                value = 0

            transactions.append({
                "type": label,
                "shares": shares,
                "price": price,
                "date": date,
                "value": round(value, 2),
                "shares_after": shares_after,
            })

        return {
            "company": issuer,
            "ticker": ticker,
            "insider": owner,
            "role": role,
            "transactions": transactions,
        }
    except Exception as e:
        print(f"[EDGAR] Form4 parse error: {e}")
        return {}


# ─── 8-K classifier ──────────────────────────────────────────────────────────

EIGHTK_IMPACT = {
    "CRITICAL": [
        "merger", "acquisition", "acquired", "buyout", "going private",
        "fda approv", "fda reject", "fda clear", "nda approv",
        "bankruptcy", "chapter 11", "chapter 7", "delisted",
        "ceo resign", "ceo terminat", "chief executive resign",
        "restatement", "fraud", "sec investigation", "subpoena",
        "material weakness", "going concern",
        "special dividend", "spin-off", "spinoff", "separation",
    ],
    "HIGH": [
        "earnings", "revenue", "guidance", "forecast", "outlook",
        "quarterly results", "annual results",
        "layoffs", "restructur", "workforce reduction",
        "plant closing", "facility clos",
        "partnership", "joint venture", "licensing agreement",
        "clinical trial", "phase 2", "phase 3",
        "patent", "intellectual property",
        "stock repurchase", "buyback", "share repurchase",
        "dividend",
    ],
}

def classify_8k(filing: dict) -> tuple:
    text = (filing.get("raw_title", "") + " " + filing.get("title", "") + " " + filing.get("summary", "")).lower()
    for kw in EIGHTK_IMPACT["CRITICAL"]:
        if kw in text:
            return "CRITICAL", kw
    for kw in EIGHTK_IMPACT["HIGH"]:
        if kw in text:
            return "HIGH", kw
    return "MEDIUM", ""


# ─── SSE broadcast ────────────────────────────────────────────────────────────

def subscribe():
    q = asyncio.Queue(maxsize=100)
    # Replay recent events to new subscriber
    for event in _recent:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            break
    _subscribers.append(q)
    return q

def unsubscribe(q):
    if q in _subscribers:
        _subscribers.remove(q)

async def broadcast(event: dict):
    global _recent
    # Store for replay
    _recent.append(event)
    if len(_recent) > _MAX_RECENT:
        _recent = _recent[-_MAX_RECENT:]
    # Push to live subscribers
    dead = []
    for q in _subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _subscribers.remove(q)

    # Publish to central event bus for agent processing
    try:
        from event_bus import publish as bus_publish
        data = event.get("data", {})
        type_ = event.get("type", "edgar")
        tickers = []
        if data.get("ticker"):
            tickers = [data["ticker"]]
        await bus_publish(
            source="edgar",
            type=type_,
            data=data,
            tickers=tickers,
            title=(data.get("title") or data.get("company") or "")[:300],
            impact=data.get("impact", "MEDIUM"),
        )
    except Exception as e:
        print(f"[EDGAR] Bus publish error: {e}")


# ─── Insider cluster detection (Strategy B) ───────────────────────────────────

async def _track_insider_buy(detail: dict, total_value: float):
    """Record an insider BUY; fire a cluster event when ≥2 distinct insiders buy."""
    ticker = detail.get("ticker", "").upper()
    insider = detail.get("insider", "")
    if not ticker or not insider:
        return

    now = time.time()
    window = CLUSTER_WINDOW_DAYS * 86400
    buys = _insider_buys.setdefault(ticker, [])
    buys.append({"insider": insider, "value": total_value, "ts": now,
                 "role": detail.get("role", "")})
    # Prune old
    _insider_buys[ticker] = [b for b in buys if now - b["ts"] <= window]
    buys = _insider_buys[ticker]

    distinct = {b["insider"] for b in buys}
    if len(distinct) < CLUSTER_MIN_INSIDERS:
        return

    # Fire once per ticker per day
    key = f"{ticker}:{datetime.utcnow().strftime('%Y-%m-%d')}"
    if key in _clusters_fired:
        return
    _clusters_fired.add(key)

    total_cluster_value = sum(b["value"] for b in buys)

    # Qualify as a small-cap edge candidate
    try:
        from universe import qualify_smallcap
        q = qualify_smallcap(ticker)
    except Exception:
        q = {"qualified": False, "reason": "screen error"}

    impact = "CRITICAL" if q.get("qualified") else "HIGH"
    cluster_data = {
        "ticker": ticker,
        "company": detail.get("company", ""),
        "distinct_insiders": len(distinct),
        "insiders": list(distinct),
        "total_value": round(total_cluster_value, 2),
        "window_days": CLUSTER_WINDOW_DAYS,
        "smallcap_qualified": q.get("qualified", False),
        "screen": q,
        "label": "Insider Cluster Buy",
    }

    # Publish to the central event bus as an insider_cluster event (→ Strategy B)
    try:
        from event_bus import publish as bus_publish
        await bus_publish(
            source="edgar_cluster",
            type="insider_cluster",
            data=cluster_data,
            tickers=[ticker],
            title=f"🟢 INSIDER CLUSTER: {len(distinct)} insiders bought {ticker} (${total_cluster_value/1000:.0f}K) {'· small-cap ✓' if q.get('qualified') else ''}",
            impact=impact,
        )
        print(f"[EDGAR] 🟢 CLUSTER: {ticker} — {len(distinct)} insiders, ${total_cluster_value:,.0f}, smallcap={q.get('qualified')}")
    except Exception as e:
        print(f"[EDGAR] Cluster publish error: {e}")


# ─── Polling loop ─────────────────────────────────────────────────────────────

async def _poll_loop(interval: int = 60):
    global _running
    _running = True
    print(f"[EDGAR] Feed started — polling every {interval}s")

    while _running:
        try:
            # Fetch 8-K and Form 4 feeds in parallel
            eightk, form4 = await asyncio.gather(
                fetch_rss("8-K", count=40),
                fetch_rss("4", count=40),
            )

            # Process 8-K filings
            for filing in eightk:
                if filing["id"] in _seen:
                    continue
                _seen.add(filing["id"])
                impact, keyword = classify_8k(filing)

                await broadcast({
                    "type": "edgar_8k",
                    "data": {
                        **filing,
                        "impact": impact,
                        "keyword": keyword,
                        "label": "8-K Filing",
                    },
                    "ts": time.time(),
                })
                if impact in ("CRITICAL", "HIGH"):
                    print(f"[EDGAR] [{impact}] 8-K: {filing['company']} — {filing['title'][:60]}")

            # Process Form 4 filings
            for filing in form4:
                if filing["id"] in _seen:
                    continue
                _seen.add(filing["id"])

                # Parse insider transaction details
                detail = await fetch_form4_detail(filing["acc_no"], filing["cik"])
                txs = detail.get("transactions", [])

                # Only alert on purchases (more bullish signal)
                buys = [t for t in txs if t["type"] == "BUY"]
                sells = [t for t in txs if t["type"] == "SELL"]
                total_value = sum(float(t.get("value", 0)) for t in txs)

                # Only surface large transactions ($100K+)
                if total_value < 100_000 and not buys:
                    continue

                impact = "HIGH" if buys else "MEDIUM"
                if total_value > 1_000_000:
                    impact = "CRITICAL"

                await broadcast({
                    "type": "edgar_form4",
                    "data": {
                        **filing,
                        "impact": impact,
                        "label": "Insider Transaction",
                        "insider": detail.get("insider", ""),
                        "ticker": detail.get("ticker", ""),
                        "role": detail.get("role", ""),
                        "transactions": txs,
                        "total_value": round(total_value, 2),
                        "buys": len(buys),
                        "sells": len(sells),
                        "company": detail.get("company", filing["company"]),
                    },
                    "ts": time.time(),
                })
                if impact in ("CRITICAL", "HIGH"):
                    action = f"{len(buys)} buys" if buys else f"{len(sells)} sells"
                    print(f"[EDGAR] [{impact}] Form 4: {detail.get('company','')} — {detail.get('insider','')} ({action}, ${total_value:,.0f})")

                # ── Insider-cluster detection (Strategy B signal) ──
                if buys and detail.get("ticker"):
                    await _track_insider_buy(detail, total_value)

        except Exception as e:
            print(f"[EDGAR] Poll error: {e}")

        await asyncio.sleep(interval)


def start_feed(interval: int = 60):
    global _poll_task
    loop = asyncio.get_event_loop()
    _poll_task = loop.create_task(_poll_loop(interval))
    return _poll_task

def stop_feed():
    global _running, _poll_task
    _running = False
    if _poll_task:
        _poll_task.cancel()


# ─── On-demand filing reader ──────────────────────────────────────────────────

async def fetch_filing_text(acc_no: str, cik: str, max_chars: int = 20000) -> str:
    """Fetch the full text of an SEC filing for AI summarization."""
    if not acc_no or not cik:
        return ""
    try:
        acc_clean = acc_no.replace("-", "")
        index_url = f"{EDGAR_VIEWER}/Archives/edgar/data/{cik}/{acc_clean}/{acc_no}-index.htm"
        async with httpx.AsyncClient(timeout=20, headers=HEADERS) as client:
            r = await client.get(index_url)
            # Find the main document (htm/html)
            matches = re.findall(r'href="(/Archives/edgar/data/[^"]+\.htm)"', r.text, re.IGNORECASE)
            if not matches:
                return ""
            # Take the first non-index file
            doc_url = next((m for m in matches if "index" not in m.lower()), matches[0])
            rd = await client.get(f"{EDGAR_VIEWER}{doc_url}")
            # Strip HTML tags
            text = re.sub(r'<[^>]+>', ' ', rd.text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:max_chars]
    except Exception as e:
        print(f"[EDGAR] Filing text fetch error: {e}")
        return ""


async def search_filings(ticker: str, form_type: str = "8-K", limit: int = 5) -> list:
    """Search EDGAR for recent filings by ticker."""
    params = {
        "q": f'"{ticker}"',
        "forms": form_type,
        "dateRange": "custom",
        "startdt": (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d"),
        "enddt": datetime.now().strftime("%Y-%m-%d"),
    }
    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
            r = await client.get(EDGAR_SEARCH, params=params)
            data = r.json()
            hits = data.get("hits", {}).get("hits", [])
            results = []
            for h in hits[:limit]:
                src = h.get("_source", {})
                adsh = src.get("adsh", "")               # accession number e.g. 0001045810-23-000014
                ciks = src.get("ciks", [""])
                cik = ciks[0].lstrip("0") if ciks else ""
                names = src.get("display_names", [])
                company = names[0].split("(")[0].strip() if names else ticker
                filed = src.get("file_date", src.get("period_ending", ""))
                acc_fmt = adsh  # already formatted with dashes
                sec_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh.replace('-','')}/{adsh}-index.htm" if adsh and cik else ""
                results.append({
                    "acc_no": acc_fmt,
                    "cik": cik,
                    "form_type": src.get("form", form_type),
                    "company": company,
                    "filed": filed,
                    "url": sec_url or f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form_type}&dateb=&owner=include&count=10",
                    "description": src.get("description", ""),
                })
            return results
    except Exception as e:
        print(f"[EDGAR] Search error: {e}")
        return []
