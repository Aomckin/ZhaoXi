"""Same-origin loopback boundary for the local browser control plane."""
from ipaddress import ip_address


def local_browser_request(request):
    peer = request.client.host if request.client else ""
    try:
        if not ip_address(peer).is_loopback:
            return False
    except ValueError:
        return False
    hostname = (request.url.hostname or "").lower()
    if hostname != "localhost":
        try:
            if not ip_address(hostname).is_loopback:
                return False
        except ValueError:
            return False
    origin = request.headers.get("origin")
    expected_origin = str(request.url).split("/", 3)[:3]
    if origin and origin.rstrip("/") != "/".join(expected_origin):
        return False
    return request.headers.get("sec-fetch-site", "none") in {"none", "same-origin"}
