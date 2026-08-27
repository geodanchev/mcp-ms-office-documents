# Pull Request: LibreChat Integration

**Title:** feat: Add LibreChat file artifacts integration

---

## Description

With this change I want to introduce a way to integrate the mcp-ms-office-documents to LibreChat.

When using the new `UPLOAD_STRATEGY=LIBRECHAT`, generated documents (DOCX, XLSX, PPTX, EML, XML) are uploaded directly to LibreChat's internal file service and appear as downloadable attachments in the chat UI — no external cloud storage required.

---

## What's New

### New Upload Strategy: `LIBRECHAT`

A new storage backend that uploads files to LibreChat's `/api/service/files` endpoint instead of S3/GCS/Azure/MinIO.

### User Context from HTTP Headers

LibreChat passes user identity via headers:
- `X-User-Id` (required) — associates files with the user
- `X-User-Email` (optional) — for audit logging  
- `X-Conversation-Id` (optional) — for conversation-scoped access

### Service Token Authentication

Secure server-to-server communication using `X-Service-Token` header. The token must match `MCP_SERVICE_TOKEN` configured in LibreChat's environment.

### Optional UUID Prefix Control

All tools now accept `add_unique_prefix` parameter (default `false`). Since LibreChat adds its own UUID prefix during storage, the MCP server prefix is disabled by default to avoid redundant prefixes.

---

## Configuration

```bash
# .env
UPLOAD_STRATEGY=LIBRECHAT
LIBRECHAT_SERVICE_URL=http://api:3080/api/service/files
LIBRECHAT_SERVICE_TOKEN=<must-match-MCP_SERVICE_TOKEN-in-LibreChat>
```

```yaml
# librechat.yaml
mcpServers:
  Office-documents:
    type: streamable-http
    url: http://mcp-office-docs:8958/mcp
    headers:
      X-User-Id: "{{LIBRECHAT_USER_ID}}"
      X-User-Email: "{{LIBRECHAT_USER_EMAIL}}"
```

---

## New Files

| File | Description |
|------|-------------|
| `librechat_integration.py` | User context extraction and upload helpers |
| `upload_tools/backends/librechat.py` | LibreChat file service upload backend |
| `tests/test_librechat_integration.py` | Unit tests for LibreChat functionality |
| `tests/test_upload_unique_prefix.py` | Tests for UUID prefix control |

---

## Modified Files

| File | Changes |
|------|---------|
| `config.py` | Added `LibreChatSettings` and `LIBRECHAT` strategy |
| `main.py` | Updated tool handlers with LibreChat support |
| `upload_tools/main.py` | Added `upload_file_async()` and `is_librechat_strategy()` |
| `upload_tools/utils.py` | Added `add_unique_prefix` parameter |
| `*_tools/base_*_tool.py` | Added `_*_buffer()` functions for buffer-only generation |
| `.env.example` | Added LibreChat configuration variables |
| `AGENTS.md`, `Readme.md` | Documentation updates |

---

## How It Works

1. LibreChat calls MCP tool with user headers (`X-User-Id`, etc.)
2. MCP server generates document (DOCX/XLSX/PPTX/EML/XML)
3. Document is uploaded to LibreChat via `POST /api/service/files`
4. MCP returns file artifact response with `file_id`, `filename`, `mimeType`
5. File appears as attachment in LibreChat conversation

---

## Testing

```bash
pytest tests/test_librechat_integration.py tests/test_upload_unique_prefix.py -v
```

All tests pass (17 tests in test_librechat_integration + 10 tests in test_upload_unique_prefix).

---

## Backward Compatibility

Existing deployments using `LOCAL`, `S3`, `GCS`, `AZURE`, or `MINIO` strategies continue to work unchanged. The LibreChat integration is fully opt-in.
