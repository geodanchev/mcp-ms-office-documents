"""Utility functions for handling images in PowerPoint presentations.

This module provides functionality to download and validate images from URLs
for embedding in PowerPoint slides.

Security features:
- SSRF protection: blocks internal IP ranges and cloud metadata endpoints
- Content-type validation: only allows image MIME types
- Size limits: prevents resource exhaustion
"""

import io
import ipaddress
import logging
import socket
from typing import Tuple
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# Allowed image MIME types
ALLOWED_MIME_TYPES = {
    'image/png',
    'image/jpeg',
    'image/jpg',
    'image/gif',
    'image/bmp',
    'image/webp',
    'image/tiff',
}

# Maximum image size in bytes (10 MB)
MAX_IMAGE_SIZE = 10 * 1024 * 1024

# Request timeout in seconds
REQUEST_TIMEOUT = 30

# =============================================================================
# SSRF Protection Configuration
# =============================================================================

# Blocked hostnames (case-insensitive)
BLOCKED_HOSTNAMES = {
    'localhost',
    'localhost.localdomain',
    'metadata.google.internal',
    'metadata.internal',
    'kubernetes.default.svc',
    'kubernetes.default',
    'kubernetes',
}

# Blocked IP ranges (RFC 1918 private networks, link-local, loopback, etc.)
BLOCKED_IP_NETWORKS = [
    # Loopback addresses
    ipaddress.ip_network('127.0.0.0/8'),
    ipaddress.ip_network('::1/128'),
    
    # Private networks (RFC 1918)
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.168.0.0/16'),
    
    # Link-local addresses (includes cloud metadata endpoint 169.254.169.254)
    ipaddress.ip_network('169.254.0.0/16'),
    ipaddress.ip_network('fe80::/10'),
    
    # Carrier-grade NAT (RFC 6598)
    ipaddress.ip_network('100.64.0.0/10'),
    
    # Documentation ranges (should not be routable)
    ipaddress.ip_network('192.0.2.0/24'),
    ipaddress.ip_network('198.51.100.0/24'),
    ipaddress.ip_network('203.0.113.0/24'),
    
    # Unspecified addresses
    ipaddress.ip_network('0.0.0.0/8'),
    ipaddress.ip_network('::/128'),
    
    # IPv6 unique local addresses
    ipaddress.ip_network('fc00::/7'),
]


class ImageDownloadError(Exception):
    """Exception raised when image download fails."""
    pass


class ImageValidationError(Exception):
    """Exception raised when image validation fails."""
    pass


class SSRFProtectionError(Exception):
    """Exception raised when SSRF protection blocks a request."""
    pass


def _is_ip_blocked(ip_str: str) -> bool:
    """Check if an IP address is in a blocked range.
    
    Args:
        ip_str: IP address string (IPv4 or IPv6).
        
    Returns:
        True if the IP is blocked, False otherwise.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
        for network in BLOCKED_IP_NETWORKS:
            if ip in network:
                return True
        return False
    except ValueError:
        # Invalid IP address format
        return False


def _resolve_hostname(hostname: str) -> list[str]:
    """Resolve a hostname to IP addresses.
    
    Args:
        hostname: The hostname to resolve.
        
    Returns:
        List of IP address strings.
        
    Raises:
        SSRFProtectionError: If hostname cannot be resolved.
    """
    try:
        # Get all address info for both IPv4 and IPv6
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
        return list(set(info[4][0] for info in addr_info))
    except socket.gaierror as e:
        raise SSRFProtectionError(f"Cannot resolve hostname '{hostname}': {e}")


def is_ssrf_safe(url: str) -> Tuple[bool, str]:
    """Check if a URL is safe from SSRF attacks.
    
    This function validates URLs against:
    - Blocked hostnames (localhost, metadata endpoints, etc.)
    - Blocked IP ranges (private networks, loopback, link-local, etc.)
    - DNS resolution to blocked IPs (prevents DNS rebinding)
    
    Args:
        url: URL string to validate.
        
    Returns:
        Tuple of (is_safe, error_message). If safe, error_message is empty.
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        
        if not hostname:
            return False, "URL has no hostname"
        
        hostname_lower = hostname.lower()
        
        # Check against blocked hostnames
        if hostname_lower in BLOCKED_HOSTNAMES:
            return False, f"Blocked hostname: {hostname}"
        
        # Check if hostname ends with a blocked suffix
        blocked_suffixes = ('.internal', '.local', '.localhost')
        if any(hostname_lower.endswith(suffix) for suffix in blocked_suffixes):
            return False, f"Blocked hostname suffix: {hostname}"
        
        # Check if hostname is an IP address directly
        try:
            ip = ipaddress.ip_address(hostname)
            if _is_ip_blocked(str(ip)):
                return False, f"Blocked IP address: {hostname}"
            # IP is allowed
            return True, ""
        except ValueError:
            # Not an IP address, it's a hostname - need to resolve
            pass
        
        # Resolve hostname to IP addresses and check each one
        try:
            resolved_ips = _resolve_hostname(hostname)
            for ip_str in resolved_ips:
                if _is_ip_blocked(ip_str):
                    return False, f"Hostname '{hostname}' resolves to blocked IP: {ip_str}"
        except SSRFProtectionError as e:
            return False, str(e)
        
        return True, ""
        
    except Exception as e:
        return False, f"Error validating URL: {e}"


def validate_url(url: str) -> bool:
    """Validate that a URL is well-formed, uses http/https, and is SSRF-safe.

    Args:
        url: URL string to validate.

    Returns:
        True if URL is valid and safe, False otherwise.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            return False
        
        # SSRF protection check
        is_safe, error = is_ssrf_safe(url)
        if not is_safe:
            logger.warning(f"SSRF protection blocked URL: {url} - {error}")
            return False
        
        return True
    except Exception:
        return False


def download_image(url: str) -> Tuple[io.BytesIO, str]:
    """Download an image from a URL and return it as a BytesIO object.

    Args:
        url: HTTP(S) URL of the image to download.

    Returns:
        Tuple of (BytesIO object containing image data, detected file extension).

    Raises:
        ImageDownloadError: If download fails.
        ImageValidationError: If image validation fails.
        SSRFProtectionError: If URL is blocked by SSRF protection.
    """
    # Validate URL format
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            raise ImageValidationError(f"Invalid URL format: {url}")
    except Exception:
        raise ImageValidationError(f"Invalid URL format: {url}")
    
    # SSRF protection check
    is_safe, error = is_ssrf_safe(url)
    if not is_safe:
        logger.warning(f"SSRF protection blocked image download: {url} - {error}")
        raise SSRFProtectionError(f"URL blocked by SSRF protection: {error}")

    logger.info(f"Downloading image from: {url}")

    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            stream=True,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) PowerPoint-MCP/1.0'
            },
            # Disable redirects to prevent SSRF via redirect
            allow_redirects=False,
        )
        
        # Handle redirects manually with SSRF checks
        redirect_count = 0
        max_redirects = 5
        
        while response.is_redirect and redirect_count < max_redirects:
            redirect_url = response.headers.get('Location')
            if not redirect_url:
                break
            
            # Make redirect URL absolute if relative
            if not redirect_url.startswith(('http://', 'https://')):
                from urllib.parse import urljoin
                redirect_url = urljoin(url, redirect_url)
            
            # Check redirect URL for SSRF
            is_safe, error = is_ssrf_safe(redirect_url)
            if not is_safe:
                raise SSRFProtectionError(f"Redirect blocked by SSRF protection: {redirect_url} - {error}")
            
            logger.debug(f"Following redirect to: {redirect_url}")
            response = requests.get(
                redirect_url,
                timeout=REQUEST_TIMEOUT,
                stream=True,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) PowerPoint-MCP/1.0'
                },
                allow_redirects=False,
            )
            redirect_count += 1
            url = redirect_url
        
        response.raise_for_status()

    except SSRFProtectionError:
        raise
    except requests.exceptions.Timeout:
        raise ImageDownloadError(f"Timeout downloading image from {url}")
    except requests.exceptions.ConnectionError:
        raise ImageDownloadError(f"Connection error downloading image from {url}")
    except requests.exceptions.HTTPError as e:
        raise ImageDownloadError(f"HTTP error {e.response.status_code} downloading image from {url}")
    except requests.exceptions.RequestException as e:
        raise ImageDownloadError(f"Error downloading image from {url}: {str(e)}")

    # Check content type
    content_type = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
    if content_type and content_type not in ALLOWED_MIME_TYPES:
        raise ImageValidationError(
            f"Invalid image type: {content_type}. Allowed types: {', '.join(ALLOWED_MIME_TYPES)}"
        )

    # Check content length if provided
    content_length = response.headers.get('Content-Length')
    if content_length:
        try:
            size = int(content_length)
            if size > MAX_IMAGE_SIZE:
                raise ImageValidationError(
                    f"Image too large: {size / (1024*1024):.1f}MB. Maximum size: {MAX_IMAGE_SIZE / (1024*1024):.0f}MB"
                )
        except ValueError:
            pass  # Invalid Content-Length header, continue with download

    # Download image data
    image_data = io.BytesIO()
    total_size = 0

    for chunk in response.iter_content(chunk_size=8192):
        total_size += len(chunk)
        if total_size > MAX_IMAGE_SIZE:
            raise ImageValidationError(
                f"Image too large. Maximum size: {MAX_IMAGE_SIZE / (1024*1024):.0f}MB"
            )
        image_data.write(chunk)

    image_data.seek(0)

    # Determine file extension from content type or URL
    extension = get_image_extension(content_type, url)

    logger.info(f"Successfully downloaded image: {total_size / 1024:.1f}KB, type: {extension}")

    return image_data, extension


def get_image_extension(content_type: str, url: str) -> str:
    """Determine image file extension from content type or URL.

    Args:
        content_type: MIME type of the image.
        url: Original URL of the image.

    Returns:
        File extension (e.g., 'png', 'jpg').
    """
    # Try to get from content type
    type_to_ext = {
        'image/png': 'png',
        'image/jpeg': 'jpg',
        'image/jpg': 'jpg',
        'image/gif': 'gif',
        'image/bmp': 'bmp',
        'image/webp': 'webp',
        'image/tiff': 'tiff',
    }

    if content_type in type_to_ext:
        return type_to_ext[content_type]

    # Try to get from URL
    parsed = urlparse(url)
    path = parsed.path.lower()
    for ext in ('png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'tiff'):
        if path.endswith(f'.{ext}'):
            return 'jpg' if ext == 'jpeg' else ext

    # Default to png
    return 'png'
