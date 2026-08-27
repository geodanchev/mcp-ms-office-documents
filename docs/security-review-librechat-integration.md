# Security Review Request: MCP Office Documents - LibreChat Integration

**To:** Security Team  
**From:** [Your Name]  
**Date:** July 20, 2026  
**Priority:** Normal  
**Classification:** Internal

---

Dear Security Team,

I would like to request a security review of the recent LibreChat integration implemented in our **MCP Office Documents** server. This integration enables document generation (DOCX, XLSX, PPTX, EML, XML) through the Model Context Protocol (MCP) with files delivered directly to LibreChat's chat interface.

---

## 1. Architecture Overview

The integration introduces a new upload strategy (`LIBRECHAT`) that routes generated documents to LibreChat's internal file service instead of external cloud storage (S3/GCS/Azure).

**Data Flow:**
```
LibreChat Client → MCP Server → Document Generation → LibreChat File Service → Chat UI
```

---

## 2. Security Architecture

### 2.1 Two-Layer Authentication

We implemented **defense-in-depth** with two independent authentication layers:

| Layer | Direction | Mechanism | Configuration |
|-------|-----------|-----------|---------------|
| **Layer 1** | Client → MCP Server | API Key | `API_KEY` env var |
| **Layer 2** | MCP Server → LibreChat | Service Token | `LIBRECHAT_SERVICE_TOKEN` env var |

**Layer 1 - API Key Authentication (`middleware.py`):**
- Validates requests via `Authorization: Bearer <key>`, plain `Authorization: <key>`, or `x-api-key` header
- Uses `secrets.compare_digest()` for **timing-safe comparison** (mitigates timing attacks)
- Rate-limited auth failure logging (1 WARNING per 60s) to prevent log flooding during brute-force attempts
- Middleware is conditionally registered only when `API_KEY` is configured

**Layer 2 - Service Token Authentication:**
- MCP Server authenticates to LibreChat using `X-Service-Token` header
- Token must match `MCP_SERVICE_TOKEN` configured in LibreChat's environment
- Invalid tokens receive HTTP 401 with explicit error message

### 2.2 User Context Isolation

LibreChat passes user identity via HTTP headers:

| Header | Required | Purpose |
|--------|----------|--------|
| `X-User-Id` | **Yes** | File ownership association |
| `X-User-Email` | No | Audit logging |
| `X-Conversation-Id` | No | Conversation-scoped file access |

**Key Security Properties:**
- Files are **bound to `user_id`** at upload time
- Download URLs are user-scoped: `/api/files/download/{user_id}/{file_id}`
- Missing `X-User-Id` results in **400 Bad Request** (fail-closed behavior)
- LibreChat enforces that users can only access their own files

---

## 3. Sensitive Data Handling

| Data Type | Storage | Protection |
|-----------|---------|------------|
| API Key | Environment variable | Never logged, timing-safe comparison |
| Service Token | Environment variable | Transmitted only in `X-Service-Token` header |
| User ID | In-memory (per-request) | Not persisted in MCP server |
| Generated documents | LibreChat file storage | User-scoped access control |

---

## 4. Error Handling & Logging

**Security-Relevant Logging:**
- Auth failures logged at DEBUG level (always) + throttled WARNING (1/60s)
- Successful uploads logged with `user_id` and `file_id` (no file content)
- Service token validation errors logged with actionable messages

**Fail-Closed Behaviors:**
- Missing API key → Request rejected (when `API_KEY` is configured)
- Invalid service token → HTTP 401 returned to client
- Missing `X-User-Id` → HTTP 400 / ValueError raised
- Upload timeout → Clear error with retry guidance

---

## 5. Configuration Requirements

For secure deployment, the following environment variables must be set:

```bash
# MCP Server authentication (client-facing)
API_KEY=<strong-random-key>

# LibreChat integration (server-to-server)
UPLOAD_STRATEGY=LIBRECHAT
LIBRECHAT_SERVICE_URL=http://api:3080/api/service/files
LIBRECHAT_SERVICE_TOKEN=<must-match-LibreChat-MCP_SERVICE_TOKEN>
```

---

## 6. Files Changed (for review)

| File | Security Relevance |
|------|--------------------|
| `middleware.py` | API key validation, timing-safe comparison |
| `librechat_integration.py` | User context extraction from headers |
| `upload_tools/backends/librechat.py` | Service token auth, file upload |
| `config.py` | LibreChatSettings validation |
| `main.py` | Middleware registration, tool handlers |

---

## 7. Requested Review Items

1. **Authentication flow** - Validate two-layer auth design
2. **Header trust model** - Confirm X-User-Id header handling is appropriate for our deployment
3. **Token storage** - Review env var approach for secrets
4. **Error messages** - Ensure no sensitive data leakage in error responses
5. **Logging practices** - Confirm auth failure logging is appropriate

---

## 8. Attachments

- [ ] Architecture flowchart diagram (attached separately)
- [ ] Full diff of changes (available in Git repository)

---

Please let me know if you need additional information or would like to schedule a walkthrough of the implementation.

Best regards,  
[Your Name]

---

*This document contains internal technical details. Please handle according to information security policy.*
