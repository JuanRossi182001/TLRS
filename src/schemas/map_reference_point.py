from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models.map_reference_point import MapReferencePointCategory


class MapReferencePointFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: MapReferencePointCategory
    other_type: str | None = Field(default=None, min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    note: str | None = None

    @model_validator(mode="after")
    def validate_category_details(self):
        if self.category is MapReferencePointCategory.OTHER:
            if self.other_type is None or not self.other_type.strip():
                raise ValueError("other_type is required for category OTHER.")
            self.other_type = self.other_type.strip()
        elif self.other_type is not None:
            raise ValueError("other_type is only allowed for category OTHER.")

        if not self.name.strip():
            raise ValueError("name cannot be blank.")
        self.name = self.name.strip()
        return self


class MapReferencePointCreate(MapReferencePointFields):
    pass


class MapReferencePointUpdate(MapReferencePointFields):
    pass


class MapReferencePointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_map_reference_point: int
    client_id: int
    category: MapReferencePointCategory
    other_type: str | None = None
    name: str
    latitude: float
    longitude: float
    note: str | None = None
    created_at: datetime
    updated_at: datetime
