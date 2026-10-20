import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from src.routers.asset import get_my_assets
from src.schemas.user import TokenData


class MyAssetsEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_the_authenticated_users_client_and_unassigned_filter(self) -> None:
        current_user = TokenData(
            user_id=7,
            username="client-user",
            client_id=12,
            is_admin=False,
        )
        db = object()
        expected_assets = [{"id_asset": 1}]

        with (
            patch(
                "src.routers.asset.validate_user_service_access",
                new=AsyncMock(),
            ) as validate_access,
            patch("src.routers.asset.AssetService") as service_class,
        ):
            service_class.return_value.get_assets_by_client_id = AsyncMock(
                return_value=expected_assets
            )

            result = await get_my_assets(
                unassigned=True,
                db=db,
                current_user=current_user,
            )

        self.assertEqual(result, expected_assets)
        validate_access.assert_awaited_once_with(
            current_user,
            "asset:get my assets",
            db,
        )
        service_class.return_value.get_assets_by_client_id.assert_awaited_once_with(
            client_id=12,
            unassigned=True,
        )

    async def test_rejects_tokens_without_a_client(self) -> None:
        current_user = TokenData(
            user_id=1,
            username="admin",
            client_id=None,
            is_admin=True,
        )

        with patch(
            "src.routers.asset.validate_user_service_access",
            new=AsyncMock(),
        ):
            with self.assertRaises(HTTPException) as context:
                await get_my_assets(
                    unassigned=None,
                    db=object(),
                    current_user=current_user,
                )

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(
            context.exception.detail,
            "client_id is required for this asset operation.",
        )


if __name__ == "__main__":
    unittest.main()
