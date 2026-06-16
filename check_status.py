import json
d = json.load(open('accounts/aquarisamatiran/source_of_truth.json', encoding='utf-8'))
for sid in sorted(d['topics']):
    for tnum in sorted(d['topics'][sid]):
        t = d['topics'][sid][tnum]
        st = t.get('status','?')
        slug = t.get('slug','?')[:30]
        p = t.get('permalink','')[:45]
        print(f"C{sid}#{tnum}: {st:10s} {slug:30s} {p}")
