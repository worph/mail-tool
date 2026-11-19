"""Calendar subscriptions end to end: Settings → Calendar & contacts → Subscriptions
(mailhub-roundcube's mailhub_dav) → the mirror's calsync (mailhub-mirror 0.9.0+) →
a read-only calendar in Baïkal, shown in the webmail's calendar.

Runs inside the mirror container (it reads /state and reaches the webmail on the app network):

    docker cp assertion.py mailhub-mirror:/tmp/ && docker cp calendar-subs-test.py mailhub-mirror:/tmp/
    docker exec -e MAILHUB_ASSERTION_SECRET mailhub-mirror python3 /tmp/calendar-subs-test.py <sub> <user>

<sub> <user>: the identity to test as (a registry user's `sub`, from /users/<user>.json).
Uses two sources: Google's public French holidays feed (a real Google iCal feed) and, as
a CalDAV account, the owner's built-in calendar (admin + MAILHUB_PASSWORD, from the
mirror's env), which must resolve to its one calendar. Leaves no subscription behind.
"""
import json, os, re, sys, time, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from assertion import opener

WEB = "http://mailhub-webmail"
GOOGLE = "https://calendar.google.com/calendar/ical/fr.french%23holiday%40group.v.calendar.google.com/public/basic.ics"
sub, user = sys.argv[1], sys.argv[2]
web = opener(sub=sub, user=user)
web.open(f"{WEB}/?_task=mail").read()  # a full page load signs in (mailhub_sso); framed ones don't
fails = []


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what, flush=True)
    if not ok:
        fails.append(what)


def page():
    html = web.open(f"{WEB}/?_task=settings&_action=edit-prefs&_section=mailhub_dav&_framed=1").read().decode()
    token = re.search(r'"request_token":"([^"]+)"', html) or re.search(r'name="_token" value="([^"]+)"', html)
    return html, token.group(1)


def save(**fields):
    html, token = page()
    data = {"_task": "settings", "_action": "save-prefs", "_section": "mailhub_dav", "_framed": "1", "_token": token,
            "_dav_url": "", "_dav_user": "", "_dav_pass": ""}
    data.update(fields)
    out = web.open(f"{WEB}/?_task=settings&_action=save-prefs", urllib.parse.urlencode(data).encode()).read().decode()
    msg = re.findall(r'display_message\("((?:[^"\\]|\\.)*)",\s*"(\w+)"', out)
    return msg[-1] if msg else ("", "")


def status(wait_for=None, timeout=90):
    path = f"/state/{user}/calendars.json"
    end = time.time() + timeout
    while True:
        try:
            st = json.load(open(path))
        except (OSError, ValueError):
            st = {}
        if wait_for is None or wait_for(st) or time.time() > end:
            return st
        time.sleep(3)


def subs_ids():
    html, _ = page()
    return re.findall(r'name="_calsub_name\[([0-9a-f]+)\]"', html)


html, _ = page()
check("Calendar subscriptions" in html or "Agendas abonnés" in html, "the section is on the page")
for i in subs_ids():  # a previous run's leftovers
    save(**{f"_calsub_remove[{i}]": "1"})

# refused before saving
m = save(_calsub_new_url="https://calendar.google.com/calendar/embed?src=fr.french%23holiday%40group.v.calendar.google.com")
check(m[1] == "error" and "iCal" in m[0], f"an embed link is refused with a hint: {m[0][:90]}")
m = save(_calsub_new_url="http://mailhub-dav/dav.php", _calsub_new_user="admin", _calsub_new_pass="wrong")
check(m[1] == "error" and ("refused" in m[0] or "refusé" in m[0]), f"a wrong CalDAV password is refused: {m[0][:90]}")

# a real Google feed
m = save(_calsub_new_url=GOOGLE.replace("https://", "webcal://"), _calsub_new_name="Jours fériés", _calsub_new_color="#d50000")
check(m[1] == "confirmation", f"the Google feed is added: {m}")
ids = subs_ids()
check(len(ids) == 1, "one subscription listed")
gid = ids[0] if ids else ""
st = status(lambda s: s.get(gid, {}).get("ok"))
check(st.get(gid, {}).get("events", 0) > 5, f"the mirror synced it: {st.get(gid)}")

# a CalDAV account with one calendar: resolved to that calendar
pw = os.environ.get("MAILHUB_PASSWORD", "")
m = save(_calsub_new_url="http://mailhub-dav/dav.php", _calsub_new_user="admin", _calsub_new_pass=pw, _calsub_new_name="Owner's")
if user == "admin":
    # admin's own home now also holds the Google subscription: two calendars, so it asks which one
    check(m[1] == "error" and "several" in m[0], f"an account with several calendars asks for one: {m[0][:160]}")
    m = save(_calsub_new_url="http://mailhub-dav/dav.php/calendars/admin/default/", _calsub_new_user="admin",
             _calsub_new_pass=pw, _calsub_new_name="Owner's")
check(m[1] == "confirmation", f"the CalDAV calendar is added: {m}")
cid = [i for i in subs_ids() if i != gid]
cid = cid[0] if cid else ""
st = status(lambda s: s.get(cid, {}).get("ok"))
check(st.get(cid, {}).get("ok") is True, f"the CalDAV subscription synced: {st.get(cid)}")

# the second save synced the Google feed again in full: nothing rewritten (Google's DTSTAMP changes on each download)
# (same round as the CalDAV one, already in `st`)
check(st.get(gid, {}).get("written") == 0, f"an unchanged feed rewrites nothing: written={st.get(gid, {}).get('written')}")


def calendars(want=None, timeout=60):
    """The webmail calendar's list ({id: props}), polled until `want(names)` holds."""
    end = time.time() + timeout
    while True:
        html = web.open(f"{WEB}/?_task=calendar").read().decode()
        env = re.search(r'"calendars":(\{.*?\}\}),"', html)
        cals = json.loads(env.group(1)) if env else {}
        if want is None or want({c.get("name") for c in cals.values()}) or time.time() > end:
            return cals
        time.sleep(4)


# the webmail's calendar: both listed, read-only
cals = calendars(lambda n: {"Jours fériés", "Owner's"} <= n)
mine = {c["name"]: c for c in cals.values() if c.get("name") in ("Jours fériés", "Owner's")}
check(set(mine) == {"Jours fériés", "Owner's"}, f"both calendars in the webmail: {sorted(c.get('name') for c in cals.values())}")
check(all(not c.get("editable") for c in mine.values()), "both read-only there: " + str({n: c.get("editable") for n, c in mine.items()}))
ev = web.open(f"{WEB}/?_task=calendar&_action=load_events&source={urllib.parse.quote(mine.get('Jours fériés', {}).get('id', ''))}"
              f"&start=2026-12-01T00:00:00&end=2027-01-01T00:00:00").read().decode()
check("Noël" in ev or "Christmas" in ev, "Christmas is in December's events")

# rename + recolour, then remove both
m = save(**{f"_calsub_name[{gid}]": "Fériés FR", f"_calsub_color[{gid}]": "#0b8043"})
check(m[1] == "confirmation", "renamed")
names = {c.get("name") for c in calendars(lambda n: "Fériés FR" in n).values()}
check("Fériés FR" in names and "Jours fériés" not in names, f"the new name is in the calendar: {sorted(names)}")
m = save(**{f"_calsub_remove[{gid}]": "1", f"_calsub_remove[{cid}]": "1"})
check(m[1] == "confirmation" and not subs_ids(), "both removed")
names = {c.get("name") for c in calendars(lambda n: not ({"Fériés FR", "Owner's"} & n)).values()}
check(not ({"Fériés FR", "Owner's"} & names), f"and gone from the calendar: {sorted(names)}")

print("\n" + ("all passed" if not fails else f"{len(fails)} failed"))
sys.exit(1 if fails else 0)
