"""Country job boards: Reed (UK), Adzuna (19 countries), Jobs2Careers & USAJOBS (US), Jobindex (DK), Jobbird (NL)."""

import base64
import json
import re
import urllib.parse
import urllib.request

api = None                                     # set by register()

# Adzuna's own code for each country it covers
ADZUNA = {"GB": "gb", "US": "us", "CA": "ca", "AU": "au", "NZ": "nz", "DE": "de", "FR": "fr", "NL": "nl", "BE": "be",
          "ES": "es", "IT": "it", "AT": "at", "CH": "ch", "PL": "pl", "IN": "in", "SG": "sg", "ZA": "za", "BR": "br",
          "MX": "mx"}


def register(_api):
    global api
    api = _api
    common = {"group": "country", "country_native": True, "location_aware": True}
    api.add_board("Reed", src_reed, "Big UK job board (needs a free key)", countries={"GB"}, needs=("reed_key",), **common)
    api.add_board("Adzuna", src_adzuna, "Job search in many countries (needs a free key)", countries=set(ADZUNA),
                  needs=("adzuna_id", "adzuna_key"), **common)
    api.add_board("Jobs2Careers", src_jobs2careers, "Large US job search", countries={"US"}, **common)
    api.add_board("USAJOBS", src_usajobs, "US government jobs", countries={"US"},
                  needs=("usajobs_key", "usajobs_email"), **common)
    api.add_board("Jobindex", src_jobindex, "Denmark's biggest job board", countries={"DK"}, **common)
    api.add_board("Jobbird", src_jobbird, "Dutch job board", countries={"NL"}, **common)


def _page(url, timeout=25):
    req = urllib.request.Request(url, headers=api.http.BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def src_reed(q, o):
    if o["country"] != "GB":
        raise api.jobs.NotHere("UK only")
    key = api.setting("reed_key")
    if not key:
        raise api.jobs.NeedsKey("add a free key in Settings")
    auth = {"Authorization": "Basic " + base64.b64encode(f"{key}:".encode()).decode()}
    out = []
    for skip in (0, 100):
        params = {"keywords": q, "resultsToTake": 100, "resultsToSkip": skip}
        if not api.geo.is_country_name(o["where"], "GB"):
            params.update(locationName=o["where"], distanceFromLocation=o["miles"])
        if o["salary_min"]:
            params["minimumSalary"] = o["salary_min"]
        jt = {"fulltime": "fullTime", "parttime": "partTime", "contract": "contract", "internship": "temp"}.get(o["jtype"])
        if jt:
            params[jt] = "true"
        d = api.http.get_json("https://www.reed.co.uk/api/1.0/search?" + urllib.parse.urlencode(params), headers=auth)
        res = d.get("results", [])
        for j in res:
            out.append(api.jobs.make("Reed", j.get("jobTitle"), j.get("employerName"), j.get("jobUrl"),
                                     j.get("locationName"), api.text.to_date(j.get("date")),
                                     api.text.money(j.get("minimumSalary"), j.get("maximumSalary"), j.get("currency") or "GBP"),
                                     "", [], j.get("jobDescription"), remote=False))
        if len(res) < 100:
            break
    return out


def src_adzuna(q, o):
    code = ADZUNA.get(o["country"])
    country = api.geo.country(o["country"])
    if not code:
        raise api.jobs.NotHere("not available in " + country["name"])
    app_id, app_key = api.setting("adzuna_id"), api.setting("adzuna_key")
    if not (app_id and app_key):
        raise api.jobs.NeedsKey("add a free key in Settings")
    out = []
    for page in (1, 2):
        params = {"app_id": app_id, "app_key": app_key, "what": q, "results_per_page": 50, "content-type": "application/json"}
        if not api.geo.is_country_name(o["where"], o["country"]):
            params.update(where=o["where"], distance=round(o["miles"] * 1.609))
        if o["posted"]:
            params["max_days_old"] = o["posted"]
        if o["salary_min"]:
            params["salary_min"] = o["salary_min"]
        jt = {"fulltime": "full_time", "parttime": "part_time", "contract": "contract"}.get(o["jtype"])
        if jt:
            params[jt] = 1
        d = api.http.get_json(f"https://api.adzuna.com/v1/api/jobs/{code}/search/{page}?" + urllib.parse.urlencode(params))
        res = d.get("results", [])
        for j in res:
            jt = " ".join(x for x in (j.get("contract_time"), j.get("contract_type")) if x).replace("_", " ")
            out.append(api.jobs.make("Adzuna", j.get("title"), (j.get("company") or {}).get("display_name"),
                                     j.get("redirect_url"), (j.get("location") or {}).get("display_name"),
                                     api.text.to_date(j.get("created")),
                                     api.text.money(j.get("salary_min"), j.get("salary_max"), country["currency"]),
                                     jt, [(j.get("category") or {}).get("label", "")], j.get("description"), remote=False))
        if len(res) < 50:
            break
    return out


def src_jobindex(q, o):
    """Jobindex.dk - Denmark's biggest job board (open JSON search, includes exact coordinates)."""
    if o["country"] != "DK":
        raise api.jobs.NotHere("Denmark only")
    out = []
    for page in (1, 2):
        params = {"q": q, "page": page}
        if not api.geo.is_country_name(o["where"], "DK"):
            params.update(address=o["where"], radius=api.jobs.km_radius(o))
        d = api.http.get_json("https://www.jobindex.dk/api/jobsearch/v3/?" + urllib.parse.urlencode(params),
                              headers=api.http.BROWSER_HEADERS)
        for r in d.get("results", []):
            addr = (r.get("addresses") or [{}])[0]
            coords = addr.get("coordinates") or {}
            sal = r.get("salary")
            j = api.jobs.make("Jobindex", r.get("headline"), r.get("companytext") or (r.get("company") or {}).get("name"),
                              r.get("share_url") or r.get("url"), r.get("area") or addr.get("city"),
                              api.text.to_date(r.get("firstdate")), sal if isinstance(sal, str) else "", "", [], "",
                              remote=bool(r.get("home_workplace")))
            if coords.get("latitude"):
                j["lat"], j["lon"] = coords["latitude"], coords["longitude"]
            out.append(j)
        if page >= (d.get("total_pages") or 1):
            break
    return out


def dutch_date(text):
    """'Nieuw' / 'gisteren' / '3 dagen geleden' -> YYYY-MM-DD."""
    s = (text or "").lower()
    if any(w in s for w in ("nieuw", "vandaag", "uur", "minu")):
        return api.text.rel_date("today")
    if "gisteren" in s:
        return api.text.rel_date("1 day ago")
    m = re.search(r"(\d+)\s*(dag|week|weken|maand)", s)
    if m:
        unit = {"dag": "day", "week": "week", "weken": "week", "maand": "month"}[m[2]]
        return api.text.rel_date(f"{m[1]} {unit} ago")
    return ""


def src_jobbird(q, o):
    """Jobbird.com - Dutch job board (reads the public search page)."""
    if o["country"] != "NL":
        raise api.jobs.NotHere("Netherlands only")
    out = []
    for page in (1, 2):
        params = {"s": q, "rad": api.jobs.km_radius(o), "ot": "date", "p": page}
        if not api.geo.is_country_name(o["where"], "NL"):
            params["l"] = o["where"]
        h = _page("https://www.jobbird.com/nl/vacature?" + urllib.parse.urlencode(params), timeout=20)
        links = list(re.finditer(r'<a href="(https://www\.jobbird\.com/nl/vacature/[^"]+)"[^>]*'
                                 r'class="job-search__result-list__result__title">(.*?)</a>', h, re.S))
        for i, m in enumerate(links):
            card = h[m.end(): links[i + 1].start() if i + 1 < len(links) else m.end() + 4000]

            def grab(cls, card=card):
                found = re.search(cls + r'[^>]*>(.*?)</span>\s*</span>', card, re.S)
                return api.text.strip_html(found[1] if found else "")
            out.append(api.jobs.make("Jobbird", m[2], grab("cro-recruiter-name"), m[1], grab("cro-job-location"),
                                     dutch_date(grab("cro-time-posted")), grab("cro-salary"), grab("cro-employment-type"),
                                     [], "", remote=False))
        if len(links) < 10:
            break
    return out


def src_jobs2careers(q, o):
    """Jobs2Careers - large US job search (reads the data embedded in its results page)."""
    if o["country"] != "US":
        raise api.jobs.NotHere("US only")
    loc = ""
    if not api.geo.is_country_name(o["where"], "US"):
        town = api.geo.place_town(o["where"], "US")
        loc = f"{town['name']}, {town['region']}" if town else o["where"]          # "Austin, TX"
    out = []
    for page in (1, 2, 3):
        params = {"q": q, "l": loc}
        if page > 1:
            params["p"] = page
        h = _page("https://www.jobs2careers.com/search/results?" + urllib.parse.urlencode(params))
        i = h.find('"jobAds":{"byId":')
        if i < 0:
            break
        ads = json.JSONDecoder().raw_decode(h, i + len('"jobAds":'))[0].get("byId", {})
        before = len(out)

        def items(x):
            return list(x.values()) if isinstance(x, dict) else (x or [])          # lists arrive as {"0": .., "1": ..}
        for a in ads.values():
            if a.get("adType") not in (None, "job"):
                continue
            sd = items(a.get("salaryDetails"))
            sal = (sd[0].get("label") if sd and isinstance(sd[0], dict) else "") or a.get("compensation") or ""
            types = ", ".join(w.get("label", "") for w in items(a.get("workTypeDetails")) if isinstance(w, dict))
            remote = (a.get("workLocation") or "") == "remote"
            j = api.jobs.make("Jobs2Careers", a.get("title"), a.get("companyName"), a.get("link"),
                              ("Remote · " if remote else "") + (a.get("cityState") or ""),
                              api.text.to_date(a.get("datePosted")), sal, types, [a.get("primaryMajorCategory") or ""],
                              a.get("description"), remote=remote)
            c = (items(a.get("coordinates")) or [None])[0]
            if c and "," in str(c):
                j["lat"], j["lon"] = (float(x) for x in str(c).split(",")[:2])
            if not any(x["url"] == j["url"] for x in out):
                out.append(j)
        if len(out) == before:
            break
    return out


def src_usajobs(q, o):
    """USAJOBS - official US government jobs (free key from developer.usajobs.gov)."""
    if o["country"] != "US":
        raise api.jobs.NotHere("US only")
    key, email = api.setting("usajobs_key"), api.setting("usajobs_email")
    if not (key and email):
        raise api.jobs.NeedsKey("add a free key in Settings")
    params = {"Keyword": q, "ResultsPerPage": 100}
    if not api.geo.is_country_name(o["where"], "US"):
        params.update(LocationName=o["where"], Radius=o["miles"])
    if o["posted"]:
        params["DatePosted"] = o["posted"]
    d = api.http.get_json("https://data.usajobs.gov/api/search?" + urllib.parse.urlencode(params),
                          headers={"Host": "data.usajobs.gov", "User-Agent": email, "Authorization-Key": key})
    out = []
    for item in (d.get("SearchResult") or {}).get("SearchResultItems", []):
        m = item.get("MatchedObjectDescriptor", {})
        pay = (m.get("PositionRemuneration") or [{}])[0]
        per = {"PA": "", "PH": " / hour", "PD": " / day", "PW": " / week", "PM": " / month"}.get(pay.get("RateIntervalCode"), "")
        sal = api.text.money(pay.get("MinimumRange"), pay.get("MaximumRange"), "USD") + (per if pay.get("MinimumRange") else "")
        locs = m.get("PositionLocation") or [{}]
        j = api.jobs.make("USAJOBS", m.get("PositionTitle"), m.get("OrganizationName"), m.get("PositionURI"),
                          m.get("PositionLocationDisplay"), api.text.to_date(m.get("PublicationStartDate")), sal,
                          ", ".join(t.get("Name", "") for t in m.get("PositionSchedule") or []), [],
                          ((m.get("UserArea") or {}).get("Details") or {}).get("JobSummary", ""), remote=False)
        if locs[0].get("Latitude"):
            j["lat"], j["lon"] = locs[0]["Latitude"], locs[0]["Longitude"]
        out.append(j)
    return out
