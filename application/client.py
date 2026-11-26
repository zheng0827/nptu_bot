"""Async HTTP client for NPTU mobile APK APIs with OAuth auto-refresh and temp_data dumping."""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Mapping

import httpx

from application.constants import (
    API_CATALOG,
    BASE_URL,
    DEFAULT_TIMEOUT,
    ENCRYPTED_STUDENT_ENDPOINTS,
    USER_AGENT,
)
from application.crypto import encrypt_path_params
from core.base_adapter import NPTUAuthError, NPTUError, TempDataDumper
from core.storage import BotStorage

logger = logging.getLogger(__name__)


@dataclass
class AppClientConfig:
    student_id: str = ""
    password: str = ""
    des_key: str = ""
    access_token: str = ""
    refresh_token: str = ""
    profile: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "AppClientConfig":
        return cls(
            student_id=(os.getenv("STUDENT_ID") or os.getenv("NPTU_STUDENT_ID") or "").strip().upper(),
            password=(os.getenv("PASSWORD") or os.getenv("NPTU_PASSWORD") or "").strip(),
            des_key=(os.getenv("NPTU_APP_3DES_KEY") or os.getenv("NPTU_3DES_KEY") or "").strip(),
        )


class NptuAppClient:
    """Async client implementing NPTU APK protocol, OAuth lifecycle, and temp_data dumps."""

    SOURCE_NAME = "application"

    def __init__(
        self,
        config: AppClientConfig,
        storage: BotStorage,
        dumper: TempDataDumper | None = None,
    ):
        self.config = config
        self.storage = storage
        self.dumper = dumper or TempDataDumper()
        self._auth_lock = asyncio.Lock()
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=DEFAULT_TIMEOUT,
            verify=False,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "*",
            },
        )
        self._load_saved_auth()

    async def close(self) -> None:
        await self._http.aclose()

    def _headers(self, include_user_id: bool = True) -> dict[str, str]:
        headers = {"User-Agent": USER_AGENT, "Accept": "*"}
        if include_user_id and self.config.student_id:
            headers["Custom-User-ID"] = self.config.student_id.upper()
        return headers

    def _load_saved_auth(self) -> None:
        if not self.config.student_id:
            return
        saved = self.storage.load_auth(self.SOURCE_NAME, self.config.student_id)
        if saved:
            self.config.access_token = saved.get("access_token", "")
            self.config.refresh_token = saved.get("refresh_token", "")
            self.config.profile = saved.get("profile", {})

    def _save_auth(self) -> None:
        if not self.config.student_id:
            return
        self.storage.save_auth(
            self.SOURCE_NAME,
            self.config.student_id,
            self.config.access_token,
            self.config.refresh_token,
            self.config.profile,
        )

    def _require_student_credentials(self) -> None:
        if not self.config.student_id or not self.config.password:
            raise NPTUAuthError("請先在 .env 設定 STUDENT_ID 與 PASSWORD。")
        if not self.config.des_key:
            raise NPTUAuthError("請先在 .env 設定 NPTU_APP_3DES_KEY（24 bytes）。")

    async def _auth_get(self, name: str, endpoint: str, params: Mapping[str, Any]) -> Any:
        encrypted = encrypt_path_params(params, self.config.des_key)
        resp = await self._http.get(f"{endpoint}/{encrypted}", headers=self._headers(True))
        if resp.status_code >= 400:
            raise NPTUAuthError(f"OAuth 端點 {name} 回傳 HTTP {resp.status_code}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise NPTUAuthError(f"OAuth 端點 {name} 未回傳有效 JSON") from exc
        self.dumper.dump(self.SOURCE_NAME, name, payload, params=params)
        return payload

    async def login(self, force: bool = False) -> dict[str, Any]:
        self._require_student_credentials()
        async with self._auth_lock:
            if not force and self.config.access_token:
                return {"profile": self.config.profile, "logged_in": True}

            result = await self._auth_get(
                "oauth_token",
                API_CATALOG["oauth_token"]["path"],
                {
                    "account": self.config.student_id.upper(),
                    "password": self.config.password,
                    "grantType": "password",
                },
            )
            data = result.get("data") if isinstance(result, dict) else None
            oauth = data.get("oauth") if isinstance(data, dict) else None
            if (
                not isinstance(result, dict)
                or result.get("result") is not True
                or not isinstance(oauth, dict)
                or not oauth.get("accessToken")
            ):
                desc = (
                    data.get("errorDescription", "登入失敗，請確認學號與密碼。")
                    if isinstance(data, dict)
                    else "登入失敗。"
                )
                raise NPTUAuthError(f"屏大 OAuth 登入失敗：{desc}")

            self.config.access_token = str(oauth["accessToken"])
            self.config.refresh_token = str(oauth.get("refreshToken") or "")
            if isinstance(data.get("profile"), dict):
                self.config.profile = data["profile"]
            self._save_auth()
            logger.info("NPTU OAuth login succeeded for %s", self.config.student_id)
            return {"profile": self.config.profile, "logged_in": True}

    async def refresh_token(self) -> bool:
        if not self.config.refresh_token or not self.config.des_key:
            return False
        async with self._auth_lock:
            result = await self._auth_get(
                "oauth_refresh",
                API_CATALOG["oauth_refresh"]["path"],
                {
                    "account": self.config.student_id.upper(),
                    "refreshToken": self.config.refresh_token,
                },
            )
            data = result.get("data") if isinstance(result, dict) else None
            if (
                not isinstance(result, dict)
                or result.get("result") is not True
                or not isinstance(data, dict)
                or not data.get("accessToken")
            ):
                return False
            self.config.access_token = str(data["accessToken"])
            self.config.refresh_token = str(data.get("refreshToken") or self.config.refresh_token)
            self._save_auth()
            logger.info("NPTU OAuth token refreshed for %s", self.config.student_id)
            return True

    async def logout(self) -> None:
        async with self._auth_lock:
            self.config.access_token = ""
            self.config.refresh_token = ""
            self.config.profile = {}
            if self.config.student_id:
                self.storage.clear_auth(self.SOURCE_NAME, self.config.student_id)

    async def _ensure_login(self) -> None:
        if not self.config.access_token:
            await self.login()

    async def request(
        self,
        name: str,
        params: Mapping[str, Any] | None = None,
        *,
        path: str | None = None,
        method: str | None = None,
        body: Mapping[str, Any] | None = None,
        allow_mutation: bool = False,
    ) -> Any:
        spec = API_CATALOG.get(name)
        if not spec and not path:
            raise NPTUError(f"未知的 API 端點：{name}")
        if spec and spec.get("mutating") and not allow_mutation:
            raise NPTUError(f"端點 {name} 會異動伺服器資料，必須經使用者確認後才能呼叫。")

        endpoint = path or spec["path"]
        if "{" in endpoint:
            raise NPTUError(f"端點路徑尚有未替換的參數：{endpoint}")

        http_method = (method or (spec["method"] if spec else "GET")).upper()
        is_encrypted = name in ENCRYPTED_STUDENT_ENDPOINTS

        if is_encrypted:
            self._require_student_credentials()
            await self._ensure_login()

        async def _perform() -> Any:
            req_params = dict(params or {})
            if is_encrypted:
                encrypted_payload = {
                    "studentID": self.config.student_id.upper(),
                    "accessToken": self.config.access_token,
                    **req_params,
                }
                encrypted_hex = encrypt_path_params(encrypted_payload, self.config.des_key)
                url = f"{endpoint}/{encrypted_hex}"
                if http_method == "GET":
                    resp = await self._http.get(url, headers=self._headers(True))
                elif http_method == "POST":
                    resp = await self._http.post(url, data=dict(body or {}), headers=self._headers(True))
                else:
                    raise NPTUError(f"不支援的 HTTP 方法：{http_method}")
            else:
                headers = self._headers(include_user_id=bool(self.config.student_id))
                if http_method == "GET":
                    resp = await self._http.get(endpoint, params=req_params or None, headers=headers)
                elif http_method == "POST":
                    form_data = dict(body) if body is not None else req_params
                    resp = await self._http.post(endpoint, data=form_data, headers=headers)
                else:
                    raise NPTUError(f"不支援的 HTTP 方法：{http_method}")

            if resp.status_code >= 400:
                raise NPTUError(f"端點 {name} 回傳 HTTP {resp.status_code}")
            try:
                return resp.json()
            except ValueError as exc:
                raise NPTUError(f"端點 {name} 未回傳 JSON（HTTP {resp.status_code}）") from exc

        payload = await _perform()

        # Auto-recovery for expired/invalid OAuth tokens (903 -> refresh, 902 -> re-login)
        if is_encrypted and isinstance(payload, dict) and payload.get("result") is False:
            data = payload.get("data") or {}
            code = str(data.get("errorCode", "")) if isinstance(data, dict) else ""
            if code == "903":
                if await self.refresh_token():
                    payload = await _perform()
                else:
                    await self.login(force=True)
                    payload = await _perform()
            elif code == "902":
                await self.login(force=True)
                payload = await _perform()

        # Dump every fetched response into temp_data/ for manual schema inspection
        self.dumper.dump(self.SOURCE_NAME, name, payload, params=params)
        return payload
