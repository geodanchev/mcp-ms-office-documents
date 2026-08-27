# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it by:

1. **Email**: Contact the maintainers directly
2. **GitHub Security Advisory**: Use GitHub's private vulnerability reporting

Please do NOT create public issues for security vulnerabilities.

## Security Measures

This project implements the following security measures:

### XML External Entity (XXE) Protection

- All XML parsing uses `defusedxml` library
- External entity processing is disabled
- Entity expansion attacks ("billion laughs") are blocked

### Server-Side Request Forgery (SSRF) Protection

- Image downloads validate URLs against blocked IP ranges
- Internal IP addresses (RFC 1918) are blocked:
  - `10.0.0.0/8`
  - `172.16.0.0/12`
  - `192.168.0.0/16`
- Cloud metadata endpoints are blocked:
  - `169.254.169.254` (AWS/GCP/Azure metadata)
  - `metadata.google.internal`
- Localhost addresses are blocked:
  - `127.0.0.0/8`
  - `localhost`
  - `::1`

### Input Sanitization

- Filenames are sanitized to prevent path traversal
- HTML content in emails is sanitized using `bleach`
- Only allowed HTML tags are permitted in email content

### Authentication

- Optional API key authentication via `API_KEY` environment variable
- Admin UI protected by password authentication
- CSRF protection on admin endpoints

## Security Headers

When deployed behind a reverse proxy, ensure the following headers are set:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Content-Security-Policy: default-src 'self'`

## Dependency Security

Dependencies are regularly audited for vulnerabilities:

```bash
pip install safety
safety check -r requirements.txt
```

## Security Changelog

### 2024-XX-XX - SSRF and Input Validation Fixes

- Added SSRF protection to image download functionality
- Implemented IP address and hostname validation
- Added HTML sanitization for email content
- Enhanced filename sanitization
