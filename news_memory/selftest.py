"""Insert a fictional multi-year domestic crisis and check get_background."""

from __future__ import annotations

from . import ingest, tools


def _ents(*roles):
    # (name, type, role)
    return [
        {"name": n, "type": t, "role": r, "aliases": aliases, "country_iso": iso}
        for n, t, r, aliases, iso in roles
    ]


ZEMBLA = ("Zembla", "country", "actor", ["Republic of Zembla"], None)
VOSS = ("Helena Voss", "person", "actor", ["Voss"], None)
SOLIN = ("Marek Solin", "person", "actor", ["Solin"], None)
ZED = ("Zed City", "place", "other", [], None)

STORIES = [
    {
        "published": "2026-04-18",
        "title": "Zembla inflation hits 41 percent as bread prices triple",
        "body": (
            "Zembla, official name Republic of Zembla, reported annual inflation of 41 percent "
            "in March 2026, the statistics office in Zed City said on 18 April 2026. "
            "The price of a standard loaf rose from 12 to 37 zeds in six months. "
            "President Helena Voss, in office since January 2024, blamed a drought and a weak currency. "
            "Opposition leader Marek Solin called for a freeze on staple prices."
        ),
        "extract": {
            "headline": "Zembla inflation hits 41 percent",
            "summary": "In March 2026 Zembla inflation reached 41 percent. Bread rose from 12 to 37 zeds. President Helena Voss blamed drought and the currency. Opposition leader Marek Solin demanded a staple-price freeze.",
            "happened_at": "2026-03-31",
            "event_type": "economy",
            "tags": ["inflation"],
            "importance": 4,
            "geo_countries": [],
            "entities": _ents(ZEMBLA, VOSS, SOLIN, ZED),
            "relations": [
                {"src": "Helena Voss", "rel": "president_of", "dst": "Zembla",
                 "valid_from": "2024-01-01", "valid_to": None,
                 "fact": "Helena Voss has been president of Zembla since January 2024."},
                {"src": "Zed City", "rel": "capital_of", "dst": "Zembla",
                 "valid_from": None, "valid_to": None, "fact": "Zed City is the capital of Zembla."},
            ],
            "pair_topics": [{"a": "Helena Voss", "b": "Zembla", "kind": "politics"}],
        },
    },
    {
        "published": "2026-11-03",
        "title": "Bread riots in Zed City after another Zembla rate shock",
        "body": (
            "Thousands protested in Zed City on 2 November 2026 after Zembla's central bank "
            "raised its key rate to 28 percent. Shops were looted on Market Street. "
            "President Helena Voss said the protests would not change the inflation fight. "
            "Unions announced a general strike for December."
        ),
        "extract": {
            "headline": "Bread riots in Zed City",
            "summary": "On 2 November 2026 protests and looting hit Zed City after Zembla's central bank raised its key rate to 28 percent. President Helena Voss said policy would not change. Unions called a December general strike.",
            "happened_at": "2026-11-02",
            "event_type": "society",
            "tags": ["protest", "inflation", "strike"],
            "importance": 4,
            "geo_countries": [],
            "entities": _ents(ZEMBLA, VOSS, ZED),
            "relations": [],
            "pair_topics": [{"a": "Helena Voss", "b": "Zembla", "kind": "politics"}],
        },
    },
    {
        "published": "2027-03-21",
        "title": "Voss pushes emergency staple tax through Zembla parliament",
        "body": (
            "On 21 March 2027 Zembla's parliament passed President Helena Voss's emergency tax "
            "on imported staples, raising the levy from 5 to 22 percent. The government said "
            "the tax would fund bread subsidies after the 2026 inflation spike. "
            "Marek Solin's opposition walked out. Economists warned the tax would lift food prices again."
        ),
        "extract": {
            "headline": "Zembla passes 22 percent staple tax",
            "summary": "On 21 March 2027 Zembla raised the imported-staple tax from 5 to 22 percent to fund bread subsidies after the 2026 inflation spike. President Helena Voss backed the levy. Marek Solin's opposition walked out.",
            "happened_at": "2027-03-21",
            "event_type": "economy",
            "tags": ["tax", "inflation", "legislation", "budget"],
            "importance": 4,
            "geo_countries": [],
            "entities": _ents(ZEMBLA, VOSS, SOLIN),
            "relations": [],
            "pair_topics": [{"a": "Helena Voss", "b": "Zembla", "kind": "politics"}],
        },
    },
    {
        "published": "2027-09-14",
        "title": "Zembla parliament crisis after tax-and-inflation year",
        "body": (
            "Zembla's ruling party lost its majority on 14 September 2027 when twelve deputies "
            "defected, citing the March staple tax and unrelenting inflation. "
            "President Helena Voss refused to dismiss her finance minister. "
            "Talks with Marek Solin collapsed after two days."
        ),
        "extract": {
            "headline": "Zembla government loses its majority",
            "summary": "On 14 September 2027 twelve deputies defected, citing the March 2027 staple tax and ongoing inflation. President Helena Voss kept her finance minister. Talks with Marek Solin failed.",
            "happened_at": "2027-09-14",
            "event_type": "politics",
            "tags": ["tax", "inflation", "other"],
            "importance": 3,
            "geo_countries": [],
            "entities": _ents(ZEMBLA, VOSS, SOLIN),
            "relations": [],
            "pair_topics": [{"a": "Helena Voss", "b": "Zembla", "kind": "politics"}],
        },
    },
    {
        "published": "2028-03-12",
        "title": "Helena Voss ousted as Zembla president after army statement",
        "body": (
            "President Helena Voss was removed from office on 12 March 2028 after the Zemblan army "
            "said it would no longer enforce her decrees. Parliament named speaker Ilya Korin acting president. "
            "Crowds in Zed City celebrated. Analysts pointed to the 2026 inflation shock, the 2026 bread riots, "
            "and the 2027 staple tax as the buildup. Voss had been president of Zembla since 2024."
        ),
        "extract": {
            "headline": "Helena Voss ousted as Zembla president",
            "summary": "On 12 March 2028 Helena Voss was removed as president of Zembla after the army refused to enforce her decrees. Speaker Ilya Korin became acting president. The 2026 inflation shock, 2026 bread riots and 2027 staple tax were cited as the buildup.",
            "happened_at": "2028-03-12",
            "event_type": "politics",
            "tags": ["coup", "resignation", "inflation", "tax", "protest"],
            "importance": 5,
            "geo_countries": [],
            "entities": _ents(
                ZEMBLA, VOSS,
                ("Ilya Korin", "person", "actor", ["Korin"], None),
                ZED,
            ),
            "relations": [
                {"src": "Helena Voss", "rel": "president_of", "dst": "Zembla",
                 "valid_from": "2024-01-01", "valid_to": "2028-03-12",
                 "fact": "Helena Voss was president of Zembla from 2024 until 12 March 2028."},
                {"src": "Ilya Korin", "rel": "president_of", "dst": "Zembla",
                 "valid_from": "2028-03-12", "valid_to": None,
                 "fact": "Ilya Korin became acting president of Zembla on 12 March 2028."},
            ],
            "pair_topics": [{"a": "Helena Voss", "b": "Zembla", "kind": "politics"}],
        },
    },
]


def run() -> int:
    ids = []
    for s in STORIES:
        aid = ingest.ingest_manual(
            s["title"], s["body"],
            published=s["published"] + "T12:00:00+00:00",
            url=f"selftest://zembla/{s['published']}",
            source_name="selftest",
            extract_data=s["extract"],
        )
        ids.append(aid)
        print(f"ingested article {aid}: {s['title']}")

    pack = tools.get_background(
        "give me the background of why Zembla ousted its president",
        as_of="2028-03-13",
        years=3,
    )
    text = " ".join(
        [d.get("current_status") or "" for d in pack.get("dossiers") or []]
        + [e.get("summary") or "" for e in pack.get("events") or []]
        + [b.get("bullet") or "" for d in pack.get("dossiers") or [] for b in d.get("timeline") or []]
    ).lower()
    needed = ["inflation", "tax", "2026", "2027", "voss"]
    missing = [n for n in needed if n not in text]
    print("entities:", [e["canonical"] for e in pack.get("entities") or []])
    print("offices:", pack.get("office_holders"))
    print("events:", len(pack.get("events") or []))
    print("dossiers:", [d["title"] for d in pack.get("dossiers") or []])
    if missing:
        print("SELFTEST_FAIL missing:", ", ".join(missing))
        return 1

    from . import language

    samples = [
        ("Die Regierung in Vaduz hat die Mehrwertsteuer erhöht.", "de"),
        ("Le gouvernement des Comores a annoncé une taxe sur le riz importé.", "fr"),
        ("ارتفع التضخم في جزر القمر بعد الضريبة الجديدة.", "ar"),
        ("The government raised the tax.", "en"),
    ]
    for text, expect in samples:
        got = language.detect(text)
        if got != expect:
            print(f"SELFTEST_FAIL lang {expect!r} got {got!r} for {text[:40]!r}")
            return 1

    # Cheap gazetteer path (no LLM): German + French copy must still hit the country.
    li = ingest.ingest_manual(
        "Vaduz erhöht die Mehrwertsteuer",
        "Die Regierung in Liechtenstein hat am 3. März 2027 die Mehrwertsteuer von 7,7 "
        "auf 8,1 Prozent erhöht. Finanzministerin Sabine Feger begründete den Schritt "
        "mit steigenden Gesundheitskosten. Die Opposition im Landtag kritisierte die Vorlage.",
        published="2027-03-03T12:00:00+00:00",
        url="selftest://li/mwst-2027",
        source_name="selftest-de",
    )
    km = ingest.ingest_manual(
        "Les Comores taxent le riz importé",
        "Moroni — Le gouvernement des Comores a instauré le 11 juin 2027 une taxe de "
        "15 pour cent sur le riz importé, après une année d'inflation élevée. "
        "L'opposition à Ndzuwani dénonce une mesure qui frappe les ménages.",
        published="2027-06-11T12:00:00+00:00",
        url="selftest://km/riz-2027",
        source_name="selftest-fr",
    )
    print(f"ingested multilingual articles {li}, {km}")

    li_pack = tools.get_background("Liechtenstein Mehrwertsteuer", as_of="2027-03-04", years=2)
    km_pack = tools.get_background("pourquoi les Comores ont taxé le riz", as_of="2027-06-12", years=2)
    li_names = {e["canonical"] for e in li_pack.get("entities") or []}
    km_names = {e["canonical"] for e in km_pack.get("entities") or []}
    if "Liechtenstein" not in li_names:
        print("SELFTEST_FAIL Liechtenstein not resolved from German article", li_names)
        return 1
    if "Comoros" not in km_names:
        print("SELFTEST_FAIL Comoros not resolved from French 'Comores'", km_names)
        return 1
    print("multilingual entities LI", li_names, "KM", km_names)

    # No translation table: German "Waldbrände", English query names no country.
    ingest.ingest_manual(
        "Massive Waldbrände in Liechtenstein",
        "Seit dem 4. Juli 2027 wüten massive Waldbrände im Süden Liechtensteins. "
        "Über 1200 Hektar Wald bei Triesenberg sind betroffen. Die Feuerwehr aus "
        "dem Kanton Graubünden hilft. Eine Verletzte.",
        published="2027-07-12T12:00:00+00:00",
        url="selftest://li/waldbrand-2027",
        source_name="selftest-de",
        extract_data={
            "headline": "Massive Waldbrände in Liechtenstein",
            "summary": "Seit dem 4. Juli 2027 wüten massive Waldbrände im Süden Liechtensteins. 1200 Hektar bei Triesenberg. Hilfe aus Graubünden.",
            "summary_en": "",
            "lang": "de",
            "happened_at": "2027-07-04",
            "event_type": "disaster",
            "tags": ["disaster"],
            "importance": 4,
            "geo_countries": ["LI"],
            "entities": [
                {"name": "Liechtenstein", "type": "country", "role": "affected",
                 "aliases": [], "country_iso": "LI"},
            ],
            "relations": [],
            "pair_topics": [],
        },
    )
    fires = tools.search_events(
        query="What were the major wildfires in July 2027",
        limit=20,
    )
    fire_text = " ".join(e.get("summary") or "" for e in fires.get("events") or []).lower()
    print("wildfire window", fires.get("date_from"), fires.get("date_to"),
          "n", len(fires.get("events") or []))
    if "waldbr" not in fire_text and "liechtenstein" not in fire_text:
        print("SELFTEST_FAIL July 2027 wildfire query missed German Waldbrände")
        print(" events:", [e.get("summary", "")[:80] for e in fires.get("events") or []])
        return 1
    print("SELFTEST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
