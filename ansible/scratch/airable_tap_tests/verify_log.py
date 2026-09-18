#!/usr/bin/env python3
"""Assert the tap logged what actually went past it."""
import json, sys

recs = [json.loads(l) for l in open("tap.jsonl")]
ex = [r for r in recs if r["event"] == "exchange"]
failures = []

def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'  ' + str(detail) if detail and not cond else ''}")
    if not cond:
        failures.append(name)

def one(path):
    hits = [r for r in ex if r["target"] == path]
    return hits[0] if hits else None

check("startup logged", any(r["event"] == "startup" for r in recs))
check("all nine exchanges paired", len(ex) == 9, [r["target"] for r in ex])

r = one("/plain")
check("GET /plain: host captured", r and r["host"] == "airable.wifiradiofrontier.com")
check("GET /plain: status 200", r and r["status"] == 200)
check("GET /plain: response body readable", r and json.loads(r["resp_body"])["path"] == "/plain")

post = [r for r in ex if r["method"] == "POST"][0]
check("POST: request body captured", post["req_body"] == "hello=world", post["req_body"])

r = one("/chunked")
check("chunked: body de-chunked in log", r and r["resp_body"].startswith("alphabetagamma-"), r and r["resp_body"][:30])
check("chunked: byte count is payload not wire", r and r["resp_bytes"] == 5 + 4 + 206, r and r["resp_bytes"])

r = one("/gzip")
check("gzip: decompressed for the log", r and json.loads(r["resp_body"])["slogan"] == "hello", r and r["resp_body"][:60])

r = one("/empty")
check("204: logged with no body, not swallowing the next response", r and r["status"] == 204 and r["resp_bytes"] == 0)

r = [x for x in ex if x["method"] == "HEAD"][0]
check("HEAD: no phantom body", r["resp_bytes"] == 0 and r["status"] == 200)

r = one("/big")
check("big: full length counted", r and r["resp_bytes"] == 40000, r and r["resp_bytes"])
check("big: log body truncated at max_body", r and r["resp_truncated"] and len(r["resp_body"]) == 1024,
      r and (r["resp_truncated"], len(r["resp_body"])))

r = one("/closed")
check("close-delimited: captured", r and r["resp_body"] == "no length here", r and r["resp_body"])

check("garbage connection reported as desync, not a crash",
      any(r["event"] == "parse_desync" for r in recs),
      [r["event"] for r in recs])

print()
print(f"{len(failures)} failure(s)" + (": " + ", ".join(failures) if failures else ""))
sys.exit(1 if failures else 0)
