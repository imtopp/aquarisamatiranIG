import json, re, sys

def resolve(slug):
    d = json.load(open('accounts/aquarisamatiran/source_of_truth.json'))
    for sid in d.get('topics', {}):
        for num, t in d['topics'][sid].items():
            s = t.get('slug', '').replace('-', '_')
            if s == slug:
                tag = f'C{sid}#{num}'
                status = t.get('status', '')
                print(f'tag={tag}')
                print(f'status={status}')
                return
    print('tag=')
    print('status=')

def clean_schedule(tag):
    if not tag:
        return
    s = json.load(open('accounts/aquarisamatiran/schedule.json'))
    before = len(s)
    s = [e for e in s if e.get('source_ref') != tag]
    after = len(s)
    json.dump(s, open('accounts/aquarisamatiran/schedule.json', 'w'), indent=2, ensure_ascii=False)
    print(f'  schedule.json: removed {before - after} entries')

def reset_topic(tag):
    if not tag:
        return
    d = json.load(open('accounts/aquarisamatiran/source_of_truth.json'))
    m = re.match(r'C(\d+)#(\d+)', tag)
    if m:
        topic = d.get('topics', {}).get(m.group(1), {}).get(m.group(2))
        if topic:
            topic['status'] = 'planned'
            for field in ['scheduled_time', 'display_name', 'subtitle', 'scientific_name', 'slides', 'result_id', 'permalink', 'caption']:
                topic.pop(field, None)
            json.dump(d, open('accounts/aquarisamatiran/source_of_truth.json', 'w'), indent=2, ensure_ascii=False)
            print(f'  source_of_truth: reset topic {tag} to planned')

def clean_uploaded(slug):
    fpath = 'accounts/aquarisamatiran/resource/.uploaded.json'
    try:
        u = json.load(open(fpath))
    except:
        return
    before = len(u)
    keys = [k for k, v in u.items() if slug in v]
    for k in keys:
        del u[k]
    after = len(u)
    json.dump(u, open(fpath, 'w'), indent=2, ensure_ascii=False)
    print(f'  .uploaded.json: removed {before - after} stale entries')

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else None
    arg = sys.argv[2] if len(sys.argv) > 2 else ''
    arg = arg.replace('-', '_')
    if cmd == 'resolve':
        resolve(arg)
    elif cmd == 'clean-schedule':
        clean_schedule(arg)
    elif cmd == 'reset-topic':
        reset_topic(arg)
    elif cmd == 'clean-uploaded':
        clean_uploaded(arg)
