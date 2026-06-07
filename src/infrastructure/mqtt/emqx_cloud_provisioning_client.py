from urllib.parse import quote

import httpx


class EMQXCloudProvisioningClient:
    """
    Creates MQTT users and optional authorization rules in EMQX Cloud.

    Requires EMQX API credentials and an authentication chain using:
    password_based:built_in_database
    """

    def __init__(
        self,
        api_base_url: str,
        api_key: str,
        api_secret: str,
        authentication_id: str = "password_based:built_in_database",
        authorization_enabled: bool = True,
        timeout_seconds: int = 10,
    ):
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.authentication_id = authentication_id
        self.authorization_enabled = authorization_enabled
        self.timeout_seconds = timeout_seconds

    async def provision_device(
        self,
        mqtt_username: str,
        mqtt_password: str,
        location_topic: str,
        status_topic: str,
        heartbeat_topic: str,
        commands_topic: str,
        acks_topic: str,
    ) -> None:
        await self.create_authentication_user(
            username=mqtt_username,
            password=mqtt_password,
        )

        if self.authorization_enabled:
            await self.set_user_authorization_rules(
                username=mqtt_username,
                publish_topics=[
                    location_topic,
                    status_topic,
                    heartbeat_topic,
                    acks_topic,
                ],
                subscribe_topics=[
                    commands_topic,
                ],
            )

    async def deprovision_device(self, mqtt_username: str) -> None:
        errors = []

        if self.authorization_enabled:
            try:
                await self.delete_user_authorization_rules(username=mqtt_username)
            except Exception as exc:
                errors.append(exc)

        try:
            await self.delete_authentication_user(username=mqtt_username)
        except Exception as exc:
            errors.append(exc)

        if errors:
            raise RuntimeError(
                "EMQX compensation failed while deprovisioning device. "
                f"Errors: {[str(error) for error in errors]}"
            )

    async def create_authentication_user(
        self,
        username: str,
        password: str,
    ) -> None:
        authentication_id = quote(self.authentication_id, safe="")

        url = (
            f"{self.api_base_url}"
            f"/authentication/{authentication_id}/users"
        )

        payload = {
            "user_id": username,
            "password": password,
            "is_superuser": False,
        }

        response = await self._post(url, json=payload)

        # 409 usually means user already exists. For provisioning,
        # we should treat it as an error to avoid silent collisions.
        if response.status_code not in (200, 201, 204):
            self._raise_error("create authentication user", response)

    async def set_user_authorization_rules(
        self,
        username: str,
        publish_topics: list[str],
        subscribe_topics: list[str],
    ) -> None:
        encoded_username = quote(username, safe="")

        url = (
            f"{self.api_base_url}"
            f"/authorization/sources/built_in_database/rules/users/{encoded_username}"
        )

        payload = {
            "username": username,
            "rules": [
                {
                    "action": "publish",
                    "permission": "allow",
                    "topic": topic,
                }
                for topic in publish_topics
            ]
            + [
                {
                    "action": "subscribe",
                    "permission": "allow",
                    "topic": topic,
                }
                for topic in subscribe_topics
            ],
        }

        response = await self._put(url, json=payload)

        if response.status_code not in (200, 201, 204):
            self._raise_error("set authorization rules", response)

    async def delete_authentication_user(self, username: str) -> None:
        authentication_id = quote(self.authentication_id, safe="")
        encoded_username = quote(username, safe="")

        url = (
            f"{self.api_base_url}"
            f"/authentication/{authentication_id}/users/{encoded_username}"
        )

        response = await self._delete(url)

        if response.status_code not in (200, 204, 404):
            self._raise_error("delete authentication user", response)

    async def delete_user_authorization_rules(self, username: str) -> None:
        encoded_username = quote(username, safe="")

        url = (
            f"{self.api_base_url}"
            f"/authorization/sources/built_in_database/rules/users/{encoded_username}"
        )

        response = await self._delete(url)

        if response.status_code not in (200, 204, 404):
            self._raise_error("delete authorization rules", response)

    async def _post(self, url: str, json: dict) -> httpx.Response:
        async with httpx.AsyncClient(
            auth=(self.api_key, self.api_secret),
            timeout=self.timeout_seconds,
        ) as client:
            return await client.post(url, json=json)

    async def _put(self, url: str, json: dict) -> httpx.Response:
        async with httpx.AsyncClient(
            auth=(self.api_key, self.api_secret),
            timeout=self.timeout_seconds,
        ) as client:
            return await client.put(url, json=json)

    async def _delete(self, url: str) -> httpx.Response:
        async with httpx.AsyncClient(
            auth=(self.api_key, self.api_secret),
            timeout=self.timeout_seconds,
        ) as client:
            return await client.delete(url)

    def _raise_error(self, action: str, response: httpx.Response) -> None:
        try:
            detail = response.json()
        except Exception:
            detail = response.text

        raise RuntimeError(
            f"EMQX API failed during {action}. "
            f"Status={response.status_code}. Detail={detail}"
        )
