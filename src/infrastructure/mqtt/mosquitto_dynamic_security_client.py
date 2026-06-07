import subprocess


class MosquittoDynamicSecurityClient:
    """
    Client responsible for provisioning MQTT users, roles and ACLs
    in Mosquitto Dynamic Security.

    This implementation calls mosquitto_ctrl inside the mosquitto container.
    """

    def __init__(
        self,
        container_name: str,
        admin_username: str,
        admin_password: str,
    ):
        self.container_name = container_name
        self.admin_username = admin_username
        self.admin_password = admin_password

    def provision_device(
        self,
        mqtt_username: str,
        mqtt_password: str,
        role_name: str,
        location_topic: str,
        status_topic: str,
        heartbeat_topic: str,
        commands_topic: str,
        acks_topic: str,
    ) -> None:
        self._create_client(mqtt_username, mqtt_password)
        self._create_role(role_name)

        self._add_publish_acl(role_name, location_topic)
        self._add_publish_acl(role_name, status_topic)
        self._add_publish_acl(role_name, heartbeat_topic)
        self._add_publish_acl(role_name, acks_topic)
        self._add_subscribe_acl(role_name, commands_topic)
        self._add_receive_acl(role_name, commands_topic)

        self._add_client_role(mqtt_username, role_name)

    def _base_cmd(self) -> list[str]:
        return [
            "docker",
            "exec",
            self.container_name,
            "mosquitto_ctrl",
            "-h",
            "localhost",
            "-u",
            self.admin_username,
            "-P",
            self.admin_password,
            "dynsec",
        ]

    def _run(self, args: list[str]) -> None:
        cmd = self._base_cmd() + args

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Mosquitto dynsec command failed: {' '.join(cmd)}\n"
                f"STDOUT: {result.stdout}\n"
                f"STDERR: {result.stderr}"
            )

    def _create_client(self, username: str, password: str) -> None:
        self._run(["createClient", username, "-p", password])

    def _create_role(self, role_name: str) -> None:
        self._run(["createRole", role_name])

    def _add_publish_acl(self, role_name: str, topic: str) -> None:
        self._run([
            "addRoleACL",
            role_name,
            "publishClientSend",
            topic,
            "allow",
        ])

    def _add_subscribe_acl(self, role_name: str, topic: str) -> None:
        self._run([
            "addRoleACL",
            role_name,
            "subscribePattern",
            topic,
            "allow",
        ])

    def _add_receive_acl(self, role_name: str, topic: str) -> None:
        self._run([
            "addRoleACL",
            role_name,
            "publishClientReceive",
            topic,
            "allow",
        ])

    def _add_client_role(self, username: str, role_name: str) -> None:
        self._run(["addClientRole", username, role_name])
