"""
test_s3.py — AWS Signature Version 4 (mc_s3), checked against the worked
example of the S3 documentation, plus the client with a simulated connection.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mc_s3

ACCESS = "AKIAIOSFODNN7EXAMPLE"
SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
DATE = "20130524T000000Z"


class TestSigV4Vectors(unittest.TestCase):

    def test_documented_get_object(self):
        headers = {"Host": "examplebucket.s3.amazonaws.com", "Range": "bytes=0-9",
                   "x-amz-content-sha256": mc_s3.EMPTY_SHA256, "x-amz-date": DATE}
        res = mc_s3.sign("GET", "/test.txt", {}, headers, mc_s3.EMPTY_SHA256, ACCESS, SECRET,
                         "us-east-1", DATE)
        self.assertEqual(res["signed_headers"], "host;range;x-amz-content-sha256;x-amz-date")
        self.assertEqual(res["signature"],
                         "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")
        self.assertIn("Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request",
                      res["authorization"])

    def test_documented_canonical_request(self):
        headers = {"host": "examplebucket.s3.amazonaws.com", "range": "bytes=0-9",
                   "x-amz-content-sha256": mc_s3.EMPTY_SHA256, "x-amz-date": DATE}
        res = mc_s3.sign("GET", "/test.txt", {}, headers, mc_s3.EMPTY_SHA256, ACCESS, SECRET,
                         "us-east-1", DATE)
        self.assertEqual(res["canonical_request"].splitlines()[0:3], ["GET", "/test.txt", ""])
        self.assertEqual(res["string_to_sign"].splitlines()[:3],
                         ["AWS4-HMAC-SHA256", DATE, "20130524/us-east-1/s3/aws4_request"])

    def test_documented_list_objects_query(self):
        headers = {"host": "examplebucket.s3.amazonaws.com", "x-amz-content-sha256": mc_s3.EMPTY_SHA256,
                   "x-amz-date": DATE}
        res = mc_s3.sign("GET", "/", {"max-keys": "2", "prefix": "J"}, headers, mc_s3.EMPTY_SHA256,
                         ACCESS, SECRET, "us-east-1", DATE)
        self.assertEqual(res["signature"],
                         "34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7")

    def test_derived_key_is_hmac_chain(self):
        key = mc_s3.signing_key(SECRET, "20130524", "us-east-1", "s3")
        self.assertEqual(len(key), 32)

    def test_query_is_sorted_and_encoded(self):
        self.assertEqual(mc_s3.canonical_query({"b": "x y", "a": "1/2"}), "a=1%2F2&b=x%20y")


class FakeResponse:
    def __init__(self, status, body=b""):
        self.status, self._body = status, body

    def read(self):
        return self._body


class FakeConn:
    log = []
    reply = FakeResponse(200)

    def __init__(self, host):
        self.host, self.headers, self.sent = host, {}, b""

    def putrequest(self, method, target, **kw):
        self.method, self.target = method, target

    def putheader(self, k, v):
        self.headers[k] = v

    def endheaders(self):
        pass

    def send(self, data):
        self.sent += data

    def getresponse(self):
        FakeConn.log.append(self)
        return FakeConn.reply

    def close(self):
        pass


class Client(mc_s3.S3Client):
    def _connect(self, host):
        return FakeConn(host)

    def _now(self):
        return DATE


class TestClient(unittest.TestCase):

    def setUp(self):
        FakeConn.log = []
        FakeConn.reply = FakeResponse(200)

    def test_put_virtual_hosted_streams_the_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello")
        self.addCleanup(os.remove, f.name)
        Client("bkt", ACCESS, SECRET, "eu-west-3").put_file("pre/fix/a b.zip", f.name)
        conn = FakeConn.log[0]
        self.assertEqual(conn.host, "bkt.s3.eu-west-3.amazonaws.com")
        self.assertEqual(conn.method, "PUT")
        self.assertEqual(conn.target, "/pre/fix/a%20b.zip")
        self.assertEqual(conn.sent, b"hello")
        self.assertEqual(conn.headers["Content-Length"], "5")
        self.assertEqual(conn.headers["x-amz-content-sha256"], mc_s3.file_sha256(f.name))
        self.assertIn("SignedHeaders=host;x-amz-content-sha256;x-amz-date", conn.headers["Authorization"])

    def test_custom_endpoint_is_path_style(self):
        Client("bkt", ACCESS, SECRET, endpoint="https://minio.local:9000").delete("k.zip")
        conn = FakeConn.log[0]
        self.assertEqual((conn.host, conn.target, conn.method), ("minio.local:9000", "/bkt/k.zip", "DELETE"))

    def test_list_parses_keys(self):
        FakeConn.reply = FakeResponse(200, b'<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                                           b'<Contents><Key>a/x.zip</Key><Size>12</Size></Contents></ListBucketResult>')
        keys = Client("bkt", ACCESS, SECRET).list("a/", max_keys=1)
        self.assertEqual(keys, [{"key": "a/x.zip", "size": 12}])
        self.assertEqual(FakeConn.log[0].target, "/?list-type=2&max-keys=1&prefix=a%2F")

    def test_error_status_raises_with_s3_message(self):
        FakeConn.reply = FakeResponse(403, b"<Error><Code>SignatureDoesNotMatch</Code><Message>bad</Message></Error>")
        with self.assertRaises(mc_s3.S3Error) as ctx:
            Client("bkt", ACCESS, SECRET).list()
        self.assertEqual(ctx.exception.code, "http_403")
        self.assertIn("SignatureDoesNotMatch", ctx.exception.detail)

    def test_object_above_single_put_limit_is_refused(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            pass
        self.addCleanup(os.remove, f.name)
        old = mc_s3.MAX_SINGLE_PUT
        mc_s3.MAX_SINGLE_PUT = -1
        self.addCleanup(setattr, mc_s3, "MAX_SINGLE_PUT", old)
        with self.assertRaises(mc_s3.S3Error) as ctx:
            Client("bkt", ACCESS, SECRET).put_file("k", f.name)
        self.assertEqual(ctx.exception.code, "too_large")


if __name__ == "__main__":
    unittest.main(verbosity=2)
