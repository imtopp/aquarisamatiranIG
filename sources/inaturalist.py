import requests


def get_inaturalist_image(scientific_name: str) -> str | None:
    url = "https://api.inaturalist.org/v1/taxa"
    params = {"q": scientific_name, "per_page": 1}

    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            results = r.json().get("results", [])
            if results:
                photo = results[0].get("default_photo")
                if photo and photo.get("medium_url"):
                    print(f"   🐾 iNaturalist: {results[0].get('name', scientific_name)}")
                    return photo["medium_url"]
    except requests.RequestException:
        pass

    return None
