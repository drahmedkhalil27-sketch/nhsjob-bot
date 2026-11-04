#!/usr/bin/env python3
"""
NHS Jobs -> Telegram alert bot.

Searches jobs.nhs.uk (England & Wales), apply.jobs.scot.nhs.uk (Scotland) and
jobs.hscni.net (Northern Ireland) for junior medical posts in General Medicine,
Geriatrics, Acute Medicine, Gastroenterology/Hepatology, Nephrology, Stroke,
Neurology, Haematology, Endocrinology/Diabetes and Respiratory medicine,
opens each new advert, checks the person specification and sends
a Telegram message for every new job that does NOT list as *essential*:
  - MRCP
  - previous NHS / UK experience
and (by default) does not say visa sponsorship is unavailable.

Usage:
  python nhs_job_bot.py            # one run (used by GitHub Actions)
  python nhs_job_bot.py --loop 180 # run forever, every 180 s (on your own PC)
  python nhs_job_bot.py --dry-run  # print instead of sending to Telegram

Env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

# --------------------------------------------------------------------------
# SETTINGS — edit these to change what the bot looks for
# --------------------------------------------------------------------------
# Which websites to search (set False to switch one off)
SOURCES = {
    "england_wales": True,     # jobs.nhs.uk
    "scotland": True,          # apply.jobs.scot.nhs.uk
    "northern_ireland": True,  # jobs.hscni.net
}

BASE = "https://www.jobs.nhs.uk"
SEARCH_URL = BASE + "/candidate/search/results?keyword={kw}&sort=publicationDateDesc&language=en&page={page}"
PAGES_PER_SEARCH = 2

SCOT_BASE = "https://apply.jobs.scot.nhs.uk"
SCOT_LIST_URLS = [                       # all vacancies list + keyword variants
    SCOT_BASE + "/Home/Job",
    SCOT_BASE + "/Home/Job?Keyword={kw}",
    SCOT_BASE + "/Home/Job?SearchText={kw}",
]
NI_BASE = "https://jobs.hscni.net"
NI_LIST_URLS = [
    NI_BASE + "/Search?SearchBandID=44",   # medical & dental listing
    NI_BASE + "/Search?SearchTerm={kw}",
    NI_BASE + "/Search?Keywords={kw}",
]
# Keyword searches used on the Scotland / NI sites (smaller sites, fewer searches)
SMALL_SITE_KEYWORDS = ["clinical fellow", "medicine", "trust grade", "FY2", "ST1"]

# Each keyword = one search on NHS Jobs (newest first).
SEARCH_KEYWORDS = [
    "clinical fellow medicine",
    "junior clinical fellow",
    "trust grade",
    "trust doctor",
    "SHO medicine",
    "FY2",
    "ST1 medicine",
    "ST2 medicine",
    "general medicine",
    "general internal medicine",
    "geriatric",
    "care of the elderly",
    "acute medicine",
    "gastroenterology",
    "hepatology",
    "nephrology",
    "renal medicine",
    "stroke",
    "neurology",
    "haematology",
    "endocrinology",
    "diabetes",
    "respiratory medicine",
]

# Title must contain one of these (the grade you want)...
GRADE_TERMS = [
    r"\bjunior clinical fellow\b", r"\bclinical fellow\b", r"\bresearch fellow\b",
    r"\btrust grade\b", r"\btrust doctor\b", r"\btrust fellow\b",
    r"\bfy\s?2\b", r"\bf2\b", r"\bfoundation\b", r"\bst\s?[12]\b", r"\bct\s?[12]\b",
    r"\bst1\s?[-/]\s?st2\b", r"\bsho\b", r"\bsenior house officer\b",
    r"\bclinical teaching fellow\b", r"\bjunior doctor\b", r"\bmt0?[1-3]\b",
    r"\blocally employed doctor\b", r"\bimt\s?[12]\b", r"\bfho\s?[12]\b",
]
# The specialties you want. One of these in the title = match.
TARGET_SPECIALTY_TERMS = [
    r"\bgeneral (internal )?medicine\b", r"\bgim\b", r"\binternal medicine\b",
    r"\bgeriatric", r"\belderly\b", r"\bolder (people|person|adult)", r"\bcote\b", r"\bfrailty\b",
    r"\bacute (and general )?medic", r"\bamu\b", r"\bsdec\b", r"\bacute (&|and) general\b",
    r"\bgastro", r"\bhepatolog", r"\bliver\b", r"\bgi\b", r"\bendoscop",
    r"\bnephrolog", r"\brenal\b", r"\bkidney\b",
    r"\bstroke\b", r"\bneurolog", r"\bhaematolog", r"\bhematolog",
    r"\bendocrin", r"\bdiabet", r"\brespiratory\b", r"\bchest medicine\b", r"\bthoracic medicine\b",
]
# Generic words: count only if the title names no other specialty
GENERIC_SPECIALTY_TERMS = [r"\bmedicine\b", r"\bmedical\b"]
# Other specialties: if one of these is in the title and none of yours, skip it
OTHER_SPECIALTY_TERMS = [
    r"\bpalliative\b", r"\bintensive\b", r"\bcritical care\b", r"\bicu\b", r"\bitu\b",
    r"\bsexual health\b", r"\bgenito", r"\bgum\b", r"\bdermatolog", r"\bophthalm",
    r"\boncolog", r"\bcardiolog", r"\brheumatolog", r"\binfectious\b", r"\bmicrobiolog",
    r"\bsports\b", r"\brehabilitation\b", r"\boccupational\b", r"\bpublic health\b",
    r"\bgeneral practice\b", r"\bgp\b", r"\bpathology\b", r"\bgenetic", r"\bimmunolog",
    r"\ballergy\b", r"\bpharmacolog", r"\bent\b", r"\bplastic", r"\burolog",
    r"\bneonat", r"\bhospice\b",
]
# Title must NOT contain any of these (too senior / other professions / other specialties).
EXCLUDE_TITLE_TERMS = [
    r"\bsenior clinical fellow\b", r"\bsenior fellow\b", r"\bregistrar\b", r"\bspr\b",
    r"\bst\s?[3-9]\b", r"\bst3\+", r"\bconsultant\b", r"\bspecialty doctor\b",
    r"\bspecialist\b(?!\s+interest)", r"\bpost[- ]?cct\b", r"\bcesr\b", r"\bportfolio pathway\b",
    r"\bnurse\b", r"\bnursing\b", r"\bpharmac", r"\bphysiotherap", r"\bdietit",
    r"\bassociate\b", r"\bphysician associate\b", r"\badministrat", r"\bsecretar",
    r"\bsurg", r"\borthopaedic", r"\banaesth", r"\bpaediatric", r"\bobstetric",
    r"\bpsychiatr", r"\bmental health\b", r"\bradiolog", r"\bemergency\b",
    r"\bdental\b", r"\bdentist", r"\bveterinar", r"\bhealthcare assistant\b",
    r"\bpractitioner\b", r"\btechnician\b", r"\bscientist\b", r"\bmanager\b",
    r"\bemployees only\b", r"\binternal applicants\b", r"\bhsc employees\b",
    r"\bneurosurg", r"\bclinical oncolog",
]

# Exclude jobs whose advert says visa sponsorship is NOT available
# (you will need a Health and Care Worker visa). Set False to keep them.
EXCLUDE_NO_SPONSORSHIP = True

STATE_FILE = Path(__file__).with_name("seen.json")
MAX_ALERTS_PER_RUN = 30
REQUEST_PAUSE_S = 1.5
HEADERS = {
    "User-Agent": "Mozilla/5.0 (personal job-alert script; checks every few minutes)",
    "Accept-Language": "en-GB,en;q=0.9",
}

# --------------------------------------------------------------------------
# Requirement detection
# --------------------------------------------------------------------------
MRCP_RE = re.compile(r"\bm\.?r\.?c\.?p\b|membership of the royal college of physicians", re.I)
NHS_EXP_RE = re.compile(
    r"(nhs|hsc|uk|united kingdom|british)[\s-]+(based\s+)?(clinical\s+|hospital\s+|medical\s+|working\s+)?experience"
    r"|experience\s+(of\s+)?(working\s+)?(in|within|of)\s+(the\s+)?(nhs|hsc|uk|united kingdom)"
    r"|(previous|prior|recent)\s+(nhs|hsc|uk)\b"
    r"|(months?|years?)\s+(of\s+)?(nhs|hsc|uk)\b",
    re.I,
)
NEGATION_RE = re.compile(r"\bnot\s+(essential|required|necessary|mandatory)\b|\bno\s+(nhs|uk)\s+experience\b"
                         r"|\bwithout\s+(nhs|uk)\s+experience\b|\bnot\s+a\s+requirement\b", re.I)
DESIRABLE_INLINE_RE = re.compile(r"\b(desirable|preferable|preferred|advantageous|would be an advantage|ideally)\b", re.I)
ESSENTIAL_INLINE_RE = re.compile(r"\b(essential|must have|must hold|required|mandatory|is a requirement)\b", re.I)

NO_SPONSOR_RE = re.compile(
    r"(certificate of sponsorship|visa sponsorship|sponsorship|sponsor)[^.]{0,80}?"
    r"\b(cannot|can not|can't|unable|not be (offered|provided|supported|available)|is not (available|offered|provided|possible)|not available|not offered|not possible|will not)\b"
    r"|\b(cannot|can not|can't|unable to|do not|does not|will not|won't|are not able to)\b[^.]{0,40}?\b(sponsor|offer sponsorship|provide sponsorship|support sponsorship|support visa)",
    re.I,
)
YES_SPONSOR_RE = re.compile(
    r"(sponsorship|skilled worker)[^.]{0,100}?\b(welcome|available|considered|supported|can be offered|may be offered)\b",
    re.I,
)

SECTION_ESSENTIAL = re.compile(r"^\s*essential(\s+criteria)?\s*:?\s*$", re.I)
SECTION_DESIRABLE = re.compile(r"^\s*desirable(\s+criteria)?\s*:?\s*$", re.I)


@dataclass
class Requirement:
    status: str          # "essential" | "desirable" | "not_required" | "not_mentioned"
    evidence: str = ""


@dataclass
class Job:
    job_id: str
    title: str
    url: str
    employer: str = ""
    location: str = ""
    salary: str = ""
    closing: str = ""
    summary: str = ""
    mrcp: Requirement = field(default_factory=lambda: Requirement("not_mentioned"))
    nhs_exp: Requirement = field(default_factory=lambda: Requirement("not_mentioned"))
    sponsorship: str = "unknown"   # "no" | "yes" | "unknown"
    spec_found: bool = False
    source: str = "england_wales"


def _lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines() if ln.strip()]


def classify_requirement(lines: list[str], pattern: re.Pattern) -> Requirement:
    """Walk the advert text; track whether we are under an Essential or a Desirable
    heading, and classify the first strongest mention of `pattern`."""
    mode = None          # None | "essential" | "desirable"
    best: Requirement = Requirement("not_mentioned")
    rank = {"not_mentioned": 0, "not_required": 1, "desirable": 2, "essential": 3}
    for ln in lines:
        if SECTION_ESSENTIAL.match(ln):
            mode = "essential"
            continue
        if SECTION_DESIRABLE.match(ln):
            mode = "desirable"
            continue
        if re.match(r"^\s*(qualifications|experience|skills|knowledge|other|personal qualities|"
                    r"clinical skills|communication|personal attributes|eligibility|"
                    r"additional requirements|training|values|research|teaching)\b.{0,30}$", ln, re.I):
            # new criterion group heading: keep mode until next Essential/Desirable heading
            pass
        if not pattern.search(ln):
            continue
        if NEGATION_RE.search(ln):
            status = "not_required"
        elif DESIRABLE_INLINE_RE.search(ln) and not re.search(r"\bessential\b", ln, re.I):
            status = "desirable"
        elif re.search(r"\bor equivalent\b|\bworking towards\b|\bin progress\b", ln, re.I) and mode != "essential":
            status = "desirable"
        elif mode == "essential" or ESSENTIAL_INLINE_RE.search(ln):
            status = "essential"
        elif mode == "desirable":
            status = "desirable"
        else:
            status = "desirable"   # mentioned but not marked essential
        if rank[status] > rank[best.status]:
            best = Requirement(status, ln[:160])
    return best


def detect_sponsorship(text: str) -> str:
    if NO_SPONSOR_RE.search(text):
        return "no"
    if YES_SPONSOR_RE.search(text):
        return "yes"
    return "unknown"


# --------------------------------------------------------------------------
# Scraping
# --------------------------------------------------------------------------
def get(session: requests.Session, url: str) -> str:
    for attempt in range(3):
        try:
            r = session.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                return r.text
            if r.status_code in (429, 503):
                time.sleep(10 * (attempt + 1))
                continue
            r.raise_for_status()
        except requests.RequestException as e:
            if attempt == 2:
                raise
            print(f"  retry {url}: {e}", file=sys.stderr)
            time.sleep(5)
    raise RuntimeError(f"failed to fetch {url}")


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el else ""


def _field(container, *names) -> str:
    """Find a field inside a search-result card by data-test attribute or class name fragments."""
    for n in names:
        el = container.find(attrs={"data-test": re.compile(n, re.I)})
        if el:
            return _text(el)
    for n in names:
        el = container.find(class_=re.compile(n, re.I))
        if el:
            return _text(el)
    return ""


def parse_search_results(page_html: str) -> list[Job]:
    soup = BeautifulSoup(page_html, "html.parser")
    jobs: dict[str, Job] = {}
    for a in soup.find_all("a", href=re.compile(r"/candidate/jobadvert/")):
        href = a["href"]
        m = re.search(r"/candidate/jobadvert/([A-Za-z0-9\-]+)", href)
        if not m:
            continue
        job_id = m.group(1)
        if job_id in jobs:
            continue
        title = _text(a)
        if not title:
            continue
        card = a.find_parent(["li", "article"]) or a.find_parent("div") or a.parent
        employer = _field(card, "organisation", "employer")
        location = ""
        loc_div = card.find(class_=re.compile("location", re.I))
        if loc_div and loc_div.name != "h3":
            location = _text(loc_div)
        if not employer:
            h3 = card.find("h3")
            employer = _text(h3)
            if location and employer.endswith(location):
                employer = employer[: -len(location)].strip()
        if not location:
            location = _field(card, "location")
        salary = _field(card, "salary")
        closing = _field(card, "closing")
        url = urljoin(BASE, "/candidate/jobadvert/" + job_id)
        jobs[job_id] = Job(job_id=job_id, title=title, url=url, employer=employer,
                           location=location, salary=salary, closing=closing,
                           summary=_text(card)[:600])
    return list(jobs.values())


def _any(patterns, text) -> bool:
    return any(re.search(p, text) for p in patterns)


def parse_scotland_list(page_html: str) -> list[Job]:
    """apply.jobs.scot.nhs.uk (Jobtrain): job links look like /Job/JobDetail?JobId=123."""
    soup = BeautifulSoup(page_html, "html.parser")
    jobs: dict[str, Job] = {}
    for a in soup.find_all("a", href=re.compile(r"JobDetail\?jobid=\d+", re.I)):
        jid = re.search(r"jobid=(\d+)", a["href"], re.I).group(1)
        key = "sco:" + jid
        card = a.find_parent(["li", "article", "tr"]) or a.find_parent("div") or a.parent
        title = _text(a)
        if not title or re.fullmatch(r"(view|more|details|apply|read more|view job).*", title, re.I):
            h = card.find(["h2", "h3", "h4"])
            title = _text(h)
        if not title:
            continue
        if key in jobs and len(jobs[key].title) >= len(title):
            continue
        jobs[key] = Job(job_id=key, title=title, source="scotland",
                        url=f"{SCOT_BASE}/Job/JobDetail?JobId={jid}", summary=_text(card)[:600])
    return list(jobs.values())


def parse_ni_list(page_html: str) -> list[Job]:
    """jobs.hscni.net: job links look like /Job/40815/slug or /Search/Details/47830."""
    soup = BeautifulSoup(page_html, "html.parser")
    jobs: dict[str, Job] = {}
    for a in soup.find_all("a", href=re.compile(r"(/Job/\d+|/Search/Details/\d+)", re.I)):
        m = re.search(r"(?:/Job/|/Search/Details/)(\d+)", a["href"], re.I)
        jid = m.group(1)
        key = "ni:" + jid
        card = a.find_parent(["li", "article", "tr"]) or a.find_parent("div") or a.parent
        title = clean_ni_title(_text(a))
        if not title or re.fullmatch(r"(view|more|details|apply|read more).*", title, re.I):
            title = clean_ni_title(_text(card.find(["h2", "h3", "h4"])))
        if not title:
            continue
        if key in jobs and len(jobs[key].title) >= len(title):
            continue
        jobs[key] = Job(job_id=key, title=title, source="northern_ireland",
                        url=urljoin(NI_BASE, a["href"]), summary=_text(card)[:600])
    return list(jobs.values())


def clean_ni_title(title: str) -> str:
    title = re.sub(r"\s*ref:\s*\S*\s*$", "", title, flags=re.I)      # "... ref:55768733"
    title = re.sub(r"^\d{6,}[\s_-]*", "", title)                       # "55018049 Clinical Fellow..."
    return title.strip()


def title_matches(job: Job) -> bool:
    t = job.title.lower()
    if _any(EXCLUDE_TITLE_TERMS, t):
        return False
    if not _any(GRADE_TERMS, t):
        return False
    if _any(TARGET_SPECIALTY_TERMS, t):
        return True
    if _any(OTHER_SPECIALTY_TERMS, t):
        return False
    if _any(GENERIC_SPECIALTY_TERMS, t):      # "Clinical Fellow in Medicine"
        return True
    # Title names a different specialty ("Clinical Fellow in Dermatology") -> no
    if re.search(r"\b(in|-|–)\s+[a-z]", t) and not re.search(r"\b(fellow|doctor|grade)\s*$", t):
        return False
    # Generic title ("Junior Clinical Fellow"): look at the card text instead,
    # after removing boilerplate that mentions "medical" for every doctor job.
    summary = job.summary.lower()
    summary = re.sub(r"medical\s*(&|and)\s*dental|foundation trust|nhs medical", " ", summary)
    if _any(TARGET_SPECIALTY_TERMS, summary):
        return True
    return _any(GENERIC_SPECIALTY_TERMS, summary) and not _any(OTHER_SPECIALTY_TERMS, summary)


LABEL_FIELDS = {
    "salary": r"salary",
    "closing": r"(?:job )?closing date|closes",
    "location": r"location|base",
    "employer": r"employer(?: \(nhs board\))?|organisation|trust",
}


def _label_value(lines: list[str], label_re: str) -> str:
    """Find 'Label: value' or a 'Label:' line followed by the value line."""
    for i, ln in enumerate(lines):
        m = re.match(rf"^\s*(?:{label_re})\s*:\s*(?P<val>.*)$", ln, re.I)
        if m:
            val = m.group("val").strip()
            if not val and i + 1 < len(lines):
                val = lines[i + 1].strip()
            if val:
                return val[:120]
    return ""


EXTERNAL_DETAIL_RE = re.compile(r"healthdaq\.com|hscrecruit\.com|jobs\.hscni\.net/Job/Detail", re.I)


def external_details_link(advert_html: str) -> str:
    """NI adverts often send you to an external page (HealthDaq) with the full job details."""
    soup = BeautifulSoup(advert_html, "html.parser")
    a = soup.find("a", href=EXTERNAL_DETAIL_RE)
    return a["href"] if a else ""


def analyse_advert(job: Job, advert_html: str) -> Job:
    soup = BeautifulSoup(advert_html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    full_text = soup.get_text("\n")
    lines = _lines(full_text)

    # Restrict requirement analysis to the person specification when we can find it
    spec_start = next((i for i, ln in enumerate(lines)
                       if re.search(r"person specification", ln, re.I)), None)
    if spec_start is not None:
        job.spec_found = True
        spec_end = next((i for i in range(spec_start + 1, len(lines))
                         if re.search(r"^(employer details|employer certification|documents to download|"
                                      r"disclosure and barring|apply online|contact details)\b",
                                      lines[i], re.I)), len(lines))
        spec_lines = lines[spec_start:spec_end]
    else:
        spec_lines = lines

    job.mrcp = classify_requirement(spec_lines, MRCP_RE)
    job.nhs_exp = classify_requirement(spec_lines, NHS_EXP_RE)

    # Phrases in the main body like "MRCP is essential" also count
    for req_name, pattern in (("mrcp", MRCP_RE), ("nhs_exp", NHS_EXP_RE)):
        body_req = classify_requirement([ln for ln in lines if ESSENTIAL_INLINE_RE.search(ln) or NEGATION_RE.search(ln)], pattern)
        cur = getattr(job, req_name)
        if body_req.status == "essential" and cur.status != "essential":
            setattr(job, req_name, body_req)

    job.sponsorship = detect_sponsorship(" ".join(lines))

    if not job.employer:
        h2 = soup.find(attrs={"data-test": re.compile("employer-name", re.I)})
        job.employer = _text(h2)
    if not job.employer:
        m = re.search(r"find out more about (the )?(.+?(trust|board|hospice))", full_text, re.I)
        if m:
            job.employer = m.group(2).strip()
    if not job.closing:
        m = re.search(r"closing date is ([0-9]{1,2} \w+ [0-9]{4})", full_text, re.I)
        if m:
            job.closing = m.group(1)
    if not job.salary:
        sal = soup.find(attrs={"data-test": re.compile("salary", re.I)})
        job.salary = _text(sal)
    # Scotland / NI pages: "Salary: ...", "Job closing date: ...", "Location: ..."
    for attr, label in LABEL_FIELDS.items():
        if not getattr(job, attr):
            setattr(job, attr, _label_value(lines, label))
    return job


def is_acceptable(job: Job) -> bool:
    if job.mrcp.status == "essential":
        return False
    if job.nhs_exp.status == "essential":
        return False
    if EXCLUDE_NO_SPONSORSHIP and job.sponsorship == "no":
        return False
    return True


# --------------------------------------------------------------------------
# Telegram
# --------------------------------------------------------------------------
LABELS = {
    "not_mentioned": "مش مذكورة ✅",
    "not_required": "مش مطلوبة ✅",
    "desirable": "Desirable بس ✅",
    "essential": "Essential ❌",
}
SPONSOR_LABEL = {"yes": "متاحة ✅", "unknown": "مش مذكورة ❓", "no": "مش متاحة ❌"}


SOURCE_LABEL = {
    "england_wales": "إنجلترا/ويلز · NHS Jobs",
    "scotland": "اسكتلندا · NHS Scotland",
    "northern_ireland": "أيرلندا الشمالية · HSC NI",
}


def format_message(job: Job) -> str:
    e = html.escape
    parts = [f"🩺 <b>{e(job.title)}</b>", f"🗺️ {SOURCE_LABEL.get(job.source, job.source)}"]
    if job.employer:
        parts.append(f"🏥 {e(job.employer)}")
    if job.location:
        parts.append(f"📍 {e(job.location)}")
    if job.salary:
        parts.append(f"💷 {e(job.salary)}")
    if job.closing:
        parts.append(f"⏳ {e(job.closing)}")
    parts.append("")
    parts.append(f"MRCP: {LABELS[job.mrcp.status]}")
    parts.append(f"خبرة NHS: {LABELS[job.nhs_exp.status]}")
    parts.append(f"الفيزا/Sponsorship: {SPONSOR_LABEL[job.sponsorship]}")
    if not job.spec_found:
        parts.append("⚠️ الـPerson specification غالبًا في ملف مرفق، راجعه قبل ما تقدم")
    parts.append("")
    parts.append(f'<a href="{e(job.url)}">افتح الإعلان وقدّم</a>')
    return "\n".join(parts)


def send_telegram(text: str, dry_run: bool) -> None:
    if dry_run:
        print("-" * 60)
        print(text)
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": "true"},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"Telegram error {r.status_code}: {r.text}", file=sys.stderr)


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"seen": [], "empty_runs": 0}


def save_state(state: dict) -> None:
    state["seen"] = state["seen"][-5000:]
    STATE_FILE.write_text(json.dumps(state, indent=0))


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def _collect(session, urls: list[str], parser) -> dict[str, Job]:
    found: dict[str, Job] = {}
    for url in urls:
        try:
            results = parser(get(session, url))
        except Exception as e:  # keep going with other searches
            print(f"search failed [{url}]: {e}", file=sys.stderr)
            results = []
        for j in results:
            found.setdefault(j.job_id, j)
        time.sleep(REQUEST_PAUSE_S)
    return found


def collect_england_wales(session) -> dict[str, Job]:
    found: dict[str, Job] = {}
    for kw in SEARCH_KEYWORDS:
        for page in range(1, PAGES_PER_SEARCH + 1):
            got = _collect(session, [SEARCH_URL.format(kw=quote_plus(kw), page=page)], parse_search_results)
            for k, j in got.items():
                found.setdefault(k, j)
            if not got:
                break
    return found


def _expand(templates: list[str]) -> list[str]:
    urls = []
    for t in templates:
        if "{kw}" in t:
            urls += [t.format(kw=quote_plus(kw)) for kw in SMALL_SITE_KEYWORDS]
        else:
            urls.append(t)
    return urls


def collect_scotland(session) -> dict[str, Job]:
    return _collect(session, _expand(SCOT_LIST_URLS), parse_scotland_list)


def collect_northern_ireland(session) -> dict[str, Job]:
    return _collect(session, _expand(NI_LIST_URLS), parse_ni_list)


COLLECTORS = {
    "england_wales": collect_england_wales,
    "scotland": collect_scotland,
    "northern_ireland": collect_northern_ireland,
}
SOURCE_NAME = {"england_wales": "NHS Jobs (إنجلترا/ويلز)", "scotland": "NHS Scotland",
               "northern_ireland": "HSC أيرلندا الشمالية"}


def run_once(dry_run: bool = False) -> int:
    state = load_state()
    seen = set(state["seen"])
    first_run = not seen
    empty_runs = state.setdefault("empty_runs_by_source", {})
    session = requests.Session()

    found: dict[str, Job] = {}
    for source, enabled in SOURCES.items():
        if not enabled:
            continue
        got = COLLECTORS[source](session)
        print(f"{source}: {len(got)} adverts found")
        # Health check: if a site's layout changes we would silently find nothing
        if got:
            empty_runs[source] = 0
        else:
            empty_runs[source] = empty_runs.get(source, 0) + 1
            if empty_runs[source] == 3:
                send_telegram(f"⚠️ البوت مش لاقي أي نتايج من {SOURCE_NAME[source]} لـ٣ مرات ورا بعض. "
                              "غالبًا شكل الموقع اتغير والجزء ده محتاج تحديث. "
                              "باقي المواقع شغالة عادي.", dry_run)
        found.update(got)

    if not found:
        save_state(state)
        return 0

    new_jobs = [j for jid, j in found.items() if jid not in seen]
    candidates = [j for j in new_jobs if title_matches(j)]
    print(f"{len(new_jobs)} new, {len(candidates)} match grade/specialty")

    sent = 0
    processed = 0
    for job in candidates:
        if sent >= MAX_ALERTS_PER_RUN:
            break
        processed += 1
        try:
            page = get(session, job.url)
            ext = external_details_link(page)
            if ext:                         # NI: full details live on an external page
                try:
                    page += get(session, ext)
                except Exception as e:
                    print(f"external details failed {ext}: {e}", file=sys.stderr)
            analyse_advert(job, page)
        except Exception as e:
            print(f"advert failed {job.url}: {e}", file=sys.stderr)
            job.spec_found = False
        time.sleep(REQUEST_PAUSE_S)
        if is_acceptable(job):
            send_telegram(format_message(job), dry_run)
            sent += 1
        else:
            print(f"  skipped (requirements): {job.title} | MRCP={job.mrcp.status} "
                  f"NHS={job.nhs_exp.status} sponsor={job.sponsorship}")

    # mark everything we looked at as seen (including non-matching titles),
    # except matching jobs we had no time to check this run (checked next run)
    unchecked = {j.job_id for j in candidates[processed:]}
    for jid in found:
        if jid not in seen and jid not in unchecked:
            state["seen"].append(jid)
            seen.add(jid)

    if first_run:
        send_telegram(f"✅ البوت اشتغل. بيراقب إنجلترا وويلز واسكتلندا وأيرلندا الشمالية، وبعتلك {sent} وظيفة مفتوحة حاليًا "
                      f"مطابقة لشروطك. من هنا ورايح هيبعتلك الجديد بس.", dry_run)

    save_state(state)
    print(f"sent {sent} alerts")
    return sent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=0, help="seconds between runs (0 = run once)")
    ap.add_argument("--dry-run", action="store_true", help="print alerts instead of sending")
    args = ap.parse_args()
    if args.loop:
        interval = max(args.loop, 120)
        while True:
            try:
                run_once(args.dry_run)
            except Exception as e:
                print(f"run failed: {e}", file=sys.stderr)
            time.sleep(interval)
    else:
        run_once(args.dry_run)


if __name__ == "__main__":
    main()
