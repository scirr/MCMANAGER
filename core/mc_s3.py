"""
mc_s3.py — Minimal S3 client signed with AWS Signature Version 4, stdlib only.

Works against AWS and S3-compatible services (custom endpoint, path-style
addressing). Supports what backups need: upload (single PUT, streamed), list,
delete.
"""
import datetime
import hashlib
import hmac
import http.client
import os
import re
import urllib.parse
from xml.etree import ElementTree

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
MAX_SINGLE_PUT = 5 * 1024 ** 3
CHUNK = 1024 * 1024


class S3Error(Exception):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _hmac(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def quote(value, keep_slash=False):
    return urllib.parse.quote(value, safe="-_.~/" if keep_slash else "-_.~")


def canonical_query(query):
    pairs = sorted((quote(str(k)), quote(str(v))) for k, v in (query or {}).items())
    return "&".join(f"{k}={v}" for k, v in pairs)


def signing_key(secret_key, date_stamp, region, service):
    k = _hmac(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k = _hmac(k, region)
    k = _hmac(k, service)
    return _hmac(k, "aws4_request")


def sign(method, canonical_uri, query, headers, payload_hash, access_key, secret_key,
         region, amz_date, service="s3"):
    """AWS SigV4. `headers` are exactly the ones to sign (names in any case).
    Returns {"signature", "authorization", "signed_headers", "canonical_request",
    "string_to_sign"}; `canonical_uri` must already be URI-encoded."""
    date_stamp = amz_date[:8]
    norm = {k.lower().strip(): re.sub(r"\s+", " ", str(v).strip()) for k, v in headers.items()}
    names = sorted(norm)
    canonical_headers = "".join(f"{n}:{norm[n]}\n" for n in names)
    signed_headers = ";".join(names)
    canonical_request = "\n".join([method, canonical_uri, canonical_query(query),
                                   canonical_headers, signed_headers, payload_hash])
    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope,
                                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()])
    key = signing_key(secret_key, date_stamp, region, service)
    signature = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
                     f"SignedHeaders={signed_headers}, Signature={signature}")
    return {"signature": signature, "authorization": authorization, "signed_headers": signed_headers,
            "canonical_request": canonical_request, "string_to_sign": string_to_sign}


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


class S3Client:
    def __init__(self, bucket, access_key, secret_key, region="us-east-1", endpoint=None,
                 path_style=None, timeout=60):
        self.bucket, self.access_key, self.secret_key = bucket, access_key, secret_key
        self.region, self.timeout = region, timeout
        if endpoint:
            parts = urllib.parse.urlparse(endpoint if "://" in endpoint else "https://" + endpoint)
            self.scheme, self.netloc = parts.scheme, parts.netloc
            self.path_style = True if path_style is None else path_style
        else:
            self.scheme, self.netloc = "https", f"s3.{region}.amazonaws.com"
            self.path_style = bool(path_style)

    def _target(self, key):
        key = key.lstrip("/")
        if self.path_style:
            return self.netloc, "/" + quote(self.bucket) + ("/" + quote(key, True) if key else "/")
        return f"{self.bucket}.{self.netloc}", "/" + quote(key, True)

    def _connect(self, host):
        cls = http.client.HTTPSConnection if self.scheme == "https" else http.client.HTTPConnection
        return cls(host, timeout=self.timeout)

    def _now(self):
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def request(self, method, key="", query=None, body_file=None, payload_hash=None):
        host, uri = self._target(key)
        size = None
        if body_file is not None:
            size = os.path.getsize(body_file)
            if size > MAX_SINGLE_PUT:
                raise S3Error("too_large", str(size))
            payload_hash = payload_hash or file_sha256(body_file)
        payload_hash = payload_hash or EMPTY_SHA256
        amz_date = self._now()
        headers = {"host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date}
        signed = sign(method, uri, query, headers, payload_hash, self.access_key, self.secret_key,
                      self.region, amz_date)
        send_headers = {"Host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date,
                        "Authorization": signed["authorization"]}
        if size is not None:
            send_headers["Content-Length"] = str(size)
        target = uri + (("?" + canonical_query(query)) if query else "")
        conn = self._connect(host)
        try:
            conn.putrequest(method, target, skip_host=True, skip_accept_encoding=True)
            for k, v in send_headers.items():
                conn.putheader(k, v)
            conn.endheaders()
            if body_file is not None:
                with open(body_file, "rb") as f:
                    for block in iter(lambda: f.read(CHUNK), b""):
                        conn.send(block)
            resp = conn.getresponse()
            data = resp.read()
        except OSError as e:
            raise S3Error("network", str(e))
        finally:
            conn.close()
        if resp.status >= 300:
            raise S3Error(f"http_{resp.status}", _error_text(data))
        return data

    def put_file(self, key, path):
        self.request("PUT", key, body_file=path)

    def delete(self, key):
        self.request("DELETE", key)

    def list(self, prefix="", max_keys=1000):
        data = self.request("GET", "", {"list-type": "2", "max-keys": str(max_keys), "prefix": prefix})
        root = ElementTree.fromstring(data)
        ns = root.tag.partition("}")[0] + "}" if root.tag.startswith("{") else ""
        return [{"key": c.findtext(f"{ns}Key"), "size": int(c.findtext(f"{ns}Size") or 0)}
                for c in root.iter(f"{ns}Contents")]


def _error_text(data):
    try:
        root = ElementTree.fromstring(data)
        code = root.findtext("Code") or ""
        msg = root.findtext("Message") or ""
        return f"{code} {msg}".strip()
    except ElementTree.ParseError:
        return data[:200].decode("utf-8", "replace")
