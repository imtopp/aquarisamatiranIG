"""Test v4 → v5 data migration: seasons→categories, level_labels→subcategories, level→subcategory."""

import json


def _migrate_v4_to_v5(raw: str) -> str:
    """Simulated migration script — transforms v4 curriculum_content.json to v5 source_of_truth.json."""
    cc = json.loads(raw)
    new = {"version": 5}

    categories = {}
    for sid, season in cc.get("seasons", {}).items():
        subcats = {}
        for lv, label in season.get("level_labels", {}).items():
            title = label.split(" — ")[0] if " — " in label else label
            subcats[lv] = {"title": title}
        categories[sid] = {
            "title": season.get("title", ""),
            "subtitle": season.get("subtitle", ""),
            "subcategories": subcats,
        }
    new["categories"] = categories

    topics = {}
    for sid, st in cc.get("topics", {}).items():
        topics[sid] = {}
        for num, t in st.items():
            nt = dict(t)
            if "level" in nt:
                nt["subcategory"] = str(nt.pop("level"))
            topics[sid][num] = nt
    new["topics"] = topics

    return json.dumps(new, indent=2, ensure_ascii=False, sort_keys=True)


class TestMigrationV4toV5:
    def test_seasons_become_categories(self, v4_content):
        result = json.loads(_migrate_v4_to_v5(json.dumps(v4_content)))
        assert "seasons" not in result
        assert "categories" in result
        assert "1" in result["categories"]
        assert result["categories"]["1"]["title"] == "Perjalanan dari Nol Sampai Pro"

    def test_level_labels_become_subcategories(self, v4_content):
        result = json.loads(_migrate_v4_to_v5(json.dumps(v4_content)))
        subcats = result["categories"]["1"]["subcategories"]
        assert "1" in subcats
        assert "2" in subcats
        assert isinstance(subcats["1"], dict)
        assert subcats["1"]["title"] == "Pemula Absolut"
        assert subcats["4"]["title"] == "Advanced"

    def test_topic_level_becomes_subcategory(self, v4_content):
        result = json.loads(_migrate_v4_to_v5(json.dumps(v4_content)))
        topic01 = result["topics"]["1"]["01"]
        assert "level" not in topic01
        assert topic01["subcategory"] == "1"
        topic07 = result["topics"]["1"]["07"]
        assert topic07["subcategory"] == "2"

    def test_other_topic_fields_preserved(self, v4_content):
        result = json.loads(_migrate_v4_to_v5(json.dumps(v4_content)))
        topic01 = result["topics"]["1"]["01"]
        assert topic01["slug"] == "aquarium-itu-apa"
        assert topic01["title"] == "Aquarium itu Apa?"
        assert topic01["status"] == "live"
        assert topic01["permalink"] == "https://ig.example/p/01"

    def test_slides_preserved(self, v4_content):
        result = json.loads(_migrate_v4_to_v5(json.dumps(v4_content)))
        slides = result["topics"]["1"]["01"]["slides"]
        assert len(slides) == 2
        assert slides[0]["type"] == "cover"
        assert slides[1]["type"] == "fact"

    def test_version_bumped(self, v4_content):
        result = json.loads(_migrate_v4_to_v5(json.dumps(v4_content)))
        assert result["version"] == 5

    def test_output_matches_expected_v5(self, v4_content, v5_content):
        result = json.loads(_migrate_v4_to_v5(json.dumps(v4_content)))
        expected = json.loads(json.dumps(v5_content))
        assert json.dumps(result, sort_keys=True) == json.dumps(expected, sort_keys=True)

    def test_empty_seasons_handled(self):
        raw = json.dumps({"version": 4, "seasons": {}, "topics": {}})
        result = json.loads(_migrate_v4_to_v5(raw))
        assert result["categories"] == {}
        assert result["topics"] == {}

    def test_topic_without_level_field_unchanged(self):
        raw = json.dumps({
            "version": 4,
            "seasons": {"1": {"title": "S1", "level_labels": {}}},
            "topics": {"1": {"01": {"slug": "test", "title": "Test", "status": "planned"}}}
        })
        result = json.loads(_migrate_v4_to_v5(raw))
        assert "level" not in result["topics"]["1"]["01"]
        assert result["topics"]["1"]["01"]["title"] == "Test"
