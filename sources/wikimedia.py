import requests


def get_wikimedia_image(scientific_name: str) -> str | None:
    name = scientific_name.replace(" ", "_")
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{name}"

    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            thumb = data.get("thumbnail")
            if thumb and thumb.get("source"):
                print(f"   🌐 Wikimedia: {data.get('title', name)}")
                return thumb["source"]
    except requests.RequestException:
        pass

    return None
