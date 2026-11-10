"""Spike: open Roundcube and list the calendars the Kolab CalDAV driver sees.
The webmail has no login form (MailHub 0.5.0+): set MAILHUB_ASSERTION_SECRET (the app's .env) and
copy assertion.py next to this script; requests carry the identity AppShield would add.
"""
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from assertion import opener
import http.cookiejar, re, sys, urllib.parse, urllib.request

RC = "http://mailhub-webmail/"
jar = http.cookiejar.CookieJar()
web = opener()


def get(params, data=None):
    body = urllib.parse.urlencode(data).encode() if data else None
    with web.open(RC + "?" + urllib.parse.urlencode(params), body) as r:
        return r.read().decode("utf-8", "replace")


get({"_task": "mail"})  # mailhub_sso logs the identity in
page = get({"_task": "calendar"})
cals = re.search(r'"calendars":(\{.*?\}\}),"', page)
print("calendars env:", cals.group(1)[:800] if cals else "(none in page)")
print("addressbooks:", re.findall(r'"name":"([^"]+)","[^}]*"carddav', get({"_task": "addressbook"}))[:5])
