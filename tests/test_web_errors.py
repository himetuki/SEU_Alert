"""采集异常 → 自然语言映射测试。"""

from __future__ import annotations

from qq_relay.adapters.web.errors import friendly_error
from qq_relay.adapters.web.seu_lectures import LectureError


class ConnectError(Exception):
    """与 httpx.ConnectError 同名，触发名称分支。"""


class ConnectTimeout(Exception):
    pass


class TestFriendlyError:
    def test_dns_failure_mentions_campus_network(self):
        msg = friendly_error(ConnectError("[Errno 11001] getaddrinfo failed"))
        assert "域名" in msg and "校园网" in msg

    def test_timeout(self):
        assert "超时" in friendly_error(ConnectTimeout("timed out"))

    def test_login_page_instead_of_json(self):
        exc = LectureError(
            "讲座列表响应非 JSON: <!DOCTYPE html><html><head>"
            "<meta http-equiv=\"X-UA-Compatible\" content=\"IE=Edge\"></head></html>")
        msg = friendly_error(exc)
        assert "网页" in msg and "登录" in msg
        assert "<!DOCTYPE" not in msg        # 不把 HTML 噪音漏给 UI

    def test_http_status_mapped(self):
        assert "403" in friendly_error(LectureError("讲座列表 HTTP 403"))
        assert "401" in friendly_error(LectureError("课程页 HTTP 401"))

    def test_labor_credentials_missing(self):
        msg = friendly_error(Exception("未配置 LABOR_USERNAME/LABOR_PASSWORD，也未提供 cookie"))
        assert "LABOR_USERNAME" in msg

    def test_cas_login_failure(self):
        msg = friendly_error(Exception("CAS 登录失败: {'success': False}"))
        assert "CAS" in msg

    def test_validation_error_passthrough(self):
        # 后台表单校验错误已经是人话，不应被改写
        assert friendly_error(ValueError("未知类别: ['foo']")) == "未知类别: ['foo']"

    def test_file_not_found(self):
        msg = friendly_error(FileNotFoundError(2, "No such file", "config/x.yml"))
        assert "不存在" in msg

    def test_generic_fallback_strips_html(self):
        msg = friendly_error(RuntimeError("<b>boom</b> <i>detail</i>"))
        assert "boom" in msg and "<b>" not in msg
