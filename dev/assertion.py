"""What AppShield adds in front of the webmail, for the dev tests (MailHub 0.5.0+: no login form).

The webmail (mailhub_sso) logs in whoever X-AppShield-Assertion names: an HS256 JWT signed with
the app's MAILHUB_ASSERTION_SECRET (in its .env). The tests talk to mailhub-webmail directly on
the app's network, so they sign it themselves.

    from assertion import opener
    web = opener()                      # urllib opener: cookies + the header on every request
    web = opener(sub="someone-else", user="bob")   # another identity: another mailbox

    python3 assertion.py [sub] [user]   # prints one, e.g. for curl -H or puppeteer
"""
import base64, hashlib, hmac, http.cookiejar, json, os, sys, time, urllib.request

SECRET = os.environ.get("MAILHUB_ASSERTION_SECRET", "")
OWNER_SUB = "dev-owner"   # the first identity to open MailHub gets the admin mailbox


def mint(sub=OWNER_SUB, user="owner", email="", name="", ttl=3600, secret=None, aud="mailhub"):
    secret = secret or SECRET
    if not secret:
        sys.exit("set MAILHUB_ASSERTION_SECRET (the app's .env)")
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d, separators=(",", ":")).encode()).rstrip(b"=").decode()
    now = int(time.time())
    h = b({"alg": "HS256", "typ": "JWT"})
    p = b({"method": "oidc", "user": user, "email": email, "name": name, "iss": "appshield",
           "aud": aud, "sub": sub, "iat": now, "exp": now + ttl})
    sig = hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}." + base64.urlsafe_b64encode(sig).rstrip(b"=").decode()


class _Header(urllib.request.BaseHandler):
    def __init__(self, **kw):
        self.kw = kw

    def http_request(self, req):
        req.add_unredirected_header("X-AppShield-Assertion", mint(**self.kw))
        return req


def opener(**kw):
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), _Header(**kw))


if __name__ == "__main__":
    print(mint(*(sys.argv[1:3] or [])))
