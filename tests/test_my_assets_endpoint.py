from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from src.routers.asset import get_my_assets
from src.schemas.user import TokenData


@pytest.mark.anyio
async def test_uses_the_authenticated_users_client_and_unassigned_filter() -> None:
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

    assert result == expected_assets
    validate_access.assert_awaited_once_with(
        current_user,
        "asset:get my assets",
        db,
    )
    service_class.return_value.get_assets_by_client_id.assert_awaited_once_with(
        client_id=12,
        unassigned=True,
    )


@pytest.mark.anyio
async def test_rejects_tokens_without_a_client() -> None:
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
        with pytest.raises(HTTPException) as exc_info:
            await get_my_assets(
                unassigned=None,
                db=object(),
                current_user=current_user,
            )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "client_id is required for this asset operation."
