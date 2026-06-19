import os, httpx
from dotenv import load_dotenv

os.chdir(r"C:\Users\_____\Documents\Project\aquarisamatiran")
load_dotenv()

pat = os.environ.get("GH_PAT", "")
print(f"PAT length: {len(pat)}, preview: {pat[:20]}...")

headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {pat}"}
r = httpx.get("https://api.github.com/repos/imtopp/aquarisamatiranIG/actions/workflows", headers=headers)
print(f"Status: {r.status_code}")
if r.status_code != 200:
    print(r.json().get("message", ""))
else:
    print("OK - PAT works, total workflows:", len(r.json().get("workflows", [])))
