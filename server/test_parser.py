import sys
sys.path.insert(0, r'd:\WSDI\server')
from sdi_bin_parser import get_parser
p = get_parser(r'd:\WSDI\index\SDI')
print("HWIDs:", len(p.hwid_map))
print("Pkgs:", len(p.bin_info))
print("Details:", len(p.driver_details))
for k,v in list(p.driver_details.items())[:3]:
    print("  {}: {} entries".format(k, len(v)))
    if v:
        r0 = v[0]
        print("    First: manuf={} desc={} inf={} ver={}".format(
            r0.get("manufacturer","?"), r0.get("device_desc","?"),
            r0.get("inf_name","?"), r0.get("version","?")))

# Test bluetooth search
results = p.search_hwid('USB\\VID_8087&PID_0A2A')
print("\nSearch USB\\VID_8087&PID_0A2A: {} results".format(len(results)))
for r in results:
    print("  pkg={} manuf={} desc={} inf={}".format(
        r["pkg_name"], r.get("manufacturer","?"),
        r.get("device_desc","?"), r.get("inf_name","?")))
