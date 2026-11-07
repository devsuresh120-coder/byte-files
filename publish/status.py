"""Diagnostic: ask Buffer what really happened to posts we sent (run via workflow_dispatch action=status)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import publish as P


def note(t, m): print(f"::notice title={t}::" + str(m).replace("\n", " ")[:1500])


def introspect():
    want = ["VideoAssetInput", "FacebookPostMetadataInput", "FacebookMetadata", "PostTypeFacebook", "VideoMetadataInput"]
    out = {}
    for n in want:
        t = P.gql('query($n:String!){ __type(name:$n){ kind fields{ name } inputFields{ name type{ name kind ofType{ name } } } enumValues{ name } } }', {"n": n})["__type"] or {}
        out[n] = [x["name"] for x in (t.get("fields") or t.get("inputFields") or t.get("enumValues") or [])]
    print("::notice title=Buffer input types::" + json.dumps(out)[:3000])


def run():
    if os.environ.get("INTROSPECT") == "1":
        introspect(); return
    for tn in ("PostError",):
        try:
            t = P.gql('query($n:String!){ __type(name:$n){ kind fields{ name } enumValues{ name } } }', {"n": tn})["__type"]
            note("type " + tn, json.dumps([f["name"] for f in (t or {}).get("fields") or []] or [e["name"] for e in (t or {}).get("enumValues") or []]))
        except Exception as e:
            note("type " + tn + " failed", e)
    posted = json.load(open("queue/posted.json"))
    for key, v in posted.items():
        pid = v.get("post_id")
        if not pid:
            continue
        for fields in ("id status dueAt sentAt externalLink error { message }", "id status dueAt sentAt externalLink error", "id status dueAt sentAt externalLink", "id status dueAt sentAt"):
            try:
                d = P.gql('query($i:PostId!){ post(input:{id:$i}){ %s } }' % fields, {"i": pid})
                if d["post"].get("status") != "scheduled": note("post " + key, json.dumps(d))
                break
            except Exception as e:
                last = str(e)
        else:
            note("post " + key + " failed", last)


run()
