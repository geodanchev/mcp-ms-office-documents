"""Dynamic template tools must work under every storage strategy.

Regression for [#113](https://github.com/ForLegalAI/mcp-ms-office-documents/issues/113):
the dynamic Word and email tools built *and* uploaded inside one
``run_blocking()`` body, so the upload ran on a worker thread and went through
the synchronous ``upload_file()`` — which refuses ``UPLOAD_STRATEGY=LIBRECHAT``
outright ("LIBRECHAT strategy requires async upload"). Every template tool was
therefore dead under LibreChat while the static tools worked.

Two halves to the fix, and both are pinned here:

- the upload happens on the event loop through ``upload_and_format_response()``,
  so the LibreChat branch (async upload + file artifact) is reachable;
- the user context is read *before* the blocking dispatch, because
  ``run_blocking()`` hands the callable to ``loop.run_in_executor()`` without
  copying contextvars, and FastMCP's ``get_http_request()`` is contextvar-based.
  Read it on the worker thread and there is no request to read.

The fake request below therefore refuses to answer off the main thread: a test
that passes here cannot be passing by reading headers after dispatch.
"""
import asyncio
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config import StorageStrategy  # noqa: E402
from docx_tools.dynamic_docx_tools import register_docx_template  # noqa: E402
from email_tools.dynamic_email_tools import register_email_template  # noqa: E402

DOCX_SPEC = {
    "name": "librechat_probe_docx",
    "description": "librechat probe",
    "docx_path": "default_docx_template.docx",
    "args": [
        {"name": "req_arg", "type": "string", "required": True,
         "description": "Required arg"},
    ],
}

EMAIL_SPEC = {
    "name": "librechat_probe_email",
    "description": "librechat probe",
    "html_path": "default_email_template.html",
    "args": [
        {"name": "subject", "type": "string", "required": True,
         "description": "Subject"},
    ],
}

LIBRECHAT_FILE_INFO = {
    "file_id": "file-abc",
    "filename": "probe.docx",
    "filepath": "/uploads/file-abc",
    "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "bytes": 4096,
    "source": "local",
}


def _register(register, spec):
    """Register *spec* on a throwaway server and return the live tool."""
    mcp = FastMCP("librechat-dynamic-test")
    assert register(mcp, spec), f"registration failed for {spec['name']}"
    return asyncio.run(mcp.get_tool(spec["name"]))


def _call(tool, args):
    """Invoke the tool the way FastMCP does and return its structured result."""
    result = asyncio.run(tool.run({"data": args}))
    # FastMCP wraps a non-dict return under "result"; unwrap that one layer so
    # the assertions read against what the tool body returned.
    return result.structured_content["result"]


class _FakeRequest:
    def __init__(self, headers):
        self.headers = headers


def _main_thread_only_request(headers):
    """A get_http_request() that only answers on the event loop's thread.

    This is the real contextvar behaviour in miniature: off the main thread
    there is no active request, exactly as on a run_blocking() worker.
    """
    def _get_http_request():
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("No active HTTP request found.")
        return _FakeRequest(headers)

    return _get_http_request


def _librechat(headers, upload_calls):
    """Context managers putting the server on LIBRECHAT with a fake upload."""
    async def fake_upload_file_async(file_object, suffix, filename=None,
                                     user_context=None, add_unique_prefix=None):
        upload_calls.append({
            "bytes": file_object.getvalue(),
            "suffix": suffix,
            "filename": filename,
            "user_context": user_context,
            "add_unique_prefix": add_unique_prefix,
        })
        return dict(LIBRECHAT_FILE_INFO)

    return (
        patch("upload_tools.main.UPLOAD_STRATEGY", StorageStrategy.LIBRECHAT),
        patch("librechat_integration.upload_file_async", fake_upload_file_async),
        patch("fastmcp.server.dependencies.get_http_request",
              _main_thread_only_request(headers)),
    )


def _local(upload_calls):
    """A fake synchronous upload for the traditional (LOCAL) path."""
    def fake_upload_file(file_object, suffix, filename=None,
                         user_context=None, add_unique_prefix=None):
        upload_calls.append({
            "bytes": file_object.getvalue(),
            "suffix": suffix,
            "filename": filename,
            "add_unique_prefix": add_unique_prefix,
        })
        return f"http://example.com/{filename}.{suffix}"

    return patch("upload_tools.upload_file", fake_upload_file)


class TestDynamicDocxUnderLibreChat:
    def test_it_returns_a_file_artifact_and_does_not_raise(self):
        tool = _register(register_docx_template, DOCX_SPEC)
        calls = []
        strategy, upload, request = _librechat({"x-user-id": "user-1"}, calls)

        with strategy, upload, request:
            result = _call(tool, {"req_arg": "hello"})

        assert isinstance(result, dict), "LIBRECHAT must return a file artifact"
        assert result["result"]["file"]["file_id"] == "file-abc"
        assert "created successfully" in result["result"]["message"]

        assert len(calls) == 1
        assert calls[0]["suffix"] == "docx"
        assert calls[0]["bytes"][:2] == b"PK", "the .docx bytes must reach the upload"

    def test_the_user_context_is_read_before_the_blocking_dispatch(self):
        """The headers are read on the event loop, not on the worker thread.

        The fake request raises off the main thread, so a user_id here can only
        have come from an extraction that happened before run_blocking().
        """
        tool = _register(register_docx_template, DOCX_SPEC)
        calls = []
        strategy, upload, request = _librechat(
            {"x-user-id": "user-42", "x-user-email": "user@example.com",
             "x-conversation-id": "conv-7"},
            calls,
        )

        with strategy, upload, request:
            _call(tool, {"req_arg": "hello"})

        context = calls[0]["user_context"]
        assert context["user_id"] == "user-42"
        assert context["user_email"] == "user@example.com"
        assert context["conversation_id"] == "conv-7"

    def test_add_unique_prefix_still_reaches_the_upload_as_none(self):
        """A template that does not declare the arg must not pin it to False."""
        tool = _register(register_docx_template, DOCX_SPEC)
        calls = []
        strategy, upload, request = _librechat({"x-user-id": "user-1"}, calls)

        with strategy, upload, request:
            _call(tool, {"req_arg": "hello"})

        assert calls[0]["add_unique_prefix"] is None

    def test_a_missing_user_id_fails_loudly_instead_of_uploading(self):
        tool = _register(register_docx_template, DOCX_SPEC)
        calls = []
        strategy, upload, request = _librechat({}, calls)

        with strategy, upload, request:
            with pytest.raises(ToolError, match="X-User-Id"):
                _call(tool, {"req_arg": "hello"})

        assert calls == [], "nothing may be uploaded without a user"


class TestDynamicDocxUnderLocal:
    def test_it_still_returns_a_url_string(self):
        tool = _register(register_docx_template, DOCX_SPEC)
        calls = []

        with _local(calls):
            result = _call(tool, {"req_arg": "hello"})

        assert isinstance(result, str)
        assert result.endswith(".docx")
        assert calls[0]["filename"] == DOCX_SPEC["name"]
        assert calls[0]["add_unique_prefix"] is None


class TestDynamicEmailUnderLibreChat:
    def test_it_returns_a_file_artifact_and_does_not_raise(self):
        tool = _register(register_email_template, EMAIL_SPEC)
        calls = []
        strategy, upload, request = _librechat({"x-user-id": "user-1"}, calls)

        with strategy, upload, request:
            result = _call(tool, {"subject": "Quarterly update"})

        assert isinstance(result, dict), "LIBRECHAT must return a file artifact"
        assert result["result"]["file"]["file_id"] == "file-abc"

        assert len(calls) == 1
        assert calls[0]["suffix"] == "eml"
        assert calls[0]["filename"] == "Quarterly update"
        assert b"X-Unsent" in calls[0]["bytes"], "the draft bytes must reach the upload"

    def test_the_user_context_is_read_before_the_blocking_dispatch(self):
        tool = _register(register_email_template, EMAIL_SPEC)
        calls = []
        strategy, upload, request = _librechat({"x-user-id": "user-42"}, calls)

        with strategy, upload, request:
            _call(tool, {"subject": "Quarterly update"})

        assert calls[0]["user_context"]["user_id"] == "user-42"

    def test_a_missing_user_id_fails_loudly_instead_of_uploading(self):
        tool = _register(register_email_template, EMAIL_SPEC)
        calls = []
        strategy, upload, request = _librechat({}, calls)

        with strategy, upload, request:
            with pytest.raises(ToolError, match="X-User-Id"):
                _call(tool, {"subject": "Quarterly update"})

        assert calls == [], "nothing may be uploaded without a user"


class TestDynamicEmailUnderLocal:
    def test_it_still_returns_a_url_string(self):
        tool = _register(register_email_template, EMAIL_SPEC)
        calls = []

        with _local(calls):
            result = _call(tool, {"subject": "Quarterly update"})

        assert isinstance(result, str)
        assert result.endswith(".eml")
        assert calls[0]["filename"] == "Quarterly update"
        assert calls[0]["add_unique_prefix"] is None
