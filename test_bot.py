"""Offline tests for the filters, using sample pages in NHS Jobs' layout."""
import nhs_job_bot as b

SEARCH_HTML = """
<ul class="nhsuk-list search-results">
 <li class="nhsuk-list-panel search-result" data-test="search-result">
  <h2><a data-test="search-result-job-title" href="/candidate/jobadvert/C9123-26-0001?keyword=x">Junior Clinical Fellow in General Medicine</a></h2>
  <h3 data-test="search-result-location">Royal Example Hospital NHS Foundation Trust <div class="location-font-size">Hull, HU3 2JZ</div></h3>
  <li data-test="search-result-salary">Salary: £49,909 a year</li>
  <li data-test="search-result-closingDate">Closing date: 10 November 2026</li>
  <li>Staff group: Medical &amp; Dental</li>
 </li>
 <li class="search-result"><h2><a href="/candidate/jobadvert/C9123-26-0002">Senior Clinical Fellow in Gastroenterology</a></h2></li>
 <li class="search-result"><h2><a href="/candidate/jobadvert/C9123-26-0003">Clinical Fellow in Dermatology</a></h2><p>Medical &amp; Dental, NHS Foundation Trust</p></li>
 <li class="search-result"><h2><a href="/candidate/jobadvert/C9123-26-0004">Trust Grade Doctor (FY2 level) - Care of the Elderly</a></h2></li>
 <li class="search-result"><h2><a href="/candidate/jobadvert/C9123-26-0005">Staff Nurse - Acute Medicine</a></h2></li>
 <li class="search-result"><h2><a href="/candidate/jobadvert/C9123-26-0006">Clinical Fellow (ST1-ST2) Nephrology</a></h2></li>
 <li class="search-result"><h2><a href="/candidate/jobadvert/C9123-26-0007">Junior Clinical Fellow</a></h2><p>Medical &amp; Dental. Join our busy acute medical unit (AMU).</p></li>
 <li class="search-result"><h2><a href="/candidate/jobadvert/C9123-26-0008">Junior Clinical Fellow</a></h2><p>Medical &amp; Dental. Based in ophthalmology clinics.</p></li>
</ul>
"""

def advert(spec, body=""):
    return f"""<html><body><h1>Job</h1><p>The closing date is 10 November 2026</p>
    <h2>Job summary</h2><p>{body}</p>
    <h2>Person Specification</h2>{spec}
    <h2>Employer details</h2><p>Employer name</p></body></html>"""

SPEC_MRCP_ESSENTIAL = """<h3>Qualifications</h3><h4>Essential</h4><ul><li>MBBS</li><li>Full GMC registration</li><li>MRCP (UK)</li></ul>
<h4>Desirable</h4><ul><li>ALS</li></ul>"""
SPEC_MRCP_DESIRABLE = """<h3>Qualifications</h3><h4>Essential</h4><ul><li>MBBS</li><li>Full GMC registration</li></ul>
<h4>Desirable</h4><ul><li>MRCP Part 1</li></ul><h3>Experience</h3><h4>Essential</h4><ul><li>Experience in general medicine</li></ul>
<h4>Desirable</h4><ul><li>Previous NHS experience</li></ul>"""
SPEC_NHS_ESSENTIAL = """<h3>Experience</h3><h4>Essential</h4><ul><li>Minimum 12 months NHS experience</li></ul>
<h4>Desirable</h4><ul><li>Audit</li></ul>"""
SPEC_CLEAN = """<h3>Qualifications</h3><h4>Essential</h4><ul><li>MBBS</li><li>Full GMC registration with licence to practise</li></ul>
<h4>Desirable</h4><ul><li>ALS</li></ul>"""


def jobs():
    return {j.job_id: j for j in b.parse_search_results(SEARCH_HTML)}


def test_search_parsing():
    js = jobs()
    assert len(js) == 8
    j = js["C9123-26-0001"]
    assert j.title == "Junior Clinical Fellow in General Medicine"
    assert "Hull" in j.location
    assert "49,909" in j.salary
    assert "10 November 2026" in j.closing
    assert j.url == "https://www.jobs.nhs.uk/candidate/jobadvert/C9123-26-0001"


def test_title_filter():
    js = jobs()
    expected = {"C9123-26-0001": True, "C9123-26-0002": False, "C9123-26-0003": False,
                "C9123-26-0004": True, "C9123-26-0005": False, "C9123-26-0006": True,
                "C9123-26-0007": True, "C9123-26-0008": False}
    for jid, ok in expected.items():
        assert b.title_matches(js[jid]) == ok, (jid, js[jid].title)


def analyse(spec, body=""):
    j = b.Job("X", "Junior Clinical Fellow in Medicine", "u")
    return b.analyse_advert(j, advert(spec, body))


def test_mrcp_essential_rejected():
    j = analyse(SPEC_MRCP_ESSENTIAL)
    assert j.mrcp.status == "essential" and not b.is_acceptable(j)


def test_mrcp_desirable_ok():
    j = analyse(SPEC_MRCP_DESIRABLE)
    assert j.mrcp.status == "desirable"
    assert j.nhs_exp.status == "desirable"
    assert b.is_acceptable(j)


def test_nhs_experience_essential_rejected():
    j = analyse(SPEC_NHS_ESSENTIAL)
    assert j.nhs_exp.status == "essential" and not b.is_acceptable(j)


def test_clean_ok():
    j = analyse(SPEC_CLEAN, "Applications from job seekers who require Skilled Worker sponsorship are welcome.")
    assert j.mrcp.status == "not_mentioned" and j.nhs_exp.status == "not_mentioned"
    assert j.sponsorship == "yes" and b.is_acceptable(j)
    assert j.spec_found


def test_mrcp_not_essential_phrase():
    j = analyse(SPEC_CLEAN, "MRCP is not essential for this post.")
    assert j.mrcp.status in ("not_required", "not_mentioned") and b.is_acceptable(j)


def test_body_says_mrcp_essential():
    j = analyse(SPEC_CLEAN, "Please note full MRCP is essential for this role.")
    assert j.mrcp.status == "essential" and not b.is_acceptable(j)


def test_no_sponsorship_rejected():
    j = analyse(SPEC_CLEAN, "Please note certificate of sponsorship cannot be supported for this position.")
    assert j.sponsorship == "no" and not b.is_acceptable(j)
    j = analyse(SPEC_CLEAN, "We are unable to offer sponsorship for this post.")
    assert j.sponsorship == "no"


def test_no_spec_flagged():
    j = b.analyse_advert(b.Job("X", "Clinical Fellow", "u"), "<html><p>See attached job description.</p></html>")
    assert not j.spec_found and b.is_acceptable(j)
    assert "ملف مرفق" in b.format_message(j)


def test_first_run_and_dedupe(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "STATE_FILE", tmp_path / "seen.json")
    monkeypatch.setattr(b, "SEARCH_KEYWORDS", ["x"])
    monkeypatch.setattr(b, "PAGES_PER_SEARCH", 1)
    monkeypatch.setattr(b, "REQUEST_PAUSE_S", 0)
    sent = []
    monkeypatch.setattr(b, "send_telegram", lambda t, d: sent.append(t))

    def fake_get(session, url):
        if "search" in url:
            return SEARCH_HTML
        if url.endswith("0001"):
            return advert(SPEC_CLEAN)
        if url.endswith("0004"):
            return advert(SPEC_MRCP_ESSENTIAL)
        return advert(SPEC_MRCP_DESIRABLE)
    monkeypatch.setattr(b, "get", fake_get)

    n = b.run_once()
    assert n == 3                      # 0001, 0006, 0007 ; 0004 rejected (MRCP essential)
    assert "اشتغل" in sent[-1]         # welcome message on first run
    sent.clear()
    assert b.run_once() == 0 and not sent   # nothing new second time


# ---------------- Scotland / Northern Ireland / new specialties ----------------
SCOT_LIST = """
<div class="job-list">
 <div class="job"><h3><a href="/Job/JobDetail?JobId=261468">Clinical Fellow in Acute and General Medicine</a></h3><span>NHS Lothian</span></div>
 <div class="job"><h3><a href="/Job/JobDetail?JobId=261470">Clinical Fellow in Paediatric Intensive Care Medicine</a></h3></div>
 <div class="job"><h3>Clinical Fellow in Medicine of the Elderly and Stroke Medicine</h3><a href="https://apply.jobs.scot.nhs.uk/Job/JobDetail?jobid=261471">View job</a></div>
</div>"""
SCOT_ADVERT = """<html><h1>Clinical Fellow in Acute and General Medicine</h1>
<p><b>Job reference:</b> 251062</p><p><b>Salary:</b> Clinical Fellow (£49,909 - £71,550)</p>
<p><b>Job closing date:</b> 24/11/2026</p><p><b>Location:</b> Western General Hospital</p>
<p><b>Employer (NHS Board):</b> NHS Lothian</p>
<p>For a job pack detailing the minimum requirements for this post please visit apply.jobs.scot.nhs.uk</p></html>"""

NI_LIST = """
<ul>
 <li><a href="/Job/40815/clinical-fellow-imt-123-level-in-general-medicine-wl">Clinical Fellow (IMT 1/2/3 level) in General Medicine (WL) ref:N/A</a></li>
 <li><a href="/Job/41800/x">OPEN TO HSC EMPLOYEES ONLY* 73825064 Clinical Fellow (ST1-2 Level) Cardiology Craigavon Area Hospital ref:55045916</a></li>
 <li><a href="/Job/43915/55018049-clinical-fellow-gim">55018049 Clinical Fellow GIM with Specialist Interest SWAH ref:N/A</a></li>
 <li><a href="/Job/46201/x">55514022 Clinical Fellow in Emergency Medicine SWAH ref:N/A</a></li>
 <li><a href="/Search/Details/47900">Clinical Fellow in Respiratory Medicine ref:55990001</a></li>
</ul>"""
NI_ADVERT = """<html><h1>Clinical Fellow (IMT 1/2/3 level) in General Medicine (WL) ref:N/A</h1>
<p><b>Location:</b> Altnagelvin Hospital</p><p><b>Salary:</b> £43,773 - £67,465 per annum pro rata</p>
<p><b>Closes:</b> Fri, 02 May 2027 @ 3:30 PM</p>
<a href="https://jobs.hscni.net/Organisation/Detail/16">Find out more about the Western Health &amp; Social Care Trust</a>
<a href="https://app.healthdaq.com/jobs/abc-clinical-fellow">Job Details and Apply</a></html>"""
NI_EXTERNAL = advert("""<h3>Experience</h3><h4>Essential</h4><ul><li>Have previous experience of working in the HSC / HSE / NHS</li></ul>""")


def test_scotland_list_and_advert():
    js = {j.job_id: j for j in b.parse_scotland_list(SCOT_LIST)}
    assert set(js) == {"sco:261468", "sco:261470", "sco:261471"}
    assert js["sco:261471"].title == "Clinical Fellow in Medicine of the Elderly and Stroke Medicine"
    assert b.title_matches(js["sco:261468"]) and b.title_matches(js["sco:261471"])
    assert not b.title_matches(js["sco:261470"])          # paediatric ICU
    j = b.analyse_advert(js["sco:261468"], SCOT_ADVERT)
    assert "NHS Lothian" in j.employer and "49,909" in j.salary
    assert j.closing == "24/11/2026" and j.location == "Western General Hospital"
    assert not j.spec_found and b.is_acceptable(j)        # job pack -> warning flag


def test_ni_list_and_external_details():
    js = {j.job_id: j for j in b.parse_ni_list(NI_LIST)}
    assert js["ni:40815"].title == "Clinical Fellow (IMT 1/2/3 level) in General Medicine (WL)"
    assert js["ni:43915"].title == "Clinical Fellow GIM with Specialist Interest SWAH"
    ok = {k: b.title_matches(v) for k, v in js.items()}
    assert ok == {"ni:40815": True, "ni:41800": False, "ni:43915": True, "ni:46201": False, "ni:47900": True}
    assert b.external_details_link(NI_ADVERT).startswith("https://app.healthdaq.com")
    j = b.analyse_advert(js["ni:40815"], NI_ADVERT + NI_EXTERNAL)
    assert j.location == "Altnagelvin Hospital" and "Western Health" in j.employer
    assert j.nhs_exp.status == "essential" and not b.is_acceptable(j)   # HSC/NHS experience essential


def test_new_specialties():
    for t in ["Junior Clinical Fellow in Stroke Medicine", "Clinical Fellow in Neurology",
              "Trust Grade Doctor - Haematology", "Clinical Fellow in Endocrinology and Diabetes",
              "Junior Clinical Fellow in Respiratory Medicine", "SHO in General Medicine and Cardiology"]:
        assert b.title_matches(b.Job("x", t, "u")), t
    for t in ["Clinical Fellow in Palliative Medicine", "Clinical Fellow in Neurosurgery",
              "Clinical Fellow in Cardiology", "Clinical Fellow in Intensive Care Medicine"]:
        assert not b.title_matches(b.Job("x", t, "u")), t


def test_all_sources_run(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "STATE_FILE", tmp_path / "seen.json")
    monkeypatch.setattr(b, "SEARCH_KEYWORDS", ["x"])
    monkeypatch.setattr(b, "SMALL_SITE_KEYWORDS", ["x"])
    monkeypatch.setattr(b, "PAGES_PER_SEARCH", 1)
    monkeypatch.setattr(b, "REQUEST_PAUSE_S", 0)
    sent = []
    monkeypatch.setattr(b, "send_telegram", lambda t, d: sent.append(t))

    def fake_get(session, url):
        if "jobs.nhs.uk/candidate/search" in url:
            return SEARCH_HTML
        if "scot.nhs.uk/Home/Job" in url:
            return SCOT_LIST
        if "hscni.net/Search?" in url:
            return NI_LIST
        if "scot.nhs.uk/Job/JobDetail" in url:
            return SCOT_ADVERT
        if "hscni.net" in url:
            return NI_ADVERT.replace("healthdaq", "nothing")   # no external page
        return advert(SPEC_CLEAN)
    monkeypatch.setattr(b, "get", fake_get)

    n = b.run_once()
    # England 0001,0004,0006,0007 + Scotland 261468,261471 + NI 40815,43915,47900
    assert n == 9, n
    assert any("اسكتلندا" in m for m in sent) and any("أيرلندا الشمالية" in m for m in sent)
    sent.clear()
    assert b.run_once() == 0


def test_source_health_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "STATE_FILE", tmp_path / "seen.json")
    monkeypatch.setattr(b, "REQUEST_PAUSE_S", 0)
    monkeypatch.setattr(b, "SEARCH_KEYWORDS", ["x"])
    monkeypatch.setattr(b, "SMALL_SITE_KEYWORDS", ["x"])
    sent = []
    monkeypatch.setattr(b, "send_telegram", lambda t, d: sent.append(t))
    monkeypatch.setattr(b, "get", lambda s, u: SEARCH_HTML if "jobs.nhs.uk" in u else "<html></html>")
    monkeypatch.setattr(b, "analyse_advert", lambda j, h: j)
    for _ in range(3):
        b.run_once()
    warnings = [m for m in sent if "⚠️ البوت مش لاقي" in m]
    assert len(warnings) == 2   # Scotland + NI, once each
