from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ClientBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=1, max_length=320)

    @field_validator("name", "email")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, min_length=1, max_length=320)

    @field_validator("name", "email")
    @classmethod
    def strip_non_null_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        return value.lower() if value is not None else None

    @model_validator(mode="after")
    def require_fields(self) -> "ClientUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided.")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Fields cannot be null.")
        return self


class ClientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_client: int
    name: str
    email: str


class ClientDashboardResponse(BaseModel):
    id_client: int
    name: str
    email: str
    device_count: int
    user_count: int
