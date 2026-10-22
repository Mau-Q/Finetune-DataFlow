"""Opt-in development access. Never derive identity from a machine username."""
from ipaddress import ip_address
from urllib.parse import urlsplit

from app.services.data_library import LibraryError


def is_loopback(value):
    try:
        return ip_address(value).is_loopback
    except ValueError:
        return False


def require_local(request):
    host = urlsplit(str(request.base_url)).hostname
    if not request.client or not is_loopback(request.client.host) or not (host == 'localhost' or is_loopback(host or '')):
        raise LibraryError('开发自动登录仅允许本机访问', 403)
