# LibreChat Integration

## Overview

This release introduces native **LibreChat file artifacts integration** for the MCP Office Documents server. Documents generated through MCP tools (DOCX, XLSX, PPTX, EML, XML) can now be uploaded directly to LibreChat's file service and appear as downloadable attachments in the chat UI.

## Changes Summary

| Metric | Value |
|--------|-------|
| Commits | 11 |
| Files Changed | 25 |
| Lines Added | +1,609 |
| Lines Removed | -135 |

## Key Features

### 1. New Upload Strategy: LIBRECHAT

A new `UPLOAD_STRATEGY=LIBRECHAT` option routes generated documents to LibreChat's internal file service instead of external cloud storage (S3/GCS/Azure/MinIO).

### 2. User Context Extraction

LibreChat passes user identity via HTTP headers:
- `X-User-Id` (required) — Associates files with the user
- `X-User-Email` (optional) — For audit logging
- `X-Conversation-Id` (optional) — For conversation-scoped access

### 3. Service Token Authentication

Secure server-to-server communication between MCP Server and LibreChat using `X-Service-Token` header. The token must match `MCP_SERVICE_TOKEN` configured in LibreChat's environment.

### 4. MCP File Artifacts Response Format

When using LIBRECHAT strategy, tools return structured file artifact responses:

```json
{
  "result": {
    "message": "Document created successfully.",
    "file": {
      "file_id": "uuid-string",
      "filename": "report.docx",
      "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "bytes": 12345,
      "source": "local"
    }
  }
}
```

### 5. Optional UUID Prefix Control

All MCP tools now accept an optional `add_unique_prefix` parameter (default `false`):
- `false`: Clean filenames without UUID prefix (e.g., `My_Report.docx`)
- `true`: Adds 8-character UUID prefix for uniqueness (e.g., `ff8ae81d_My_Report.docx`)

LibreChat adds its own UUID prefix during file storage, making the MCP server prefix redundant in most cases.

## New Files

| File | Purpose |
|------|---------|
| `librechat_integration.py` | User context extraction and upload helpers |
| `upload_tools/backends/librechat.py` | LibreChat file service upload backend |
| `tests/test_librechat_integration.py` | Unit tests for LibreChat functionality |
| `tests/test_upload_unique_prefix.py` | Tests for UUID prefix control |

## Modified Files

| File | Changes |
|------|---------|
| `config.py` | Added `LibreChatSettings` model and `LIBRECHAT` strategy enum |
| `main.py` | Updated tool handlers with LibreChat support |
| `upload_tools/main.py` | Added `upload_file_async()` and `is_librechat_strategy()` |
| `upload_tools/utils.py` | Added `add_unique_prefix` parameter to filename generation |
| `docx_tools/base_docx_tool.py` | Added `_markdown_to_word_buffer()` for buffer-only generation |
| `xlsx_tools/base_xlsx_tool.py` | Added `_markdown_to_excel_buffer()` |
| `pptx_tools/base_pptx_tool.py` | Added `_create_presentation_buffer()` |
| `email_tools/base_email_tool.py` | Added `_create_eml_buffer()` |
| `xml_tools/base_xml_tool.py` | Added `_create_xml_buffer()` |
| `.env.example` | Added LibreChat configuration variables |
| `AGENTS.md` | Documented UUID prefix control |
| `Readme.md` | Added `add_unique_prefix` parameter documentation |

## Configuration

To enable LibreChat integration, set the following environment variables:

```bash
# Enable LibreChat upload strategy
UPLOAD_STRATEGY=LIBRECHAT

# LibreChat service endpoint (inside Docker network)
LIBRECHAT_SERVICE_URL=http://api:3080/api/service/files

# Service token (must match MCP_SERVICE_TOKEN in LibreChat)
LIBRECHAT_SERVICE_TOKEN=<your-service-token>
```

## LibreChat MCP Configuration Example

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

## Security Highlights

- **Two-layer authentication**: API Key (client→MCP) + Service Token (MCP→LibreChat)
- **User isolation**: Files are bound to `user_id` at upload time
- **Timing-safe comparison**: Uses `secrets.compare_digest()` for token validation
- **Rate-limited logging**: Auth failures logged at 1 WARNING per 60 seconds
- **Fail-closed behavior**: Missing `X-User-Id` results in 400 Bad Request

## Backward Compatibility

Existing deployments using `LOCAL`, `S3`, `GCS`, `AZURE`, or `MINIO` upload strategies continue to work unchanged. The LibreChat integration is opt-in via the `UPLOAD_STRATEGY` environment variable.
